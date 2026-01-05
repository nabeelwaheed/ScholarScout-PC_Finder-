import json
import os
from typing import Any, Optional

from sqlalchemy.orm import Session
from . import models
from .db import SessionLocal

SAMPLE_JSON_PATH = os.path.join(os.path.dirname(__file__), "sample_data", "pc_data.json")


def normalize_name(name: str) -> str:
    return " ".join((name or "").lower().split())


def split_topics(text: Optional[str]):
    if not text:
        return []
    parts = [p.strip() for p in text.replace(";", ",").split(",")]
    return [p for p in parts if p]


def _to_int(x: Any) -> Optional[int]:
    if x is None:
        return None
    try:
        return int(x)
    except Exception:
        return None


def _to_counts_by_year(x: Any) -> Optional[str]:
    """
    Store counts_by_year in DB as JSON text (portable across SQLite/Postgres).
    Accepts list[dict] or dict or JSON string; returns JSON string.
    """
    if x is None:
        return None

    # already JSON string?
    if isinstance(x, str):
        s = x.strip()
        if not s:
            return None
        # validate it is JSON
        try:
            json.loads(s)
            return s
        except Exception:
            return None

    # list/dict -> dump
    if isinstance(x, (list, dict)):
        try:
            return json.dumps(x, ensure_ascii=False)
        except Exception:
            return None

    return None


def ingest_json(path: str, db_sess: Session):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    for item in data:
        name = item.get("name")
        conf = item.get("conference")
        year = _to_int(item.get("year")) or 0

        affiliation = item.get("affiliation")
        country = item.get("country")
        bio = item.get("bio")
        research_interests = item.get("research_interests")
        profile_url = item.get("person_profile_url")
        committee_page_url = item.get("committee_page_url")

        # NEW fields from JSON (OpenAlex-style)
        works_count = _to_int(item.get("works_count"))
        cited_by_count = _to_int(item.get("cited_by_count"))
        h_index = _to_int(item.get("h_index"))
        counts_by_year = _to_counts_by_year(item.get("counts_by_year"))

        norm_name = normalize_name(name)

        researcher = (
            db_sess.query(models.Researcher)
            .filter_by(normalized_name=norm_name)
            .one_or_none()
        )

        if not researcher:
            researcher = models.Researcher(
                full_name=name,
                normalized_name=norm_name,
                affiliation=affiliation,
                country=country,
                bio=bio,
                person_profile_url=profile_url,
                research_interests=research_interests,
                # Old + new impact fields
                citation_count=None,  # keep for backward-compat if you still use it
                h_index=h_index,
                works_count=works_count,
                cited_by_count=cited_by_count,
                counts_by_year=counts_by_year,
            )
            db_sess.add(researcher)
            db_sess.flush()
        else:
            # only fill missing fields (don't overwrite existing enriched data)
            if research_interests and not getattr(researcher, "research_interests", None):
                researcher.research_interests = research_interests

            if affiliation and not researcher.affiliation:
                researcher.affiliation = affiliation
            if country and not researcher.country:
                researcher.country = country
            if profile_url and not researcher.person_profile_url:
                researcher.person_profile_url = profile_url
            if bio and not researcher.bio:
                researcher.bio = bio

            # NEW fields: fill if missing
            if works_count is not None and getattr(researcher, "works_count", None) is None:
                researcher.works_count = works_count

            if cited_by_count is not None and getattr(researcher, "cited_by_count", None) is None:
                researcher.cited_by_count = cited_by_count

            if h_index is not None and getattr(researcher, "h_index", None) is None:
                researcher.h_index = h_index

            if counts_by_year and not getattr(researcher, "counts_by_year", None):
                researcher.counts_by_year = counts_by_year

        conf_ed = (
            db_sess.query(models.ConferenceEdition)
            .filter_by(series=conf, year=year)
            .one_or_none()
        )
        if not conf_ed:
            conf_ed = models.ConferenceEdition(
                series=conf,
                year=year,
                committee_page_url=committee_page_url,
            )
            db_sess.add(conf_ed)
            db_sess.flush()

        existing = (
            db_sess.query(models.PCMembership)
            .filter_by(researcher_id=researcher.id, conference_id=conf_ed.id)
            .one_or_none()
        )
        if not existing:
            membership = models.PCMembership(
                researcher_id=researcher.id,
                conference_id=conf_ed.id,
                role="pc_member",
            )
            db_sess.add(membership)

        # topics from research_interests
        for topic_name in split_topics(research_interests):
            topic = db_sess.query(models.Topic).filter_by(name=topic_name).one_or_none()
            if not topic:
                topic = models.Topic(name=topic_name)
                db_sess.add(topic)
                db_sess.flush()
            if topic not in researcher.topics:
                researcher.topics.append(topic)

    db_sess.commit()


def load_sample_data_if_empty(SessionFactory=SessionLocal):
    sess = SessionFactory()
    try:
        has_any = sess.query(models.Researcher).first()
        if not has_any and os.path.exists(SAMPLE_JSON_PATH):
            ingest_json(SAMPLE_JSON_PATH, sess)
    finally:
        sess.close()


def ingest_all():
    """
    Entry point expected by main.py.
    Loads sample PC data if the database is empty.
    """
    load_sample_data_if_empty()
