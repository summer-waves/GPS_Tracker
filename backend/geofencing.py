"""
Geofencing -- the "Home / Work / University, ENTERED/LEFT" piece from the
original plan. Reuses haversine_distance from analytics.py rather than
duplicating distance math.
"""

from sqlalchemy.orm import Session
import models
from analytics import haversine_distance


def check_geofences(db: Session, device_id: int, lat: float, lon: float):
    """
    Compares a new ping against every geofence defined for this device and
    logs an ENTERED/LEFT event on state transitions (not on every ping --
    only when the state actually changes). Returns the list of newly
    created events as (geofence_name, event_type) tuples.
    """
    geofences = db.query(models.Geofence).filter(models.Geofence.device_id == device_id).all()
    new_events = []

    for fence in geofences:
        distance = haversine_distance(lat, lon, fence.center_lat, fence.center_lon)
        is_inside = distance <= fence.radius_meters

        last_event = (
            db.query(models.GeofenceEvent)
            .filter(
                models.GeofenceEvent.device_id == device_id,
                models.GeofenceEvent.geofence_id == fence.id,
            )
            .order_by(models.GeofenceEvent.occurred_at.desc())
            .first()
        )
        was_inside = last_event is not None and last_event.event_type == "ENTERED"

        if is_inside and not was_inside:
            db.add(models.GeofenceEvent(device_id=device_id, geofence_id=fence.id, event_type="ENTERED"))
            new_events.append((fence.name, "ENTERED"))
        elif not is_inside and was_inside:
            db.add(models.GeofenceEvent(device_id=device_id, geofence_id=fence.id, event_type="LEFT"))
            new_events.append((fence.name, "LEFT"))

    if new_events:
        db.commit()

    return new_events
