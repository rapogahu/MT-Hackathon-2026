from __future__ import annotations

import hashlib
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd


class ForecastRepository:
    """
    Репозиторий прогнозов.

    Сейчас источник данных — CSV.
    В будущем этот класс можно заменить PostgreSQL-реализацией,
    не меняя HTTP API.
    """

    REQUIRED_COLUMNS = {
        "route",
        "date",
        "hour",
        "prediction",
    }

    LOAD_CATEGORIES = (
        "very_low",
        "low",
        "medium",
        "high",
        "very_high",
    )

    def __init__(self, file_path: str | Path):
        self.file_path = Path(file_path)

        if not self.file_path.exists():
            raise FileNotFoundError(
                f"Файл прогнозов не найден: {self.file_path}"
            )

        print(
            f"Загрузка прогнозов из: "
            f"{self.file_path}"
        )

        self.data = self._read_csv()

        self.run_id = self._make_run_id()

        self._validate()

        self._prepare()

        print(
            f"Прогноз успешно загружен: "
            f"{len(self.data)} строк"
        )

        print(
            f"Run ID: {self.run_id}"
        )

    # =========================================================
    # CSV
    # =========================================================

    def _read_csv(self) -> pd.DataFrame:
        """
        Читает CSV.

        Основной формат хакатона:
            route;date;hour;prediction

        Также пытаемся определить разделитель автоматически,
        если файл вдруг окажется с запятыми.
        """

        try:
            df = pd.read_csv(
                self.file_path,
                sep=";",
            )

            if len(df.columns) == 1:
                df = pd.read_csv(
                    self.file_path,
                    sep=",",
                )

        except Exception as exc:
            raise ValueError(
                f"Не удалось прочитать CSV "
                f"{self.file_path}: {exc}"
            ) from exc

        df.columns = (
            df.columns
            .astype(str)
            .str.strip()
            .str.replace(
                "\ufeff",
                "",
                regex=False,
            )
        )

        return df

    # =========================================================
    # VALIDATION
    # =========================================================

    def _validate(self):
        """
        Проверяет структуру и содержимое прогноза.
        """

        missing = (
            self.REQUIRED_COLUMNS
            - set(self.data.columns)
        )

        if missing:
            raise ValueError(
                "В CSV отсутствуют обязательные "
                f"колонки: {sorted(missing)}. "
                f"Найдены: {self.data.columns.tolist()}"
            )

        # route
        if self.data["route"].isna().any():
            raise ValueError(
                "В колонке route обнаружены "
                "пустые значения."
            )

        # date
        try:
            parsed_dates = pd.to_datetime(
                self.data["date"],
                errors="raise",
            )
        except Exception as exc:
            raise ValueError(
                "Колонка date содержит "
                "некорректные даты."
            ) from exc

        self.data["date"] = (
            parsed_dates.dt.strftime("%Y-%m-%d")
        )

        # hour
        self.data["hour"] = pd.to_numeric(
            self.data["hour"],
            errors="coerce",
        )

        if self.data["hour"].isna().any():
            raise ValueError(
                "Колонка hour содержит "
                "некорректные значения."
            )

        self.data["hour"] = (
            self.data["hour"]
            .astype(int)
        )

        invalid_hours = self.data[
            ~self.data["hour"].between(0, 23)
        ]

        if not invalid_hours.empty:
            raise ValueError(
                "Колонка hour должна содержать "
                "значения от 0 до 23."
            )

        # prediction
        self.data["prediction"] = pd.to_numeric(
            self.data["prediction"],
            errors="coerce",
        )

        if self.data["prediction"].isna().any():
            raise ValueError(
                "Колонка prediction содержит "
                "некорректные значения."
            )

        if (
            self.data["prediction"] < 0
        ).any():
            raise ValueError(
                "prediction не может быть отрицательным."
            )

        # duplicates
        duplicates = self.data.duplicated(
            subset=[
                "route",
                "date",
                "hour",
            ]
        )

        if duplicates.any():
            duplicate_count = int(
                duplicates.sum()
            )

            raise ValueError(
                "В прогнозе обнаружены дубли "
                "по ключу route + date + hour: "
                f"{duplicate_count}"
            )

    # =========================================================
    # PREPARE
    # =========================================================

    def _prepare(self):
        """
        Подготавливает внутренние поля.
        """

        self.data["route"] = (
            self.data["route"]
            .astype(str)
            .str.strip()
        )

        self.data["hour"] = (
            self.data["hour"]
            .astype(int)
        )

        self.data["prediction"] = (
            self.data["prediction"]
            .astype(float)
        )

        self.routes = sorted(
            self.data["route"].unique(),
            key=self._route_sort_key,
        )

        self.min_date = (
            self.data["date"].min()
        )

        self.max_date = (
            self.data["date"].max()
        )

        self._calculate_load_metrics()

    # =========================================================
    # RUN
    # =========================================================

    def _make_run_id(self) -> str:
        """
        Создаёт стабильный ID на основе содержимого CSV.

        Если файл не изменился, run_id остаётся тем же.
        """

        content = self.file_path.read_bytes()

        digest = hashlib.sha256(
            content
        ).hexdigest()[:16]

        return f"csv-{digest}"

    def get_run_id(self) -> str:
        return self.run_id

    def get_run_metadata(self) -> dict:
        return {
            "run_id": self.run_id,
            "source": "csv",
            "source_file": self.file_path.name,
            "status": "ready",
            "route_count": len(self.routes),
            "row_count": len(self.data),
            "date_from": self.min_date,
            "date_to": self.max_date,
        }

    # =========================================================
    # ROUTES
    # =========================================================

    @staticmethod
    def _route_sort_key(
        route: str,
    ):
        try:
            return (
                0,
                int(route),
            )
        except ValueError:
            return (
                1,
                route,
            )

    def get_routes(self) -> list[int | str]:
        """
        Возвращает маршруты, присутствующие
        именно в прогнозном файле.
        """

        result = []

        for route in self.routes:
            try:
                result.append(int(route))
            except ValueError:
                result.append(route)

        return result

    # =========================================================
    # FILTER
    # =========================================================

    def _filter(
        self,
        route: str | None = None,
        start: str | None = None,
        end: str | None = None,
    ) -> pd.DataFrame:

        df = self.data

        if route is not None:
            df = df[
                df["route"].astype(str)
                == str(route)
            ]

        if start is not None:
            df = df[
                df["date"] >= start
            ]

        if end is not None:
            df = df[
                df["date"] <= end
            ]

        return df.copy()

    # =========================================================
    # LOAD METRICS
    # =========================================================

    def _calculate_load_metrics(self):
        """
        Рассчитывает относительную загрузку.

        Нормализация выполняется отдельно для каждого маршрута.
        Q05 и Q95 используются как нижняя и верхняя границы.

        Если все значения маршрута одинаковы,
        normalization_degenerate = True.
        """

        self.data["relative_load"] = 0.0
        self.data["normalization_degenerate"] = False

        for route in self.data["route"].unique():

            mask = (
                self.data["route"]
                == route
            )

            values = (
                self.data.loc[
                    mask,
                    "prediction"
                ]
            )

            q05 = values.quantile(0.05)
            q95 = values.quantile(0.95)

            if q95 <= q05:
                self.data.loc[
                    mask,
                    "relative_load"
                ] = 0.0

                self.data.loc[
                    mask,
                    "normalization_degenerate"
                ] = True

                continue

            normalized = (
                (
                    values - q05
                )
                / (
                    q95 - q05
                )
            )

            normalized = normalized.clip(
                0,
                1,
            )

            self.data.loc[
                mask,
                "relative_load"
            ] = normalized

    @staticmethod
    def _load_index(
        relative_load: float,
    ) -> int:
        """
        0..1 -> 1..10
        """

        value = max(
            0.0,
            min(
                1.0,
                float(relative_load),
            ),
        )

        return min(
            10,
            max(
                1,
                int(value * 10) + 1,
            ),
        )

    @staticmethod
    def _load_category(
        load_index: int,
    ) -> str:

        if load_index <= 2:
            return "very_low"

        if load_index <= 4:
            return "low"

        if load_index <= 6:
            return "medium"

        if load_index <= 8:
            return "high"

        return "very_high"

    # =========================================================
    # DTO
    # =========================================================

    @classmethod
    def _record(
        cls,
        row: pd.Series,
    ) -> dict:

        relative_load = float(
            row["relative_load"]
        )

        load_index = cls._load_index(
            relative_load
        )

        return {
            "route": cls._route_value(
                row["route"]
            ),
            "date": str(
                row["date"]
            ),
            "hour": int(
                row["hour"]
            ),
            "prediction": float(
                row["prediction"]
            ),
            "relative_load": round(
                relative_load,
                4,
            ),
            "relative_load_pct": int(
                round(
                    relative_load * 100
                )
            ),
            "load_index": load_index,
            "load_category": cls._load_category(
                load_index
            ),
            "normalization_degenerate": bool(
                row["normalization_degenerate"]
            ),
        }

    @staticmethod
    def _route_value(
        route: Any,
    ):
        try:
            return int(route)
        except (
            ValueError,
            TypeError,
        ):
            return str(route)

    # =========================================================
    # FORECAST
    # =========================================================

    def get_forecast(
        self,
        route: str | None = None,
        date_value: str | None = None,
    ) -> list[dict]:

        df = self._filter(
            route=route,
            start=date_value,
            end=date_value,
        )

        df = df.sort_values(
            [
                "date",
                "hour",
                "route",
            ]
        )

        return [
            self._record(row)
            for _, row in df.iterrows()
        ]

    # =========================================================
    # POINT
    # =========================================================

    def get_point(
        self,
        route: str,
        date_value: str,
        hour: int,
    ) -> dict | None:

        df = self.data[
            (
                self.data["route"]
                == str(route)
            )
            & (
                self.data["date"]
                == date_value
            )
            & (
                self.data["hour"]
                == int(hour)
            )
        ]

        if df.empty:
            return None

        return self._record(
            df.iloc[0]
        )

    # =========================================================
    # TIMESERIES
    # =========================================================

    def get_timeseries(
        self,
        route: str | None = None,
        start: str | None = None,
        end: str | None = None,
    ) -> list[dict]:

        df = self._filter(
            route=route,
            start=start,
            end=end,
        )

        df = df.sort_values(
            [
                "date",
                "hour",
                "route",
            ]
        )

        return [
            self._record(row)
            for _, row in df.iterrows()
        ]

    # =========================================================
    # AGGREGATE
    # =========================================================

    def get_aggregate(
        self,
        route: str | None = None,
        start: str | None = None,
        end: str | None = None,
        granularity: str = "day",
    ) -> list[dict]:

        if granularity != "day":
            raise ValueError(
                "Поддерживается только "
                "granularity=day."
            )

        df = self._filter(
            route=route,
            start=start,
            end=end,
        )

        if df.empty:
            return []

        grouped = (
            df.groupby(
                [
                    "route",
                    "date",
                ],
                as_index=False,
            )
            .agg(
                prediction=(
                    "prediction",
                    "sum",
                ),
                relative_load=(
                    "relative_load",
                    "mean",
                ),
            )
        )

        result = []

        for _, row in grouped.iterrows():

            relative_load = float(
                row["relative_load"]
            )

            load_index = self._load_index(
                relative_load
            )

            result.append(
                {
                    "route": self._route_value(
                        row["route"]
                    ),
                    "date": str(
                        row["date"]
                    ),
                    "prediction": float(
                        row["prediction"]
                    ),
                    "relative_load": round(
                        relative_load,
                        4,
                    ),
                    "relative_load_pct": int(
                        round(
                            relative_load * 100
                        )
                    ),
                    "load_index": load_index,
                    "load_category": self._load_category(
                        load_index
                    ),
                }
            )

        return result

    # =========================================================
    # CSV
    # =========================================================

    def export_csv(
        self,
        route: str | None = None,
        start: str | None = None,
        end: str | None = None,
    ) -> str:

        df = self._filter(
            route=route,
            start=start,
            end=end,
        )

        columns = [
            "route",
            "date",
            "hour",
            "prediction",
        ]

        return df[
            columns
        ].to_csv(
            index=False,
            sep=";",
        )