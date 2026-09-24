from datetime import datetime, timedelta

from fastapi import APIRouter


router = APIRouter(
    prefix="/api/forecast",
    tags=["Forecast"]
)


@router.get("/")
def get_forecast(
    route_id: str,
    start: datetime,
    end: datetime
):
    """
    тестовый прогноз пассажиропотока, здесь будет вызов настоящей модели
    """

    result = []

    current_time = start

    while current_time <= end:

        result.append(
            {
                "route_id": route_id,
                "stop_id": "125",
                "timestamp": current_time,
                "prediction": 35,
                "p10": 25,
                "p90": 50
            }
        )

        current_time += timedelta(minutes=15)

    return {
        "route_id": route_id,
        "forecast": result
    }