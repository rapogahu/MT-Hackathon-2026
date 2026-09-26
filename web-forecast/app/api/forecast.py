from datetime import date

from fastapi import APIRouter, HTTPException, Query

from app.repositories.forecast_repository import (
    ForecastRepository,
)


def create_forecast_router(
    repository: ForecastRepository,
) -> APIRouter:

    router = APIRouter(
        prefix="/api/forecast",
        tags=["Forecast"],
    )

    # GET /api/forecast/routes

    @router.get("/routes")
    def get_forecast_routes():
        """
        Получить маршруты, для которых
        доступны прогнозы.
        """

        routes = repository.get_routes()

        return {
            "count": len(routes),
            "routes": routes,
        }

    # GET /api/forecast/dates

    @router.get("/dates")
    def get_forecast_dates():
        """
        Получить доступный период прогнозирования.

        Frontend может использовать этот endpoint
        для календаря и выбора периода.
        """

        date_range = repository.get_date_range()

        return {
            "start": date_range["start"],
            "end": date_range["end"],
        }

    # GET /api/forecast

    @router.get("")
    def get_forecast(
        route: int = Query(
            ...,
            description="Номер маршрута",
        ),
        forecast_date: date = Query(
            ...,
            alias="date",
            description="Дата прогноза",
        ),
    ):
        """
        Получить прогноз по часам для одного маршрута за один день.

        Пример: /api/forecast?route=1&date=2025-11-15
        """

        if not repository.has_route(route):
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Маршрут №{route} "
                    "отсутствует в прогнозах."
                ),
            )

        if not repository.has_date(
            forecast_date
        ):
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Дата {forecast_date} отсутствует в прогнозах."
                ),
            )

        forecast = repository.get_forecast(
            route=route,
            forecast_date=forecast_date,
        )

        return {
            "route": route,
            "date": forecast_date,
            "forecast": forecast,
        }

    # GET /api/forecast/period

    @router.get("/period")
    def get_forecast_period(
        route: int = Query(
            ...,
            description="Номер маршрута",
        ),
        start: date = Query(
            ...,
            description="Начало периода",
        ),
        end: date = Query(
            ...,
            description="Конец периода",
        ),
    ):
        """
        Получить прогноз за период.

        Пример: /api/forecast/period?route=1&start=2025-11-01&end=2025-11-30
        """

        if start > end:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Дата начала периода не может быть позже даты окончания."
                ),
            )

        if not repository.has_route(route):
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Маршрут №{route} отсутствует в прогнозах."
                ),
            )

        forecast = repository.get_period(
            route=route,
            start=start,
            end=end,
        )

        return {
            "route": route,
            "start": start,
            "end": end,
            "count": len(forecast),
            "forecast": forecast,
        }

    # GET /api/forecast/summary

    @router.get("/summary")
    def get_forecast_summary(
        route: int = Query(
            ...,
            description="Номер маршрута",
        ),
        start: date = Query(
            ...,
            description="Начало периода",
        ),
        end: date = Query(
            ...,
            description="Конец периода",
        ),
    ):
        """
        Получить агрегированную информацию.
        """

        if start > end:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Дата начала периода не может быть позже даты окончания."
                ),
            )

        if not repository.has_route(route):
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Маршрут №{route} отсутствует в прогнозах."
                ),
            )

        summary = repository.get_summary(
            route=route,
            start=start,
            end=end,
        )

        return {
            "route": route,
            "start": start,
            "end": end,
            **summary,
        }

    return router