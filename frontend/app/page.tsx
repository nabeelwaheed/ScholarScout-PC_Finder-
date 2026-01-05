"use client";

import React from "react";
import Link from "next/link";
import { apiDocsUrl, recommend, type RecommendationItem, type RecommendationQuery, type ScoreBreakdown } from "../lib/api";

function Pill({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center rounded-full border border-white/10 bg-white/5 px-2.5 py-1 text-xs text-white/80">
      {children}
    </span>
  );
}

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
      <div className="text-xs text-white/60">{label}</div>
      <div className="mt-1 font-mono text-lg">{value}</div>
    </div>
  );
}

function clamp01(x: number) {
  return Math.max(0, Math.min(1, x));
}

function Progress({ value }: { value: number }) {
  const v = clamp01(value);
  return (
    <div className="h-2 w-full rounded-full bg-white/10">
      <div className="h-2 rounded-full bg-white" style={{ width: `${v * 100}%` }} />
    </div>
  );
}

function Modal({
  open,
  title,
  onClose,
  children,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <div className="absolute inset-0 flex items-center justify-center p-4">
        <div className="w-full max-w-xl rounded-3xl border border-white/10 bg-black shadow-glow">
          <div className="flex items-center justify-between border-b border-white/10 px-6 py-4">
            <div className="text-sm font-semibold">{title}</div>
            <button
              onClick={onClose}
              className="rounded-xl border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-white/80 hover:bg-white/10"
            >
              Close
            </button>
          </div>
          <div className="px-6 py-5">{children}</div>
        </div>
      </div>
    </div>
  );
}

function ScoreBreakdownView({ b }: { b: ScoreBreakdown }) {
  const rows: Array<{ k: keyof ScoreBreakdown; label: string; note?: string }> = [
    { k: "topic_sim", label: "Topic match" },
    { k: "semantic_score", label: "Semantic (embeddings)", note: "If cosine is used, negatives may appear as 0 in bars." },
    { k: "pub_recency_score", label: "Publication recency" },
    { k: "pc_recency_score", label: "PC recency" },
    { k: "impact_score", label: "Impact" },
    { k: "pagerank_score", label: "PageRank" },
    { k: "experience_score", label: "Experience" },
    { k: "newcomer_score", label: "Newcomer" },
  ];

  return (
    <div className="space-y-4">
      {rows.map((r) => (
        <div key={r.k} className="space-y-2">
          <div className="flex items-center justify-between text-sm">
            <div className="text-white/80">
              {r.label}
              {r.note ? <div className="text-xs text-white/50">{r.note}</div> : null}
            </div>
            <div className="font-mono text-white">{Number(b[r.k]).toFixed(3)}</div>
          </div>
          <Progress value={Number(b[r.k])} />
        </div>
      ))}
    </div>
  );
}

