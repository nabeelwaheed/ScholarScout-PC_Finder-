# backend/topic_extraction.py

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Optional, Tuple, Dict, List

from sqlalchemy.orm import Session, selectinload

from . import models

# You need: pip install scikit-learn
from sklearn.feature_extraction.text import TfidfVectorizer


_WORD_RE = re.compile(r"[a-zA-Z][a-zA-Z\-]{1,}")  # keep words like "graph-based"


@dataclass(frozen=True)
class TopicExtractionConfig:
    top_k: int = 5
    max_titles_per_researcher: int = 50
    min_titles_required: int = 3
    min_df: int = 2            # ignore phrases that appear in <2 researchers
    max_df: float = 0.80       # ignore phrases that appear in >80% of researchers
    ngram_range: Tuple[int, int] = (1, 2)  # unigrams + bigrams


def _normalize_text(s: str) -> str:
    s = (s or "").lower()
    # Remove obvious noise
    s = s.replace("\n", " ").replace("\t", " ")
    # Collapse whitespace
    s = " ".join(s.split())
    return s


def _titles_to_doc(titles: Iterable[str]) -> str:
    cleaned: List[str] = []
    for t in titles:
        t = _normalize_text(t)
        if not t:
            continue
        cleaned.append(t)
    return " ".join(cleaned)


def _tokenize_for_vectorizer(text: str) -> List[str]:
    """
    Custom tokenizer to avoid TF-IDF pulling junk tokens.
    Keeps alpha words + hyphenated tokens.
    """
    return _WORD_RE.findall(text.lower())


def _pick_top_terms(tfidf_row, feature_names: List[str], top_k: int) -> List[str]:
    # tfidf_row is a 1 x N sparse row
    if tfidf_row.nnz == 0:
        return []
    # Get non-zero indices and weights
    indices = tfidf_row.indices
    data = tfidf_row.data
    pairs = sorted(zip(indices, data), key=lambda x: x[1], reverse=True)[:top_k]
    return [feature_names[i] for i, _ in pairs]


def extract_topics_from_publications(
    db: Session,
    cfg: TopicExtractionConfig = TopicExtractionConfig(),
    *,
    researcher_limit: Optional[int] = None,
    missing_only: bool = False,
) -> Dict[str, int]:
    """
    Extract topics using TF-IDF over concatenated publication titles per researcher,
    then attach (append-only) those topic terms to Researcher.topics.

    Returns counters:
      - researchers_considered
      - researchers_updated
      - topics_added
    """
    q = (
        db.query(models.Researcher)
        .options(
            selectinload(models.Researcher.publications),
            selectinload(models.Researcher.topics),
        )
        .order_by(models.Researcher.id.asc())
    )
    if researcher_limit is not None:
        q = q.limit(researcher_limit)

    researchers = q.all()

    # Build docs per researcher (only if they have enough titles)
    docs: List[str] = []
    r_ids: List[int] = []
    r_obj_by_id: Dict[int, models.Researcher] = {}

    for r in researchers:
        r_obj_by_id[r.id] = r

        if missing_only and r.topics and len(r.topics) > 0:
            # they already have topics, skip if you only want missing
            continue

        titles = [p.title for p in (r.publications or []) if p.title][: cfg.max_titles_per_researcher]
        if len(titles) < cfg.min_titles_required:
            continue

        docs.append(_titles_to_doc(titles))
        r_ids.append(r.id)

    if not docs:
        return {"researchers_considered": len(researchers), "researchers_updated": 0, "topics_added": 0}

    # Fit TF-IDF across all researcher docs (global model)
    vectorizer = TfidfVectorizer(
        tokenizer=_tokenize_for_vectorizer,
        lowercase=True,
        ngram_range=cfg.ngram_range,
        min_df=cfg.min_df,
        max_df=cfg.max_df,
    )
    X = vectorizer.fit_transform(docs)
    feature_names = vectorizer.get_feature_names_out().tolist()

    researchers_updated = 0
    topics_added = 0

    for row_idx, researcher_id in enumerate(r_ids):
        r = r_obj_by_id[researcher_id]

        existing = {t.name.strip().lower() for t in (r.topics or []) if t.name}
        tfidf_row = X[row_idx]

        terms = _pick_top_terms(tfidf_row, feature_names, cfg.top_k)
        # Light cleanup: drop 1-char tokens, and dedupe while preserving order
        dedup_terms: List[str] = []
        seen = set()
        for term in terms:
            term = term.strip().lower()
            if len(term) < 2:
                continue
            if term in seen or term in existing:
                continue
            seen.add(term)
            dedup_terms.append(term)

        if not dedup_terms:
            continue

        # Attach new Topic rows (if needed) + link
        added_for_r = 0
        for name in dedup_terms:
            topic = db.query(models.Topic).filter_by(name=name).one_or_none()
            if not topic:
                topic = models.Topic(name=name)
                db.add(topic)
                db.flush()  # ensure topic.id
            if topic not in r.topics:
                r.topics.append(topic)
                added_for_r += 1

        if added_for_r > 0:
            researchers_updated += 1
            topics_added += added_for_r

    db.commit()
    return {
        "researchers_considered": len(researchers),
        "researchers_updated": researchers_updated,
        "topics_added": topics_added,
    }
