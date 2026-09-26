from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from sqlalchemy import desc

import models
import schemas
import analytics
import geofencing
import trips
import anomaly
import eta
import auth
from database import engine, get_db

models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Consent-Based Location Tracker")

# Needed so a browser page (the web-client, opened from a file:// or different
# port) is allowed to call this API directly. Fine for local dev -- tighten
# this to your real frontend's domain once you deploy.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serves web-client/index.html (copied into backend/static/) at /client --
# gets it a real HTTPS URL for free from the same deployment, which mobile
# browsers require for Geolocation API access (a local file:// origin often
# won't work on phones the way it does on desktop Chrome).
app.mount("/client", StaticFiles(directory="static", html=True), name="client")


@app.post("/auth/register", response_model=schemas.UserOut)
def register_user(user: schemas.UserCreate, db: Session = Depends(get_db)):
    existing = db.query(models.User).filter(models.User.username == user.username).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username already taken")
    db_user = models.User(username=user.username, hashed_password=auth.hash_password(user.password))
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


@app.post("/auth/login", response_model=schemas.Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.username == form_data.username).first()
    if not user or not auth.verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    token = auth.create_access_token({"sub": user.username})
    return {"access_token": token, "token_type": "bearer"}


@app.post("/devices", response_model=schemas.DeviceOut)
def register_device(
    device: schemas.DeviceCreate, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_user)
):
    db_device = models.Device(
        device_name=device.device_name, owner_name=device.owner_name, owner_user_id=current_user.id
    )
    db.add(db_device)
    db.commit()
    db.refresh(db_device)
    return db_device


@app.get("/devices", response_model=list[schemas.DeviceOut])
def list_devices(db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_user)):
    """Devices this user owns, plus devices explicitly shared with them (deduplicated)."""
    owned = db.query(models.Device).filter(models.Device.owner_user_id == current_user.id).all()
    shared_ids = [
        s.device_id for s in
        db.query(models.SharePermission).filter(
            models.SharePermission.viewer_user_id == current_user.id,
            models.SharePermission.active == True,  # noqa: E712
        ).all()
    ]
    shared = db.query(models.Device).filter(models.Device.id.in_(shared_ids)).all() if shared_ids else []

    seen_ids = set()
    deduplicated = []
    for device in owned + shared:
        if device.id not in seen_ids:
            seen_ids.add(device.id)
            deduplicated.append(device)
    return deduplicated


