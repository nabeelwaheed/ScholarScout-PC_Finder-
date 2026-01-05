"""
OpenAlex integration utilities.

This module provides:
- OpenAlexService: a tiny HTTP client wrapper
- helper functions to enrich Researcher entities with citation_count, h_index, and topics
- helper functions to fetch and attach publications (works) into the Publication table
"""

from __future__ import annotations

import os
from typing import Optional, List, Dict, Any

import httpx
from sqlalchemy import func
from sqlalchemy.orm import Session

from . import models

OPENALEX_BASE_URL = "https://api.openalex.org"


class OpenAlexService:
    def __init__(self, mailto: Optional[str] = None, timeout: float = 10.0):
        """
        :param mailto: optional contact email to include in OpenAlex requests (recommended by OpenAlex)
        :param timeout: HTTP timeout in seconds
        """
        self.mailto = (
            mailto
            or os.environ.get("OPENALEX_MAILTO")
            or "frank.eve.cs@gmail.com"   # <-- put your email here
        )
        self.base_url = OPENALEX_BASE_URL
        self.timeout = timeout

    def _get_client(self) -> httpx.Client:
        return httpx.Client(timeout=self.timeout)

    def _add_common_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        if self.mailto:
            params = dict(params)
            params["mailto"] = self.mailto
        return params

    def search_authors(self, name: str, affiliation: Optional[str] = None, per_page: int = 5) -> List[Dict[str, Any]]:
        """
        Search OpenAlex authors by display name.
        We use display_name.search + relevance_score sorting to get the best matches.
        """
        q = " ".join(name.split())
        params = {
            "filter": f"display_name.search:{q}",
            "sort": "relevance_score:desc",
            "per_page": per_page,
        }
        params = self._add_common_params(params)
        url = f"{self.base_url}/authors"

        with self._get_client() as client:
            resp = client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

        return data.get("results", []) or []

    def get_author(self, author_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetch a single author by OpenAlex author ID or full URL.
        """
        if author_id.startswith("http"):
            url = author_id
        else:
            url = f"{self.base_url}/authors/{author_id}"
        params = self._add_common_params({})
        with self._get_client() as client:
            resp = client.get(url, params=params)
            resp.raise_for_status()
            return resp.json()

    # --- works (publications) ---

    @staticmethod
    def _author_id_compact(author_id: str) -> str:
        """
        Normalize OpenAlex author id into compact form like 'A123...'.
        Accepts:
          - 'https://openalex.org/A123'
          - 'A123'
        """
        author_id = (author_id or "").strip()
        if author_id.startswith("http"):
            return author_id.rstrip("/").split("/")[-1]
        return author_id

    def list_works_for_author(
        self,
        author_id: str,
        *,
        per_page: int = 200,
        cursor: str = "*",
        sort: str = "publication_date:desc",
    ) -> Dict[str, Any]:
        """
        Cursor-paginated works query for an author.
        Returns the raw JSON response.
        """
        aid = self._author_id_compact(author_id)
        params = {
            # OpenAlex uses authorships.author.id for works filtering
            "filter": f"authorships.author.id:{aid}",
            "per_page": per_page,
            "cursor": cursor,
            "sort": sort,
        }
        params = self._add_common_params(params)
        url = f"{self.base_url}/works"

        with self._get_client() as client:
            resp = client.get(url, params=params)
            resp.raise_for_status()
            return resp.json()

    # --- candidate ranking helpers ---

    @staticmethod
    def _normalize(s: Optional[str]) -> str:
        return (s or "").strip().lower()

    def pick_best_author_candidate(
        self,
        candidates: List[Dict[str, Any]],
        name: str,
        affiliation: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Pick the best candidate from a list of authors.

        Strategy:
        - Assume candidates are already sorted by relevance_score (we request that).
        - Optionally boost when affiliation matches last_known_institution.
        - Always return the top-scoring candidate if there is at least one.
        """
        if not candidates:
            return None

        target_aff = self._normalize(affiliation)

        best_score = -1.0
        best_cand = None

        for cand in candidates:
            inst = self._normalize(
                (cand.get("last_known_institutions") or cand.get("last_known_institution") or [{}])[0].get("display_name")
                if cand.get("last_known_institutions")
                else (cand.get("last_known_institution") or {}).get("display_name")
            )

            score = cand.get("relevance_score") or 0.0

            if target_aff and target_aff in inst:
                score += 100.0  # big bump if affiliation matches (e.g., Brock University)

            if score > best_score:
                best_score = score
                best_cand = cand

        # no hard threshold: if we have any candidate at all, return the best one
        return best_cand


def enrich_researcher_with_openalex(
    db_sess: Session,
    researcher: models.Researcher,
    svc: OpenAlexService,
    overwrite_existing: bool = False,
    attach_topics: bool = True,
) -> bool:
    """
    Enrich a single Researcher row with data from OpenAlex:
    - citation_count
    - h_index
    - additional topics (if available)

    :returns: True if enrichment succeeded, False otherwise.
    """
    # If we already have impact data and overwrite is False, skip
    if not overwrite_existing and (researcher.citation_count is not None or researcher.h_index is not None):
        return False

    # basic sanity
    if not researcher.full_name:
        return False

    try:
        candidates = svc.search_authors(researcher.full_name, researcher.affiliation)
    except Exception:
        # network error, etc.
        return False

    cand = svc.pick_best_author_candidate(candidates, researcher.full_name, researcher.affiliation)
    if not cand:
        return False

    # OpenAlex author ID is usually something like "https://openalex.org/A123456789"
    author_id = cand.get("id")
    if not author_id:
        return False

    try:
        author = svc.get_author(author_id)
    except Exception:
        return False

    if not author:
        return False

    # --- update impact metrics ---
    cited_by = author.get("cited_by_count")
    summary_stats = author.get("summary_stats") or {}
    h_index = summary_stats.get("h_index")

    if cited_by is not None:
        researcher.citation_count = int(cited_by)
    if h_index is not None:
        try:
            researcher.h_index = int(h_index)
        except Exception:
            pass

    # --- attach topics from OpenAlex, if any ---
    if attach_topics:
        # author["topics"] is a list of { "id": ..., "display_name": ..., ... }
        topics = author.get("topics") or []
        existing_topic_names = {t.name.lower() for t in researcher.topics}
        for t in topics:
            name = t.get("display_name")
            if not name:
                continue
            lname = name.lower()
            if lname in existing_topic_names:
                continue
            topic_obj = db_sess.query(models.Topic).filter_by(name=name).one_or_none()
            if not topic_obj:
                topic_obj = models.Topic(name=name)
                db_sess.add(topic_obj)
                db_sess.flush()
            if topic_obj not in researcher.topics:
                researcher.topics.append(topic_obj)
                existing_topic_names.add(lname)

    db_sess.add(researcher)
    return True


def enrich_all_researchers(
    db_sess: Session,
    svc: Optional[OpenAlexService] = None,
    overwrite_existing: bool = False,
    limit: Optional[int] = None,
) -> int:
    """
    Enrich all researchers currently in the DB.

    :param overwrite_existing: if True, overwrite citation_count/h_index even if present.
    :param limit: optionally limit the number of researchers processed (for testing).
    :returns: number of researchers successfully enriched.
    """
    if svc is None:
        svc = OpenAlexService()

    q = db_sess.query(models.Researcher)
    if limit is not None:
        q = q.limit(limit)

    count = 0
    for r in q.all():
        ok = enrich_researcher_with_openalex(db_sess, r, svc, overwrite_existing=overwrite_existing)
        if ok:
            count += 1

    db_sess.commit()
    return count


# -----------------------------
# Publications ingestion (works)
# -----------------------------

def _resolve_openalex_author_id_for_researcher(
    researcher: models.Researcher,
    svc: OpenAlexService,
) -> Optional[str]:
    """
    Uses search_authors + pick_best_author_candidate to find the OpenAlex author id.
    Returns something like "https://openalex.org/A123..." or None.
    """
    if not researcher.full_name:
        return None
    try:
        candidates = svc.search_authors(researcher.full_name, researcher.affiliation)
    except Exception:
        return None

    cand = svc.pick_best_author_candidate(candidates, researcher.full_name, researcher.affiliation)
    if not cand:
        return None

    return cand.get("id")


def _upsert_publication(
    db_sess: Session,
    researcher_id: int,
    title: str,
    year: Optional[int],
    venue: Optional[str],
) -> bool:
    """
    Returns True if inserted, False if already existed.

    Dedupe rule:
      (researcher_id, lower(title), year, lower(venue))
    """
    title_norm = (title or "").strip()
    if not title_norm:
        return False

    q = db_sess.query(models.Publication).filter(models.Publication.researcher_id == researcher_id)
    q = q.filter(func.lower(models.Publication.title) == title_norm.lower())

    if year is None:
        q = q.filter(models.Publication.year.is_(None))
    else:
        q = q.filter(models.Publication.year == int(year))

    venue_norm = (venue or "").strip()
    if venue_norm:
        q = q.filter(func.lower(models.Publication.venue) == venue_norm.lower())
    else:
        q = q.filter((models.Publication.venue.is_(None)) | (models.Publication.venue == ""))

    existing = q.first()
    if existing:
        return False

    pub = models.Publication(
        researcher_id=researcher_id,
        title=title_norm,
        year=int(year) if year is not None else None,
        venue=venue_norm or None,
    )
    db_sess.add(pub)
    return True


def fetch_and_attach_publications_for_researcher(
    db_sess: Session,
    researcher: models.Researcher,
    svc: OpenAlexService,
    *,
    max_works: int = 50,
    overwrite_existing: bool = False,
) -> int:
    """
    Fetch up to max_works works from OpenAlex and store them in Publication table.
    Returns the number of newly added publications.

    overwrite_existing=False:
      - if the researcher already has ANY publications, this does nothing.
    """
    if not researcher or not researcher.id:
        return 0

    if not overwrite_existing:
        has_any = (
            db_sess.query(models.Publication.id)
            .filter(models.Publication.researcher_id == researcher.id)
            .first()
        )
        if has_any:
            return 0

    author_id = _resolve_openalex_author_id_for_researcher(researcher, svc)
    if not author_id:
        return 0

    added = 0
    cursor = "*"
    remaining = max(1, int(max_works))
    per_page = min(200, remaining)

    while remaining > 0:
        try:
            data = svc.list_works_for_author(author_id, per_page=per_page, cursor=cursor)
        except Exception:
            break

        results = data.get("results") or []
        if not results:
            break

        for w in results:
            if remaining <= 0:
                break

            title = w.get("display_name") or w.get("title") or ""
            year = w.get("publication_year")

            hv = w.get("host_venue") or {}
            venue = hv.get("display_name")

            if not venue:
                # fallback path for some records
                venue = (
                    (w.get("primary_location") or {})
                    .get("source", {})  # type: ignore[union-attr]
                    .get("display_name")
                )

            if _upsert_publication(db_sess, researcher.id, title, year, venue):
                added += 1

            remaining -= 1

        meta = data.get("meta") or {}
        cursor = meta.get("next_cursor")
        if not cursor:
            break

    db_sess.commit()
    return added


def fetch_publications_for_all_researchers(
    db_sess: Session,
    svc: Optional[OpenAlexService] = None,
    *,
    limit: Optional[int] = None,
    max_works: int = 50,
    missing_only: bool = True,
) -> Dict[str, int]:
    """
    Fetch OpenAlex works for researchers and populate Publication table.

    missing_only=True:
      - only fetch for researchers that currently have 0 publications.

    Returns counters:
      - researchers_considered
      - researchers_updated
      - publications_added
    """
    if svc is None:
        svc = OpenAlexService()

    q = db_sess.query(models.Researcher)
    if limit is not None:
        q = q.limit(int(limit))

    researchers = q.all()
    considered = 0
    updated = 0
    pubs_added = 0

    for r in researchers:
        considered += 1

        if missing_only:
            has_any = (
                db_sess.query(models.Publication.id)
                .filter(models.Publication.researcher_id == r.id)
                .first()
            )
            if has_any:
                continue

        n = fetch_and_attach_publications_for_researcher(
            db_sess,
            r,
            svc,
            max_works=max_works,
            overwrite_existing=not missing_only,
        )
        if n > 0:
            updated += 1
            pubs_added += n

    return {
        "researchers_considered": considered,
        "researchers_updated": updated,
        "publications_added": pubs_added,
    }
