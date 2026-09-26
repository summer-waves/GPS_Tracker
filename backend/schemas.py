from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class DeviceCreate(BaseModel):
    device_name: str
    owner_name: str


class DeviceOut(BaseModel):
    id: int
    device_name: str
    owner_name: str
    is_sharing: bool

    class Config:
        from_attributes = True


class LocationIn(BaseModel):
    device_id: int
    latitude: float
    longitude: float
    accuracy: Optional[float] = None
    speed: Optional[float] = None


class LocationOut(BaseModel):
    id: int
    device_id: int
    latitude: float
    longitude: float
    accuracy: Optional[float]
    speed: Optional[float]
    recorded_at: datetime

    class Config:
        from_attributes = True


class SharingToggle(BaseModel):
    is_sharing: bool


class GeofenceCreate(BaseModel):
    device_id: int
    name: str
    center_lat: float
    center_lon: float
    radius_meters: float = 150.0


class GeofenceOut(BaseModel):
    id: int
    device_id: int
    name: str
    center_lat: float
    center_lon: float
    radius_meters: float

    class Config:
        from_attributes = True


class GeofenceEventOut(BaseModel):
    id: int
    device_id: int
    geofence_id: int
    event_type: str
    occurred_at: datetime

    class Config:
        from_attributes = True


class ETARequest(BaseModel):
    device_id: int
    dest_lat: float
    dest_lon: float


class UserCreate(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    id: int
    username: str

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ShareCreate(BaseModel):
    viewer_username: str


class SharePermissionOut(BaseModel):
    id: int
    device_id: int
    viewer_user_id: int
    active: bool

    class Config:
        from_attributes = True