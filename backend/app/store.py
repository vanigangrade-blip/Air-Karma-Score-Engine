"""SQLite store. Each upload of a data.gov.in snapshot is appended; history accumulates over time."""
import sqlite3
import pandas as pd
from .config import DB_PATH

SCHEMA = """CREATE TABLE IF NOT EXISTS readings(
  snapshot TEXT, state TEXT, city TEXT, station TEXT, latitude REAL, longitude REAL,
  pollutant_id TEXT, pollutant_min REAL, pollutant_max REAL, pollutant_avg REAL,
  PRIMARY KEY(snapshot, station, pollutant_id))"""


def conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.execute(SCHEMA)
    return c


def ingest(df: pd.DataFrame) -> dict:
    """Insert rows. Raw (uncleaned) rows are stored so QC is always re-run on the full record."""
    d = df.copy()
    d = d[d["last_update"].notna()]
    d["snapshot"] = d["last_update"].dt.strftime("%Y-%m-%d %H:%M:%S")
    cols = ["snapshot", "state", "city", "station", "latitude", "longitude",
            "pollutant_id", "pollutant_min", "pollutant_max", "pollutant_avg"]
    d = d[cols].drop_duplicates(["snapshot", "station", "pollutant_id"])
    with conn() as c:
        before = c.execute("SELECT COUNT(*) FROM readings").fetchone()[0]
        c.executemany("INSERT OR REPLACE INTO readings VALUES(?,?,?,?,?,?,?,?,?,?)",
                      [tuple(None if pd.isna(v) else v for v in r) for r in d.itertuples(index=False)])
        after = c.execute("SELECT COUNT(*) FROM readings").fetchone()[0]
    return {"rows_received": int(len(d)), "rows_new": int(after - before),
            "snapshots": sorted(d["snapshot"].unique().tolist())}


def snapshots() -> list[str]:
    with conn() as c:
        return [r[0] for r in c.execute("SELECT DISTINCT snapshot FROM readings ORDER BY snapshot")]


def load(snapshot: str | None = None) -> pd.DataFrame:
    q = "SELECT * FROM readings" + (" WHERE snapshot=?" if snapshot else "")
    with conn() as c:
        df = pd.read_sql_query(q, c, params=(snapshot,) if snapshot else None)
    df["last_update"] = pd.to_datetime(df["snapshot"])
    return df.drop(columns="snapshot")
