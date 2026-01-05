from pydantic import BaseModel, HttpUrl
from typing import Optional, List, Dict, Any
from . import models


class RecommendationQuery(BaseModel):
    conference_series: Optional[str] = None
    year: Optional[int] = None
    topics: List[str] = []
    years_back: int = 3


class ResearcherShort(BaseModel):
    id: int
    full_name: str
    affiliation: Optional[str]
    country: Optional[str]

    # Impact signals
    works_count: Optional[int] = None
    cited_by_count: Optional[int] = None
    citation_count: Optional[int] = None  # keep for backward compatibility
    h_index: Optional[int] = None

    topics: List[str] = []


class ScoreBreakdown(BaseModel):
    topic_sim: float
    semantic_score: float
    pub_recency_score: float
    pc_recency_score: float
    impact_score: float
    pagerank_score: float
    experience_score: float
    newcomer_score: float


class RecommendationItem(BaseModel):
    researcher: ResearcherShort
    score: float
    score_breakdown: ScoreBreakdown

    @staticmethod
    def from_internal(internal):
        r, total, breakdown = internal
        return RecommendationItem(
            researcher=ResearcherShort(
                id=r.id,
                full_name=r.full_name,
                affiliation=r.affiliation,
                country=r.country,
                works_count=getattr(r, "works_count", None),
                cited_by_count=getattr(r, "cited_by_count", None),
                citation_count=getattr(r, "citation_count", None),
                h_index=getattr(r, "h_index", None),
                topics=[t.name for t in r.topics],
            ),
            score=total,
            score_breakdown=ScoreBreakdown(**breakdown),
        )


class RecommendationResponse(BaseModel):
    query: RecommendationQuery
    results: List[RecommendationItem]


class SemanticQueryRequest(BaseModel):
    query: str
    years_back: int = 3


class SemanticQueryItem(BaseModel):
    researcher: ResearcherShort
    score: float
    explanation: str


class SemanticQueryResponse(BaseModel):
    query: str
    results: List[SemanticQueryItem]


class PCHistoryItem(BaseModel):
    conference_series: str
    year: int
    role: str


class PublicationItem(BaseModel):
    title: str
    year: Optional[int]
    venue: Optional[str]


class ResearcherDetail(BaseModel):
    id: int
    full_name: str
    affiliation: Optional[str]
    country: Optional[str]

    works_count: Optional[int]
    cited_by_count: Optional[int]
    citation_count: Optional[int]
    h_index: Optional[int]

    counts_by_year: Optional[Any] = None  # can be list/dict (we may parse JSON text)
    topics: List[str]
    pc_history: List[PCHistoryItem]
    recent_publications: List[PublicationItem]
    person_profile_url: Optional[HttpUrl]

    @staticmethod
    def from_model(r: models.Researcher) -> "ResearcherDetail":
        # Parse counts_by_year if it's stored as JSON text
        raw_cby = getattr(r, "counts_by_year", None)
        parsed_cby = None
        if isinstance(raw_cby, str) and raw_cby.strip():
            try:
                import json
                parsed_cby = json.loads(raw_cby)
            except Exception:
                parsed_cby = None
        else:
            parsed_cby = raw_cby

        return ResearcherDetail(
            id=r.id,
            full_name=r.full_name,
            affiliation=r.affiliation,
            country=r.country,
            works_count=getattr(r, "works_count", None),
            cited_by_count=getattr(r, "cited_by_count", None),
            citation_count=getattr(r, "citation_count", None),
            h_index=getattr(r, "h_index", None),
            counts_by_year=parsed_cby,
            topics=[t.name for t in r.topics],
            pc_history=[
                PCHistoryItem(
                    conference_series=m.conference.series,
                    year=m.conference.year,
                    role=m.role,
                )
                for m in r.pc_memberships
            ],
            recent_publications=[
                PublicationItem(
                    title=p.title,
                    year=p.year,
                    venue=p.venue,
                )
                for p in sorted(r.publications, key=lambda x: x.year or 0, reverse=True)[:5]
            ],
            person_profile_url=r.person_profile_url,
        )