@app.post("/devices/{device_id}/sharing", response_model=schemas.DeviceOut)
def set_sharing(
    device_id: int, toggle: schemas.SharingToggle, db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """The consent switch. Only the device owner (the tracked person) controls this -- not a viewer."""
    device = auth.require_owner(db, current_user, device_id)
    device.is_sharing = toggle.is_sharing
    db.commit()
    db.refresh(device)
    return device


@app.post("/locations", response_model=schemas.LocationOut)
def post_location(loc: schemas.LocationIn, db: Session = Depends(get_db)):
    # Intentionally NOT behind user auth -- this is the device itself posting
    # its own data, not a logged-in viewer. In production this would carry a
    # per-device API key/token instead of trusting a bare device_id; that's
    # the natural next hardening step once you deploy past localhost.
    device = db.query(models.Device).filter(models.Device.id == loc.device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Unknown device_id -- register the device first")
    if not device.is_sharing:
        # Enforced server-side, not just hidden in a UI -- this is the whole point.
        raise HTTPException(status_code=403, detail="Sharing is currently OFF for this device")

    ping = models.LocationPing(
        device_id=loc.device_id,
        latitude=loc.latitude,
        longitude=loc.longitude,
        accuracy=loc.accuracy,
        speed=loc.speed,
    )
    db.add(ping)
    db.commit()
    db.refresh(ping)

    geofencing.check_geofences(db, loc.device_id, loc.latitude, loc.longitude)

    return ping


@app.get("/devices/{device_id}/location", response_model=schemas.LocationOut)
def latest_location(
    device_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_user)
):
    auth.require_view_access(db, current_user, device_id)
    ping = (
        db.query(models.LocationPing)
        .filter(models.LocationPing.device_id == device_id)
        .order_by(desc(models.LocationPing.recorded_at))
        .first()
    )
    if not ping:
        raise HTTPException(status_code=404, detail="No location data yet for this device")
    return ping


@app.get("/devices/{device_id}/history", response_model=list[schemas.LocationOut])
def location_history(
    device_id: int, limit: int = 200, db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    auth.require_view_access(db, current_user, device_id)
    return (
        db.query(models.LocationPing)
        .filter(models.LocationPing.device_id == device_id)
        .order_by(desc(models.LocationPing.recorded_at))
        .limit(limit)
        .all()
    )


@app.get("/devices/{device_id}/analytics/summary")
def analytics_summary(
    device_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_user)
):
    """Distance traveled, avg/max speed, duration -- over all recorded pings."""
    auth.require_view_access(db, current_user, device_id)
    pings = (
        db.query(models.LocationPing)
        .filter(models.LocationPing.device_id == device_id)
        .order_by(models.LocationPing.recorded_at)
        .all()
    )
    if not pings:
        raise HTTPException(status_code=404, detail="No location data yet for this device")

    ping_dicts = [
        {"latitude": p.latitude, "longitude": p.longitude, "recorded_at": p.recorded_at, "speed": p.speed}
        for p in pings
    ]
    return analytics.compute_summary(ping_dicts)


@app.get("/devices/{device_id}/analytics/frequent-locations")
def analytics_frequent_locations(
    device_id: int, eps_meters: float = 150, min_samples: int = 5, db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """Auto-detected frequently visited places (home, work, etc.) via DBSCAN clustering."""
    auth.require_view_access(db, current_user, device_id)
    pings = db.query(models.LocationPing).filter(models.LocationPing.device_id == device_id).all()
    if not pings:
        raise HTTPException(status_code=404, detail="No location data yet for this device")

    ping_dicts = [{"latitude": p.latitude, "longitude": p.longitude} for p in pings]
    return analytics.find_frequent_locations(ping_dicts, eps_meters=eps_meters, min_samples=min_samples)


@app.get("/devices/{device_id}/trips")
def device_trips(
    device_id: int, gap_minutes: float = 10.0, db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """History split into discrete trips -- a gap of gap_minutes+ between pings starts a new trip."""
    auth.require_view_access(db, current_user, device_id)
    pings = (
        db.query(models.LocationPing)
        .filter(models.LocationPing.device_id == device_id)
        .order_by(models.LocationPing.recorded_at)
        .all()
    )
    if not pings:
        raise HTTPException(status_code=404, detail="No location data yet for this device")

    ping_dicts = [
        {"latitude": p.latitude, "longitude": p.longitude, "recorded_at": p.recorded_at, "speed": p.speed}
        for p in pings
    ]
    return trips.detect_trips(ping_dicts, gap_minutes=gap_minutes)


@app.get("/devices/{device_id}/anomalies")
def device_anomalies(
    device_id: int, contamination: float = 0.05, db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """Flags physically implausible jumps plus statistically unusual location/time/speed patterns."""
    auth.require_view_access(db, current_user, device_id)
    pings = (
        db.query(models.LocationPing)
        .filter(models.LocationPing.device_id == device_id)
        .order_by(models.LocationPing.recorded_at)
        .all()
    )
    if not pings:
        raise HTTPException(status_code=404, detail="No location data yet for this device")

    ping_dicts = [
        {"latitude": p.latitude, "longitude": p.longitude, "recorded_at": p.recorded_at, "speed": p.speed}
        for p in pings
    ]
    return anomaly.detect_anomalies(ping_dicts, contamination=contamination)


@app.post("/eta")
def predict_eta(
    req: schemas.ETARequest, db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """Predicted time to reach a destination, based on this device's own historical speeds."""
    auth.require_view_access(db, current_user, req.device_id)

    latest = (
        db.query(models.LocationPing)
        .filter(models.LocationPing.device_id == req.device_id)
        .order_by(desc(models.LocationPing.recorded_at))
        .first()
    )
    if not latest:
        raise HTTPException(status_code=404, detail="No location data yet for this device")

    historical_speeds = [
        p.speed for p in
        db.query(models.LocationPing).filter(models.LocationPing.device_id == req.device_id).all()
    ]

    return eta.predict_eta(latest.latitude, latest.longitude, req.dest_lat, req.dest_lon, historical_speeds)


@app.post("/geofences", response_model=schemas.GeofenceOut)
def create_geofence(
    fence: schemas.GeofenceCreate, db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    auth.require_view_access(db, current_user, fence.device_id)

    db_fence = models.Geofence(
        device_id=fence.device_id,
        name=fence.name,
        center_lat=fence.center_lat,
        center_lon=fence.center_lon,
        radius_meters=fence.radius_meters,
    )
    db.add(db_fence)
    db.commit()
    db.refresh(db_fence)
    return db_fence


@app.get("/devices/{device_id}/geofences", response_model=list[schemas.GeofenceOut])
def list_geofences(
    device_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_user)
):
    auth.require_view_access(db, current_user, device_id)
    return db.query(models.Geofence).filter(models.Geofence.device_id == device_id).all()


@app.delete("/geofences/{geofence_id}")
def delete_geofence(
    geofence_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_user)
):
    fence = db.query(models.Geofence).filter(models.Geofence.id == geofence_id).first()
    if not fence:
        raise HTTPException(status_code=404, detail="Geofence not found")
    auth.require_view_access(db, current_user, fence.device_id)
    db.delete(fence)
    db.commit()
    return {"deleted": geofence_id}


@app.get("/devices/{device_id}/geofence-events", response_model=list[schemas.GeofenceEventOut])
def geofence_events(
    device_id: int, limit: int = 50, db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    auth.require_view_access(db, current_user, device_id)
    return (
        db.query(models.GeofenceEvent)
        .filter(models.GeofenceEvent.device_id == device_id)
        .order_by(desc(models.GeofenceEvent.occurred_at))
        .limit(limit)
        .all()
    )


@app.post("/devices/{device_id}/share")
def share_device(
    device_id: int, share: schemas.ShareCreate, db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """Grant (or re-activate) another user's access to this device. Owner only."""
    auth.require_owner(db, current_user, device_id)

    viewer = db.query(models.User).filter(models.User.username == share.viewer_username).first()
    if not viewer:
        raise HTTPException(status_code=404, detail=f"No user named '{share.viewer_username}'")

    existing = (
        db.query(models.SharePermission)
        .filter(models.SharePermission.device_id == device_id, models.SharePermission.viewer_user_id == viewer.id)
        .first()
    )
    if existing:
        existing.active = True
        db.commit()
        return {"device_id": device_id, "shared_with": share.viewer_username, "active": True}

    grant = models.SharePermission(device_id=device_id, viewer_user_id=viewer.id, active=True)
    db.add(grant)
    db.commit()
    return {"device_id": device_id, "shared_with": share.viewer_username, "active": True}


@app.delete("/devices/{device_id}/share/{viewer_username}")
def revoke_share(
    device_id: int, viewer_username: str, db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """Revoke another user's access. Owner only."""
    auth.require_owner(db, current_user, device_id)

    viewer = db.query(models.User).filter(models.User.username == viewer_username).first()
    if not viewer:
        raise HTTPException(status_code=404, detail=f"No user named '{viewer_username}'")

    grant = (
        db.query(models.SharePermission)
        .filter(models.SharePermission.device_id == device_id, models.SharePermission.viewer_user_id == viewer.id)
        .first()
    )
    if not grant:
        raise HTTPException(status_code=404, detail="No share grant found for this user")
    grant.active = False
    db.commit()
    return {"device_id": device_id, "revoked_from": viewer_username}


@app.get("/devices/{device_id}/shares")
def list_shares(
    device_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_user)
):
    """Who currently has access to this device. Owner only."""
    auth.require_owner(db, current_user, device_id)
    grants = (
        db.query(models.SharePermission)
        .filter(models.SharePermission.device_id == device_id, models.SharePermission.active == True)  # noqa: E712
        .all()
    )
    result = []
    for g in grants:
        viewer = db.query(models.User).filter(models.User.id == g.viewer_user_id).first()
        result.append({"viewer_username": viewer.username if viewer else "unknown", "active": g.active})
    return result


@app.delete("/devices/{device_id}")
def delete_device(
    device_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_user)
):
    """Permanently remove a device and everything tied to it (pings, geofences, shares). Owner only."""
    auth.require_owner(db, current_user, device_id)

    db.query(models.LocationPing).filter(models.LocationPing.device_id == device_id).delete()
    db.query(models.GeofenceEvent).filter(models.GeofenceEvent.device_id == device_id).delete()
    db.query(models.Geofence).filter(models.Geofence.device_id == device_id).delete()
    db.query(models.SharePermission).filter(models.SharePermission.device_id == device_id).delete()
    db.query(models.Device).filter(models.Device.id == device_id).delete()
    db.commit()
    return {"deleted": device_id}