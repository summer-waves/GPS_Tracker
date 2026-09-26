"""
Anomaly detection -- flags pings that look statistically unusual for a
GIVEN DEVICE'S OWN history, not against some universal rule. Combines:
  - distance from the device's own established frequent locations
  - time of day
  - speed

Uses Isolation Forest (unsupervised) rather than fixed thresholds, so
"unusual" is learned per-device instead of hardcoded (a device that
normally commutes 40 miles daily has a different baseline than one that
never leaves a five-block radius).

Needs a reasonable amount of history before it can tell normal from
unusual -- see min_pings below. A device with only home-clustered pings
will correctly find nothing anomalous; that's the model working, not a bug.
"""

from typing import List, Dict
import numpy as np
from sklearn.ensemble import IsolationForest
from analytics import haversine_distance, find_frequent_locations

MAX_PLAUSIBLE_SPEED_MPS = 90.0  # ~200 mph -- generous ceiling, just catches physically impossible jumps


def detect_speed_anomalies(pings: List[Dict]) -> List[Dict]:
    """
    Rule-based, works from the very first ping (no history needed): flags
    any ping-to-ping jump implying a physically implausible speed --
    catches GPS glitches or spoofed data, independent of the learned model
    below.
    """
    flags = []
    for prev, curr in zip(pings, pings[1:]):
        dt = (curr["recorded_at"] - prev["recorded_at"]).total_seconds()
        if dt <= 0:
            continue
        dist = haversine_distance(prev["latitude"], prev["longitude"], curr["latitude"], curr["longitude"])
        implied_speed = dist / dt
        if implied_speed > MAX_PLAUSIBLE_SPEED_MPS:
            flags.append({
                "latitude": curr["latitude"],
                "longitude": curr["longitude"],
                "recorded_at": curr["recorded_at"],
                "anomaly_score": None,
                "reasons": [f"implied speed of {implied_speed:.1f} m/s between consecutive pings is not physically plausible"],
            })
    return flags


def detect_statistical_anomalies(pings: List[Dict], contamination: float = 0.05, min_pings: int = 20) -> List[Dict]:
    """
    pings: list of dicts with latitude, longitude, recorded_at (datetime), speed,
    sorted oldest -> newest.

    Returns pings flagged as anomalous, each with a plain-English reason,
    most anomalous first.
    """
    if len(pings) < min_pings:
        return []  # not enough history to establish what's "normal" yet

    # Establish this device's own known places from its own history.
    clusters = find_frequent_locations(
        [{"latitude": p["latitude"], "longitude": p["longitude"]} for p in pings],
        eps_meters=200, min_samples=max(5, len(pings) // 20),
    )

    def distance_from_known_places(p):
        if not clusters:
            return 0.0  # no established pattern yet -- can't call anything "far"
        return min(
            haversine_distance(p["latitude"], p["longitude"], c["center_lat"], c["center_lon"])
            for c in clusters
        )

    features = []
    for p in pings:
        hour = p["recorded_at"].hour
        dist = distance_from_known_places(p)
        speed = p.get("speed") or 0.0
        features.append([hour, dist, speed])

    X = np.array(features)
    model = IsolationForest(contamination=contamination, random_state=42)
    labels = model.fit_predict(X)          # -1 = anomaly, 1 = normal
    scores = model.decision_function(X)    # lower = more anomalous

    anomalies = []
    for p, label, score, feat in zip(pings, labels, scores, features):
        if label != -1:
            continue

        hour, dist, speed = feat
        reasons = []
        if dist > 1000:
            reasons.append(f"{dist / 1609.34:.1f} mi from any known frequent location")
        if hour < 5 or hour > 23:
            reasons.append(f"unusual hour ({int(hour)}:00)")
        if speed > 30:
            reasons.append(f"high speed ({speed:.1f} m/s)")
        if not reasons:
            reasons.append("statistically unusual combination of time, location, and speed")

        anomalies.append({
            "latitude": p["latitude"],
            "longitude": p["longitude"],
            "recorded_at": p["recorded_at"],
            "anomaly_score": round(float(score), 4),
            "reasons": reasons,
        })

    anomalies.sort(key=lambda a: a["anomaly_score"])
    return anomalies


def detect_anomalies(pings: List[Dict], contamination: float = 0.05, min_pings: int = 20) -> List[Dict]:
    """Combined: rule-based speed check (works immediately) + Isolation Forest (needs history)."""
    flags = detect_speed_anomalies(pings)
    flags += detect_statistical_anomalies(pings, contamination=contamination, min_pings=min_pings)
    flags.sort(key=lambda a: a["recorded_at"], reverse=True)
    return flags
