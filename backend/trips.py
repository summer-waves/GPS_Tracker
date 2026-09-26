"""
Trip detection -- segments a device's location history into discrete trips.
A gap of `gap_minutes` or more between consecutive pings is treated as a
stop, and everything after it starts a new trip. Reuses compute_summary()
from analytics.py for the per-trip distance/speed stats rather than
duplicating that math.
"""

from datetime import timedelta
from typing import List, Dict
from analytics import compute_summary


def detect_trips(pings: List[Dict], gap_minutes: float = 10.0) -> List[Dict]:
    """
    pings: list of dicts with latitude, longitude, recorded_at (datetime), speed,
    sorted oldest -> newest.
    """
    if not pings:
        return []

    gap = timedelta(minutes=gap_minutes)
    segments = [[pings[0]]]

    for prev, curr in zip(pings, pings[1:]):
        if curr["recorded_at"] - prev["recorded_at"] > gap:
            segments.append([])
        segments[-1].append(curr)

    trips = []
    for i, segment in enumerate(segments):
        if len(segment) < 2:
            continue  # single stray ping isn't a "trip"
        summary = compute_summary(segment)
        trips.append({
            "trip_number": i + 1,
            "start_time": segment[0]["recorded_at"],
            "end_time": segment[-1]["recorded_at"],
            "start_lat": segment[0]["latitude"],
            "start_lon": segment[0]["longitude"],
            "end_lat": segment[-1]["latitude"],
            "end_lon": segment[-1]["longitude"],
            **summary,
        })

    return trips
