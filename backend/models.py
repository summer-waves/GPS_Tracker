from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from database import Base


class User(Base):
    """A real account -- either a device owner, a viewer someone shared with, or both."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class Device(Base):
    __tablename__ = "devices"

    id = Column(Integer, primary_key=True, index=True)
    device_name = Column(String, index=True)     # e.g. "Mom's Phone"
    owner_name = Column(String)                  # display name -- kept for convenience alongside owner_user_id
    owner_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # the actual authenticated owner
    is_sharing = Column(Boolean, default=True)   # consent toggle -- must be True to accept pings
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    locations = relationship("LocationPing", back_populates="device")


class LocationPing(Base):
    __tablename__ = "location_pings"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(Integer, ForeignKey("devices.id"))
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    accuracy = Column(Float, nullable=True)       # meters
    speed = Column(Float, nullable=True)          # m/s
    recorded_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    device = relationship("Device", back_populates="locations")


class SharePermission(Base):
    """Who is allowed to view a given device's location, enforced server-side (see auth.can_view_device)."""
    __tablename__ = "share_permissions"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(Integer, ForeignKey("devices.id"))
    viewer_user_id = Column(Integer, ForeignKey("users.id"))
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class Geofence(Base):
    """A named circular zone (Home, Work, Gym...) defined per device."""
    __tablename__ = "geofences"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(Integer, ForeignKey("devices.id"))
    name = Column(String)
    center_lat = Column(Float, nullable=False)
    center_lon = Column(Float, nullable=False)
    radius_meters = Column(Float, default=150.0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class GeofenceEvent(Base):
    """Audit log entry: a device entered or left a geofence."""
    __tablename__ = "geofence_events"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(Integer, ForeignKey("devices.id"))
    geofence_id = Column(Integer, ForeignKey("geofences.id"))
    event_type = Column(String)  # "ENTERED" or "LEFT"
    occurred_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))