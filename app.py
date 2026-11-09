#!/usr/bin/env python3
"""
PresenAIT Outreach dashboard
============================

A small website that runs only on your own computer and gives the outreach
agent buttons instead of commands.

  pip install -r requirements.txt
  python app.py            # opens http://127.0.0.1:5055 in your browser

Stop it with Ctrl+C in the Terminal window.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import threading
import time
import webbrowser
from pathlib import Path

import anthropic
from flask import Flask, abort, jsonify, request, send_from_directory

import agent
import store

HERE = Path(__file__).resolve().parent
PROSPECTS = agent.PROSPECTS_CSV
OUTPUT = agent.OUTPUT_DIR
RESULTS = OUTPUT / "results.jsonl"
SETTINGS_PATH = HERE / "settings.json"
ENV_PATH = HERE / ".env"

DEFAULT_SETTINGS = {
    "sender_name": "", "sender_title": "", "sender_email": "",
    "model": "claude-opus-5-5", "effort": "low", "max_searches": 2, "budget_usd": 5.0,
    "referral_offer": agent.DEFAULT_REFERRAL,
}
EDITABLE_DRAFT_FIELDS = {"status", "email_subject", "email_body", "follow_up_email",
                         "linkedin_message", "call_opener"}

app = Flask(__name__, static_folder=str(HERE / "static"))


# ------------------------------------------------------------------ settings & API key
def load_env() -> None:
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def has_api_key() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def load_settings() -> dict:
    s = dict(DEFAULT_SETTINGS)
    if SETTINGS_PATH.exists():
        s.update(json.loads(SETTINGS_PATH.read_text()))
    return s


def config_from(settings: dict, overrides: dict | None = None) -> agent.Config:
    s = {**settings, **{k: v for k, v in (overrides or {}).items() if v not in (None, "")}}
    model = s["model"] if s["model"] in agent.MODELS else "claude-opus-5-5"
    return agent.Config(
        model=model, effort=s.get("effort", "low"), max_searches=int(s.get("max_searches", 2)),
        budget_usd=float(s.get("budget_usd", 5.0)),
        sender_name=s.get("sender_name") or "[Your name]",
        sender_title=s.get("sender_title") or "[Your title]",
        sender_email=s.get("sender_email") or "[your@email]",
        referral_offer=s.get("referral_offer") or agent.DEFAULT_REFERRAL,
    )


# ------------------------------------------------------------------ background job (one at a time)
LOCK = threading.Lock()
JOB: dict = {"running": False, "kind": "", "log": [], "error": "", "found": [], "stop": False,
             "progress": [0, 0], "spend_obj": None, "finished_at": 0}
SESSION_SPEND = {"total": 0.0}


def job_log(line: str) -> None:
    with LOCK:
        JOB["log"].append(f"{time.strftime('%H:%M:%S')}  {line}")
        JOB["log"] = JOB["log"][-300:]
        m = re.match(r"\[(\d+)/(\d+)\]", line)
        if m:
            i, n = int(m.group(1)), int(m.group(2))
            JOB["progress"] = [i if "(fit " in line else i - 1, n]  # "(fit" marks a finished business


def friendly_error(e: Exception) -> str:
    if isinstance(e, anthropic.AuthenticationError):
        return "Your API key was rejected. Check it in Settings."
    if isinstance(e, anthropic.PermissionDeniedError):
        return "Your API key isn't allowed to do this. Check your Anthropic account."
    if isinstance(e, anthropic.RateLimitError):
        return "Anthropic's rate limit was hit. Wait a few minutes and try again."
    if isinstance(e, anthropic.APIConnectionError):
        return "Couldn't reach Anthropic. Check your internet connection."
    if isinstance(e, anthropic.APIStatusError):
        return f"Anthropic returned an error ({e.status_code}): {getattr(e, 'message', e)}"
    return str(e)[:300]


def start_job(kind: str, target, *args) -> bool:
    with LOCK:
        if JOB["running"]:
            return False
        JOB.update(running=True, kind=kind, log=[], error="", found=[] if kind == "find" else JOB["found"],
                   stop=False, progress=[0, 0], spend_obj=None)

    def runner():
        try:
            target(*args)
        except Exception as e:  # noqa: BLE001 - shown to the user in the dashboard
            with LOCK:
                JOB["error"] = friendly_error(e)
            job_log(f"Error: {friendly_error(e)}")
        finally:
            with LOCK:
                if JOB["spend_obj"] is not None:
                    SESSION_SPEND["total"] += JOB["spend_obj"].total
                JOB["running"] = False
                JOB["finished_at"] = time.time()

    threading.Thread(target=runner, daemon=True).start()
    return True


def _find_job(params: dict) -> None:
    cfg = config_from(load_settings(), {"model": params.get("model")})
    spend = agent.Spend(cfg.model)
    JOB["spend_obj"] = spend
    kind = params.get("type", "client")
    what = "shopping centres" if kind == "partner" else params.get("industry", "")
    job_log(f"Searching the web for {params.get('count', 10)} {what} near {params.get('location')} ...")
    existing_rows = store.read_prospects(PROSPECTS)
    rows = agent.find_businesses(
        agent.make_client(), cfg, spend, industry=params.get("industry", ""),
        location=params.get("location", ""), count=int(params.get("count", 10)), kind=kind,
        exclude=[r["company"] for r in existing_rows])
    names = {r["company"].strip().lower() for r in existing_rows}
    domains = {store.domain_of(r["website"]) for r in existing_rows if r["website"]}
    for r in rows:
        r["already"] = r["company"].strip().lower() in names or store.domain_of(r["website"]) in domains
    with LOCK:
        JOB["found"] = rows
    job_log(f"Found {len(rows)} businesses. Estimated spend ${spend.total:.2f}.")


def _draft_job(params: dict) -> None:
    cfg = config_from(load_settings(), {"model": params.get("model"), "budget_usd": params.get("budget_usd")})
    spend = agent.Spend(cfg.model)
    JOB["spend_obj"] = spend
    rows = store.read_prospects(PROSPECTS)
    limit = int(params.get("limit") or 0)
    n = len(agent.pending_rows(rows, OUTPUT)[: limit or None])
    with LOCK:
        JOB["progress"] = [0, n]
    agent.draft_prospects(rows, cfg, OUTPUT, client=agent.make_client(), limit=limit, log=job_log,
                          should_stop=lambda: JOB["stop"], spend=spend)


# ------------------------------------------------------------------ routes
@app.before_request
def guard():
    # Blocks other websites from triggering actions on this local app.
    if request.method != "GET" and request.headers.get("X-Outreach") != "1":
        abort(403)


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/meta")
def meta():
    rows = store.read_prospects(PROSPECTS)
    return jsonify(
        api_key=has_api_key(), models=agent.MODELS, settings=load_settings(),
        est_draft=agent.EST_PER_DRAFT, est_find=agent.EST_PER_FIND,
        pending=len(agent.pending_rows(rows, OUTPUT)), session_spend=SESSION_SPEND["total"],
    )


@app.get("/api/prospects")
def prospects():
    done = store.read_results(RESULTS)
    out = []
    for r in store.read_prospects(PROSPECTS):
        k = store.key_of(r)
        out.append(r | {"key": k, "draft_status": done.get(k, {}).get("status", "")})
    return jsonify(out)


@app.post("/api/prospects/add")
def prospects_add():
    rows = request.json.get("rows", [])
    added, skipped = store.add_prospects(PROSPECTS, rows)
    return jsonify(added=added, skipped=skipped)


@app.post("/api/prospects/update")
def prospects_update():
    body = request.json
    fields = {k: v for k, v in body.get("fields", {}).items() if k not in ("company", "website")}
    row = store.update_prospect(PROSPECTS, body["key"], fields)
    return (jsonify(row), 200) if row else (jsonify(error="not found"), 404)


@app.post("/api/prospects/delete")
def prospects_delete():
    return jsonify(deleted=store.delete_prospects(PROSPECTS, request.json.get("keys", [])))


@app.get("/api/drafts")
def drafts():
    current = {store.key_of(r): r for r in store.read_prospects(PROSPECTS)}
    out = []
    for k, rec in store.read_results(RESULTS).items():
        live = current.get(k, {})
        merged = dict(rec)
        for f in ("email", "contact_name", "contact_role", "phone", "contact_page", "website", "suburb_state"):
            if live.get(f):
                merged[f] = live[f]
        merged["in_prospects"] = bool(live)
        out.append(merged)
    out.sort(key=lambda r: (r.get("status") == "ERROR", -int(r.get("fit_score") or 0)))
    return jsonify(out)


@app.post("/api/drafts/update")
def drafts_update():
    body = request.json
    fields = {k: v for k, v in body.get("fields", {}).items() if k in EDITABLE_DRAFT_FIELDS}
    if "status" in fields and fields["status"] not in store.DRAFT_STATUSES:
        return jsonify(error="bad status"), 400
    rec = store.update_result(RESULTS, body["key"], fields)
    if not rec:
        return jsonify(error="not found"), 404
    store.write_outputs(list(store.read_results(RESULTS).values()), OUTPUT)
    return jsonify(rec)


@app.post("/api/drafts/redo")
def drafts_redo():
    rec = store.update_result(RESULTS, request.json["key"], {"status": "ERROR", "error": "Queued to be drafted again"})
    return (jsonify(ok=True), 200) if rec else (jsonify(error="not found"), 404)


@app.get("/api/settings")
def settings_get():
    return jsonify(load_settings())


@app.post("/api/settings")
def settings_set():
    s = load_settings()
    for k, v in request.json.items():
        if k in DEFAULT_SETTINGS:
            s[k] = v
    SETTINGS_PATH.write_text(json.dumps(s, indent=2))
    return jsonify(s)


@app.post("/api/apikey")
def apikey_set():
    key = (request.json.get("key") or "").strip()
    if not key:
        os.environ.pop("ANTHROPIC_API_KEY", None)
        if ENV_PATH.exists():
            ENV_PATH.unlink()
        return jsonify(api_key=has_api_key())
    if not key.startswith("sk-ant-") or len(key) < 30:
        return jsonify(error="That doesn't look like an Anthropic API key (it should start with sk-ant-)."), 400
    ENV_PATH.write_text(f"ANTHROPIC_API_KEY={key}\n")
    os.chmod(ENV_PATH, 0o600)
    os.environ["ANTHROPIC_API_KEY"] = key
    return jsonify(api_key=True)


@app.post("/api/find")
def find():
    p = request.json
    if not has_api_key():
        return jsonify(error="Add your Anthropic API key in Settings first."), 400
    if not p.get("location") or (p.get("type") != "partner" and not p.get("industry")):
        return jsonify(error="Enter a business type and a location."), 400
    if not start_job("find", _find_job, p):
        return jsonify(error="Another job is already running."), 409
    return jsonify(ok=True)


@app.post("/api/run")
def run():
    if not has_api_key():
        return jsonify(error="Add your Anthropic API key in Settings first."), 400
    if not start_job("draft", _draft_job, request.json):
        return jsonify(error="Another job is already running."), 409
    return jsonify(ok=True)


@app.post("/api/stop")
def stop():
    with LOCK:
        JOB["stop"] = True
    job_log("Stopping after the current business ...")
    return jsonify(ok=True)


@app.get("/api/job")
def job():
    with LOCK:
        live = JOB["spend_obj"].total if JOB["spend_obj"] is not None else 0.0
        return jsonify(
            running=JOB["running"], kind=JOB["kind"], log=JOB["log"][-80:], error=JOB["error"],
            found=JOB["found"], progress=JOB["progress"], spend=live,
            session_spend=SESSION_SPEND["total"] + (live if JOB["running"] else 0.0),
            finished_at=JOB["finished_at"],
        )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=5055)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()
    load_env()
    OUTPUT.mkdir(exist_ok=True)
    if not PROSPECTS.exists():
        store.write_prospects(PROSPECTS, [])
    url = f"http://127.0.0.1:{args.port}"
    print(f"PresenAIT Outreach dashboard running at {url}  (Ctrl+C to stop)")
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=args.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
