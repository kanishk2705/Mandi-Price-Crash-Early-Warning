"""One-off access check for the data.gov.in Agmarknet resources.

Runs ONLY inside GitHub Actions with DATA_GOV_IN_API_KEY from repository secrets.
The key is never printed: every URL and error string passes through `redact()`.
Writes results/api_probe/summary.json and a Markdown report for the job summary.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE = "https://api.data.gov.in/resource/"
KEY = os.environ.get("DATA_GOV_IN_API_KEY", "")
OUT = Path("results/api_probe")

RESOURCES = {
    "variety_wise_daily": "35985678-0d79-46b4-9ed6-6f13308a1d24",
    "current_daily_mandi": "9ef84268-d588-465a-a308-a864a43d0070",
}
CROPS = ["Tomato", "Onion", "Potato"]


def redact(text: str) -> str:
    return text.replace(KEY, "***") if KEY else text


def call(rid: str, params: dict, retries: int = 2) -> dict:
    q = {"api-key": KEY, "format": "json", "limit": 1, "offset": 0, **params}
    last = {}
    for attempt in range(retries):
        t0 = time.time()
        try:
            r = requests.get(BASE + rid, params=q, timeout=45)
            info = {"http": r.status_code, "secs": round(time.time() - t0, 2)}
            try:
                body = r.json()
            except ValueError:
                info["error"] = redact(r.text[:300])
                last = info
                time.sleep(3 * (attempt + 1))
                continue
            info["total"] = body.get("total")
            info["count"] = body.get("count")
            info["message"] = redact(str(body.get("message", "")))[:200]
            info["updated_date"] = body.get("updated_date")
            info["fields"] = [f.get("id") for f in body.get("field", [])]
            info["records"] = body.get("records", [])
            if r.status_code == 200:
                return info
            last = info
        except requests.RequestException as exc:
            last = {"http": None, "error": redact(f"{type(exc).__name__}: {exc}")[:300]}
        time.sleep(3 * (attempt + 1))
    return last


def date_field(fields: list[str]) -> str | None:
    for f in fields or []:
        if "arrival" in f.lower() and "date" in f.lower():
            return f
    return None


def commodity_field(fields: list[str]) -> str:
    for f in fields or []:
        if f.lower() == "commodity":
            return f
    return "commodity"


def main() -> int:
    if not KEY:
        print("DATA_GOV_IN_API_KEY is not set", file=sys.stderr)
        return 2
    OUT.mkdir(parents=True, exist_ok=True)
    report: dict = {"run_utc": datetime.now(timezone.utc).isoformat(), "resources": {}}

    for name, rid in RESOURCES.items():
        res: dict = {"resource_id": rid}
        head = call(rid, {})
        res["head"] = {k: v for k, v in head.items() if k != "records"}
        res["sample_record"] = (head.get("records") or [None])[0]
        fields = head.get("fields") or []
        dfield, cfield = date_field(fields), commodity_field(fields)
        res["date_field"], res["commodity_field"] = dfield, cfield
        total = head.get("total") or 0

        # Ordering of the raw feed: first and last record
        if total:
            last = call(rid, {"offset": max(int(total) - 1, 0)})
            res["last_record"] = (last.get("records") or [None])[0]
            res["last_record_http"] = last.get("http")
        if dfield:
            for order in ("asc", "desc"):
                s = call(rid, {f"sort[{dfield}]": order})
                res[f"sorted_{order}"] = {"http": s.get("http"), "message": s.get("message"),
                                           "record": (s.get("records") or [None])[0]}

        # Per-crop totals
        res["crop_totals"] = {}
        for crop in CROPS:
            c = call(rid, {f"filters[{cfield}]": crop})
            res["crop_totals"][crop] = {"http": c.get("http"), "total": c.get("total")}

        # History coverage: does the ORIGINAL source keep past days?
        # One mid-quarter date per year (Tomato) plus the last 12 days (all crops).
        cov = {}
        if dfield:
            probe_dates = [f"15/{m:02d}/{y}" for y in range(2014, 2027) for m in (1, 7)]
            today = datetime.now(timezone.utc).date()
            from datetime import timedelta
            probe_dates += [(today - timedelta(days=k)).strftime("%d/%m/%Y") for k in range(0, 12)]
            for d in probe_dates:
                p = call(rid, {f"filters[{dfield}]": d})
                cov[d] = {"http": p.get("http"), "total": p.get("total"), "msg": p.get("message")}
                time.sleep(0.3)
        res["date_coverage_probe"] = cov
        report["resources"][name] = res

    text = json.dumps(report, indent=2, ensure_ascii=False, default=str)
    assert KEY not in text, "API key leaked into report"
    (OUT / "summary.json").write_text(text, encoding="utf-8")

    md = ["# data.gov.in API access check", f"Run (UTC): {report['run_utc']}", ""]
    for name, res in report["resources"].items():
        h = res["head"]
        md += [f"## {name} (`{res['resource_id']}`)",
               f"- HTTP {h.get('http')}, total records: **{h.get('total')}**, updated: {h.get('updated_date')}",
               f"- message: {h.get('message')}", f"- fields: {h.get('fields')}",
               f"- crop totals: {res['crop_totals']}", ""]
        hits = {d: v.get("total") for d, v in res["date_coverage_probe"].items() if v.get("total")}
        md += [f"- probed dates that returned records: {hits}",
               f"- first/last raw record: {res.get('sample_record')} / {res.get('last_record')}", ""]
    (OUT / "summary.md").write_text("\n".join(md), encoding="utf-8")
    assert KEY not in "\n".join(md)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    sys.exit(main())