export default function Home() {
  const [conference, setConference] = React.useState("");
  const [year, setYear] = React.useState("");
  const [yearsBack, setYearsBack] = React.useState("3");
  const [topics, setTopics] = React.useState("");

  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [items, setItems] = React.useState<RecommendationItem[]>([]);

  const [openModal, setOpenModal] = React.useState(false);
  const [selected, setSelected] = React.useState<RecommendationItem | null>(null);

  async function run() {
    setLoading(true);
    setError(null);

    const payload: RecommendationQuery = {
      conference_series: conference.trim() || null,
      year: year.trim() ? Number(year.trim()) : null,
      topics: topics.split(",").map((t) => t.trim()).filter(Boolean),
      years_back: yearsBack.trim() ? Number(yearsBack.trim()) : 3,
    };

    try {
      const res = await recommend(payload);
      setItems(res.results || []);
    } catch (e: any) {
      setError(e?.message ? String(e.message) : String(e));
      setItems([]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="relative">
      <div className="pointer-events-none absolute inset-0 overflow-hidden">
        <div className="absolute -top-40 left-1/2 h-[520px] w-[820px] -translate-x-1/2 rounded-full bg-gradient-to-r from-fuchsia-600/25 via-indigo-600/25 to-cyan-500/25 blur-3xl" />
        <div className="absolute bottom-[-220px] left-[-120px] h-[520px] w-[520px] rounded-full bg-gradient-to-r from-emerald-500/20 to-cyan-500/10 blur-3xl" />
      </div>

      <div className="mx-auto max-w-6xl px-6 py-10">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="h-9 w-9 rounded-2xl bg-white/10 ring-1 ring-white/10" />
            <div>
              <div className="text-sm font-semibold tracking-wide">ScholarScout</div>
              <div className="text-xs text-white/60">Find the right experts for your conference in seconds, with transparent scoring.</div>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <a
              href={apiDocsUrl()}
              target="_blank"
              className="rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs text-white/80 hover:bg-white/10"
            >
              API Docs
            </a>
          </div>
        </div>

        <section className="mt-10 rounded-3xl border border-white/10 bg-white/[0.04] p-8 shadow-glow">
          <div className="flex flex-col gap-6 md:flex-row md:items-end md:justify-between">
            <div>
              <h1 className="text-3xl font-semibold tracking-tight md:text-4xl">Discover Program Committee candidates</h1>
              <p className="mt-2 max-w-2xl text-sm text-white/65">
                ScholarScout is a research-intelligence platform that helps conference chairs and organizers identify high-quality Program Committee candidates with clear, explainable reasoning. It ingests committee rosters and publication metadata, enriches profiles with impact signals (e.g., citations and h-index), and builds an expertise graph that captures relationships and prior service. ScholarScout then ranks candidates using a weighted blend of topical fit, semantic similarity from publication-based embeddings, recency of contributions and PC service, and network centrality—returning not just a list, but a transparent score breakdown for every recommendation.
              </p>
              <div className="mt-4 flex flex-wrap gap-2">
                <Pill>Explainable scores</Pill>
                <Pill>Embeddings-ready</Pill>
                <Pill>OpenAlex enrichment</Pill>
              </div>
            </div>

          
          </div>

          <div className="mt-8 grid grid-cols-1 gap-4 md:grid-cols-4">
            <div className="md:col-span-1">
              <label className="text-xs text-white/60">Conference series</label>
              <input
                className="mt-2 h-11 w-full rounded-2xl border border-white/10 bg-black/40 px-3 text-sm text-white outline-none focus:ring-2 focus:ring-white/10"
                placeholder="ICSE / FSE / ICSME"
                value={conference}
                onChange={(e) => setConference(e.target.value)}
              />
            </div>

            <div className="md:col-span-1">
              <label className="text-xs text-white/60">Target year</label>
              <input
                className="mt-2 h-11 w-full rounded-2xl border border-white/10 bg-black/40 px-3 text-sm text-white outline-none focus:ring-2 focus:ring-white/10"
                placeholder="2026"
                value={year}
                onChange={(e) => setYear(e.target.value)}
              />
            </div>

            <div className="md:col-span-1">
              <label className="text-xs text-white/60">Years back</label>
              <input
                className="mt-2 h-11 w-full rounded-2xl border border-white/10 bg-black/40 px-3 text-sm text-white outline-none focus:ring-2 focus:ring-white/10"
                value={yearsBack}
                onChange={(e) => setYearsBack(e.target.value)}
              />
            </div>

            <div className="md:col-span-1">
              <label className="text-xs text-white/60">Topics (comma-separated)</label>
              <input
                className="mt-2 h-11 w-full rounded-2xl border border-white/10 bg-black/40 px-3 text-sm text-white outline-none focus:ring-2 focus:ring-white/10"
                placeholder="testing, program analysis, security"
                value={topics}
                onChange={(e) => setTopics(e.target.value)}
              />
            </div>

            <div className="md:col-span-4 flex items-center justify-between">
              
              <button
                onClick={run}
                disabled={loading}
                className="rounded-2xl bg-white px-4 py-2 text-sm font-semibold text-black hover:opacity-90 disabled:opacity-60"
              >
                {loading ? "Searching..." : "Search"}
              </button>
            </div>

            {error ? (
              <div className="md:col-span-4 rounded-2xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-200">
                {error}
              </div>
            ) : null}
          </div>
        </section>

        <section className="mt-8">
          <div className="mb-3 flex items-center justify-between">
            <div>
              <div className="text-sm font-semibold">Results</div>
              <div className="text-xs text-white/60">{items.length} candidates</div>
            </div>
          </div>

          <div className="overflow-hidden rounded-3xl border border-white/10 bg-white/[0.03] shadow-glow">
            {items.length === 0 ? (
              <div className="p-10 text-center">
                <div className="text-sm font-semibold">No results yet</div>
                <div className="mt-2 text-sm text-white/60">Run a search above to see candidates.</div>
              </div>
            ) : (
              <div className="divide-y divide-white/10">
                {items.map((it) => (
                  <div key={it.researcher.id} className="p-5 md:flex md:items-center md:justify-between">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <Link className="truncate text-sm font-semibold hover:underline" href={`/researcher/${it.researcher.id}`}>
                          {it.researcher.full_name}
                        </Link>
                        <Pill>{it.researcher.affiliation || "Unknown affiliation"}</Pill>
                        <Pill>{it.researcher.country || "Unknown country"}</Pill>
                      </div>

                      <div className="mt-3 flex flex-wrap gap-2">
                        {(it.researcher.topics || []).slice(0, 8).map((t) => (
                          <span key={t} className="inline-flex items-center rounded-full border border-white/10 bg-white/5 px-2.5 py-1 text-xs text-white/75">
                            {t}
                          </span>
                        ))}
                      </div>
                    </div>

                    <div className="mt-4 flex items-center gap-3 md:mt-0">
                      <div className="text-right">
                        <div className="font-mono text-sm">{it.score.toFixed(4)}</div>
                        <div className="text-xs text-white/60">total score</div>
                      </div>
                      <button
                        className="rounded-2xl border border-white/10 bg-white/5 px-4 py-2 text-sm text-white/85 hover:bg-white/10"
                        onClick={() => {
                          setSelected(it);
                          setOpenModal(true);
                        }}
                      >
                        Explain
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </section>

        <footer className="mt-10 pb-10 text-xs text-white/50"></footer>

        <Modal open={openModal} title="Score breakdown" onClose={() => setOpenModal(false)}>
          {selected ? <ScoreBreakdownView b={selected.score_breakdown} /> : null}
        </Modal>
      </div>
    </main>
  );
}
