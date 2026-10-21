"""Load and clean data.gov.in / CPCB real-time AQI CSVs. Every drop is counted (research gap G5)."""
import numpy as np
import pandas as pd
from .config import CAP, NAAQS, SCORED_DEFAULT

ALIASES = {
    "pollutant_min": ["min_value", "min", "pollutant_min"],
    "pollutant_max": ["max_value", "max", "pollutant_max"],
    "pollutant_avg": ["avg_value", "avg", "pollutant_avg"],
    "last_update": ["last_update", "lastupdate", "datetime"],
}
POLL_ALIAS = {"PM25": "PM2.5", "PM2_5": "PM2.5", "O3": "OZONE"}
REQUIRED = {"state", "city", "station", "last_update", "pollutant_id", "pollutant_avg"}


def read_csv(path_or_buf) -> pd.DataFrame:
    df = pd.read_csv(path_or_buf, low_memory=False)
    df.columns = [c.strip().lower() for c in df.columns]
    for std, opts in ALIASES.items():
        for o in opts:
            if o in df.columns:
                if o != std:
                    df = df.rename(columns={o: std})
                break
    missing = REQUIRED - set(df.columns)
    if missing:
        raise ValueError(f"CSV is missing columns {sorted(missing)}; found {list(df.columns)}")
    for c in ["pollutant_min", "pollutant_max"]:
        if c not in df.columns:
            df[c] = np.nan
    for c in ["latitude", "longitude"]:
        if c not in df.columns:
            df[c] = np.nan
    df["pollutant_id"] = df["pollutant_id"].astype(str).str.upper().str.strip().replace(POLL_ALIAS)
    ts = pd.to_datetime(df["last_update"], format="%d-%m-%Y %H:%M:%S", errors="coerce")
    alt = pd.to_datetime(df["last_update"], dayfirst=True, errors="coerce")
    df["last_update"] = ts.fillna(alt)
    for c in ["pollutant_avg", "pollutant_min", "pollutant_max", "latitude", "longitude"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")  # 'NA' text becomes NaN
    for c in ["state", "city", "station"]:
        df[c] = df[c].astype(str).str.strip()
    return df[["state", "city", "station", "latitude", "longitude", "last_update",
               "pollutant_id", "pollutant_min", "pollutant_max", "pollutant_avg"]]


def clean(df: pd.DataFrame):
    """Return (clean_df, report). Rows are removed only for a stated, counted reason."""
    rep = {"steps": []}

    def step(name, before, after):
        rep["steps"].append({"step": name, "removed": int(before - after), "remaining": int(after)})

    n0 = len(df)
    rep["rows_loaded"] = int(n0)
    d = df.copy()

    b = len(d)
    d = d.drop_duplicates(subset=["station", "last_update", "pollutant_id"])
    step("Duplicate station/time/pollutant rows", b, len(d))

    b = len(d)
    d = d[d["pollutant_id"].isin(NAAQS)]
    step("Pollutants without an Indian NAAQS standard", b, len(d))

    b = len(d)
    d = d[d["last_update"].notna() & d["latitude"].notna() & d["longitude"].notna()]
    step("Missing timestamp or coordinates", b, len(d))
    bad_coord = ~d["latitude"].between(6, 38) | ~d["longitude"].between(68, 98)
    b = len(d)
    d = d[~bad_coord]
    step("Coordinates outside India's bounding box", b, len(d))

    # 'NA' readings: kept out of statistics, but counted per pollutant (sensor missing/offline).
    na_by_pollutant = d[d["pollutant_avg"].isna()]["pollutant_id"].value_counts().to_dict()
    rep["na_by_pollutant"] = {k: int(v) for k, v in na_by_pollutant.items()}
    b = len(d)
    d = d[d["pollutant_avg"].notna()]
    step("Reading is NA (sensor offline or not reporting)", b, len(d))

    b = len(d)
    d = d[d["pollutant_avg"] >= 0]
    step("Negative concentration", b, len(d))

    b = len(d)
    d = d[d["pollutant_avg"] <= d["pollutant_id"].map(CAP)]
    step("Above physical plausibility cap", b, len(d))

    b = len(d)
    ok = ~((d["pollutant_min"] > d["pollutant_max"]) | (d["pollutant_avg"] > d["pollutant_max"]) |
           (d["pollutant_avg"] < d["pollutant_min"]))
    d = d[ok | d["pollutant_min"].isna() | d["pollutant_max"].isna()]
    step("Inconsistent min / avg / max", b, len(d))

    rep["rows_clean"] = int(len(d))
    rep["pct_kept"] = round(100 * len(d) / max(n0, 1), 1)

    # Unit sanity check: CO must be mg/m3 (NAAQS 2). If the median is far above the standard the
    # feed is not in mg/m3 and CO cannot be compared with the standard.
    notes, scored = [], list(SCORED_DEFAULT)
    co = d.loc[d["pollutant_id"] == "CO", "pollutant_avg"]
    if len(co):
        ratio = float(co.median() / NAAQS["CO"])
        rep["co_median"] = float(co.median())
        if ratio > 5:
            notes.append(f"CO median is {co.median():.0f} but the NAAQS is {NAAQS['CO']} mg/m3 "
                         f"({ratio:.0f}x). The unit in this feed is not mg/m3, so CO is excluded from the "
                         "score. It is still used as a model feature.")
        else:
            scored.append("CO")
    rep["notes"] = notes
    rep["scored_pollutants"] = scored

    # Station reporting coverage
    wide = d.pivot_table(index="station", columns="pollutant_id", values="pollutant_avg")
    all_st = df["station"].nunique()
    rep["stations_total"] = int(all_st)
    rep["stations_with_any_reading"] = int(len(wide))
    rep["stations_by_n_pollutants"] = {int(k): int(v) for k, v in
                                       wide.notna().sum(axis=1).value_counts().sort_index().items()}
    return d, rep
