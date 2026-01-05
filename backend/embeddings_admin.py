# embeddings_admin.py
from __future__ import annotations

from datetime import datetime
from sqlalchemy.orm import Session, selectinload

from . import models
from .embedding_service import EmbeddingService, dumps_embedding


def build_profile_text(r: models.Researcher, max_pubs: int = 15) -> str:
    parts = []
    if r.full_name:
        parts.append(f"Name: {r.full_name}")
    if r.affiliation:
        parts.append(f"Affiliation: {r.affiliation}")
    if r.country:
        parts.append(f"Country: {r.country}")

    if getattr(r, "research_interests", None):
        parts.append(f"Research interests: {r.research_interests}")

    if r.bio:
        parts.append(f"Bio: {r.bio}")

    # Topics table
    if r.topics:
        parts.append("Topics: " + ", ".join(t.name for t in r.topics if t.name))

    # Publications (titles are great signal)
    pubs = sorted(r.publications or [], key=lambda p: (p.year or 0), reverse=True)
    pubs = pubs[:max_pubs]
    if pubs:
        parts.append("Publications: " + " | ".join(p.title for p in pubs if p.title))

    # One compact blob
    return "\n".join(parts).strip()


def rebuild_embeddings(db: Session, svc: EmbeddingService, limit: int | None = None) -> int:
    q = (
        db.query(models.Researcher)
        .options(
            selectinload(models.Researcher.topics),
            selectinload(models.Researcher.publications),
        )
        .order_by(models.Researcher.id.asc())
    )
    if limit is not None:
        q = q.limit(int(limit))

    researchers = q.all()
    if not researchers:
        return 0

    texts = [build_profile_text(r) for r in researchers]
    vectors = svc.embed_texts(texts)

    now = datetime.utcnow()
    for r, txt, vec in zip(researchers, texts, vectors):
        r.profile_text = txt
        r.embedding = dumps_embedding(vec)
        r.embedding_model = svc.model_name
        r.embedding_updated_at = now

    db.commit()
    return len(researchers)
