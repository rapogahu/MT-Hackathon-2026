from __future__ import annotations

import hashlib
from io import StringIO

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from app.repositories.forecast_repository import ForecastRepository
from app.repositories.gtfs_repository import GTFSRepository


def create_forecast_router(forecast: ForecastRepository, gtfs: GTFSRepository) -> APIRouter:
    router = APIRouter(tags=["Forecast integration"])
    reference_version = f"sha256:{hashlib.sha256(gtfs.file_path.read_bytes()).hexdigest()[:16]}"

    def check_run(run_id: str):
        if run_id != forecast.run_id: raise HTTPException(404, "Выпуск прогноза не найден")

    def check_route(route: int | None):
        if route is not None and route not in forecast.summary["routes"]: raise HTTPException(422, "Маршрут не поддерживается")

    def check_range(start: str, end: str):
        if start > end: raise HTTPException(422, "Начало диапазона позже окончания")
        if start < forecast.summary["forecast_start"] or end > forecast.summary["forecast_end"]: raise HTTPException(422, "Диапазон вне покрытия выпуска")

    def geometry_rows(route: int):
        frame = gtfs.stops_coordinates
        return frame[frame["route_short_name"].astype(str) == str(route)].copy()

    def paths(route: int) -> list[dict]:
        frame = geometry_rows(route)
        result = []
        keys = ["route_id", "trip_id", "direction_id", "start_date"]
        for key, group in frame.groupby(keys, dropna=False, sort=True):
            route_id, trip_id, direction_id, start_date = key
            group = group.sort_values("stop_sequence"); coordinates = [[float(row.stop_lon), float(row.stop_lat)] for row in group.itertuples() if pd.notna(row.stop_lon) and pd.notna(row.stop_lat)]
            if len(coordinates) < 2: continue
            valid_from = str(start_date)[:10]; geometry_id = f"ref-{route}-{trip_id}-{int(direction_id)}-{valid_from}"
            actual = group["actual_date"].dropna(); valid_to = group["end_date"].dropna()
            properties = {"route": route, "route_id": str(route_id), "trip_id": str(trip_id), "direction_id": int(direction_id), "geometry_id": geometry_id, "valid_from": valid_from, "valid_to": str(valid_to.iloc[0])[:10] if len(valid_to) else None, "reference_actual_date": str(actual.iloc[0])[:10] if len(actual) else valid_from, "geometry_source": "stop_sequence"}
            result.append({"properties": properties, "coordinates": coordinates, "rows": group})
        return result

    @router.get("/forecast/runs")
    def runs(): return {"active_run_id": forecast.run_id, "active_runs": {"day": None, "month": forecast.run_id, "year": None}, "runs": [forecast.summary]}

    @router.get("/forecast/runs/{run_id}")
    def run(run_id: str): check_run(run_id); return forecast.metadata()

    @router.get("/forecast/routes")
    def product_routes(run_id: str):
        check_run(run_id); items = []
        for route in forecast.summary["routes"]:
            route_rows = gtfs.get_route_by_number(str(route)); items.append({"route": route, "name": f"Трамвай {route}", "gtfs_route_ids": [str(row["route_id"]) for row in route_rows], "geometry_available": bool(paths(route)), "forecast_available": True})
        return {"run_id": run_id, "count": len(items), "routes": items}

    @router.get("/forecast")
    def day(run_id: str, date: str, route: int | None = None):
        check_run(run_id); check_route(route); check_range(date, date); points = forecast.records(forecast.select(route=route, date=date)); return {"run_id": run_id, "route": route, "date": date, "count": len(points), "points": points}

    @router.get("/forecast/point")
    def point(run_id: str, date: str, hour: int = Query(ge=0, le=23), route: int | None = None):
        check_run(run_id); check_route(route); check_range(date, date); points = forecast.records(forecast.select(route=route, date=date, hour=hour)); return {"run_id": run_id, "route": route, "date": date, "hour": hour, "count": len(points), "points": points}

    @router.get("/timeseries")
    def timeseries(run_id: str, from_: str = Query(alias="from"), to: str = Query(), route: int | None = None):
        check_run(run_id); check_route(route); check_range(from_, to); points = forecast.records(forecast.select(route=route, start=from_, end=to)); return {"run_id": run_id, "route": route, "from": from_, "to": to, "count": len(points), "points": points}

    @router.get("/forecast/aggregate")
    def aggregate(run_id: str, from_: str = Query(alias="from"), to: str = Query(), granularity: str = Query(pattern="^(day|week|month)$"), route: int | None = None):
        check_run(run_id); check_route(route); check_range(from_, to); frame = forecast.select(route=route, start=from_, end=to).copy(); frame["parsed"] = pd.to_datetime(frame["date"])
        if granularity == "day": frame["bucket"] = frame["date"]
        elif granularity == "month": frame["bucket"] = frame["parsed"].dt.to_period("M").astype(str)
        else: frame["bucket"] = ((frame["parsed"] - pd.Timestamp(from_)).dt.days // 7).astype(int)
        points = []
        for (route_number, _), group in frame.groupby(["route", "bucket"], sort=True):
            start, end = str(group["date"].min()), str(group["date"].max()); hours = int(len(group)); expected = (pd.Timestamp(end) - pd.Timestamp(start)).days * 24 + 24
            points.append({"route": int(route_number), "date": start, "period_start": start, "period_end": end, "prediction": float(group["prediction"].sum()), "hours_count": hours, "expected_hours": expected, "is_partial": hours != expected})
        return {"run_id": run_id, "route": route, "from": from_, "to": to, "granularity": granularity, "count": len(points), "points": points}

    @router.get("/export.csv")
    def export_csv(run_id: str, from_: str = Query(alias="from"), to: str = Query(), route: int | None = None, hour: int | None = Query(default=None, ge=0, le=23)):
        check_run(run_id); check_route(route); check_range(from_, to); frame = forecast.select(route=route, start=from_, end=to, hour=hour); columns = ["route", "date", "hour", "prediction", "relative_load_pct", "load_index", "load_category"]; buffer = StringIO(); frame.to_csv(buffer, sep=";", columns=columns, index=False, lineterminator="\n")
        return Response(buffer.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="forecast_{from_}_{to}.csv"'})

    @router.get("/map/routes")
    def map_routes(run_id: str, date: str, hour: int = Query(ge=0, le=23), route: int | None = None):
        check_run(run_id); check_route(route); check_range(date, date); selected = forecast.records(forecast.select(route=route, date=date, hour=hour)); by_route = {row["route"]: row for row in selected}; features = []
        for route_number, value in by_route.items():
            for path in paths(route_number):
                props = path["properties"]; outside = date < props["valid_from"] or (props["valid_to"] is not None and date > props["valid_to"])
                features.append({"type": "Feature", "id": props["geometry_id"], "geometry": {"type": "LineString", "coordinates": path["coordinates"]}, "properties": {**value, **props, "outside_validity_period": outside}})
        return {"type": "FeatureCollection", "features": features, "run_id": run_id, "date": date, "hour": hour, "reference_version": reference_version, "geometry_mode": "reference"}

    @router.get("/routes/number/{route}/geometry")
    def geometry(route: int):
        features = [{"type": "Feature", "id": path["properties"]["geometry_id"], "geometry": {"type": "LineString", "coordinates": path["coordinates"]}, "properties": path["properties"]} for path in paths(route)]
        return {"type": "FeatureCollection", "features": features, "route": route, "reference_version": reference_version, "geometry_available": bool(features), "geometry_mode": "reference"}

    @router.get("/routes/number/{route}/directions")
    def directions(route: int):
        items = [{key: path["properties"][key] for key in ("geometry_id", "trip_id", "direction_id", "valid_from", "valid_to")} for path in paths(route)]; return {"route": route, "reference_version": reference_version, "count": len(items), "directions": items}

    @router.get("/routes/number/{route}/stops")
    def route_stops(route: int, trip_id: str | None = None, direction_id: int | None = None):
        items = []
        for path in paths(route):
            props = path["properties"]
            if trip_id is not None and props["trip_id"] != trip_id: continue
            if direction_id is not None and props["direction_id"] != direction_id: continue
            for row in path["rows"].sort_values("stop_sequence").itertuples(): items.append({"route": route, "route_id": props["route_id"], "trip_id": props["trip_id"], "direction_id": props["direction_id"], "geometry_id": props["geometry_id"], "stop_sequence": int(row.stop_sequence), "stop_id": str(row.stop_id), "stop_name": str(row.stop_name), "lat": float(row.stop_lat), "lon": float(row.stop_lon)})
        return {"route": route, "reference_version": reference_version, "count": len(items), "stops": items}

    return router
