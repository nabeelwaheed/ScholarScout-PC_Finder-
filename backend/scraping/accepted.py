from __future__ import annotations
from typing import List, Dict, Tuple
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
import re

from autopc.utils.http import Http
from autopc.scraping.researchr import norm_space, ResearchrScraper

# Hints for the *research papers* track slug across conferences/years
# We are strict: we only want research/technical papers, not demo, industry, DS, NIER, etc.
_ALLOWED_TRACK_HINTS = (
    "papers",            # e.g., saner-2025-papers
    "research-track",    # e.g., icse-2024-research-track
    "technical-papers",  # sometimes used in older sites
    "research-papers",
    "technical-research",     # icpc-2019-technical-research
    "call-for-research-papers",  # ecsa-2025-call-for-research-papers
)

class AcceptedPapersScraper:
    """
    Discover and scrape accepted research papers for (conference, year).
    Emits one row per (paper, author).
    """

    def __init__(self, base_url: str, http_client: Http, delay_min: float, delay_max: float):
        self.base = base_url.rstrip("/")
        self.http = http_client
        self.delay_min = delay_min
        self.delay_max = delay_max
        self._profile = ResearchrScraper(base_url, http_client, delay_min, delay_max)

    # ----------------- Discovery -----------------
    def _is_research_track(self, href: str, conf: str, year: int) -> bool:
        if not href:
            return False
        full = urljoin(self.base, href)
        path = urlparse(full).path.strip("/")
        parts = path.split("/")
        # Expect: track/<conf>-<year>/<slug>
        if len(parts) < 3 or parts[0] != "track" or parts[1] != f"{conf}-{year}":
            return False
        slug = parts[-1].lower()
        return any(h in slug for h in _ALLOWED_TRACK_HINTS)

    def discover_research_track(self, conf: str, year: int) -> List[str]:
        """
        Return a list of track URLs that match *research papers* for this (conf, year).
        We only keep slugs containing the allowed hints above.
        """
        urls = set()
        # Try the obvious index pages that list tracks
        candidates = [
            f"{self.base}/track/{conf}-{year}",
            f"{self.base}/home/{conf}-{year}",
            f"{self.base}/{conf}-{year}",
        ]
        for page in candidates:
            self.http.polite_delay(self.delay_min, self.delay_max)
            r = self.http.get(page)
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, "lxml")
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if self._is_research_track(href, conf, year):
                    full = urljoin(self.base, href)
                    # Normalize to the #event-overview anchor if missing
                    if "#event-overview" not in full:
                        full = full + "#event-overview"
                    urls.add(full)
        # Final filter: we do NOT allow substrings that clearly indicate non-research tracks
        def reject(u: str) -> bool:
            s = u.lower()
            return any(bad in s for bad in [
                "industry", "demo", "tool", "doctoral", "nier", "registered-reports",
                "student", "artifact", "journal-first", "poster", "vision", "education"
            ])
        return sorted(u for u in urls if not reject(u))

    # ----------------- Parsing -----------------
    def parse_track(self, track_url: str, conference: str, year: int) -> List[Dict]:
        """
        Parse a research papers track page and return rows per (paper, author).
        """
        self.http.polite_delay(self.delay_min, self.delay_max)
        r = self.http.get(track_url)
        if r.status_code != 200:
            return []

        soup = BeautifulSoup(r.text, "lxml")
        out: List[Dict] = []

        # Heuristic: "event-overview" section contains accepted talks/papers
        section = soup.find(id="event-overview") or soup
        blocks = section.find_all(["div", "section", "article", "li"])
        if not blocks:
            blocks = [section]

        def extract_title(node):
            for tag in ["h3", "h4", "strong", "b"]:
                t = node.find(tag)
                if t:
                    title = norm_space(t.get_text(" ", strip=True))
                    if title and not re.search(r"\b(Keynote|Session|Chair|Opening|Welcome)\b", title, re.I):
                        return title
            return ""

        for blk in blocks:
            author_anchors = [a for a in blk.find_all("a", href=True)
                              if ("/profile/" in a["href"] or "/person/" in a["href"])]
            if not author_anchors:
                continue

            paper_title = extract_title(blk)
            if not paper_title:
                prev_heading = blk.find_previous(["h3", "h4", "strong", "b"])
                if prev_heading:
                    t = norm_space(prev_heading.get_text(" ", strip=True))
                    if t and not re.search(r"\b(Keynote|Session|Chair|Opening|Welcome)\b", t, re.I):
                        paper_title = t

            for a in author_anchors:
                href = a.get("href", "")
                profile_url = urljoin(self.base, href)
                author_name = norm_space(a.get_text(" ", strip=True))

                aff = country = bio = ""
                interests: List[str] = []
                if "/profile/" in href:
                    nm, bio, interests, aff, country = self._profile.fetch_profile_details(profile_url, conference, year)
                    author_name = nm or author_name

                out.append({
                    "conference": conference.upper(),
                    "year": year,
                    "paper_title": paper_title,
                    "author_name": author_name,
                    "affiliation": aff,
                    "country": country,
                    "bio": bio,
                    "research_interests": interests,
                    "person_profile_url": profile_url if "/profile/" in href else "",
                    "track_url": track_url,
                })

        # De-dup
        seen = set(); uniq = []
        for r in out:
            key = (r["conference"], r["year"], r["paper_title"], r["author_name"], r.get("person_profile_url",""))
            if key in seen:
                continue
            seen.add(key); uniq.append(r)
        return uniq
