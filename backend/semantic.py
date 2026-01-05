from sqlalchemy.orm import Session
from . import models, ranking, schemas

class SemanticService:
    """
    Simplified semantic search / RAG stub:
    - Uses the same ranking engine
    - Treats query text as topic keywords (split by spaces)
    - Generates simple textual explanations
    """
    def __init__(self, db_sess: Session):
        self.db = db_sess
        self.ranking_svc = ranking.RankingService(db_sess)

    def handle_query(self, req: schemas.SemanticQueryRequest) -> schemas.SemanticQueryResponse:
        # naive "parsing": use all words longer than 3 chars as topics
        tokens = [t.strip(",.") for t in req.query.split() if len(t) > 3]
        ctx = ranking.QueryContext(
            conference_series=None,
            year=None,
            topics=tokens,
            years_back=req.years_back,
        )
        ranked = self.ranking_svc.rank_candidates(ctx, limit=30)

        items = []
        for r, total, breakdown in ranked:
            explanation = self._build_explanation(r, breakdown, ctx)
            items.append(
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
                    score=total,
                    explanation=explanation,
                )
            )

        return schemas.SemanticQueryResponse(query=req.query, results=items)

    def _build_explanation(self, r: models.Researcher, breakdown: dict, ctx: ranking.QueryContext) -> str:
        pieces = []
        if breakdown["topic_sim"] > 0:
            pieces.append("their topics match your query")
        if breakdown["pc_recency_score"] > 0.3:
            pieces.append("they recently served on program committees")
        if breakdown["impact_score"] > 0.3:
            pieces.append("they have solid citation impact")
        if breakdown["pagerank_score"] > 0.3:
            pieces.append("they are well-connected in the co-PC network")

        if not pieces:
            pieces.append("they appear in the PC data and roughly match your query")

        return f"{r.full_name} is recommended because " + ", and ".join(pieces) + "."
