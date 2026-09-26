from pathlib import Path
from typing import Any

import pandas as pd


class GTFSRepository:
    """
    Репозиторий для работы со справочниками
    трамвайной сети.
    """

    SHEETS = {
        "routes": "Маршруты GTFS_ROUTES",
        "stops": "Остановки GTFS_STOPS",
        "trips_stops": "Порядок_остановок GTFS_TRIPS_ST",
        "assignments": "Наряд",
        "schedule": "Расписание",
        "stops_coordinates": "Порядок_с_координатами",
    }

    # Все листы, кроме этого, имеют строку
    # с пояснениями перед названиями колонок.
    SHEETS_WITH_DESCRIPTION_ROW = {
        "routes",
        "stops",
        "trips_stops",
        "assignments",
        "schedule",
    }

    def __init__(self, file_path: str | Path):
        self.file_path = Path(file_path)

        if not self.file_path.exists():
            raise FileNotFoundError(
                f"Файл справочника не найден: {self.file_path}"
            )

        print(
            f"Загрузка справочников из: "
            f"{self.file_path}"
        )

        self.routes = self._read_sheet("routes")

        self.stops = self._read_sheet("stops")

        self.trips_stops = self._read_sheet(
            "trips_stops"
        )

        self.assignments = self._read_sheet(
            "assignments"
        )

        self.schedule = self._read_sheet(
            "schedule"
        )

        self.stops_coordinates = self._read_sheet(
            "stops_coordinates"
        )

        # Проверяем необходимые колонки.

        self._require_columns(
            self.routes,
            [
                "route_id",
                "reg_num",
                "route_short_name",
                "route_long_name",
            ],
            self.SHEETS["routes"],
        )

        self._require_columns(
            self.stops,
            [
                "stop_id",
                "stop_name",
                "stop_lat",
                "stop_lon",
            ],
            self.SHEETS["stops"],
        )

        self._require_columns(
            self.trips_stops,
            [
                "route_id",
                "route_short_name",
                "trip_id",
                "trip_short_name",
                "direction_id",
                "stop_sequence",
                "stop_id",
            ],
            self.SHEETS["trips_stops"],
        )

        self._require_columns(
            self.stops_coordinates,
            [
                "route_id",
                "route_short_name",
                "trip_id",
                "trip_short_name",
                "direction_id",
                "stop_sequence",
                "stop_id",
                "stop_name",
                "stop_lat",
                "stop_lon",
            ],
            self.SHEETS["stops_coordinates"],
        )

        print(
            "Справочники успешно загружены."
        )

    # =========================================================
    # EXCEL
    # =========================================================

    def _read_sheet(
        self,
        sheet_key: str,
    ) -> pd.DataFrame:
        """
        Читает лист Excel.

        Для большинства листов:
            строка 1 — пояснение,
            строка 2 — названия колонок.

        Для Порядок_с_координатами:
            строка 1 — сразу названия колонок.
        """

        sheet_name = self.SHEETS[sheet_key]

        if sheet_key in self.SHEETS_WITH_DESCRIPTION_ROW:
            header = 1
        else:
            header = 0

        df = pd.read_excel(
            self.file_path,
            sheet_name=sheet_name,
            header=header,
            engine="openpyxl",
        )

        # Нормализуем названия колонок.
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

        # Удаляем полностью пустые строки.
        df = df.dropna(
            how="all"
        )

        print(
            f"Лист '{sheet_name}': "
            f"{len(df)} строк"
        )

        print(
            f"Колонки: "
            f"{df.columns.tolist()}"
        )

        return df

    # =========================================================
    # VALIDATION
    # =========================================================

    @staticmethod
    def _require_columns(
        df: pd.DataFrame,
        columns: list[str],
        sheet_name: str,
    ):
        """
        Проверяет наличие необходимых колонок.
        """

        missing = [
            column
            for column in columns
            if column not in df.columns
        ]

        if missing:
            raise ValueError(
                f"На листе '{sheet_name}' "
                f"отсутствуют колонки: "
                f"{missing}. "
                f"Найдены колонки: "
                f"{df.columns.tolist()}"
            )

    # =========================================================
    # JSON CONVERSION
    # =========================================================

    @staticmethod
    def _clean_value(
        value: Any,
    ):
        """
        Преобразует pandas/numpy значения
        в обычные Python-типы.
        """

        if value is None:
            return None

        try:
            if pd.isna(value):
                return None
        except (
            TypeError,
            ValueError,
        ):
            pass

        if hasattr(
            value,
            "isoformat",
        ):
            return value.isoformat()

        if hasattr(
            value,
            "item",
        ):
            try:
                return value.item()
            except (
                ValueError,
                TypeError,
            ):
                pass

        return value

    @classmethod
    def _clean_records(
        cls,
        df: pd.DataFrame,
    ) -> list[dict]:
        """
        DataFrame -> JSON-compatible
        список словарей.
        """

        records = []

        for row in df.to_dict(
            orient="records"
        ):
            clean_row = {
                key: cls._clean_value(value)
                for key, value in row.items()
            }

            records.append(clean_row)

        return records

    # =========================================================
    # ROUTES
    # =========================================================

    def get_routes(self) -> list[dict]:
        """
        Получить все маршруты.
        """

        return self._clean_records(
            self.routes
        )

    def get_route(
        self,
        route_id: str,
    ) -> list[dict]:
        """
        Получить маршрут по GTFS route_id.
        """

        df = self.routes[
            self.routes["route_id"]
            .astype(str)
            == str(route_id)
        ]

        return self._clean_records(df)

    def get_route_by_number(
        self,
        route_number: str,
    ) -> list[dict]:
        """
        Получить маршрут по короткому номеру.

        Например:

        /api/routes/number/1
        """

        df = self.routes[
            self.routes["route_short_name"]
            .astype(str)
            == str(route_number)
        ]

        return self._clean_records(df)

    # =========================================================
    # STOPS
    # =========================================================

    def get_stops(self) -> list[dict]:
        """
        Получить все остановки.
        """

        return self._clean_records(
            self.stops
        )

    def get_stop(
        self,
        stop_id: str,
    ) -> list[dict]:
        """
        Получить остановку по stop_id.
        """

        df = self.stops[
            self.stops["stop_id"]
            .astype(str)
            == str(stop_id)
        ]

        return self._clean_records(df)

    # =========================================================
    # TRIP STOPS
    # =========================================================

    def get_trip_stops(
        self,
        route_id: str,
        direction_id: str | None = None,
    ) -> list[dict]:
        """
        Получить остановки конкретного маршрута
        с координатами.

        Связь выполняется через route_id.

        direction_id позволяет получить только
        одно направление движения.
        """

        df = self.stops_coordinates[
            self.stops_coordinates["route_id"]
            .astype(str)
            == str(route_id)
        ]

        if direction_id is not None:
            df = df[
                df["direction_id"]
                .astype(str)
                == str(direction_id)
            ]

        # Восстанавливаем порядок остановок.
        df = df.sort_values(
            "stop_sequence"
        )

        return self._clean_records(df)

    # =========================================================
    # ASSIGNMENTS
    # =========================================================

    def get_assignments(
        self,
        route_id: str | None = None,
        date: str | None = None,
    ) -> list[dict]:
        """
        Получить наряды.
        """

        df = self.assignments.copy()

        if route_id is not None:
            df = df[
                df["route_id"]
                .astype(str)
                == str(route_id)
            ]

        if date is not None:
            df = df[
                df["date"]
                .astype(str)
                == str(date)
            ]

        return self._clean_records(df)

    # =========================================================
    # SCHEDULE
    # =========================================================

    def get_schedule(self) -> list[dict]:
        """
        Получить расписание.
        """

        return self._clean_records(
            self.schedule
        )

    # =========================================================
    # COORDINATES
    # =========================================================

    def get_stops_coordinates(
        self,
        route_id: str | None = None,
        direction_id: str | None = None,
    ) -> list[dict]:
        """
        Получить остановки с координатами.

        Можно отфильтровать по route_id
        и direction_id.
        """

        df = self.stops_coordinates.copy()

        if route_id is not None:
            df = df[
                df["route_id"]
                .astype(str)
                == str(route_id)
            ]

        if direction_id is not None:
            df = df[
                df["direction_id"]
                .astype(str)
                == str(direction_id)
            ]

        df = df.sort_values(
            "stop_sequence"
        )

        return self._clean_records(df)

    # =========================================================
    # ROUTE GEOMETRY
    # =========================================================

    def get_route_geometry(
        self,
        route_id: str,
        direction_id: str | None = None,
    ) -> list[dict]:
        """
        Получить последовательность остановок
        маршрута с координатами.

        Важно:
        trip_short_name не используется как ключ маршрута,
        потому что в текущем справочнике он может быть одинаковым
        для разных маршрутов.

        Основной ключ:
            route_id + direction_id
        """

        df = self.stops_coordinates[
            self.stops_coordinates["route_id"]
            .astype(str)
            == str(route_id)
        ]

        if direction_id is not None:
            df = df[
                df["direction_id"]
                .astype(str)
                == str(direction_id)
            ]

        df = df.sort_values(
            "stop_sequence"
        )

        return self._clean_records(
            df
        )

    def get_route_directions(
        self,
        route_id: str,
    ) -> list[dict]:
        """
        Получить направления конкретного маршрута.
        """

        df = self.stops_coordinates[
            self.stops_coordinates["route_id"]
            .astype(str)
            == str(route_id)
        ]

        if df.empty:
            return []

        directions = (
            df[
                [
                    "route_id",
                    "route_short_name",
                    "trip_id",
                    "trip_short_name",
                    "direction_id",
                ]
            ]
            .drop_duplicates()
            .sort_values(
                "direction_id"
            )
        )

        return self._clean_records(
            directions
        )