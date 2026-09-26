"""
Analytics layer, mirroring your phishing detector's ml/ scripts:
- compute_summary()          ~ evaluate.py-style metrics reporting
- find_frequent_locations()  ~ your train.py, but clustering instead of classifying

No PostGIS needed for any of this -- plain lat/lon + scikit-learn is enough
until you're doing serious spatial queries (radius search, geofence
containment at scale), which is what Phase 2 (Supabase + PostGIS) buys you.
"""

import math
from typing import List, Dict, Optional
import numpy as np
from sklearn.cluster import DBSCAN


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points, in meters."""
    R = 6371000  # Earth radius in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def compute_summary(pings: List[Dict]) -> Dict:
    """
    pings: list of dicts with latitude, longitude, recorded_at (datetime), speed,
    sorted oldest -> newest.
    """
    if len(pings) < 2:
        return {
            "total_distance_m": 0.0,
            "total_distance_mi": 0.0,
            "avg_speed_mps": None,
            "max_speed_mps": None,
            "duration_minutes": 0.0,
            "num_points": len(pings),
        }

    total_distance = 0.0
    speeds = []
    for i in range(1, len(pings)):
        p1, p2 = pings[i - 1], pings[i]
        total_distance += haversine_distance(p1["latitude"], p1["longitude"], p2["latitude"], p2["longitude"])
        if p2.get("speed") is not None:
            speeds.append(p2["speed"])

    duration_minutes = (pings[-1]["recorded_at"] - pings[0]["recorded_at"]).total_seconds() / 60.0

    return {
        "total_distance_m": round(total_distance, 1),
        "total_distance_mi": round(total_distance / 1609.34, 2),
        "avg_speed_mps": round(sum(speeds) / len(speeds), 2) if speeds else None,
        "max_speed_mps": round(max(speeds), 2) if speeds else None,
        "duration_minutes": round(duration_minutes, 1),
        "num_points": len(pings),
    }


def find_frequent_locations(
    pings: List[Dict], eps_meters: float = 150, min_samples: int = 5
) -> List[Dict]:
    """
    DBSCAN over raw lat/lon to auto-detect frequently visited places
    (home, work, gym, etc.) without being told what they are.

    eps_meters: how close two points need to be to count as "the same place".
    min_samples: how many pings are needed before a cluster counts as a real
    place (filters out one-off passes-through).

    Degrees-per-meter conversion is approximate (~111km/degree of latitude)
    and only good for a single metro area -- fine here, but if you later
    track someone traveling across a wide latitude range, switch to a
    proper projected distance (or just move this logic into a PostGIS
    ST_ClusterDBSCAN query once you're on Phase 2).
    """
    if len(pings) < min_samples:
        return []

    coords = np.array([[p["latitude"], p["longitude"]] for p in pings])
    eps_deg = eps_meters / 111_000.0

    labels = DBSCAN(eps=eps_deg, min_samples=min_samples).fit(coords).labels_

    clusters = []
    for label in set(labels):
        if label == -1:
            continue  # noise -- one-off points that aren't a "place"
        cluster_points = coords[labels == label]
        clusters.append({
            "cluster_id": int(label),
            "center_lat": round(float(cluster_points[:, 0].mean()), 6),
            "center_lon": round(float(cluster_points[:, 1].mean()), 6),
            "num_visits": int(len(cluster_points)),
        })

    clusters.sort(key=lambda c: -c["num_visits"])
    return clusters
