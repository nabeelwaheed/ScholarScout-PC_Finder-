import uvicorn
from fastapi import FastAPI, Depends, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session, selectinload

from . import db, models, schemas
from .ingestion import ingest_all
from .ranking import RankingService, QueryContext
from .embedding_service import EmbeddingService, cosine_sim_unit, loads_embedding
from . import embeddings_admin
from . import openalex_service
from . import topic_extraction


app = FastAPI(title="PC Finder Demo")

# Dev-friendly CORS 
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db():
    sess = db.SessionLocal()
    try:
        yield sess
    finally:
        sess.close()


@app.on_event("startup")
def on_startup():
    models.Base.metadata.create_all(bind=db.engine)
    ingest_all()


@app.get("/health")
def health():
    return {"status": "ok"}


# ---------------------------
# Recommendation (Ranking)
# ---------------------------

@app.post("/recommend", response_model=schemas.RecommendationResponse)
def recommend(query: schemas.RecommendationQuery, db_sess: Session = Depends(get_db)):
    ctx = QueryContext(
        conference_series=query.conference_series,
        year=query.year,
        topics=query.topics or [],
        years_back=query.years_back,
    )

    svc = RankingService(db_sess)
    ranked = svc.rank_candidates(ctx, limit=50)

    return schemas.RecommendationResponse(
        query=query,
        results=[schemas.RecommendationItem.from_internal(x) for x in ranked],
    )


# ---------------------------
# Semantic Query endpoint (embeddings-only scoring)
# This is separate from the ranking blend.
# ---------------------------

@app.post("/semantic-query", response_model=schemas.SemanticQueryResponse)
def semantic_query(req: schemas.SemanticQueryRequest, db_sess: Session = Depends(get_db)):
    """
    Pure semantic search:
    - embed the query text
    - cosine similarity to researcher.embedding
    - return top researchers with an explanation

    Note: this expects embeddings to exist in Researcher.embedding (JSON list).
    
    """
    svc = EmbeddingService()
    q_emb = svc.embed_text(req.query)

    researchers = (
        db_sess.query(models.Researcher)
        .options(selectinload(models.Researcher.topics))
        .all()
    )

    scored = []
    for r in researchers:
        raw = getattr(r, "embedding", None)
        if not raw:
            continue
        try:
            r_emb = loads_embedding(raw)
        except Exception:
            continue

        cos = cosine_sim_unit(q_emb, r_emb)  # unit vectors => dot
        scored.append((r, cos))

    scored.sort(key=lambda x: x[1], reverse=True)
    top = scored[:25]

    results = []
    for r, cos in top:
        results.append(
            schemas.SemanticQueryItem(
                researcher=schemas.ResearcherShort(
                    id=r.id,
                    full_name=r.full_name,
                    affiliation=r.affiliation,
                    country=r.country,
                    citation_count=r.citation_count,
                    h_index=r.h_index,
                    topics=[t.name for t in r.topics],
                ),
                score=float(cos),
                explanation="Cosine similarity between query embedding and researcher profile embedding.",
            )
        )

    return schemas.SemanticQueryResponse(query=req.query, results=results)


# ---------------------------
# Researcher detail endpoint
# ---------------------------

@app.get("/researcher/{researcher_id}", response_model=schemas.ResearcherDetail)
def researcher_detail(researcher_id: int, db_sess: Session = Depends(get_db)):
    r = (
        db_sess.query(models.Researcher)
        .options(
            selectinload(models.Researcher.topics),
            selectinload(models.Researcher.publications),
            selectinload(models.Researcher.pc_memberships).selectinload(models.PCMembership.conference),
        )
        .filter(models.Researcher.id == researcher_id)
        .first()
    )
    if not r:
        raise HTTPException(status_code=404, detail="Researcher not found")

    return schemas.ResearcherDetail.from_model(r)


# ---------------------------
# Admin: OpenAlex enrich (metrics + topics)
# ---------------------------

@app.post("/admin/openalex/enrich")
def admin_openalex_enrich(
    limit: int | None = None,
    overwrite_existing: bool = False,
    db_sess: Session = Depends(get_db),
):
    svc = openalex_service.OpenAlexService()
    n = openalex_service.enrich_all_researchers(
        db_sess,
        svc=svc,
        overwrite_existing=overwrite_existing,
        limit=limit,
    )
    db_sess.commit()
    return {"enriched": n}


# ---------------------------
# Admin: OpenAlex fetch works -> Publication table
# ---------------------------

@app.post("/admin/openalex/fetch-publications")
def admin_openalex_fetch_publications(
    limit: int | None = None,
    max_works: int = 50,
    missing_only: bool = True,
    db_sess: Session = Depends(get_db),
):
    svc = openalex_service.OpenAlexService()
    stats = openalex_service.fetch_publications_for_all_researchers(
        db_sess,
        svc=svc,
        limit=limit,
        max_works=max_works,
        missing_only=missing_only,
    )
    return stats


# ---------------------------
# Admin: TF-IDF topic extraction from publication titles
# ---------------------------

def _run_topic_extraction_job(
    top_k: int,
    max_titles: int,
    min_titles: int,
    limit: int | None,
    missing_only: bool,
):
    sess = db.SessionLocal()
    try:
        cfg = topic_extraction.TopicExtractionConfig(
            top_k=top_k,
            max_titles_per_researcher=max_titles,
            min_titles_required=min_titles,
        )
        topic_extraction.extract_topics_from_publications(
            sess,
            cfg,
            researcher_limit=limit,
            missing_only=missing_only,
        )
    finally:
        sess.close()


@app.post("/admin/topics/extract-from-publications")
def admin_extract_topics_from_publications(
    top_k: int = 5,
    max_titles: int = 50,
    min_titles: int = 3,
    limit: int | None = None,
    missing_only: bool = False,
    background: bool = True,
    background_tasks: BackgroundTasks = None,
    db_sess: Session = Depends(get_db),
):
    """
    background=True: schedule extraction after response (quick return)
    background=False: run now and return counters
    """
    if background:
        if background_tasks is None:
            background_tasks = BackgroundTasks()
        background_tasks.add_task(
            _run_topic_extraction_job,
            top_k, max_titles, min_titles, limit, missing_only
        )
        return {"status": "scheduled"}

    cfg = topic_extraction.TopicExtractionConfig(
        top_k=top_k,
        max_titles_per_researcher=max_titles,
        min_titles_required=min_titles,
    )
    return topic_extraction.extract_topics_from_publications(
        db_sess,
        cfg,
        researcher_limit=limit,
        missing_only=missing_only,
    )


# ---------------------------
# Admin: embeddings rebuild (local sentence-transformers)
# ---------------------------

@app.post("/admin/embeddings/rebuild")
def admin_rebuild_embeddings(
    limit: int | None = None,
    db_sess: Session = Depends(get_db),
):
    svc = EmbeddingService()
    n = embeddings_admin.rebuild_embeddings(db_sess, svc, limit=limit)
    return {"embedded": n, "model": svc.model_name}


if __name__ == "__main__":
    # Run the ASGI server locally:
    #   python -m backend.main
    # or:
    #   uvicorn backend.main:app --reload
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
