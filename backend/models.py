# backend/models.py
from sqlalchemy import (
    Column,
    Integer,
    String,
    ForeignKey,
    Text,
    DateTime,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from .db import Base


class Researcher(Base):
    __tablename__ = "researchers"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String, index=True)
    normalized_name = Column(String, index=True)

    affiliation = Column(String, nullable=True)
    country = Column(String, nullable=True)
    bio = Column(Text, nullable=True)
    person_profile_url = Column(String, nullable=True)

    # Used by ingestion
    research_interests = Column(Text, nullable=True)

    # OpenAlex-style impact fields
    works_count = Column(Integer, nullable=True)         # total works
    cited_by_count = Column(Integer, nullable=True)      # total citations (OpenAlex naming)
    counts_by_year = Column(Text, nullable=True)         # JSON text (list[{"year":..., "works_count":..., "cited_by_count":...}])

    # Backward-compat fields
    citation_count = Column(Integer, nullable=True)      
    h_index = Column(Integer, nullable=True)

    # Embedding fields
    profile_text = Column(Text, nullable=True)
    embedding = Column(Text, nullable=True)              # JSON string: "[0.12, -0.03, ...]"
    embedding_model = Column(String, nullable=True)
    embedding_updated_at = Column(DateTime, nullable=True)

    pc_memberships = relationship("PCMembership", back_populates="researcher")
    publications = relationship("Publication", back_populates="researcher")
    topics = relationship("Topic", secondary="researcher_topics", back_populates="researchers")


class ConferenceEdition(Base):
    __tablename__ = "conference_editions"
    __table_args__ = (
        UniqueConstraint("series", "year", name="uq_conference_series_year"),
    )

    id = Column(Integer, primary_key=True, index=True)
    series = Column(String, index=True)  # e.g., ICSME
    year = Column(Integer, index=True)
    committee_page_url = Column(String, nullable=True)

    pc_memberships = relationship("PCMembership", back_populates="conference")


class PCMembership(Base):
    __tablename__ = "pc_memberships"

    id = Column(Integer, primary_key=True, index=True)
    researcher_id = Column(Integer, ForeignKey("researchers.id"), index=True)
    conference_id = Column(Integer, ForeignKey("conference_editions.id"), index=True)
    role = Column(String, default="pc_member")

    researcher = relationship("Researcher", back_populates="pc_memberships")
    conference = relationship("ConferenceEdition", back_populates="pc_memberships")


class Publication(Base):
    __tablename__ = "publications"

    id = Column(Integer, primary_key=True, index=True)
    researcher_id = Column(Integer, ForeignKey("researchers.id"), index=True)
    title = Column(String)
    year = Column(Integer, nullable=True)
    venue = Column(String, nullable=True)

    researcher = relationship("Researcher", back_populates="publications")


class Topic(Base):
    __tablename__ = "topics"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)

    researchers = relationship("Researcher", secondary="researcher_topics", back_populates="topics")


class ResearcherTopic(Base):
    __tablename__ = "researcher_topics"

    researcher_id = Column(Integer, ForeignKey("researchers.id"), primary_key=True)
    topic_id = Column(Integer, ForeignKey("topics.id"), primary_key=True)
