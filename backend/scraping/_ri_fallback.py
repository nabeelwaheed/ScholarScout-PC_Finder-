from __future__ import annotations
from bs4 import BeautifulSoup, NavigableString
from typing import List
import re

def norm_space(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("\u00a0", " ").strip())

def _split_interests(text: str) -> List[str]:
    if not text: return []
    parts = [p.strip() for p in re.split(r"[;,]", text) if p.strip()]
    out, seen = [], set()
    for p in parts:
        p = re.sub(r"^\band\b\s+", "", p, flags=re.I).rstrip(".")
        p = norm_space(p)
        p = re.sub(r"\bsoftware analytic\b", "software analytics", p, flags=re.I)
        k = p.lower()
        if p and k not in seen:
            seen.add(k); out.append(p)
    return out

# Words that indicate we reached UI/another section
STOP_BLOCK = re.compile(
    r"\b("
    r"name|country|affiliation|bio|contributions?|committee|program|organis(?:e|ing)|track|chair|papers?|poster|"
    r"show|share|view|profile|activities|general|member|within|using|conference|conferences?|"
    r"mon|tue|wed|thu|fri|sat|sun|[0-9]{4}"
    r")\b",
    re.I,
)

SAFE_CHARS = re.compile(r"^[A-Za-z0-9\s\-/&\+\.']+$")

def _seems_interest_token(s: str) -> bool:
    if not s: return False
    if STOP_BLOCK.search(s): return False
    if len(s) > 80: return False
    if len(s.split()) > 8: return False
    if not SAFE_CHARS.match(s): return False
    # avoid generic UI crumbs
    if s.lower() in {"share", "view", "profile"}: return False
    return True

def _collect_tokens_after_label(label_node) -> List[str]:
    """Collect ONLY chip/tag-like items (a/span/li) immediately after the label."""
    tokens, seen = [], set()

    parent = label_node.parent if label_node else None
    if not parent:
        return []

    # 1) If inline form "Research interests: X, Y" within same element, grab just that inline list
    txt = norm_space(parent.get_text(" ", strip=True))
    m = re.search(r"(?i)research\s*interests\s*[:：]\s*(.+)$", txt)
    if m:
        for t in _split_interests(m.group(1)):
            if _seems_interest_token(t) and t.lower() not in seen:
                seen.add(t.lower()); tokens.append(t)
        if tokens:
            return tokens[:8]

    # 2) Walk siblings; only accept items from <a>, <span>, <li>. If none present in a block, stop.
    sib = parent.next_sibling
    hops = 0
    while sib and hops < 20 and len(tokens) < 8:
        if isinstance(sib, NavigableString):
            t = norm_space(str(sib))
            if STOP_BLOCK.search(t): break
            # ignore bare text
        else:
            # If this block screams a new section, stop.
            block_text = norm_space(sib.get_text(" ", strip=True)) if hasattr(sib, "get_text") else ""
            if STOP_BLOCK.search(block_text): break

            bag = []
            bag.extend([a.get_text(" ", strip=True) for a in sib.find_all("a")])
            bag.extend([sp.get_text(" ", strip=True) for sp in sib.find_all("span")])
            bag.extend([li.get_text(" ", strip=True) for li in sib.find_all("li")])

            # If we didn't find any structured tokens here, assume we've reached non-interest content; stop.
            if not bag:
                break

            for b in bag:
                for part in _split_interests(norm_space(b)):
                    if _seems_interest_token(part) and part.lower() not in seen:
                        seen.add(part.lower()); tokens.append(part)
                        if len(tokens) >= 8:
                            break
        sib = sib.next_sibling; hops += 1

    return tokens[:8]

def _interests_from_dom(soup: BeautifulSoup) -> List[str]:
    # 1) <dt>Research interests</dt><dd>…</dd>
    for dt in soup.find_all("dt"):
        head = (dt.get_text(" ", strip=True) or "").lower().rstrip(": ")
        if "research interest" in head:
            dd = dt.find_next_sibling("dd")
            if dd:
                got = _split_interests(dd.get_text(" ", strip=True))
                if got: return got

    # 2) Any node that mentions label; then collect only tag-like tokens
    for node in soup.find_all(string=re.compile(r"research\s*interests", re.I)):
        got = _collect_tokens_after_label(node)
        if got:
            return got

    # 3) Plain-text line; cautiously split but filter strongly
    blob = soup.get_text("\n", strip=True)
    m = re.search(r"(?mi)^\s*research\s*interests\s*[:：]?\s*(.+)$", blob)
    if m:
        got = [g for g in _split_interests(m.group(1)) if _seems_interest_token(g)]
        if got: return got
    return []

def _interests_from_bio_or_page(soup: BeautifulSoup, bio: str) -> List[str]:
    bio = norm_space(bio)
    hay = []
    if bio: hay.append(bio)
    hay.append(norm_space(soup.get_text(" ", strip=True)))

    patt = re.compile(
        r"(?is)\bresearch\s*interests?\s*(?:are|include|focus(?:es)?\s+on)?\s*[:：]?\s*(.+?)(?:\.|$)"
    )
    for text in hay:
        m = patt.search(text)
        if m:
            items = [g for g in _split_interests(m.group(1)) if _seems_interest_token(g)]
            if items:
                return items

    # Emergency slice
    for text in hay:
        i = re.search(r"(?i)research\s*interests?", text)
        if i:
            tail = text[i.end():]
            piece = tail.split(".")[0]
            got = [g for g in _split_interests(piece) if _seems_interest_token(g)]
            if got:
                return got
    return []
