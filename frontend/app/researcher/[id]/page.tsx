"use client";

import React from "react";
import Link from "next/link";
import { getResearcher, type ResearcherDetail } from "../../../lib/api";

function Pill({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center rounded-full border border-white/10 bg-white/5 px-2.5 py-1 text-xs text-white/80">
      {children}
    </span>
  );
}

export default function ResearcherPage({ params }: { params: { id: string } }) {
  const id = Number(params.id);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [r, setR] = React.useState<ResearcherDetail | null>(null);

  React.useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        setLoading(true);
        setError(null);
        const data = await getResearcher(id);
        if (mounted) setR(data);
      } catch (e: any) {
        if (mounted) setError(e?.message ? String(e.message) : String(e));
      } finally {
        if (mounted) setLoading(false);
      }
    })();
    return () => {
      mounted = false;
    };
  }, [id]);

  return (
    <main className="min-h-screen bg-black text-white">
      <div className="mx-auto max-w-5xl px-6 py-10">
        <div className="flex items-center justify-between">
          <Link href="/" className="text-sm font-semibold hover:underline">← Back</Link>
          <div className="text-xs text-white/60">Researcher detail</div>
        </div>

        <div className="mt-6 rounded-3xl border border-white/10 bg-white/[0.04] p-8 shadow-glow">
          {loading ? (
            <div className="text-sm text-white/70">Loading...</div>
          ) : error ? (
            <div className="rounded-2xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-200">{error}</div>
          ) : !r ? (
            <div className="text-sm text-white/70">Not found.</div>
          ) : (
            <>
              <div className="flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
                <div className="min-w-0">
                  <div className="text-2xl font-semibold tracking-tight">{r.full_name}</div>
                  <div className="mt-1 text-sm text-white/60">{r.affiliation || "Unknown affiliation"} · {r.country || "Unknown country"}</div>
                  <div className="mt-3 flex flex-wrap gap-2">{(r.topics || []).map((t) => <Pill key={t}>{t}</Pill>)}</div>
                </div>

                <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                  <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
                    <div className="text-xs text-white/60">Citations</div>
                    <div className="mt-1 font-mono text-lg">{r.citation_count ?? "-"}</div>
                  </div>
                  <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
                    <div className="text-xs text-white/60">h-index</div>
                    <div className="mt-1 font-mono text-lg">{r.h_index ?? "-"}</div>
                  </div>
                  <div className="col-span-2 rounded-2xl border border-white/10 bg-white/5 p-4">
                    <div className="text-xs text-white/60">Profile</div>
                    <div className="mt-1 text-sm">
                      {r.person_profile_url ? (
                        <a className="underline text-white/90" target="_blank" href={r.person_profile_url}>Open profile</a>
                      ) : (
                        <span className="text-white/60">—</span>
                      )}
                    </div>
                  </div>
                </div>
              </div>

              <div className="mt-8 grid gap-5 md:grid-cols-2">
                <div className="rounded-3xl border border-white/10 bg-white/[0.03] p-5">
                  <div className="text-sm font-semibold">PC history</div>
                  <div className="mt-4 space-y-2">
                    {(r.pc_history || []).slice(0, 20).map((m, idx) => (
                      <div key={idx} className="flex items-center justify-between text-sm">
                        <span className="text-white/80">{m.conference_series} {m.year}</span>
                        <span className="text-white/55">{m.role}</span>
                      </div>
                    ))}
                    {(r.pc_history || []).length === 0 ? <div className="text-sm text-white/60">No PC history found.</div> : null}
                  </div>
                </div>

                <div className="rounded-3xl border border-white/10 bg-white/[0.03] p-5">
                  <div className="text-sm font-semibold">Recent publications</div>
                  <div className="mt-4 space-y-3">
                    {(r.recent_publications || []).map((p, idx) => (
                      <div key={idx}>
                        <div className="text-sm font-medium text-white/90">{p.title}</div>
                        <div className="text-xs text-white/55">{p.venue || "Unknown venue"} · {p.year ?? "?"}</div>
                      </div>
                    ))}
                    {(r.recent_publications || []).length === 0 ? <div className="text-sm text-white/60">No publications found.</div> : null}
                  </div>
                </div>
              </div>
            </>
          )}
        </div>

        <footer className="mt-8 text-xs text-white/50">Tip: If topics/impact are empty, run your backend admin endpoints to enrich.</footer>
      </div>
    </main>
  );
}
