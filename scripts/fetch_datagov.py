"""Download the CPCB real-time AQI feed from data.gov.in and append it to a CSV history.

Run this on a machine with internet access (hourly via cron / Task Scheduler) to build the
history the Air Karma engine needs.  Free API key: register at https://data.gov.in -> My Account.

    export DATAGOV_API_KEY=xxxx
    python fetch_datagov.py data/snapshots.csv

Resource id below is the "Real time Air Quality Index from various locations" resource.
Check it against the URL on https://data.gov.in/resource/real-time-air-quality-index-various-locations
(the "API" tab shows the current id) in case the portal has re-issued it.
"""
import os
import sys
import time
import pandas as pd
import requests

RESOURCE_ID = "3b01bcb8-0b14-4abf-b6f2-c1bfd384ba69"
URL = f"https://api.data.gov.in/resource/{RESOURCE_ID}"


def fetch_all(api_key: str, page: int = 500) -> pd.DataFrame:
    frames, offset = [], 0
    while True:
        r = requests.get(URL, params={"api-key": api_key, "format": "json",
                                      "limit": page, "offset": offset}, timeout=60)
        r.raise_for_status()
        recs = r.json().get("records", [])
        if not recs:
            break
        frames.append(pd.DataFrame(recs))
        offset += page
        time.sleep(0.5)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "data/snapshots.csv"
    key = os.environ.get("DATAGOV_API_KEY")
    if not key:
        sys.exit("Set DATAGOV_API_KEY first.")
    df = fetch_all(key)
    df["fetched_at"] = pd.Timestamp.now(tz="Asia/Kolkata").isoformat()
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    df.to_csv(out, mode="a", header=not os.path.exists(out), index=False)
    print(f"appended {len(df)} rows -> {out}")
