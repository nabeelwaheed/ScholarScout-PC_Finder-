export type RecommendationQuery = {
  conference_series?: string | null;
  year?: number | null;
  topics: string[];
  years_back: number;
};

export type ScoreBreakdown = {
  topic_sim: number;
  semantic_score: number;
  pub_recency_score: number;
  pc_recency_score: number;
  impact_score: number;
  pagerank_score: number;
  experience_score: number;
  newcomer_score: number;
};

export type ResearcherShort = {
  id: number;
  full_name: string;
  affiliation?: string | null;
  country?: string | null;
  citation_count?: number | null;
  h_index?: number | null;
  topics: string[];
};

export type RecommendationItem = {
  researcher: ResearcherShort;
  score: number;
  score_breakdown: ScoreBreakdown;
};

export type RecommendationResponse = {
  query: RecommendationQuery;
  results: RecommendationItem[];
};

export type PCHistoryItem = { conference_series: string; year: number; role: string };
export type PublicationItem = { title: string; year?: number | null; venue?: string | null };

export type ResearcherDetail = {
  id: number;
  full_name: string;
  affiliation?: string | null;
  country?: string | null;
  citation_count?: number | null;
  h_index?: number | null;
  topics: string[];
  pc_history: PCHistoryItem[];
  recent_publications: PublicationItem[];
  person_profile_url?: string | null;
};

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API ${res.status}: ${text}`);
  }
  return res.json();
}

export function recommend(payload: RecommendationQuery): Promise<RecommendationResponse> {
  return request("/recommend", { method: "POST", body: JSON.stringify(payload) });
}

export function getResearcher(id: number): Promise<ResearcherDetail> {
  return request(`/researcher/${id}`, { method: "GET" });
}

export function apiDocsUrl(): string {
  return `${API_BASE}/docs`;
}
