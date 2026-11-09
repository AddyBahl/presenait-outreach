#!/usr/bin/env python3
"""
PresenAIT outreach agent
========================

Two jobs:

  find   - searches the web for businesses of a given type in a given area
           (e.g. "commercial cleaning" near "Werribee VIC") and adds them to
           prospects.csv with their website, phone and contact page.
           It deliberately does NOT collect email addresses: Australia's
           Spam Act 2003 (s 20-22) bans software that harvests email addresses.

  draft  - researches each business in prospects.csv and drafts a personalised
           email, follow-up, LinkedIn message and call opener pitching
           PresenAIT attendance tracking. Nothing is ever sent.

Prospect "type":
  client  - a business that could use PresenAIT Time
  partner - a shopping centre that could refer its tenants for a referral fee

Command line (the dashboard, app.py, does the same things with buttons):
  python agent.py find --industry "commercial cleaning" --location "Werribee VIC" --count 10
  python agent.py draft --dry-run
  python agent.py draft --limit 5 --budget-usd 2
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import anthropic

from store import (
    add_prospects, append_result, key_of, read_prospects, read_results, write_outputs,
)

HERE = Path(__file__).resolve().parent
PROSPECTS_CSV = HERE / "prospects.csv"
OUTPUT_DIR = HERE / "output"

# --------------------------------------------------------------------------
# Pricing (USD per 1M tokens: input, output). Check
# https://platform.claude.com/docs/en/about-claude/pricing before relying on it.
# --------------------------------------------------------------------------
PRICES = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
}
MODELS = list(PRICES)
WEB_SEARCH_USD = 10.00 / 1000  # per search request

# Rough cost ranges (USD) used for estimates before a run
EST_PER_DRAFT = {"claude-opus-5-5": (0.12, 0.35), "claude-sonnet-5-5": (0.06, 0.18),
                 "claude-haiku-5-5": (0.02, 0.05)}
EST_PER_FIND = {"claude-opus-5-5": (0.15, 0.60), "claude-sonnet-5-5": (0.08, 0.35),
                "claude-haiku-5-5": (0.05, 0.12)}

# PresenAIT Time pricing (AUD per active staff / month, ex GST, $30 minimum)
PLAN_RATES = {"Lite": 5, "Core": 8, "Pro": 12}
PLAN_MINIMUM = 30

DEFAULT_REFERRAL = ("20% of each referred tenant's first-year subscription, and referred "
                    "tenants get their first month free")

# --------------------------------------------------------------------------
# What the agent knows about the product. Kept stable so it can be cached.
# --------------------------------------------------------------------------
PRODUCT_BRIEF = """\
PRODUCT: PresenAIT Time - attendance tracking for Australian workplaces.
Made by DataAIT Technologies Pty Ltd, Melbourne. Website: presenait.com

What it does:
- Staff clock in/out and take breaks on a shared tablet kiosk (PIN) or their own phone.
- Face recognition at the kiosk (Pro) and geo-fencing so phone clock-ins only work on site.
- PIN + Authenticator (TOTP) for stronger identity (Core and up).
- Hours and breaks become electronic timesheets automatically; managers approve them
  (1 level on Lite, 2 levels on Core/Pro) with an audit trail (Core and up).
- Approved hours export for payroll: CSV on every plan, custom templates from Core,
  Xero and MYOB presets on Pro. Payroll itself stays in Xero / MYOB / their payroll tool.
- Optional add-ons on the same staff record: RosterAIT (rostering) and CompliAIT
  (AI reads staff certificates and flags expiries).

Pricing (AUD per active staff per month, excluding GST, $30/month minimum on every plan):
- Lite  $5  - up to 15 staff, one site, shared tablet kiosk
- Core  $8  - unlimited staff, phone app, up to 3 geo-fenced sites, 2-level approvals
- Pro   $12 - unlimited staff and sites, face recognition, Xero/MYOB export presets
- 14-day free trial, no credit card. Sign up: app.presenait.com/signup

Why businesses care (use only claims that fit the prospect; never invent numbers):
- Stops "buddy punching" (one worker clocking in for another) and rounding-up of hours.
- Fair Work requires employers to keep accurate time and wage records for 7 years;
  poor records make underpayment claims hard to defend.
