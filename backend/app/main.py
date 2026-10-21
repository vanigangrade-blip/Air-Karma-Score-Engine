"""FastAPI server: JSON API + static frontend."""
import io
import mimetypes
import threading
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config as C
from . import pipeline, qc, store

# Windows can map .js to text/plain via the registry, which makes browsers refuse the scripts.
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")

app = FastAPI(title="Air Karma Score Engine - India", version="1.0")
STATE = {"result": None, "status": "starting", "message": "", "error": None}
_lock = threading.Lock()


def _rebuild():
    with _lock:
        STATE.update(status="building", error=None)
        try:
            STATE["result"] = pipeline.build_and_cache(lambda m: STATE.update(message=m))
            STATE.update(status="ready", message="")
        except Exception as e:  # surface the reason in the UI instead of a blank page
            STATE.update(status="error", error=str(e))


def _bootstrap():
    # first run: load every CSV in data/raw into the database
    if not store.snapshots():
        for f in sorted(C.RAW_DIR.glob("*.csv")):
            store.ingest(qc.read_csv(f))
    cached = pipeline.load_cache()
    if cached and cached["meta"]["snapshots"] == store.snapshots():
        STATE.update(result=cached, status="ready")
    elif store.snapshots():
        _rebuild()
    else:
        STATE.update(status="error", error="No data. Put a data.gov.in CSV in data/raw/ and restart.")


@app.on_event("startup")
def startup():
    threading.Thread(target=_bootstrap, daemon=True).start()


def R():
    if STATE["result"] is None:
        raise HTTPException(503, STATE["error"] or f"Still computing: {STATE['message'] or STATE['status']}")
    return STATE["result"]


@app.get("/api/status")
def status():
    return {k: STATE[k] for k in ("status", "message", "error")}


@app.get("/api/summary")
def summary():
    r = R()
    sc = [s for s in r["stations"] if s["score"] is not None]
    by_label = {}
    for s in sc:
        by_label[s["label"]] = by_label.get(s["label"], 0) + 1
    cities = r["cities"]
    return {"meta": r["meta"], "labels": by_label,
            "national_mean": sum(s["score"] for s in sc) / len(sc),
            "worst_cities": cities[::-1][:10], "best_cities": cities[:10],
            "states": r["states"], "fairness": {k: v for k, v in r["fairness"].items() if k != "widest"}}


@app.get("/api/stations")
def stations(state: str | None = None, city: str | None = None, q: str | None = None):
    r = R()
    out = []
    for s in r["stations"]:
        if state and s["state"] != state:
            continue
        if city and s["city"] != city:
            continue
        if q and q.lower() not in f'{s["station"]} {s["city"]} {s["state"]}'.lower():
            continue
        out.append({k: s[k] for k in ("id", "state", "city", "station", "lat", "lon", "score", "label",
                                      "dominant", "aqi", "aqi_cat", "pm25", "pm25_est")})
    return out


@app.get("/api/station/{sid}")
def station(sid: str):
    r = R()
    s = next((x for x in r["stations"] if x["id"] == sid), None)
    if not s:
        raise HTTPException(404, "Unknown station id")
    city = next((c for c in r["cities"] if c["city"] == s["city"] and c["state"] == s["state"]), None)
    peers = [x for x in r["stations"] if x["city"] == s["city"] and x["state"] == s["state"] and x["id"] != sid]
    return {**s, "city_stats": city, "peers": [{k: p[k] for k in ("id", "station", "score", "label")} for p in peers],
            "pm25_explanation": r["model"]["local"].get(sid)}


@app.get("/api/cities")
def cities(state: str | None = None, min_stations: int = Query(1, ge=1)):
    r = R()
    return [c for c in r["cities"] if (not state or c["state"] == state) and c["stations"] >= min_stations]


@app.get("/api/fairness")
def fairness():
    return R()["fairness"]


@app.get("/api/model")
def model():
    m = dict(R()["model"])
    m.pop("local", None)
    return m


@app.get("/api/quality")
def quality():
    r = R()
    return {"qc": r["qc"], "sensitivity": r["sensitivity"]}


@app.get("/api/equity")
def equity():
    return pipeline.equity(R())


@app.get("/api/history")
def history():
    return {"snapshots": store.snapshots()}


@app.post("/api/ingest")
async def ingest(file: UploadFile = File(...)):
    """Upload another data.gov.in snapshot. History accumulates; the analysis re-runs in the background."""
    try:
        df = qc.read_csv(io.BytesIO(await file.read()))
    except Exception as e:
        raise HTTPException(400, f"Could not read CSV: {e}")
    info = store.ingest(df)
    if STATE["status"] != "building":
        threading.Thread(target=_rebuild, daemon=True).start()
    return {**info, "note": "Re-analysis started; poll /api/status."}


FRONT = Path(C.ROOT / "frontend")
app.mount("/static", StaticFiles(directory=FRONT), name="static")


@app.get("/")
def index():
    return FileResponse(FRONT / "index.html", headers={"Cache-Control": "no-store"})