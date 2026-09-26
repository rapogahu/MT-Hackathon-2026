from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.repositories.gtfs_repository import (
    GTFSRepository,
)

from app.repositories.forecast_repository import (
    ForecastRepository,
)

from app.api.routes import (
    create_routes_router,
)

from app.api.stops import (
    create_stops_router,
)

from app.api.assignments import (
    create_assignments_router,
)

from app.api.forecast import (
    create_forecast_router,
)


# Путь до справочников


PROJECT_ROOT = Path(__file__).resolve().parents[2]

GTFS_FILE = (
    PROJECT_ROOT
    / "dataset"
    / "spravochniki"
    / "Хакатон_справочники_трамвай_10_маршрутов.xlsx"
)

FORECAST_FILE = (
    PROJECT_ROOT
    / "dataset"
    / "test_submission.csv"
)


# Репозитории

gtfs_repository = GTFSRepository(
    GTFS_FILE
)

forecast_repository = ForecastRepository(
    FORECAST_FILE
)


# FASTAPI


app = FastAPI(
    title="Tram Forecast API",
    description=(
        "Backend веб-сервиса прогнозирования пассажиропотока трамвайных маршрутов."
    ),
    version="0.2.0",
)



# Коры


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



# Маршруты


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

app.include_router(
    create_forecast_router(
        forecast_repository
    ),
)


# Health


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
        "version": "0.2.0",
        "docs": "/docs",
        "health": "/health",
    }