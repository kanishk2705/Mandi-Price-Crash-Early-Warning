"""Light-weight data.gov.in probe: small, filtered requests in several formats.

Purpose: tell apart "API down / overloaded" from "query too heavy" from "key invalid".
Never prints the key. Appends one JSON line per run to results/api_probe/variants.jsonl.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

KEY = os.environ.get("DATA_GOV_IN_API_KEY", "")
BASE = "https://api.data.gov.in/resource/"
CUR = "9ef84268-d588-465a-a308-a864a43d0070"
VAR = "35985678-0d79-46b4-9ed6-6f13308a1d24"
OUT = Path("results/api_probe/variants.jsonl")


def redact(t: str) -> str:
    return t.replace(KEY, "***") if KEY else t


VARIANTS = [
    ("cur_json_tomato_TN", CUR, {"format": "json", "limit": 5, "filters[state.keyword]": "Tamil Nadu", "filters[commodity]": "Tomato"}),
    ("cur_json_tomato", CUR, {"format": "json", "limit": 5, "filters[commodity]": "Tomato"}),
    ("cur_json_plain10", CUR, {"format": "json", "limit": 10}),
    ("cur_csv_plain10", CUR, {"format": "csv", "limit": 10}),
    ("cur_xml_plain10", CUR, {"format": "xml", "limit": 10}),
    ("var_json_tomato", VAR, {"format": "json", "limit": 5, "filters[Commodity]": "Tomato"}),
    ("var_json_plain10", VAR, {"format": "json", "limit": 10}),
]


def main() -> int:
    if not KEY:
        print("key missing", file=sys.stderr)
        return 2
    run = {"run_utc": datetime.now(timezone.utc).isoformat(), "results": {}}
    for name, rid, params in VARIANTS:
        q = {"api-key": KEY, "offset": 0, **params}
        t0 = time.time()
        info: dict = {}
        try:
            r = requests.get(BASE + rid, params=q, timeout=(20, 150))
            info["http"] = r.status_code
            info["bytes"] = len(r.content)
            body = r.text
            if params["format"] == "json":
                try:
                    j = r.json()
                    info["total"] = j.get("total")
                    info["count"] = j.get("count")
                    info["message"] = redact(str(j.get("message", "")))[:200]
                    info["status"] = j.get("status")
                    info["fields"] = [f.get("id") for f in j.get("field", [])]
                    info["records"] = j.get("records", [])[:5]
                    info["updated_date"] = j.get("updated_date")
                except ValueError:
                    info["body_head"] = redact(body[:300])
            else:
                info["body_head"] = redact(body[:600])
        except requests.RequestException as exc:
            info["error"] = redact(f"{type(exc).__name__}: {exc}")[:200]
        info["secs"] = round(time.time() - t0, 1)
        run["results"][name] = info
        print(f"{name}: http={info.get('http')} total={info.get('total')} secs={info['secs']} "
              f"err={info.get('error', '')[:60]}", flush=True)
        time.sleep(2)
    line = json.dumps(run, ensure_ascii=False)
    assert KEY not in line
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
