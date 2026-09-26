"""
Phase 1: GPS simulator.

Generates a plausible route (small random-walk steps around a start point,
occasionally "commuting" toward a second point) and POSTs pings to the
FastAPI backend, just like a real phone would. This lets you build and test
the whole backend + dashboard before touching Android/iOS at all.

Usage:
    python gps_simulator.py --device-id 1 --lat 29.4241 --lon -98.4936
"""

import argparse
import random
import time
import requests

API_URL = "https://gps-detect-tracker.fly.dev"


def login_or_register(username: str, password: str) -> str:
    """Try logging in; if the user doesn't exist yet, register then log in."""
    resp = requests.post(f"{API_URL}/auth/login", data={"username": username, "password": password})
    if resp.ok:
        return resp.json()["access_token"]

    reg = requests.post(f"{API_URL}/auth/register", json={"username": username, "password": password})
    if not reg.ok:
        raise RuntimeError(f"Could not register or log in as '{username}': {reg.text}")

    resp = requests.post(f"{API_URL}/auth/login", data={"username": username, "password": password})
    resp.raise_for_status()
    return resp.json()["access_token"]


def register_device(name: str, owner: str, token: str) -> int:
    resp = requests.post(
        f"{API_URL}/devices",
        json={"device_name": name, "owner_name": owner},
        headers={"Authorization": f"Bearer {token}"},
    )
    resp.raise_for_status()
    return resp.json()["id"]


def simulate_route(device_id: int, start_lat: float, start_lon: float, steps: int = 200, interval: float = 2.0):
    lat, lon = start_lat, start_lon

    for i in range(steps):
        # Small random-walk step (~roughly walking/driving pace depending on interval)
        lat += random.uniform(-0.0006, 0.0006)
        lon += random.uniform(-0.0006, 0.0006)
        speed = round(random.uniform(0.5, 15.0), 2)   # m/s
        accuracy = round(random.uniform(3.0, 12.0), 2)  # meters

        payload = {
            "device_id": device_id,
            "latitude": round(lat, 6),
            "longitude": round(lon, 6),
            "accuracy": accuracy,
            "speed": speed,
        }

        try:
            resp = requests.post(f"{API_URL}/locations", json=payload)
            resp.raise_for_status()
            print(f"[{i+1}/{steps}] sent -> lat={lat:.6f} lon={lon:.6f} speed={speed} m/s")
        except requests.exceptions.RequestException as e:
            print(f"Failed to send ping: {e}")

        time.sleep(interval)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--device-id", type=int, help="Existing device ID. If omitted, registers a new device.")
    parser.add_argument("--name", type=str, default="Simulated Phone")
    parser.add_argument("--owner", type=str, default="Test User")
    parser.add_argument("--username", type=str, default="marco", help="Account to own this device (auto-registers if it doesn't exist)")
    parser.add_argument("--password", type=str, default="changeme123")
    parser.add_argument("--lat", type=float, default=29.4241, help="Starting latitude (default: San Antonio, TX)")
    parser.add_argument("--lon", type=float, default=-98.4936, help="Starting longitude")
    parser.add_argument("--steps", type=int, default=200)
    parser.add_argument("--interval", type=float, default=2.0, help="Seconds between pings")
    args = parser.parse_args()

    device_id = args.device_id
    if device_id is None:
        token = login_or_register(args.username, args.password)
        device_id = register_device(args.name, args.owner, token)
        print(f"Registered new device with id={device_id} (owned by '{args.username}')")

    simulate_route(device_id, args.lat, args.lon, args.steps, args.interval)