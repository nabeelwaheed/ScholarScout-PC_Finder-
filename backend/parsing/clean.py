from __future__ import annotations
import csv
from pathlib import Path
from typing import List, Dict
import re

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())

def clean_rows(rows: List[Dict]) -> List[Dict]:
    cleaned = []
    seen = set()
    for r in rows:
        r = dict(r)
        r["conference"] = (r.get("conference") or "").upper()
        if "committee" in r:
            r["committee"] = _norm(r["committee"])
        for k in ("name","affiliation","country"):
            if k in r and r[k] is not None:
                r[k] = _norm(r[k])
        key = (
            r.get("conference"),
            r.get("year"),
            r.get("committee"),
            r.get("name"),
            r.get("person_profile_url"),
        )
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(r)
    return cleaned

def write_csv(path: Path, rows: List[Dict], fieldnames: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            r = dict(r)
            val = r.get("research_interests")
            if isinstance(val, list):
                r["research_interests"] = "; ".join(val)
            elif val is None:
                r["research_interests"] = ""
            else:
                r["research_interests"] = str(val)
            w.writerow(r)

def make_summary(rows: List[Dict]) -> str:
    by = {}
    for r in rows:
        key = (r.get("conference"), r.get("year"), r.get("committee") or "UNKNOWN")
        by.setdefault(key, 0)
        by[key] += 1
    lines = ["# AutoPC Summary", ""]
    for (conf, year, committee), cnt in sorted(by.items()):
        lines.append(f"- {conf} {year} [{committee}]: {cnt} members")
    lines.append("")
    return "\n".join(lines)
