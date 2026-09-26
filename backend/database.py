"""
Database setup.

Local dev: SQLite (zero config, just works).
Production: point DATABASE_URL at your Supabase Postgres connection string
(Project Settings -> Database -> Connection string) and this switches over
automatically. Supabase has PostGIS available as an extension you enable
from the dashboard (Database -> Extensions -> postgis) -- once enabled,
swap the `latitude`/`longitude` Float columns in models.py for a single
`geometry(Point, 4326)` column if/when you want real geospatial queries
(ST_DWithin, ST_Distance, etc.) instead of manual Haversine math.
"""

import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

load_dotenv(override=True)  # reads backend/.env if present -- put DATABASE_URL there for Supabase
# override=True: an existing OS-level env var named DATABASE_URL would otherwise
# silently win over .env, since load_dotenv() defaults to NOT overwriting
# variables that already exist in the environment.

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./gps_tracker.db")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()