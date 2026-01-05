from __future__ import annotations
from urllib.parse import urljoin
from bs4 import BeautifulSoup, NavigableString
from typing import Optional, List, Dict, Tuple
import re

def norm_space(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())

# ---------------- existing helpers you already have ----------------
# (we re-declare only the parts we need to overwrite cleanly)

def split_research_interests(text: str) -> List[str]:
    if not text:
        return []
    parts = [p.strip() for p in re.split(r"[;,]", text) if p.strip()]
    cleaned, seen = [], set()
    for p in parts:
        p = re.sub(r"^\band\b\s+", "", p, flags=re.I)   # drop leading "and "
        p = p.rstrip(".")                               # drop trailing period
        p = norm_space(p)
        p = re.sub(r"\bsoftware analytic\b", "software analytics", p, flags=re.I)
        k = p.lower()
        if p and k not in seen:
            seen.add(k); cleaned.append(p)
    return cleaned

def _extract_interests_from_dom(soup: BeautifulSoup) -> List[str]:
    """Strong DOM-based strategies."""
    # A) <dt>Research interests</dt><dd>…</dd>
    for dt in soup.find_all("dt"):
        head = (dt.get_text(" ", strip=True) or "").strip().lower().rstrip(":")
        if "research interest" in head:
            dd = dt.find_next_sibling("dd")
            if dd:
                return split_research_interests(dd.get_text(" ", strip=True))

    # B) any element whose text contains 'Research interests:'
    for el in soup.find_all(text=re.compile(r"research interests\s*[:：]", re.I)):
        container = el.parent if hasattr(el, "parent") else None
        if not container:
            continue
        text = container.get_text(" ", strip=True)
        m = re.search(r"(?i)research interests\s*[:：]\s*(.+)$", text)
        if m:
            return split_research_interests(m.group(1))

    # C) sometimes it’s “Research Interests” (capital I) or extra spacing
    blob = soup.get_text("\n", strip=True)
    m = re.search(r"(?mi)^\s*research\s+interests\s*[:：]\s*(.+)$", blob)
    if m:
        return split_research_interests(m.group(1))

    return []

def _extract_interests_from_bio_or_page(soup: BeautifulSoup, bio: str) -> List[str]:
    """Fallback from bio or full page sentences like '… research interests include … .'"""
    haystacks = []
    if bio:
        haystacks.append(bio)
    # also scan whole page once
    haystacks.append(soup.get_text(" ", strip=True))

    for text in haystacks:
        m = re.search(
            r"(?is)\bresearch interests?\s+(?:include|are|focus(?:es)?\s+on)\s+(.+?)(?:\.|\n|$)",
            text,
        )
        if m:
            return split_research_interests(m.group(1))
    return []

# --------- Public function you call in fetch_profile_details ---------

def extract_interests(soup: BeautifulSoup, bio_text: str) -> List[str]:
    interests = _extract_interests_from_dom(soup)
    if interests:
        return interests
    return _extract_interests_from_bio_or_page(soup, bio_text)
