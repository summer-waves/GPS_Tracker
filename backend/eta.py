"""
ETA prediction -- "how long will it take this device to reach a
destination?" Rather than jumping straight to a trained regression model
(which needs far more historical trips than a portfolio project will
realistically have), this uses the device's own historical trip speeds as
the model: predicted time = distance / typical speed, with a prediction
interval built from the spread of the device's own past speeds. That's
still a real statistical model (mean + standard deviation of a per-device
distribution), just an honest one for the amount of data you'll actually
have -- and it degrades gracefully instead of guessing wildly when there's
no history yet.
"""

from typing import List, Dict, Optional
import numpy as np
from analytics import haversine_distance

# Used only when a device has no trip history yet -- a generic mixed
# urban/highway assumption, clearly labeled as a fallback in the response.
DEFAULT_SPEED_MPS = 11.0  # ~25 mph


def predict_eta(
    current_lat: float, current_lon: float,
    dest_lat: float, dest_lon: float,
    historical_speeds_mps: List[float],
) -> Dict:
    distance_m = haversine_distance(current_lat, current_lon, dest_lat, dest_lon)

    moving_speeds = [s for s in historical_speeds_mps if s and s > 0.5]  # drop near-zero/stationary pings

    if len(moving_speeds) >= 3:
        avg_speed = float(np.mean(moving_speeds))
        std_speed = float(np.std(moving_speeds))
        method = "historical"
    else:
        avg_speed = DEFAULT_SPEED_MPS
        std_speed = DEFAULT_SPEED_MPS * 0.4  # a wide, honestly-uncertain band
        method = "default_assumption"

    eta_minutes = (distance_m / avg_speed) / 60.0

    # Faster-than-average -> lower bound; slower-than-average -> upper bound.
    fast_speed = max(avg_speed + std_speed, 0.1)
    slow_speed = max(avg_speed - std_speed, 0.1)
    lower_minutes = (distance_m / fast_speed) / 60.0
    upper_minutes = (distance_m / slow_speed) / 60.0

    return {
        "distance_m": round(distance_m, 1),
        "distance_mi": round(distance_m / 1609.34, 2),
        "predicted_eta_minutes": round(eta_minutes, 1),
        "eta_interval_minutes": [round(lower_minutes, 1), round(upper_minutes, 1)],
        "assumed_speed_mps": round(avg_speed, 2),
        "method": method,
        "num_historical_trips_used": len(moving_speeds),
    }
