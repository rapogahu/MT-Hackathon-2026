from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from app.repositories.forecast_repository import (
    ForecastRepository,
)
from app.repositories.gtfs_repository import (
    GTFSRepository,
)


def create_forecast_router(
    forecast_repository: ForecastRepository,
    gtfs_repository: GTFSRepository,
) -> APIRouter:

    router = APIRouter(
        prefix="/forecast",
        tags=["Forecast"],
    )

    # =========================================================
    # RUNS
    # =========================================================

    @router.get("/runs")
    def get_runs():
        """
        Получить список доступных forecast runs.
        """

        metadata = forecast_repository.get_run_metadata()
        run_id = forecast_repository.get_run_id()

        return {
            "active_run_id": run_id,
            "active_runs": {
                "day": None,
                "month": run_id,
                "year": None,
            },
            "runs": [
                metadata,
            ],
        }

    @router.get("/runs/{run_id}")
    def get_run(run_id: str):
        """
        Получить информацию о конкретном run.
        """

        _check_run(
            forecast_repository,
            run_id,
        )

        return forecast_repository.get_run_metadata()

    # =========================================================
    # ROUTES
    # =========================================================

    @router.get("/routes")
    def get_forecast_routes(
        run_id: str = Query(...),
    ):
        """
        Получить маршруты, доступные в прогнозе,
        с метаданными из GTFS.
        """

        _check_run(
            forecast_repository,
            run_id,
        )

        forecast_routes = forecast_repository.get_routes()

        routes = []

        for route_number in forecast_routes:
            route_info = (
                gtfs_repository
                .get_route_by_number(
                    str(route_number)
                )
            )

            if not route_info:
                routes.append(
                    {
                        "route": int(route_number),
                        "name": f"Маршрут {route_number}",
                        "gtfs_route_ids": [],
                        "geometry_available": False,
                        "forecast_available": True,
                    }
                )
                continue

            gtfs_route_ids = [
                str(item["route_id"])
                for item in route_info
                if item.get("route_id") is not None
            ]

            geometry_available = False

            for route_id in gtfs_route_ids:
                geometry = (
                    gtfs_repository
                    .get_route_geometry(
                        route_id=route_id,
                    )
                )

                if geometry:
                    geometry_available = True
                    break

            route_name = (
                route_info[0].get("route_long_name")
                or route_info[0].get("route_short_name")
                or f"Маршрут {route_number}"
            )

            routes.append(
                {
                    "route": int(route_number),
                    "name": str(route_name),
                    "gtfs_route_ids": gtfs_route_ids,
                    "geometry_available": geometry_available,
                    "forecast_available": True,
                }
            )

        return {
            "run_id": run_id,
            "routes": routes,
        }

    # =========================================================
    # DAY
    # =========================================================

    @router.get("")
    def get_forecast(
        run_id: str = Query(...),
        route: str | None = Query(None),
        date: str = Query(...),
    ):
        """
        Прогноз за конкретную дату.

        Если route не указан —
        возвращаются данные по всем маршрутам.
        """

        _check_run(
            forecast_repository,
            run_id,
        )

        _validate_date(date)

        result = forecast_repository.get_forecast(
            route=route,
            date_value=date,
        )

        return {
            "run_id": run_id,
            "route": (
                int(route)
                if route is not None and route.isdigit()
                else route
            ),
            "date": date,
            "count": len(result),
            "points": result,
        }

    # =========================================================
    # POINT
    # =========================================================

    @router.get("/point")
    def get_forecast_point(
        run_id: str = Query(...),
        route: str = Query(...),
        date: str = Query(...),
        hour: int = Query(
            ...,
            ge=0,
            le=23,
        ),
    ):
        """
        Прогноз в конкретный час.
        """

        _check_run(
            forecast_repository,
            run_id,
        )

        _validate_date(date)

        point = forecast_repository.get_point(
            route=route,
            date_value=date,
            hour=hour,
        )

        if point is None:
            raise HTTPException(
                status_code=404,
                detail="Forecast point not found.",
            )

        return {
            "run_id": run_id,
            "route": (
                int(route)
                if route.isdigit()
                else route
            ),
            "date": date,
            "hour": hour,
            "count": 1,
            "points": [
                point,
            ],
        }

    # =========================================================
    # TIMESERIES
    # =========================================================

    @router.get("/timeseries")
    def get_timeseries(
        run_id: str = Query(...),
        route: str | None = Query(None),
        from_date: str = Query(..., alias="from"),
        to_date: str = Query(..., alias="to"),
    ):
        """
        Почасовой прогноз за диапазон дат.
        """

        _check_run(
            forecast_repository,
            run_id,
        )

        _validate_range(
            from_date,
            to_date,
        )

        result = forecast_repository.get_timeseries(
            route=route,
            start=from_date,
            end=to_date,
        )

        return {
            "run_id": run_id,
            "route": (
                int(route)
                if route is not None and route.isdigit()
                else route
            ),
            "from": from_date,
            "to": to_date,
            "count": len(result),
            "points": result,
        }

    # =========================================================
    # AGGREGATE
    # =========================================================

    @router.get("/aggregate")
    def get_aggregate(
        run_id: str = Query(...),
        route: str | None = Query(None),
        from_date: str = Query(..., alias="from"),
        to_date: str = Query(..., alias="to"),
        granularity: str = Query("day"),
    ):
        """
        Агрегированный прогноз.

        Сейчас поддерживается только granularity=day.
        """

        _check_run(
            forecast_repository,
            run_id,
        )

        _validate_range(
            from_date,
            to_date,
        )

        if granularity not in {"day", "week", "month"}:
            raise HTTPException(
                status_code=400,
                detail="Supported granularity: day, week, month.",
            )

        result = forecast_repository.get_aggregate(
            route=route,
            start=from_date,
            end=to_date,
            granularity=granularity,
        )

        return {
            "run_id": run_id,
            "route": (
                int(route)
                if route is not None and route.isdigit()
                else route
            ),
            "from": from_date,
            "to": to_date,
            "granularity": granularity,
            "count": len(result),
            "points": result,
        }

    return router


