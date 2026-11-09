"""
Reading and writing the agent's files:
  prospects.csv          - the businesses you want to contact
  output/results.jsonl   - one finished draft (or error) per business
  output/drafts.md/.csv  - readable copies of the drafts, best fit first
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

PROSPECT_COLS = [
    "type", "company", "website", "suburb_state", "industry", "contact_name",
    "contact_role", "email", "phone", "contact_page", "size_hint", "why_fit", "source",
]
DRAFT_STATUSES = ["NEEDS REVIEW", "READY", "SENT", "SKIPPED", "ERROR"]


def domain_of(url: str) -> str:
    url = (url or "").strip().lower()
    url = re.sub(r"^[a-z]+://", "", url)
    url = re.sub(r"^www\.", "", url)
    return url.split("/")[0]


def key_of(row: dict) -> str:
    return f"{(row.get('company') or '').strip().lower()}|{(row.get('website') or '').strip().lower()}"


# ------------------------------------------------------------------ prospects
def read_prospects(path: Path) -> list[dict]:
    if not Path(path).exists():
        return []
    with open(path, newline="") as f:
        rows = []
        for r in csv.DictReader(f):
            if not (r.get("company") or "").strip():
                continue
            row = {c: (r.get(c) or "").strip() for c in PROSPECT_COLS}
            row["type"] = (row["type"] or "client").lower()
            rows.append(row)
        return rows


def write_prospects(path: Path, rows: list[dict]) -> None:
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=PROSPECT_COLS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in PROSPECT_COLS})


def add_prospects(path: Path, new_rows: list[dict]) -> tuple[int, int]:
    """Append rows, skipping businesses already in the list (same website or same name)."""
    rows = read_prospects(path)
    seen_domains = {domain_of(r["website"]) for r in rows if r.get("website")}
    seen_names = {r["company"].strip().lower() for r in rows}
    added = skipped = 0
    for r in new_rows:
        name = (r.get("company") or "").strip()
        dom = domain_of(r.get("website", ""))
        if not name or name.lower() in seen_names or (dom and dom in seen_domains):
            skipped += 1
            continue
        rows.append({c: (r.get(c) or "").strip() for c in PROSPECT_COLS} | {"type": r.get("type") or "client"})
        seen_names.add(name.lower())
        if dom:
            seen_domains.add(dom)
        added += 1
    write_prospects(path, rows)
    return added, skipped


def update_prospect(path: Path, key: str, fields: dict) -> dict | None:
    rows = read_prospects(path)
    for r in rows:
        if key_of(r) == key:
            for k, v in fields.items():
                if k in PROSPECT_COLS:
                    r[k] = str(v).strip()
            write_prospects(path, rows)
            return r
    return None


def delete_prospects(path: Path, keys: list[str]) -> int:
    rows = read_prospects(path)
    keep = [r for r in rows if key_of(r) not in set(keys)]
    write_prospects(path, keep)
    return len(rows) - len(keep)


# ------------------------------------------------------------------ results
def read_results(path: Path) -> dict[str, dict]:
    done: dict[str, dict] = {}
    if Path(path).exists():
        for line in Path(path).read_text().splitlines():
            if line.strip():
                rec = json.loads(line)
                done[rec["key"]] = rec  # later lines win
    return done


def append_result(path: Path, rec: dict) -> None:
    with open(path, "a") as f:
        f.write(json.dumps(rec) + "\n")


def update_result(path: Path, key: str, fields: dict) -> dict | None:
    done = read_results(path)
    if key not in done:
        return None
    done[key].update(fields)
    with open(path, "w") as f:
        for rec in done.values():
            f.write(json.dumps(rec) + "\n")
    return done[key]


def write_outputs(records: list[dict], out_dir: Path) -> None:
    cols = ["status", "type", "company", "contact_name", "contact_role", "email", "phone",
            "contact_page", "fit_score", "price_estimate", "email_subject", "email_body",
            "follow_up_email", "linkedin_message", "call_opener", "fit_reason", "attendance_pain",
            "business_summary", "research_notes", "error"]
    ordered = sorted(records, key=lambda r: -int(r.get("fit_score") or 0))
    with open(Path(out_dir) / "drafts.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in ordered:
            w.writerow(r)

    lines = ["# PresenAIT outreach drafts", "",
             "Nothing here has been sent. Check every fact before sending.", ""]
    for r in ordered:
        lines.append(f"## {r['company']}  -  fit {r.get('fit_score', '?')}/5  ({r.get('type')})  [{r.get('status')}]")
        if r.get("error"):
            lines += [f"**Error:** {r['error']}", ""]
            continue
        lines += [
            f"**To:** {r.get('contact_name') or '-'} ({r.get('contact_role') or '-'}) {r.get('email') or ''}",
            f"**Why:** {r.get('fit_reason')}",
            f"**Price:** {r.get('price_estimate')}", "",
            f"**Subject:** {r.get('email_subject')}", "", r.get("email_body", ""), "",
            "**Follow-up (day 4):**", "", r.get("follow_up_email", ""), "",
            f"**LinkedIn:** {r.get('linkedin_message')}", "",
            f"**Call opener:** {r.get('call_opener')}", "", "---", "",
        ]
    (Path(out_dir) / "drafts.md").write_text("\n".join(lines))