- No more paper timesheets or chasing hours before the pay run.
- Managers see who is on site right now, across multiple sites.
- Australian-built and supported, priced in AUD.

Existing customers (may be mentioned by name): Elite Panel Repairs (VIC),
Harmony Helping Hands (NDIS, NT), HighQ Advisory (VIC), Fix Core (VIC), Seker Patrol (NT).
"""

RESEARCH_SYSTEM = (
    "You research Australian businesses for a B2B salesperson. Be factual and brief. "
    "Use web search only to confirm details about the specific business named. "
    "If you cannot find the business, say so rather than guessing."
)

FIND_SYSTEM = (
    "You help an Australian B2B salesperson build a list of real businesses to contact. "
    "Only list businesses you actually found on the web, with their real website. "
    "Never invent businesses, websites or phone numbers. Never collect or list email addresses."
)

DRAFT_SYSTEM = (
    "You write short, honest B2B outreach for PresenAIT, an Australian attendance-tracking "
    "product. Plain Australian English, no hype, no exclamation marks, no emojis. "
    "Only use facts from the product brief and the research notes - never invent "
    "statistics, customers, or details about the prospect.\n\n" + PRODUCT_BRIEF
)

DRAFT_SCHEMA = {
    "type": "object",
    "properties": {
        "fit_score": {"type": "integer", "description": "1 (poor fit) to 5 (excellent fit)"},
        "fit_reason": {"type": "string"},
        "business_summary": {"type": "string"},
        "attendance_pain": {"type": "string", "description": "the most likely attendance/timesheet problem for this business"},
        "estimated_staff": {"type": "integer", "description": "best estimate of hourly/shift staff; 0 if unknown"},
        "suggested_plan": {"type": "string", "enum": ["Lite", "Core", "Pro"]},
        "email_subject": {"type": "string"},
        "email_body": {"type": "string", "description": "under 120 words, no signature"},
        "follow_up_email": {"type": "string", "description": "under 70 words, sent 4 days later, no signature"},
        "linkedin_message": {"type": "string", "description": "under 280 characters"},
        "call_opener": {"type": "string", "description": "30-second phone opener ending in a question"},
    },
    "required": [
        "fit_score", "fit_reason", "business_summary", "attendance_pain", "estimated_staff",
        "suggested_plan", "email_subject", "email_body", "follow_up_email",
        "linkedin_message", "call_opener",
    ],
    "additionalProperties": False,
}

FIND_SCHEMA = {
    "type": "object",
    "properties": {
        "businesses": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "company": {"type": "string"},
                    "website": {"type": "string"},
                    "suburb_state": {"type": "string"},
                    "phone": {"type": "string"},
                    "contact_page": {"type": "string"},
                    "size_hint": {"type": "string"},
                    "why_fit": {"type": "string"},
                },
                "required": ["company", "website", "suburb_state", "phone", "contact_page",
                             "size_hint", "why_fit"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["businesses"],
    "additionalProperties": False,
}

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")


@dataclass
class Config:
    model: str = "claude-opus-5-5"
    effort: str = "low"
    max_searches: int = 2
    budget_usd: float = 5.0
    sender_name: str = "[Your name]"
    sender_title: str = "[Your title]"
    sender_email: str = "[your@email]"
    referral_offer: str = DEFAULT_REFERRAL


class Spend:
    """Running estimate of API spend in USD."""

    def __init__(self, model: str):
        self.in_price, self.out_price = PRICES.get(model, PRICES["claude-opus-5-5"])
        self.total = 0.0

    def add(self, usage) -> float:
        cost = (
            (usage.input_tokens or 0) * self.in_price
            + (getattr(usage, "cache_creation_input_tokens", 0) or 0) * self.in_price * 1.25
            + (getattr(usage, "cache_read_input_tokens", 0) or 0) * self.in_price * 0.10
            + (usage.output_tokens or 0) * self.out_price
        ) / 1_000_000
        stu = getattr(usage, "server_tool_use", None)
        searches = (getattr(stu, "web_search_requests", 0) or 0) if stu else 0
        cost += searches * WEB_SEARCH_USD
        self.total += cost
        return cost


def estimate(model: str, n: int, kind: str = "draft") -> tuple[float, float]:
    lo, hi = (EST_PER_FIND if kind == "find" else EST_PER_DRAFT).get(model, EST_PER_DRAFT["claude-opus-5-5"])
    return lo * n, hi * n


# --------------------------------------------------------------------------
# API helpers
# --------------------------------------------------------------------------
def make_client() -> anthropic.Anthropic:
    return anthropic.Anthropic()


def uses_server_fallbacks(model: str) -> bool:
    # Server-side refusal fallbacks exist for Opus/Sonnet/Fable, not Haiku 5.5.
    return not model.startswith("claude-haiku")


def web_tools(model: str, max_searches: int, max_fetches: int = 2) -> list[dict]:
    newer = not model.startswith("claude-haiku")
    return [
        {
            "type": "web_search_20260209" if newer else "web_search_20250305",
            "name": "web_search",
            "max_uses": max_searches,
            "user_location": {"type": "approximate", "country": "AU"},
        },
        {
            "type": "web_fetch_20260209" if newer else "web_fetch_20250910",
            "name": "web_fetch",
            "max_uses": max_fetches,
            "max_content_tokens": 6000,
        },
    ]


def call_claude(client, cfg: Config, *, system: str, messages: list, max_tokens: int,
                tools: list | None = None, output_format: dict | None = None):
    output_config: dict = {"effort": cfg.effort}
    if output_format:
        output_config["format"] = output_format
    params = dict(
        model=cfg.model,
        max_tokens=max_tokens,
        system=system,
        messages=messages,
        output_config=output_config,
        cache_control={"type": "ephemeral"},  # reuses the stable system prompt across calls
    )
    if tools:
        params["tools"] = tools
    if uses_server_fallbacks(cfg.model):
        # If a safety classifier declines, the API retries on a recommended model.
        return client.beta.messages.create(
            betas=["server-side-fallback-2026-07-01"], fallbacks="default", **params
        )
    return client.messages.create(**params)


def text_of(response) -> str:
    return "\n".join(b.text for b in response.content if b.type == "text").strip()


def web_turn(client, cfg: Config, spend: Spend, system: str, prompt: str, tools: list) -> str:
    """One request with web search/fetch, resuming if a long server-tool turn pauses."""
    messages = [{"role": "user", "content": prompt}]
    response = None
    for _ in range(3):
        response = call_claude(client, cfg, system=system, messages=messages,
                               max_tokens=8000, tools=tools)
        spend.add(response.usage)
        if response.stop_reason == "pause_turn":
            messages = [messages[0], {"role": "assistant", "content": response.content}]
            continue
        break
    if response.stop_reason == "refusal":
        raise RuntimeError("request was declined")
    return text_of(response)


def structured(client, cfg: Config, spend: Spend, system: str, prompt: str, schema: dict,
               max_tokens: int = 4000) -> dict:
    response = call_claude(client, cfg, system=system, max_tokens=max_tokens,
                           messages=[{"role": "user", "content": prompt}],
                           output_format={"type": "json_schema", "schema": schema})
    spend.add(response.usage)
    if response.stop_reason == "refusal":
        raise RuntimeError("request was declined")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("answer was cut off (max_tokens)")
    return json.loads(text_of(response))


# --------------------------------------------------------------------------
# FIND: discover businesses by type and location
# --------------------------------------------------------------------------
def find_businesses(client, cfg: Config, spend: Spend, *, industry: str, location: str,
                    count: int = 10, kind: str = "client", exclude: list[str] | None = None) -> list[dict]:
    count = max(1, min(20, int(count)))
    skip = ", ".join(sorted(exclude or [])[:60])
    skip_line = f"Skip these, which are already on my list: {skip}.\n" if skip else ""
    if kind == "partner":
        prompt = (
            f"Find {count} shopping centres or retail precincts in or near {location}, Australia, "
            "that have many specialty retail tenants. Prefer independently owned or smaller centres.\n"
            f"{skip_line}"
            "For each give: centre name, website, suburb and state, centre management phone number "
            "if shown, the URL of the centre management or leasing contact page, a size hint (number "
            "of stores; owner or manager such as Scentre, Vicinity, Stockland or an independent "
            "owner) and one line on why a tenant-perk partnership could suit them.\n"
            "Do not collect, copy or list any email addresses. Reply with a numbered list."
        )
    else:
        prompt = (
            f"Find {count} real, currently operating businesses in this category: {industry}.\n"
            f"Location: in or near {location}, Australia.\n"
            "Prefer independent businesses or small groups employing roughly 10-200 hourly, casual "
            "or shift workers - they need staff attendance tracking. Avoid national chains, "
            "franchise head offices, government bodies and businesses that have closed.\n"
            f"{skip_line}"
            "For each give: business name, website, suburb and state, public phone number if shown, "
            "the URL of their contact page, a size hint (locations, team size, hiring) and one line "
            "on why staff attendance tracking would help them.\n"
            "Do not collect, copy or list any email addresses. Reply with a numbered list."
        )
    searches = min(8, 3 + count // 4)
    notes = web_turn(client, cfg, spend, FIND_SYSTEM, prompt, web_tools(cfg.model, searches, 3))
    data = structured(
        client, cfg, spend, FIND_SYSTEM,
        "Convert these research notes into the schema. Include only businesses named in the notes "
        "that have a website. Use an empty string for anything unknown. Never include email "
        f"addresses.\n\nNotes:\n{notes}",
        FIND_SCHEMA, max_tokens=6000,
    )
    rows = []
    for b in data.get("businesses", [])[:count]:
        clean = {k: EMAIL_RE.sub("", str(v)).strip() for k, v in b.items()}
        if not clean.get("company") or not clean.get("website"):
            continue
        for k in ("website", "contact_page"):
            if clean[k] and not clean[k].startswith("http"):
                clean[k] = "https://" + clean[k]
        rows.append(clean | {
            "type": kind,
            "industry": "Shopping centre" if kind == "partner" else industry,
            "source": f"finder: {industry or 'shopping centres'} near {location}",
        })
    return rows


# --------------------------------------------------------------------------
# DRAFT: research one business, then write the outreach
# --------------------------------------------------------------------------
def research(client, cfg: Config, spend: Spend, row: dict) -> str:
    who = ", ".join(v for v in [row.get("company"), row.get("suburb_state"), row.get("website")] if v)
    goal = (
        "This is a shopping centre / mall. Find: centre owner/manager (e.g. Scentre, Vicinity, "
        "Stockland, independent), number of specialty stores, any retailer support or "
        "small-business programs, and the centre management team or leasing contact."
        if row.get("type") == "partner" else
        "Find: what the business does, roughly how many hourly or shift staff it has, how many "
        "sites/locations, opening hours or shift patterns, whether it is hiring, and anything "
        "suggesting manual timesheets or rostering pain."
    )
    prompt = (f"Business: {who}\nIndustry: {row.get('industry') or 'unknown'}\n\n{goal}\n"
              "Reply with 5-8 short bullet points and list the URLs you used.")
    return web_turn(client, cfg, spend, RESEARCH_SYSTEM, prompt, web_tools(cfg.model, cfg.max_searches))


def draft(client, cfg: Config, spend: Spend, row: dict, notes: str) -> dict:
    contact = row.get("contact_name") or "there"
    role = row.get("contact_role") or "unknown role"
    if row.get("type") == "partner":
        task = (
            f"Write outreach to {contact} ({role}) at {row.get('company')}, a shopping centre. "
            "Goal: a 15-minute call about a referral partnership. Pitch: their specialty "
            "retailers struggle with casual staff timesheets and Fair Work record-keeping; "
            "PresenAIT can be offered to tenants as a centre perk, and the centre earns a "
            f"referral fee. Offer: {cfg.referral_offer}. "
            "fit_score = how likely this centre is to run a tenant-perk partnership. "
            "estimated_staff = number of specialty stores (0 if unknown). suggested_plan = Lite."
        )
    else:
        task = (
            f"Write outreach to {contact} ({role}) at {row.get('company')}. "
            "Goal: start the 14-day free trial or book a 15-minute demo of PresenAIT attendance "
            "tracking. Lead with the attendance problem most likely for this specific business, "
            "mention one concrete detail from the research, and give the price for their likely "
            "plan in one short phrase. Pick suggested_plan from the brief (Lite if up to 15 staff "
            "on one site; Core if staff clock in on phones or there are 2-3 sites; Pro if many "
            "sites, face recognition, or Xero/MYOB export matter)."
        )
    return structured(client, cfg, spend, DRAFT_SYSTEM, f"{task}\n\nResearch notes:\n{notes}", DRAFT_SCHEMA)


def monthly_price(plan: str, staff: int) -> str:
    if staff <= 0:
        return f"from ${PLAN_MINIMUM}/month"
    if plan == "Lite" and staff > 15:
        plan = "Core"
    return f"${max(PLAN_MINIMUM, PLAN_RATES[plan] * staff)}/month ({plan}, {staff} staff, ex GST)"


def signature(cfg: Config) -> str:
    return (
        f"\n\n{cfg.sender_name}\n{cfg.sender_title}, PresenAIT by DataAIT Technologies Pty Ltd\n"
        f"{cfg.sender_email} | presenait.com\n"
        "If you'd rather not hear from me again, just reply 'unsubscribe'."
    )


FINISHED = {"NEEDS REVIEW", "READY", "SENT", "SKIPPED"}


def pending_rows(rows: list[dict], out_dir: Path = OUTPUT_DIR) -> list[dict]:
    """Prospects that still need a draft (never drafted, or errored last time)."""
    done = read_results(Path(out_dir) / "results.jsonl")
    return [r for r in rows
            if not r["company"].upper().startswith("EXAMPLE")
            and done.get(key_of(r), {}).get("status") not in FINISHED]


def draft_prospects(rows: list[dict], cfg: Config, out_dir: Path = OUTPUT_DIR, *, client=None,
                    limit: int = 0, log: Callable[[str], None] = print,
                    should_stop: Callable[[], bool] = lambda: False, spend: Spend | None = None) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_path = out_dir / "results.jsonl"
    todo = pending_rows(rows, out_dir)
    if limit:
        todo = todo[:limit]
    client = client or make_client()
    spend = spend or Spend(cfg.model)
    start = spend.total
    processed, stopped = 0, ""
    for i, row in enumerate(todo, 1):
        if should_stop():
            stopped = "stopped by you"
            break
        if spend.total - start >= cfg.budget_usd:
            stopped = f"budget of ${cfg.budget_usd:.2f} reached"
            break
        rec = {"key": key_of(row), **{k: row.get(k, "") for k in
               ["type", "company", "website", "suburb_state", "contact_name", "contact_role",
                "email", "phone", "contact_page"]}}
        before = spend.total
        log(f"[{i}/{len(todo)}] Researching {row['company']} ...")
        try:
            notes = research(client, cfg, spend, row)
            log(f"[{i}/{len(todo)}] Writing drafts for {row['company']} ...")
            d = draft(client, cfg, spend, row, notes)
            d["fit_score"] = max(1, min(5, int(d["fit_score"])))
            rec.update(d)
            rec["research_notes"] = notes
            rec["price_estimate"] = (
                "partner (referral)" if row["type"] == "partner"
                else monthly_price(d["suggested_plan"], int(d["estimated_staff"])))
            rec["email_body"] = d["email_body"].strip() + signature(cfg)
            rec["follow_up_email"] = d["follow_up_email"].strip() + signature(cfg)
            rec["status"] = "NEEDS REVIEW"
        except anthropic.RateLimitError:
            stopped = "Anthropic rate limit hit - try again in a few minutes"
            break
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as e:
            stopped = f"API key problem: {e}"
            break
        except (anthropic.APIStatusError, anthropic.APIConnectionError, RuntimeError,
                json.JSONDecodeError, KeyError, ValueError) as e:
            rec.update(status="ERROR", error=str(e)[:300])
        append_result(cache_path, rec)
        processed += 1
        log(f"[{i}/{len(todo)}] {row['company']}: {rec['status']} (fit {rec.get('fit_score', '-')}) "
            f"${spend.total - before:.3f}, total ${spend.total - start:.2f}")
    write_outputs(list(read_results(cache_path).values()), out_dir)
    if stopped:
        log(f"Stopped: {stopped}.")
    log(f"Done. {processed} processed, estimated spend ${spend.total - start:.2f}.")
    return {"processed": processed, "spend": spend.total - start, "stopped": stopped}


# --------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------
def cli_find(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="agent.py find", description="Find businesses and add them to prospects.csv")
    ap.add_argument("--industry", default="", help='e.g. "commercial cleaning" (ignored for --type partner)')
    ap.add_argument("--location", required=True, help='e.g. "Werribee VIC"')
    ap.add_argument("--count", type=int, default=10)
    ap.add_argument("--type", default="client", choices=["client", "partner"])
    ap.add_argument("--model", default="claude-opus-5-5", choices=MODELS)
    ap.add_argument("--prospects", default=str(PROSPECTS_CSV))
    args = ap.parse_args(argv)
    if args.type == "client" and not args.industry:
        ap.error("--industry is required for client searches")
    cfg = Config(model=args.model)
    spend = Spend(cfg.model)
    existing = [r["company"] for r in read_prospects(Path(args.prospects))]
    lo, hi = estimate(cfg.model, 1, "find")
    print(f"Searching (estimated ${lo:.2f}-${hi:.2f}) ...")
    rows = find_businesses(make_client(), cfg, spend, industry=args.industry, location=args.location,
                           count=args.count, kind=args.type, exclude=existing)
    for r in rows:
        print(f"  - {r['company']} | {r['suburb_state']} | {r['website']} | {r['phone']}")
    added, skipped = add_prospects(Path(args.prospects), rows)
    print(f"Added {added} to {args.prospects} ({skipped} already there). Spend ${spend.total:.2f}.")
    print("Email addresses are not collected: open each contact page and add the address yourself "
          "if it is published for that role.")
    return 0


def cli_draft(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="agent.py draft", description="Draft outreach (never sends).")
    ap.add_argument("--prospects", default=str(PROSPECTS_CSV))
    ap.add_argument("--out", default=str(OUTPUT_DIR))
    ap.add_argument("--model", default="claude-opus-5-5", choices=MODELS)
    ap.add_argument("--effort", default="low", choices=["low", "medium", "high"])
    ap.add_argument("--max-searches", type=int, default=2)
    ap.add_argument("--budget-usd", type=float, default=5.0)
    ap.add_argument("--limit", type=int, default=0, help="max new prospects this run (0 = all)")
    ap.add_argument("--sender-name", default="[Your name]")
    ap.add_argument("--sender-title", default="[Your title]")
    ap.add_argument("--sender-email", default="[your@email]")
    ap.add_argument("--referral-offer", default=DEFAULT_REFERRAL)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    cfg = Config(args.model, args.effort, args.max_searches, args.budget_usd, args.sender_name,
                 args.sender_title, args.sender_email, args.referral_offer)
    rows = read_prospects(Path(args.prospects))
    todo = pending_rows(rows, Path(args.out))
    if args.limit:
        todo = todo[: args.limit]
    lo, hi = estimate(cfg.model, len(todo))
    print(f"{len(rows)} prospects, {len(todo)} to draft with {cfg.model}. "
          f"Estimate ${lo:.2f}-${hi:.2f} (budget cap ${cfg.budget_usd:.2f}).")
    if args.dry_run:
        for r in todo:
            print(f"  - [{r['type']}] {r['company']} {r.get('website', '')}")
        print("Dry run: no API calls made.")
        return 0
    result = draft_prospects(rows, cfg, Path(args.out), limit=args.limit)
    print(f"Drafts are in {Path(args.out) / 'drafts.md'} and {Path(args.out) / 'drafts.csv'}.")
    return 1 if result["stopped"].startswith("API key") else 0


def main() -> int:
    argv = sys.argv[1:]
    if argv and argv[0] == "find":
        return cli_find(argv[1:])
    if argv and argv[0] == "draft":
        argv = argv[1:]
    return cli_draft(argv)


if __name__ == "__main__":
    sys.exit(main())
