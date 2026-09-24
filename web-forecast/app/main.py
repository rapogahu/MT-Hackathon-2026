from fastapi import FastAPI

from app.routes import router as routes_router
from app.stops import router as stops_router
from app.forecast import router as forecast_router


app = FastAPI(
    title="Tram Passenger Flow Forecast API",
    description="Backend для прогнозирования",
    version="0.1.0",
)


app.include_router(routes_router)
app.include_router(stops_router)
app.include_router(forecast_router)


@app.get("/")
def root():
    return {
        "message": "Tram Forecast API is running"
    }


@app.get("/api/health")
def health():
    return {
        "status": "ok"
    }