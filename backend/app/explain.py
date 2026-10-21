"""Plain-language reasons for citizens and authorities (research gap G7: decision support)."""
import numpy as np
from . import config as C


def station_text(s: dict, city_stats: dict | None) -> list[str]:
    """s: station record. Returns short sentences, each backed by a number in the record."""
    out = []
    if s.get("score") is None:
        reasons = []
        if s.get("n_scored", 0) < C.MIN_POLLUTANTS:
            reasons.append(f"only {s.get('n_scored', 0)} of 6 scored pollutants are reporting (need {C.MIN_POLLUTANTS})")
        if s.get("pm25") is None and s.get("pm10") is None:
            reasons.append("neither PM2.5 nor PM10 is reporting")
        return ["No Karma Score for this station: " + "; ".join(reasons or ["not enough valid readings"]) + "."]
    d = s["dominant"]
    ratio = s["ratios"][d]
    share = s["contrib"][d] / s["burden"] if s["burden"] else 0
    out.append(f"Score {s['score']:.0f}/100 ({s['label']}). {d} is {ratio:.1f}x the Indian legal limit "
               f"and accounts for {share:.0%} of this station's pollution burden.")
    over = [p for p, r in s["ratios"].items() if r is not None and r > 1]
    if len(over) > 1:
        out.append("Above the legal limit: " + ", ".join(f"{p} ({s['ratios'][p]:.1f}x)" for p in over) + ".")
    elif not over:
        out.append("No scored pollutant is above its legal limit right now.")
    if city_stats and city_stats["stations"] >= 2:
        diff = s["score"] - city_stats["score"]
        side = "better" if diff >= 0 else "worse"
        out.append(f"{abs(diff):.0f} points {side} than the {s['city']} average ({city_stats['score']:.0f}). "
                   f"Best station in the city: {city_stats['best_station']} ({city_stats['best_score']:.0f}); "
                   f"worst: {city_stats['worst_station']} ({city_stats['worst_score']:.0f}).")
    if s.get("aqi_cat"):
        out.append(f"Indicative CPCB category: {s['aqi_cat']}. {C.HEALTH[s['aqi_cat']]}")
    if s.get("pm25") is None and s.get("pm25_est") is not None:
        out.append(f"PM2.5 is not reporting here; the model estimates about {s['pm25_est']:.0f} ug/m3 from "
                   "nearby stations and other pollutants (estimate, not a measurement).")
    out.append("Based on one hourly reading compared with 24-hour standards, so treat it as a snapshot.")
    return out
