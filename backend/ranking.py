# backend/ranking.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Any

import json
import math
import re
import time
import hashlib

import networkx as nx
from sqlalchemy.orm import Session
from sqlalchemy import text

from . import models


# -----------------------------
# Public API
# -----------------------------

@dataclass
class QueryContext:
    conference_series: Optional[str]
    year: Optional[int]
    topics: List[str]
    years_back: int = 3


@dataclass
class RankingWeights:
    #total does not have to sum to 1; we clamp sub-scores to [0,1]
    topic: float = 0.30
    semantic: float = 0.25
    pub_recency: float = 0.12
    pc_recency: float = 0.18
    impact: float = 0.10
    pagerank: float = 0.03
    experience: float = 0.02
    newcomer: float = 0.05 


class RankingService:
    """
    ranking:
    - Topic similarity: weighted phrase matching (no Jaccard)
    - Semantic similarity: sentence-transformers embeddings with DB cache 
    - Publication recency: uses counts_by_year, falls back to publications table
    - PC recency: decayed + count bonus within the window
    - Impact: uses cited_by_count/citation_count + h_index + works_count
    - PageRank: cached in DB using signature of the membership graph
    """

    # ---- PageRank cache config ----
    _PR_CACHE_KEY = "co_pc_pagerank_v2"
    _PR_CACHE_TTL_SEC = 24 * 60 * 60  # 24 hours (safe default)

    # ---- Embeddings cache config ----
    _EMB_TABLE = "researcher_embeddings"
    _EMB_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"  # good default
    _EMB_MAX_PUB_TITLES = 50

    def __init__(self, db_sess: Session):
        self.db = db_sess
        self._embedder = None 

    # -----------------------------
    # Utilities
    # -----------------------------

    @staticmethod
    def _clamp01(x: float) -> float:
        if x < 0.0:
            return 0.0
        if x > 1.0:
            return 1.0
        return x

    @staticmethod
    def _norm_text(s: Optional[str]) -> str:
        s = (s or "").strip().lower()
        s = re.sub(r"[^a-z0-9\s\-_/]", " ", s)
        s = re.sub(r"\s+", " ", s).strip()
        return s

    @staticmethod
    def _tokenize(s: str) -> List[str]:
        s = RankingService._norm_text(s)
        if not s:
            return []
        # keep meaningful tokens, drop tiny noise
        toks = [t for t in re.split(r"[\s\-/_,;]+", s) if len(t) >= 2]
        return toks

    @staticmethod
    def _cosine(a: List[float], b: List[float]) -> float:
        # pure-python cosine to avoid hard dependency on numpy in this file
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = 0.0
        na = 0.0
        nb = 0.0
        for x, y in zip(a, b):
            dot += x * y
            na += x * x
            nb += y * y
        den = math.sqrt(na) * math.sqrt(nb)
        if den <= 0:
            return 0.0
        return dot / den

    @staticmethod
    def _safe_log_norm(x: float, cap: float) -> float:
        """
        log1p(x) normalized by log1p(cap). cap is a "reasonable upper bound".
        """
        if x <= 0:
            return 0.0
        denom = math.log1p(max(1.0, cap))
        if denom <= 0:
            return 0.0
        return RankingService._clamp01(math.log1p(x) / denom)

    # -----------------------------
    # Topic collection + weighted matching
    # -----------------------------

    def _collect_researcher_topics(self, researcher: models.Researcher) -> List[str]:
        """
        Collect topic-like phrases from:
        - research_interests (free text) if present
        - Topic relationship names
        """
        out: List[str] = []

        # free-text interests 
        interests = getattr(researcher, "research_interests", None)
        if interests:
            for part in re.split(r"[;,/]", interests):
                t = self._norm_text(part)
                if t:
                    out.append(t)

        # normalized Topic nodes
        for t in getattr(researcher, "topics", []) or []:
            name = self._norm_text(getattr(t, "name", None))
            if name:
                out.append(name)

        # dedupe while preserving order
        seen = set()
        uniq = []
        for x in out:
            if x not in seen:
                seen.add(x)
                uniq.append(x)
        return uniq

    def _phrase_token_similarity(self, a: str, b: str) -> float:
        """
        Token-overlap similarity in [0,1] between two phrases.
        This replaces Jaccard-over-sets-of-topics with "weighted matching":
        - we compute token overlap for each query phrase against best researcher phrase
        """
        ta = set(self._tokenize(a))
        tb = set(self._tokenize(b))
        if not ta or not tb:
            return 0.0
        inter = len(ta & tb)
        if inter == 0:
            return 0.0
        # Sørensen–Dice coefficient (often nicer than Jaccard for short phrases)
        return (2.0 * inter) / (len(ta) + len(tb))

    def _topic_similarity_weighted(self, researcher: models.Researcher, ctx: QueryContext) -> float:
        query_phrases = [self._norm_text(t) for t in (ctx.topics or []) if self._norm_text(t)]
        cand_phrases = self._collect_researcher_topics(researcher)

        if not query_phrases or not cand_phrases:
            return 0.0

        # For each query phrase, find best match among candidate phrases
        # Weight longer query phrases slightly higher (more specific)
        total_w = 0.0
        total_s = 0.0

        for qp in query_phrases:
            q_tokens = self._tokenize(qp)
            w = 1.0 + 0.15 * max(0, len(q_tokens) - 1)  # longer phrase => more weight
            best = 0.0
            for cp in cand_phrases:
                s = self._phrase_token_similarity(qp, cp)
                if s > best:
                    best = s
                    if best >= 0.95:
                        break
            total_w += w
            total_s += w * best

        if total_w <= 0:
            return 0.0
        return self._clamp01(total_s / total_w)

    # -----------------------------
    # Publication recency (counts_by_year preferred)
    # -----------------------------

    def _get_base_year(self, ctx: QueryContext) -> int:
        if ctx.year:
            return int(ctx.year)
        # fallback: use most recent conference year in DB if present
        max_year = self.db.query(models.ConferenceEdition.year).order_by(models.ConferenceEdition.year.desc()).first()
        if max_year and max_year[0]:
            return int(max_year[0])
        # last resort
        return time.gmtime().tm_year

    def _extract_counts_by_year(self, researcher: models.Researcher) -> List[Dict[str, Any]]:
        """
        Supports multiple storage styles:
        - researcher.counts_by_year already as list[dict]
        - researcher.counts_by_year as JSON string
        - researcher.counts_by_year as None
        """
        raw = getattr(researcher, "counts_by_year", None)
        if raw is None:
            return []

        if isinstance(raw, list):
            return [x for x in raw if isinstance(x, dict)]

        if isinstance(raw, str):
            try:
                data = json.loads(raw)
                if isinstance(data, list):
                    return [x for x in data if isinstance(x, dict)]
            except Exception:
                return []

        return []

    def _pub_recency_score(self, researcher: models.Researcher, ctx: QueryContext) -> float:
        """
        Uses counts_by_year if available (best).
        Otherwise falls back to publications table (if you populated it).
        Score ~ how much the researcher published recently (works_count-weighted, time-decayed).
        """
        base_year = self._get_base_year(ctx)
        start_year = base_year - max(0, int(ctx.years_back))

        counts = self._extract_counts_by_year(researcher)
        weighted_works = 0.0

        if counts:
            for row in counts:
                try:
                    y = int(row.get("year"))
                except Exception:
                    continue
                if y < start_year or y > base_year:
                    continue
                wc = row.get("works_count", row.get("worksCount", 0)) or 0
                try:
                    wc = float(wc)
                except Exception:
                    wc = 0.0
                age = max(0, base_year - y)
                decay = math.exp(-0.45 * age)
                weighted_works += wc * decay
        else:
            # fallback: derive from publications table
            pubs = getattr(researcher, "publications", []) or []
            for p in pubs:
                y = getattr(p, "year", None)
                if not y:
                    continue
                try:
                    y = int(y)
                except Exception:
                    continue
                if y < start_year or y > base_year:
                    continue
                age = max(0, base_year - y)
                decay = math.exp(-0.45 * age)
                weighted_works += 1.0 * decay

        # Normalize: 50-ish recent weighted works is "very strong"
        return self._safe_log_norm(weighted_works, cap=50.0)

    # -----------------------------
    # PC recency + experience
    # -----------------------------

    def _pc_recency_score(self, researcher: models.Researcher, ctx: QueryContext) -> float:
        """
        Combines:
        - most recent PC service year (decayed)
        - small bonus for multiple services within [base_year - years_back, base_year]
        """
        memberships = getattr(researcher, "pc_memberships", []) or []
        if not memberships:
            return 0.0

        base_year = self._get_base_year(ctx)
        start_year = base_year - max(0, int(ctx.years_back))

        years = []
        for m in memberships:
            conf = getattr(m, "conference", None)
            if not conf:
                continue
            y = getattr(conf, "year", None)
            if y is None:
                continue
            try:
                y = int(y)
            except Exception:
                continue
            years.append(y)

        if not years:
            return 0.0

        # focus on window
        in_window = [y for y in years if start_year <= y <= base_year]
        if not in_window:
            # if nothing in-window, still decay from most recent overall
            most_recent = max(years)
            age = max(0, base_year - most_recent)
            return self._clamp01(math.exp(-0.55 * age))

        most_recent = max(in_window)
        age = max(0, base_year - most_recent)
        base = math.exp(-0.55 * age)  # 0 years => 1.0

        # bonus for repeated service (helps avoid "all 1.0" ties when many served in same year)
        count_bonus = 1.0 + 0.12 * max(0, len(in_window) - 1)
        return self._clamp01(base * count_bonus)

    def _experience_score(self, researcher: models.Researcher, ctx: QueryContext) -> float:
        memberships = getattr(researcher, "pc_memberships", []) or []
        if not memberships:
            return 0.0

        if ctx.conference_series:
            c = 0
            for m in memberships:
                conf = getattr(m, "conference", None)
                if conf and getattr(conf, "series", None) == ctx.conference_series:
                    c += 1
        else:
            c = len(memberships)

        # normalize: 10 memberships is "maxed out"
        return self._clamp01(c / 10.0)

    # -----------------------------
    # Impact score (works_count + cited_by_count + h_index + optional cited_by_count history)
    # -----------------------------

    def _impact_score(self, researcher: models.Researcher) -> float:

        cited_by = getattr(researcher, "cited_by_count", None)
        if cited_by is None:
            # existing field in your codebase is citation_count
            cited_by = getattr(researcher, "citation_count", None)
        cited_by = int(cited_by or 0)

        h = int(getattr(researcher, "h_index", 0) or 0)

        works = getattr(researcher, "works_count", None)
        if works is None:
            works = getattr(researcher, "worksCount", None)
        works = int(works or 0)

        cited_norm = self._safe_log_norm(float(cited_by), cap=150_000.0)
        h_norm = self._clamp01(h / 90.0)
        works_norm = self._safe_log_norm(float(works), cap=800.0)

        # weights: citations + h-index dominate; works_count is mild signal
        score = 0.50 * cited_norm + 0.35 * h_norm + 0.15 * works_norm
        return self._clamp01(score)

    # -----------------------------
    # PageRank (cached)
    # -----------------------------

    def _ensure_pagerank_cache_table(self) -> None:
        self.db.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS pagerank_cache (
                    cache_key TEXT PRIMARY KEY,
                    computed_at INTEGER NOT NULL,
                    signature TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
        )
        self.db.commit()

    def _pagerank_signature(self) -> str:
        """
        Create a cheap signature that changes when the graph changes.
        (Good enough without a heavyweight edge-hash.)
        """
        members = self.db.query(models.PCMembership).count()
        researchers = self.db.query(models.Researcher).count()
        confs = self.db.query(models.ConferenceEdition).count()
        max_year_row = self.db.query(models.ConferenceEdition.year).order_by(models.ConferenceEdition.year.desc()).first()
        max_year = int(max_year_row[0]) if max_year_row and max_year_row[0] else 0

        raw = f"m={members}|r={researchers}|c={confs}|y={max_year}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    def _load_pagerank_cache(self) -> Optional[Dict[int, float]]:
        self._ensure_pagerank_cache_table()

        now = int(time.time())
        sig = self._pagerank_signature()

        row = self.db.execute(
            text("SELECT computed_at, signature, payload FROM pagerank_cache WHERE cache_key = :k"),
            {"k": self._PR_CACHE_KEY},
        ).fetchone()

        if not row:
            return None

        computed_at, signature, payload = int(row[0]), str(row[1]), str(row[2])
        if signature != sig:
            return None
        if (now - computed_at) > self._PR_CACHE_TTL_SEC:
            return None

        try:
            data = json.loads(payload)
            if not isinstance(data, dict):
                return None
            out: Dict[int, float] = {}
            for k, v in data.items():
                try:
                    out[int(k)] = float(v)
                except Exception:
                    continue
            return out
        except Exception:
            return None

    def _save_pagerank_cache(self, pr: Dict[int, float]) -> None:
        self._ensure_pagerank_cache_table()

        now = int(time.time())
        sig = self._pagerank_signature()
        payload = json.dumps({str(k): float(v) for k, v in pr.items()})

        self.db.execute(
            text(
                """
                INSERT INTO pagerank_cache (cache_key, computed_at, signature, payload)
                VALUES (:k, :t, :s, :p)
                ON CONFLICT(cache_key) DO UPDATE SET
                    computed_at=excluded.computed_at,
                    signature=excluded.signature,
                    payload=excluded.payload
                """
            ),
            {"k": self._PR_CACHE_KEY, "t": now, "s": sig, "p": payload},
        )
        self.db.commit()

    def _build_co_pc_graph(self) -> nx.Graph:
        """
        Co-PC graph:
        - nodes: researcher_id
        - edge weight: number of times two researchers appear on same conference edition committee
        """
        G = nx.Graph()

        memberships = self.db.query(models.PCMembership).all()
        by_conf: Dict[int, List[int]] = {}
        for m in memberships:
            by_conf.setdefault(m.conference_id, []).append(m.researcher_id)

        for _, r_ids in by_conf.items():
            # add nodes
            for rid in r_ids:
                if not G.has_node(rid):
                    G.add_node(rid)

            # add edges
            for i in range(len(r_ids)):
                for j in range(i + 1, len(r_ids)):
                    u, v = r_ids[i], r_ids[j]
                    if u == v:
                        continue
                    if G.has_edge(u, v):
                        G[u][v]["weight"] += 1
                    else:
                        G.add_edge(u, v, weight=1)

        return G

    def _pagerank_scores(self) -> Dict[int, float]:
        cached = self._load_pagerank_cache()
        if cached is not None:
            return cached

        G = self._build_co_pc_graph()
        if G.number_of_nodes() == 0:
            self._save_pagerank_cache({})
            return {}

        # Use robust power-iteration pagerank
        try:
            pr = nx.pagerank(G, weight="weight", alpha=0.85, max_iter=200, tol=1.0e-06)
        except Exception:
            # if anything goes wrong, degrade gracefully
            pr = {int(n): 0.0 for n in G.nodes()}

        # Min-max normalize into [0,1]. If all equal, make all zeros (prevents "all 1.0")
        vals = list(pr.values())
        if not vals:
            normed = {}
        else:
            vmin = min(vals)
            vmax = max(vals)
            if vmax - vmin <= 1.0e-12:
                normed = {int(k): 0.0 for k in pr.keys()}
            else:
                normed = {int(k): float((v - vmin) / (vmax - vmin)) for k, v in pr.items()}

        self._save_pagerank_cache(normed)
        return normed

    # -----------------------------
    # Semantic embeddings (cached)
    # -----------------------------

    def _ensure_embedding_table(self) -> None:
        self.db.execute(
            text(
                f"""
                CREATE TABLE IF NOT EXISTS {self._EMB_TABLE} (
                    researcher_id INTEGER PRIMARY KEY,
                    model_name TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    updated_at INTEGER NOT NULL,
                    embedding_json TEXT NOT NULL
                )
                """
            )
        )
        self.db.commit()

    def _lazy_load_embedder(self):
        if self._embedder is not None:
            return self._embedder
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
            self._embedder = SentenceTransformer(self._EMB_MODEL_NAME)
        except Exception:
            self._embedder = None
        return self._embedder

    def _researcher_text_for_embedding(self, r: models.Researcher) -> str:
        parts: List[str] = []

        bio = getattr(r, "bio", None)
        if bio:
            parts.append(str(bio))

        # publication titles (if present)
        pubs = getattr(r, "publications", []) or []
        # Most recent first if years exist
        pubs_sorted = sorted(pubs, key=lambda x: (getattr(x, "year", 0) or 0), reverse=True)
        for p in pubs_sorted[: self._EMB_MAX_PUB_TITLES]:
            title = getattr(p, "title", None)
            if title:
                parts.append(str(title))

        # fallback: if no pubs/bio, use topics / interests
        if not parts:
            topics = self._collect_researcher_topics(r)
            if topics:
                parts.append(" ".join(topics))

        return "\n".join(parts).strip()

    def _hash_text(self, s: str) -> str:
        return hashlib.sha1(s.encode("utf-8", errors="ignore")).hexdigest()

    def _load_cached_embedding(self, researcher_id: int) -> Optional[Tuple[str, List[float]]]:
        self._ensure_embedding_table()
        row = self.db.execute(
            text(
                f"""
                SELECT content_hash, embedding_json
                FROM {self._EMB_TABLE}
                WHERE researcher_id = :rid AND model_name = :mn
                """
            ),
            {"rid": researcher_id, "mn": self._EMB_MODEL_NAME},
        ).fetchone()

        if not row:
            return None

        content_hash = str(row[0])
        emb_json = str(row[1])
        try:
            emb = json.loads(emb_json)
            if not isinstance(emb, list):
                return None
            emb_f = [float(x) for x in emb]
            return content_hash, emb_f
        except Exception:
            return None

    def _save_cached_embedding(self, researcher_id: int, content_hash: str, emb: List[float]) -> None:
        self._ensure_embedding_table()
        now = int(time.time())
        self.db.execute(
            text(
                f"""
                INSERT INTO {self._EMB_TABLE} (researcher_id, model_name, content_hash, updated_at, embedding_json)
                VALUES (:rid, :mn, :ch, :t, :ej)
                ON CONFLICT(researcher_id) DO UPDATE SET
                    model_name=excluded.model_name,
                    content_hash=excluded.content_hash,
                    updated_at=excluded.updated_at,
                    embedding_json=excluded.embedding_json
                """
            ),
            {
                "rid": int(researcher_id),
                "mn": self._EMB_MODEL_NAME,
                "ch": content_hash,
                "t": now,
                "ej": json.dumps([float(x) for x in emb]),
            },
        )
        self.db.commit()

    def _semantic_score(self, researcher: models.Researcher, query_text: str) -> float:
        """
        Returns [0,1] semantic similarity between query and researcher profile text.
        Uses sentence-transformers if available; otherwise returns 0.
        """
        embedder = self._lazy_load_embedder()
        if embedder is None:
            return 0.0

        query_text = (query_text or "").strip()
        if not query_text:
            return 0.0

        r_text = self._researcher_text_for_embedding(researcher)
        if not r_text:
            return 0.0

        # cached researcher embedding keyed by content hash
        rid = int(getattr(researcher, "id"))
        r_hash = self._hash_text(r_text)
        cached = self._load_cached_embedding(rid)

        if cached and cached[0] == r_hash:
            r_emb = cached[1]
        else:
            # compute and cache
            r_vec = embedder.encode(r_text, normalize_embeddings=True)
            # convert to python list
            try:
                r_emb = [float(x) for x in r_vec.tolist()]
            except Exception:
                r_emb = [float(x) for x in list(r_vec)]
            self._save_cached_embedding(rid, r_hash, r_emb)

        # query embedding 
        q_vec = embedder.encode(query_text, normalize_embeddings=True)
        try:
            q_emb = [float(x) for x in q_vec.tolist()]
        except Exception:
            q_emb = [float(x) for x in list(q_vec)]

        # cosine in [-1,1] => map to [0,1]
        cos = self._cosine(q_emb, r_emb)
        return self._clamp01((cos + 1.0) / 2.0)

    # -----------------------------
    # Ranking
    # -----------------------------

    def rank_candidates(
        self,
        ctx: QueryContext,
        weights: Optional[RankingWeights] = None,
        limit: int = 50,
    ) -> List[Tuple[models.Researcher, float, dict]]:
        if weights is None:
            weights = RankingWeights()

        researchers = self.db.query(models.Researcher).all()
        if not researchers:
            return []

        pr_scores = self._pagerank_scores()

        # Semantic query text: use topic phrases joined, plus conference hint
        q_parts = []
        if ctx.topics:
            q_parts.append(", ".join([t for t in ctx.topics if t]))
        if ctx.conference_series:
            q_parts.append(f"conference {ctx.conference_series}")
        query_text = " | ".join(q_parts).strip()

        results: List[Tuple[models.Researcher, float, dict]] = []

        for r in researchers:
            topic_sim = self._topic_similarity_weighted(r, ctx)
            semantic_score = self._semantic_score(r, query_text) if weights.semantic > 0 else 0.0
            pub_recency_score = self._pub_recency_score(r, ctx)
            pc_recency_score = self._pc_recency_score(r, ctx)
            impact_score = self._impact_score(r)
            pagerank_score = float(pr_scores.get(int(r.id), 0.0))
            experience_score = self._experience_score(r, ctx)

            # Optional newcomer score: reward fewer past PC services (diversity),
            # but only if they still match topics/semantic
            newcomer_score = 0.0
            if weights.newcomer > 0:
                memberships = getattr(r, "pc_memberships", []) or []
                # fewer memberships => higher newcomer
                newcomer_score = self._clamp01(1.0 - min(1.0, len(memberships) / 8.0))
                # gate by relevance so random newcomers don't float up
                newcomer_score *= max(topic_sim, semantic_score)

            total = (
                weights.topic * topic_sim
                + weights.semantic * semantic_score
                + weights.pub_recency * pub_recency_score
                + weights.pc_recency * pc_recency_score
                + weights.impact * impact_score
                + weights.pagerank * pagerank_score
                + weights.experience * experience_score
                + weights.newcomer * newcomer_score
            )

            breakdown = {
                "topic_sim": float(topic_sim),
                "semantic_score": float(semantic_score),
                "pub_recency_score": float(pub_recency_score),
                "pc_recency_score": float(pc_recency_score),
                "impact_score": float(impact_score),
                "pagerank_score": float(pagerank_score),
                "experience_score": float(experience_score),
                "newcomer_score": float(newcomer_score),
            }

            results.append((r, float(total), breakdown))

        results.sort(key=lambda x: x[1], reverse=True)
        return results[: max(1, int(limit))]
