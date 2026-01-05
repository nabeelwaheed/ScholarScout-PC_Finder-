from __future__ import annotations
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from typing import List, Dict, Tuple
import re

def norm_space(s: str) -> str:
    import re as _re
    return _re.sub(r"\s+", " ", (s or "").replace("\u00a0"," ").strip())

# Only keep the MAIN research PC (papers) and Organizing
_PC_SLUG_HINTS = (
    "papers-program-committee",           # main research PC (most conferences)
    "research-papers-program-committee",  # ASE/ECSA/FSE style
    "technical-papers-program-committee", # ISSTA technical papers
    "technical-research-program-committee", # ICPC 2019
    "research-program-committee",         # ICPC 2020+
    "program-committee",                  # plain "program committee" (ISSTA 2021, some others)
    "call-for-papers-program-committee",  # ECSA 2025
)


'''''
_ORG_SLUG_HINTS = (
    "organizing-committee",
    "organising-committee",
)
'''

class ResearchrScraper:
    def __init__(self, base_url: str, http_client, delay_min: float, delay_max: float):
        self.base = base_url.rstrip("/")
        self.http = http_client
        self.delay_min = delay_min
        self.delay_max = delay_max

    # ---- URL helpers ---------------------------------------------------------
    def _committee_candidates(self, conf: str, year: int, try_organising: bool) -> list[tuple[str,str]]:
        """Return (committee_label, url) candidates to try directly."""
        cslug = f"{conf}-{year}"
        out = []

        # Organizing
        out.append(("Organizing Committee", f"{self.base}/committee/{cslug}/{cslug}-organizing-committee"))
        if try_organising:
            out.append(("Organizing Committee", f"{self.base}/committee/{cslug}/{cslug}-organising-committee"))

        # Main Program Committee — EXACT papers PC
        for hint in _PC_SLUG_HINTS:
            out.append(("Program Committee", f"{self.base}/committee/{cslug}/{cslug}-{hint}"))

        return out

    def _slug_to_committee_label(self, slug: str, conf: str, year: int) -> str | None:
        """Return 'Program Committee' or 'Organizing Committee' for known slugs, else None."""
        if not slug:
            return None

        s = slug.lower()
        conf = conf.lower()

        # Generic patterns that already worked
        main_org_1 = f"{conf}-{year}-organizing-committee"
        main_org_2 = f"{conf}-{year}-organising-committee"
        main_pc    = f"{conf}-{year}-papers-program-committee"

        # --- Generic organising committees ---
        if s == main_org_1 or s == main_org_2:
            return "Organizing Committee"

        # APLAS 2021, 2023: research-papers/papers organising committees
        if conf == "aplas":
            if s == f"{conf}-{year}-papers-organising-committee":
                return "Organizing Committee"
            if s == f"{conf}-{year}-research-papers-organizing-committee":
                return "Organizing Committee"

        # --- Generic MAIN PCs: "papers-program-committee" ---
        if s == main_pc:
            return "Program Committee"

        # Generic "research-papers-program-committee" (FSE, APLAS, EASE, PROFES, etc.)
        if s == f"{conf}-{year}-research-papers-program-committee":
            return "Program Committee"

        # Some conferences number research tracks: "...-research-papers-1-program-committee"
        if s.startswith(f"{conf}-{year}-research-papers") and s.endswith("program-committee"):
            return "Program Committee"

        # Shorter generic variants
        if s == f"{conf}-{year}-program-committee":
            return "Program Committee"

        if s == f"{conf}-{year}-pc":
            return "Program Committee"

        # Fallback: anything that looks like "<conf>-<year>-*papers*-program-committee"
        if s.startswith(f"{conf}-{year}-") and s.endswith("program-committee") and "papers" in s:
            return "Program Committee"

        # ---------------- ICSE special cases ----------------
        if conf == "icse":
            # ICSE 2023: technical-track-programme-committee
            if "technical-track-programme-committee" in s:
                return "Program Committee"

            # ICSE 2024–2026: research-track or research-track-research-track
            if s == f"{conf}-{year}-research-track" or s == f"{conf}-{year}-research-track-research-track":
                return "Program Committee"

        # ---------------- EASE special cases ----------------
        if conf == "ease":
            # 2022: ease-2022-research-pc-research-track
            if s == f"{conf}-{year}-research-pc-research-track":
                return "Program Committee"
            # 2023: ease-2023-research-program-committee
            if s == f"{conf}-{year}-research-program-committee":
                return "Program Committee"
            # 2026: ease-2026-research-papers-research-papers (we treat as main PC)
            if s == f"{conf}-{year}-research-papers-research-papers":
                return "Program Committee"

        # ---------------- PROFES special cases ----------------
        if conf == "profes":
            # 2024: profes-2024-Research-Papers-1-program-committee
            if s == f"{conf}-{year}-research-papers-1-program-committee":
                return "Program Committee"

        # ---------------- APLAS special cases ----------------
        if conf == "aplas":
            # 2020: aplas-2020-program-committee
            if s == f"{conf}-{year}-program-committee":
                return "Program Committee"
            # 2022: aplas-2022-pc
            if s == f"{conf}-{year}-pc":
                return "Program Committee"
            # 2025: aplas-2025-aplas-2025-program-committee
            if s == f"{conf}-{year}-{conf}-{year}-program-committee":
                return "Program Committee"

        # ---------------- XP special cases ----------------
        if conf == "xp":
            # 2025: typo "reseach-papers-program-committee"
            if s == f"{conf}-{year}-reseach-papers-program-committee":
                return "Program Committee"

        # If we reach here, we don't care about this slug
        return None




    def _is_committee_path(self, path: str, conf: str, year: int) -> bool:
        if not path:
            return False

        parts = path.strip("/").split("/")
        if not parts or parts[0] != "committee":
            return False

        slug = None

        # Pattern 1: /committee/<conf>-<year>/<slug>  (conf.researchr.org)
        if len(parts) >= 3 and parts[1] == f"{conf}-{year}":
            slug = parts[-1]

        # Pattern 2: /committee/<slug> where slug starts with "<conf>-<year>-"
        # (2022.esec-fse.org style: /committee/fse-2022-research-papers-program-committee)
        elif len(parts) == 2 and parts[1].lower().startswith(f"{conf}-{year}-"):
            slug = parts[1]

        if not slug:
            return False

        return self._slug_to_committee_label(slug, conf, year) is not None


    # ---- Discovery -----------------------------------------------------------
    def find_all_committees(self, conf: str, year: int, try_organising: bool) -> list[tuple[str,str]]:
        """
        Return list of (committee_label, url) for this (conf, year).
        We try direct candidates, then scan home pages for committee links.
        """
        seen = set()
        out: list[tuple[str,str]] = []

        # 1) direct candidates
        for label, url in self._committee_candidates(conf, year, try_organising):
            self.http.polite_delay(self.delay_min, self.delay_max)
            r = self.http.get(url)
            if r.status_code == 200:
                key = (label, url)
                if key not in seen:
                    seen.add(key); out.append((label, url))

        # 2) scan home pages for /committee/<conf-year>/<slug> anchors
        for home in [f"{self.base}/home/{conf}-{year}", f"{self.base}/{conf}-{year}"]:
            self.http.polite_delay(self.delay_min, self.delay_max)
            r = self.http.get(home)
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, "lxml")
            for a in soup.find_all("a", href=True):
                href = a["href"]
                full = urljoin(self.base, href)
                path = urlparse(full).path
                if self._is_committee_path(path, conf, year):
                    label = self._slug_to_committee_label(path.strip("/").split("/")[-1], conf, year)
                    if label:
                        key = (label, full)
                        if key not in seen:
                            seen.add(key); out.append((label, full))
        return out

    # ---- Person/profile parsing ---------------------------------------------
    def fetch_profile_details(self, profile_url: str, conf: str, year: int):
        from bs4 import BeautifulSoup as _BS
        import re as _re

        # --- Network fetch with fail-soft handling ---
        try:
            self.http.polite_delay(self.delay_min, self.delay_max)
            r = self.http.get(profile_url)
        except Exception as e:
            # DNS / connection / retry failure: skip enrichment for this person
            print(f"[yellow]PROFILE-ERROR[/yellow] {conf}-{year} {profile_url}: {e}")
            return "", "", [], "", ""

        if r.status_code != 200:
            return "", "", [], "", ""

        soup = _BS(r.text, "lxml")

        def extract_label(label: str) -> str:
            lab = label.lower()
            for dt in soup.find_all("dt"):
                head = (dt.get_text(" ", strip=True) or "").lower().rstrip(": ")
                if head == lab or lab in head:
                    dd = dt.find_next_sibling("dd")
                    if dd:
                        return norm_space(dd.get_text(" ", strip=True))
            for tag in soup.find_all(["p", "div", "li"]):
                strong = tag.find(["strong", "b"])
                if strong:
                    head = (strong.get_text(" ", strip=True) or "").lower().rstrip(": ")
                    if head == lab or lab in head:
                        text = tag.get_text(" ", strip=True)
                        m = _re.search(rf"(?i)\b{_re.escape(label)}\s*[:：]\s*(.+)$", text)
                        if m:
                            return norm_space(m.group(1))
            txt = soup.find(string=_re.compile(rf"(?i)\b{_re.escape(label)}\s*[:：]"))
            if txt and getattr(txt, "parent", None):
                text = txt.parent.get_text(" ", strip=True)
                m = _re.search(rf"(?i)\b{_re.escape(label)}\s*[:：]\s*(.+)$", text)
                if m:
                    return norm_space(m.group(1))
            plaintext = soup.get_text("\n", strip=True)
            m = _re.search(rf"(?mi)^\s*{_re.escape(label)}\s*[:：]\s*(.+)$", plaintext)
            if m:
                return norm_space(m.group(1))
            return ""

        # Name
        name = extract_label("Name")
        if not name and soup.find("h1"):
            name = norm_space(soup.find("h1").get_text(" ", strip=True))

        # Bio
        bio = extract_label("Bio")
        if not bio:
            ps = [norm_space(p.get_text(" ", strip=True)) for p in soup.find_all("p")]
            long_ps = [p for p in ps if len(p) > 120]
            if long_ps:
                bio = long_ps[0]

        affiliation = extract_label("Affiliation")
        country = extract_label("Country")

        # Interests
        def split_interests(text: str) -> list[str]:
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

        ri_text = extract_label("Research interests")
        interests = split_interests(ri_text)

        if not interests and bio:
            m = re.search(
                r"(?is)\bresearch\s*interests?\s*(?:are|include|focus(?:es)?\s+on)?\s*[:：]?\s*(.+?)(?:\.|$)",
                bio
            )
            if m:
                interests = split_interests(m.group(1))

        return name, bio, interests, affiliation, country

    def parse_committee(self, committee_url: str, conf: str, year: int, committee_label: str):
        from bs4 import BeautifulSoup as _BS
        self.http.polite_delay(self.delay_min, self.delay_max)
        r = self.http.get(committee_url)
        if r.status_code != 200:
            return []
        soup = _BS(r.text, "lxml")
        out = []
        for a in soup.select("a[href*='/profile/']"):
            profile_url = urljoin(self.base, a.get("href", ""))
            if not profile_url:
                continue
            name, bio, interests, affiliation, country = self.fetch_profile_details(profile_url, conf, year)
            if not name:
                name = norm_space(a.get_text(" ", strip=True).split(" - ")[0].split("|")[0].split(":")[0])
            out.append({
                "conference": conf.upper(),
                "year": year,
                "committee": committee_label,   # keep the label
                "name": name,
                "affiliation": affiliation,
                "country": country,
                "bio": bio,
                "research_interests": interests,
                "person_profile_url": profile_url,
                "committee_page_url": committee_url,
            })
        # de-dup
        seen=set(); uniq=[]
        for r in out:
            key=(r["conference"], r["year"], r.get("committee"), r["name"], r["person_profile_url"])
            if key in seen: continue
            seen.add(key); uniq.append(r)
        return uniq
