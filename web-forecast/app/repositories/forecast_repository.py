from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


ROUTES = (1, 5, 7, 11, 12, 17, 25, 26, 28, 50)


class ForecastRepository:
    """Read-only integration repository. The CSV is loaded and normalized once."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        if not self.path.is_file():
            raise FileNotFoundError(f"Файл прогноза не найден: {self.path}")
        raw = self.path.read_bytes()
        self.checksum = hashlib.sha256(raw).hexdigest()
        frame = pd.read_csv(self.path, sep=";", dtype={"route": "int64", "date": "string", "hour": "int64", "prediction": "float64"})
        required = {"route", "date", "hour", "prediction"}
        if not required.issubset(frame.columns):
            raise ValueError(f"В прогнозе отсутствуют колонки: {sorted(required - set(frame.columns))}")
        if frame.empty or frame[list(required)].isna().any().any():
            raise ValueError("Прогноз пуст или содержит пропуски")
        if not frame["route"].isin(ROUTES).all() or not frame["hour"].between(0, 23).all() or (frame["prediction"] < 0).any():
            raise ValueError("Прогноз содержит неподдерживаемый маршрут, час или отрицательное значение")
        parsed_dates = pd.to_datetime(frame["date"], format="%Y-%m-%d", errors="raise")
        frame["date"] = parsed_dates.dt.strftime("%Y-%m-%d")
        if frame.duplicated(["route", "date", "hour"]).any():
            raise ValueError("Прогноз содержит дубли route/date/hour")

        self.normalization: list[dict] = []
        normalized = []
        for route, group in frame.groupby("route", sort=True):
            values = group["prediction"]
            q05, q95 = float(values.quantile(.05)), float(values.quantile(.95))
            degenerate = q95 <= q05
            current = group.copy()
            relative = pd.Series(.5, index=current.index) if degenerate else ((values - q05) / (q95 - q05)).clip(0, 1)
            current["relative_load"] = relative
            current["relative_load_pct"] = (relative * 100 + .5).astype(int)
            current["load_index"] = 5 if degenerate else ((relative * 10).astype(int) + 1).clip(1, 10)
            current["normalization_degenerate"] = degenerate
            current["load_category"] = current["load_index"].map(self._category)
            normalized.append(current)
            self.normalization.append({"route": int(route), "source_type": "forecast", "actual_batch_id": None, "period_start": frame["date"].min(), "period_end": frame["date"].max(), "sample_count": int(len(group)), "q05": q05, "q95": q95, "degenerate": degenerate, "fallback_reason": "forecast_distribution" if not degenerate else "constant_forecast", "algorithm_version": "q05-q95-v1"})

        self.frame = pd.concat(normalized).sort_values(["route", "date", "hour"]).reset_index(drop=True)
        self.run_id = f"csv-{self.checksum[:16]}"
        modified = datetime.fromtimestamp(self.path.stat().st_mtime, timezone.utc).isoformat()
        self.summary = {"run_id": self.run_id, "profile": "competition", "horizon": "month", "forecast_kind": "forecast", "training_end": "2025-10-31", "forecast_start": str(self.frame["date"].min()), "forecast_end": str(self.frame["date"].max()), "routes": sorted(int(value) for value in self.frame["route"].unique()), "row_count": int(len(self.frame)), "imported_at": modified, "generated_at": None, "model_version": self.path.stem, "timezone": "Europe/Moscow"}

    @staticmethod
    def _category(index: int) -> str:
        return "very_low" if index <= 2 else "low" if index <= 4 else "medium" if index <= 6 else "high" if index <= 8 else "very_high"

    def metadata(self) -> dict:
        return {**self.summary, "source_checksum": self.checksum, "actual_batch_id": None, "normalization_version": "q05-q95-v1", "normalization": self.normalization, "evaluation_ids": [], "scenario_assumptions": None}

    def select(self, *, route: int | None = None, date: str | None = None, hour: int | None = None, start: str | None = None, end: str | None = None) -> pd.DataFrame:
        result = self.frame
        if route is not None: result = result[result["route"] == route]
        if date is not None: result = result[result["date"] == date]
        if hour is not None: result = result[result["hour"] == hour]
        if start is not None: result = result[result["date"] >= start]
        if end is not None: result = result[result["date"] <= end]
        return result

    @staticmethod
    def records(frame: pd.DataFrame) -> list[dict]:
        columns = ["route", "date", "hour", "prediction", "relative_load", "relative_load_pct", "load_index", "load_category", "normalization_degenerate"]
        records = frame[columns].to_dict("records")
        for row in records:
            for key in ("route", "hour", "relative_load_pct", "load_index"): row[key] = int(row[key])
            row["prediction"] = float(row["prediction"]); row["relative_load"] = float(row["relative_load"]); row["normalization_degenerate"] = bool(row["normalization_degenerate"])
        return records
