import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.repositories.gtfs_repository import GTFSRepository
from app.repositories.forecast_repository import ForecastRepository

from app.api.routes import create_routes_router
from app.api.stops import create_stops_router
from app.api.assignments import create_assignments_router
from app.api.forecast_integration import create_forecast_router


# =========================================================
# Пути к файлам (справочник)
# =========================================================

PROJECT_ROOT = Path(__file__).resolve().parents[2]

GTFS_FILE = Path(os.getenv("GTFS_EXCEL_PATH", str(PROJECT_ROOT / "dataset" / "spravochniki" / "Хакатон_справочники_трамвай_10_маршрутов.xlsx")))
FORECAST_FILE = Path(os.getenv("FORECAST_CSV_PATH", str(PROJECT_ROOT / "data" / "processed" / "forecast.csv")))
if not FORECAST_FILE.is_file():
    development_submission = PROJECT_ROOT / "MT-Hackathon-2026" / "data" / "test_submission.csv"
    if development_submission.is_file():
        FORECAST_FILE = development_submission


# =========================================================
# Справочник
# =========================================================

gtfs_repository = GTFSRepository(
    GTFS_FILE
)
forecast_repository = ForecastRepository(FORECAST_FILE) if FORECAST_FILE.is_file() else None


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
    allow_origins=[value.strip() for value in os.getenv("CORS_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173").split(",") if value.strip()],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================================================
# Маршруты
# =========================================================

if forecast_repository is not None:
    app.include_router(create_forecast_router(forecast_repository, gtfs_repository), prefix="/api")

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
        "status": "ok" if forecast_repository is not None else "degraded",
        "service": "tram-forecast-backend",
        "forecast_loaded": forecast_repository is not None,
        "forecast_source": FORECAST_FILE.name if forecast_repository is not None else None,
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