# =========================================================
# MAP
# =========================================================


def create_map_router(
    forecast_repository: ForecastRepository,
    gtfs_repository: GTFSRepository,
) -> APIRouter:

    router = APIRouter(
        prefix="/map",
        tags=["Map"],
    )

    @router.get("/routes")
    def get_map_routes(
        run_id: str = Query(...),
        route: str = Query(...),
        date: str = Query(...),
        hour: int = Query(
            ...,
            ge=0,
            le=23,
        ),
    ):
        """
        Возвращает GeoJSON маршрута.

        Геометрия берётся из GTFS-справочника.
        Прогноз берётся из ForecastRepository.

        Если маршрут есть в прогнозе, но отсутствует
        в справочнике — возвращается пустой FeatureCollection.
        """

        _check_run(
            forecast_repository,
            run_id,
        )

        _validate_date(date)

        point = (
            forecast_repository
            .get_point(
                route=route,
                date_value=date,
                hour=hour,
            )
        )

        if point is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    "Прогноз не найден."
                ),
            )

        geometry = _get_route_geometry(
            gtfs_repository,
            route,
        )

        if not geometry:
            return {
                "type": "FeatureCollection",
                "features": [],
            }

        feature = {
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": [
                    [
                        float(item["stop_lon"]),
                        float(item["stop_lat"]),
                    ]
                    for item in geometry
                ],
            },
            "properties": {
                "route": point["route"],
                "load_index": point["load_index"],
                "load_category": point[
                    "load_category"
                ],
                "prediction": point[
                    "prediction"
                ],
                "geometry_id": (
                    f"route-{route}"
                ),
                "route_id": str(
                    geometry[0]["route_id"]
                ),
                "trip_id": str(
                    geometry[0]["trip_id"]
                ),
                "direction_id": int(
                    geometry[0]["direction_id"]
                ),
            },
        }

        return {
            "type": "FeatureCollection",
            "features": [
                feature
            ],
        }

    return router


# =========================================================
# HELPERS
# =========================================================


def _check_run(
    repository: ForecastRepository,
    run_id: str,
):
    if run_id != repository.get_run_id():
        raise HTTPException(
            status_code=404,
            detail=f"Run '{run_id}' не найден.",
        )


def _validate_date(
    value: str,
):
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Некорректная дата: {value}. "
                "Ожидается YYYY-MM-DD."
            ),
        ) from exc


def _validate_range(
    start: str,
    end: str,
):
    _validate_date(start)
    _validate_date(end)

    if start > end:
        raise HTTPException(
            status_code=400,
            detail=(
                "Дата from не может быть "
                "позже даты to."
            ),
        )


def _get_route_geometry(
    repository: GTFSRepository,
    route_number: str,
) -> list[dict]:

    routes = (
        repository
        .get_route_by_number(
            route_number
        )
    )

    if not routes:
        return []

    route_id = str(
        routes[0]["route_id"]
    )

    coordinates = (
        repository
        .get_route_geometry(
            route_id=route_id,
        )
    )

    if not coordinates:
        return []

    # Берём первое направление,
    # если в справочнике несколько направлений.
    direction_ids = sorted(
        {
            str(item["direction_id"])
            for item in coordinates
        }
    )

    if not direction_ids:
        return []

    selected_direction = (
        direction_ids[0]
    )

    geometry = [
        item
        for item in coordinates
        if str(item["direction_id"])
        == selected_direction
    ]

    geometry.sort(
        key=lambda item: int(
            item["stop_sequence"]
        )
    )

    return geometry