import os
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

from app.api.forecast_integration import (
    create_forecast_router,
    create_map_router,
)


# =========================================================
# PATHS
# =========================================================

PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parents[2]
)


DEFAULT_GTFS_FILE = (
    PROJECT_ROOT
    / "dataset"
    / "spravochniki"
    / "Хакатон_справочники_трамвай_10_маршрутов.xlsx"
)


DEFAULT_FORECAST_FILE = (
    PROJECT_ROOT
    / "dataset"
    / "test_submission.csv"
)


GTFS_FILE = Path(
    os.getenv(
        "GTFS_EXCEL_PATH",
        DEFAULT_GTFS_FILE,
    )
)


FORECAST_FILE = Path(
    os.getenv(
        "FORECAST_CSV_PATH",
        DEFAULT_FORECAST_FILE,
    )
)


# =========================================================
# REPOSITORIES
# =========================================================

gtfs_repository = GTFSRepository(
    GTFS_FILE
)


forecast_repository = None

if FORECAST_FILE.exists():
    forecast_repository = (
        ForecastRepository(
            FORECAST_FILE
        )
    )


# =========================================================
# FASTAPI
# =========================================================

app = FastAPI(
    title="Tram Forecast API",
    description=(
        "Backend веб-сервиса "
        "прогнозирования пассажиропотока "
        "трамвайных маршрутов."
    ),
    version="0.2.0",
)


# =========================================================
# CORS
# =========================================================

default_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

cors_origins_env = os.getenv(
    "CORS_ORIGINS"
)

if cors_origins_env:
    cors_origins = [
        origin.strip()
        for origin in cors_origins_env.split(",")
        if origin.strip()
    ]
else:
    cors_origins = default_origins


app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================================================
# REFERENCE API
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
# FORECAST API
# =========================================================

if forecast_repository is not None:

    app.include_router(
        create_forecast_router(
            forecast_repository,
            gtfs_repository,
        ),
        prefix="/api",
    )

    app.include_router(
        create_map_router(
            forecast_repository,
            gtfs_repository,
        ),
        prefix="/api",
    )


# =========================================================
# ROOT
# =========================================================

@app.get("/")
def root():
    return {
        "service": "tram-forecast-backend",
        "status": "ok",
        "version": "0.2.0",
        "forecast_loaded": (
            forecast_repository is not None
        ),
        "docs": "/docs",
        "health": "/health",
    }


# =========================================================
# HEALTH
# =========================================================

@app.get("/health")
def health():
    loaded = (
        forecast_repository is not None
    )

    return {
        "status": (
            "ok"
            if loaded
            else "degraded"
        ),
        "forecast_loaded": loaded,
    }