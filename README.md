# ScholarScout (PC Finder) — Explainable PC Member Discovery & Ranking

ScholarScout is a full-stack system that helps conference organizers **discover and rank** potential Program Committee (PC) members using a blend of:

- **Expertise matching** (topics + semantic similarity)
- **Recent activity** (publication recency signals)
- **Scientometric impact** (works_count, cited_by_count, h_index, counts_by_year)
- **Community structure** (PageRank over a co-PC network)
- **Explainability** (score breakdown returned per candidate)

This repository contains:
- a **FastAPI backend** that exposes a stable REST API
- a **Next.js frontend** that consumes the API and provides a modern UI
- a **data pipeline** that starts from scraped conference committee pages and produces JSON used for ingestion


---

## Key Features

- **Conference-aware recommendations**
  - Query by `conference_series`, `year`, and `topics`
- **Explainable scoring**
  - Each recommendation includes a full score breakdown
- **Graph-based community signal**
  - PageRank computed on a co-service (co-PC) network
- **OpenAlex enrichment (optional)**
  - Fetch impact stats and attach topics/activity signals
- **Extensible pipeline**
  - Scraper → JSON dataset → ingestion → DB → ranking → API → frontend


---

## Tech Stack

**Backend**
- Python + FastAPI
- SQLAlchemy ORM
- SQLite (dev/demo; easy to switch to Postgres)

**Frontend**
- Next.js (React)
- Tailwind CSS (UI styling)

**Optional / Enrichment**
- OpenAlex API (via `httpx`)

---

## Repository Structure (high level)

```txt
backend/
  main.py                # FastAPI app + routes
  models.py              # SQLAlchemy models
  schemas.py             # Pydantic schemas
  ingestion.py           # JSON → database ingestion
  ranking.py             # ranking logic (topic/impact/recency/pagerank)
  semantic.py            # semantic query endpoint 
  openalex_service.py    # OpenAlex enrichment utilities
  sample_data/pc_data.json

frontend/                # Next.js app (UI)
  (Next.js files)

enrich_openalex.py       # optional CLI enrichment script
requirements.txt
README.md
```

---

## Data Collection (Scraper → JSON)

ScholarScout’s dataset starts from **public conference committee pages**. We used a scraper to:

1. collect the committee rosters per conference edition (series/year)
2. extract structured fields (name, affiliation, country, profile URLs when available)
3. normalize and clean the outputs
4. export a consistent JSON dataset (e.g., `pc_data.json`) for ingestion

The ingestion module then transforms this JSON into normalized database tables:
- `Researcher`
- `ConferenceEdition`
- `PCMembership`
- `Topic` (+ association table)



---

## Quickstart

### 1) Backend Setup (FastAPI)

From the project root:

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

Run the API:

```bash
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

On startup the backend will typically:
- create the local SQLite database (if configured that way)
- ingest `backend/sample_data/pc_data.json` when the DB is empty

API docs (Swagger):
- `http://127.0.0.1:8000/docs`

---

### 2) Frontend Setup (Next.js)

Prereqs:
- Node.js 18+ (recommended)

From the `frontend/` folder:

```bash
npm install
npm run dev
```

Then open:
- `http://localhost:3000`

If your frontend needs the backend URL, set it via an env var:

```bash
# frontend/.env.local
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
```

---

## API Endpoints (Quick Reference)

> Endpoint names can vary slightly depending on your current branch, but the core idea is stable.

### `GET /`
Health check.

### `GET /recommendations` (or `POST /recommend`)
Inputs typically include:
- `conference_series` (optional) — e.g., `ICSME`
- `year` (optional) — e.g., `2025`
- `topics` (optional) — list or comma-separated string
- `years_back` (optional) — recency window, default `3`

Returns:
- ranked researchers
- `score_breakdown` per result item

### `GET /researchers/{researcher_id}`
Returns a profile view:
- affiliation/country
- topics
- PC history
- recent publications (if stored)

### Semantic Query Endpoint
Some versions include a semantic endpoint such as `POST /semantic-query` backed by embeddings, returning ranked researchers with explanation strings.

---

## Ranking Signals (What Data Is Used)

ScholarScout combines multiple signals:

1. **Topic match**
   - overlap between query topics and researcher topics/interests
2. **Semantic match**
   - embedding similarity between query text and researcher profile text
3. **Publication activity / recency**
   - derived from `counts_by_year` (and/or stored publications)
4. **PC service recency**
   - how recently the researcher served on relevant PCs
5. **Impact**
   - `works_count`, `cited_by_count`, `h_index` (and trends via `counts_by_year`)
6. **Network centrality**
   - PageRank on a co-PC graph (proxy for community connectivity)

Each response returns a **score breakdown** so the ranking remains explainable.

---

## OpenAlex Enrichment (Optional)

ScholarScout supports an optional OpenAlex enrichment flow to populate/refresh scientometric signals and activity histories.

### CLI enrichment
```bash
source .venv/bin/activate
export OPENALEX_MAILTO="your-email@example.com"   # recommended
python enrich_openalex.py
```

> CLI is recommended for controlled runs and monitoring.

---

## Troubleshooting

### Backend starts but scores look “flat” (e.g., PageRank = 1.0 everywhere)
This usually means:
- the graph has too few nodes/edges (tiny dataset), or
- enrichment has not been run (missing variation in impact/activity), or
- the recency window makes many candidates equally “recent” (e.g., only 1 year of roster data)

Fixes:
- ingest more years / more conference editions
- run OpenAlex enrichment to improve impact/activity signals
- verify PageRank caching is enabled and recomputed after ingestion

### Frontend cannot call backend (CORS)
- Ensure backend is running on `127.0.0.1:8000`
- Ensure frontend uses the correct API base URL
- Ensure CORS middleware allows the frontend origin (e.g., `http://localhost:3000`)

---

## Roadmap / Future Work

### 1) Paper-aware matching (Title + Abstract → Best PC members)
Goal: upload a set of papers (or title+abstract metadata) and recommend the best-matching PC members for *each paper*.

High-level process:
1. build a paper text representation (title + abstract)
2. embed paper text using the same embedding model
3. embed researcher profiles (bio + interests + publications)
4. rank researchers per paper using cosine similarity + suitability signals (impact, recency, PC experience)
5. return top-K candidates per paper with explanations

### 2) Conflict-of-interest checks and assignment constraints
- co-author conflicts
- affiliation conflicts
- load balancing (max papers per reviewer)
- optional fairness/diversity constraints (policy-dependent)

### 3) Stronger identity resolution
- OpenAlex IDs / ORCID integration
- improved author disambiguation

---


---

## Acknowledgements
- OpenAlex for public scholarly metadata
