from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.repositories.gtfs_repository import GTFSRepository

from app.api.routes import create_routes_router
from app.api.stops import create_stops_router
from app.api.assignments import create_assignments_router


# =========================================================
# Пути к файлам (справочник)
# =========================================================

PROJECT_ROOT = Path(__file__).resolve().parents[2]

GTFS_FILE = (
    PROJECT_ROOT
    / "dataset"
    / "spravochniki"
    / "Хакатон_справочники_трамвай_10_маршрутов.xlsx"
)


# =========================================================
# Справочник
# =========================================================

gtfs_repository = GTFSRepository(
    GTFS_FILE
)


# =========================================================
# FAST API
# =========================================================

app = FastAPI(
    title="Tram Forecast API",
    description=(
        "Backend веб-сервиса "
        "прогнозирования пассажиропотока "
        "трамвайных маршрутов."
    ),
    version="0.1.0",
)


# =========================================================
# Кор
# =========================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================================================
# Маршруты
# =========================================================

app.include_router(
    create_routes_router(
        gtfs_repository
    ),
    prefix="/api",
)

app.include_router(
    create_stops_router(
        gtfs_repository
    ),
    prefix="/api",
)

app.include_router(
    create_assignments_router(
        gtfs_repository
    ),
    prefix="/api",
)


# =========================================================
# health
# =========================================================

@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "tram-forecast-backend",
    }

@app.get("/")
def root():
    return {
        "service": "tram-forecast-backend",
        "status": "ok",
        "version": "0.1.0",
        "docs": "/docs",
        "health": "/health",
    }