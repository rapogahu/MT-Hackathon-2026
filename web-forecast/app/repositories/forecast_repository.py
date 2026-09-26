from pathlib import Path
from datetime import date

import pandas as pd


class ForecastRepository:
    """
    Репозиторий прогнозов.

    Сейчас источник данных: test_submission.csv

    В будущем источник можно заменить на бд.
    """

    REQUIRED_COLUMNS = {
        "route",
        "date",
        "hour",
        "prediction",
    }

    def __init__(
        self,
        file_path: str | Path,
    ):
        self.file_path = Path(file_path)

        if not self.file_path.exists():
            raise FileNotFoundError(
                f"Файл прогнозов не найден: {self.file_path}"
            )

        print(
            f"Загрузка прогнозов из: "
            f"{self.file_path}"
        )

        self.data = self._load()

        print(
            f"Прогнозы загружены: "
            f"{len(self.data)} записей"
        )


    # Загрузка данных прогноза.


    def _load(self) -> pd.DataFrame:
        """
        Загружает test_submission.csv.

        Файл небольшой для текущего этапа, поэтому держим его в памяти.
        """

        df = pd.read_csv(
            self.file_path,
            sep=";",
        )

        missing = (
            self.REQUIRED_COLUMNS
            - set(df.columns)
        )

        if missing:
            raise ValueError(
                "В файле прогнозов отсутствуют "
                f"колонки: {sorted(missing)}. "
                f"Найдены: {df.columns.tolist()}"
            )

        # Типы данных

        df["route"] = pd.to_numeric(
            df["route"],
            errors="raise",
        ).astype(int)

        df["hour"] = pd.to_numeric(
            df["hour"],
            errors="raise",
        ).astype(int)

        df["prediction"] = pd.to_numeric(
            df["prediction"],
            errors="raise",
        )

        df["date"] = pd.to_datetime(
            df["date"],
            errors="raise",
        ).dt.date

        # Проверяем часы

        invalid_hours = df[
            ~df["hour"].between(0, 23)
        ]

        if not invalid_hours.empty:
            raise ValueError(
                "В файле обнаружены некорректные часы."
            )

        # Сортировка

        df = df.sort_values(
            [
                "route",
                "date",
                "hour",
            ]
        ).reset_index(drop=True)

        return df


    # Маршруты


    def get_routes(self) -> list[int]:
        """
        Получить маршруты, для которых доступны прогнозы.
        """

        return sorted(
            self.data["route"]
            .unique()
            .tolist()
        )

    # Интервал дат

    def get_date_range(self) -> dict:
        """
        Получить минимальную и максимальную доступную дату.
        """

        start = self.data["date"].min()
        end = self.data["date"].max()

        return {
            "start": start,
            "end": end,
        }

    def get_dates(self) -> list[date]:
        """
        Получить все доступные даты.
        """

        return sorted(
            self.data["date"]
            .unique()
            .tolist()
        )

    # Прогноз на день

    def get_forecast(
        self,
        route: int,
        forecast_date: date,
    ) -> list[dict]:
        """
        Получить почасовой прогноз
        для маршрута за один день.
        """

        df = self.data[
            (self.data["route"] == route)
            & (self.data["date"] == forecast_date)
        ]

        return [
            {
                "hour": int(row["hour"]),
                "prediction": float(
                    row["prediction"]
                ),
            }
            for _, row in df.iterrows()
        ]

    # Период

    def get_period(
        self,
        route: int,
        start: date,
        end: date,
    ) -> list[dict]:
        """
        Получить прогноз за период.
        """

        df = self.data[
            (self.data["route"] == route)
            & (self.data["date"] >= start)
            & (self.data["date"] <= end)
        ]

        return [
            {
                "date": row["date"],
                "hour": int(row["hour"]),
                "prediction": float(
                    row["prediction"]
                ),
            }
            for _, row in df.iterrows()
        ]

    
    # Агрегация

    def get_summary(
        self,
        route: int,
        start: date,
        end: date,
    ) -> dict:
        """
        Агрегированная информация за период.
        """

        df = self.data[
            (self.data["route"] == route)
            & (self.data["date"] >= start)
            & (self.data["date"] <= end)
        ]

        if df.empty:
            return {
                "total": 0,
                "average_per_day": 0,
                "max_hour": None,
                "days": 0,
            }

        daily = (
            df.groupby("date")["prediction"]
            .sum()
        )

        max_index = df[
            "prediction"
        ].idxmax()

        max_row = df.loc[max_index]

        return {
            "total": float(
                df["prediction"].sum()
            ),
            "average_per_day": float(
                daily.mean()
            ),
            "max_hour": {
                "date": max_row["date"],
                "hour": int(max_row["hour"]),
                "prediction": float(
                    max_row["prediction"]
                ),
            },
            "days": int(
                daily.shape[0]
            ),
        }


    # Проверка наличия информации


    def has_route(
        self,
        route: int,
    ) -> bool:
        """
        Проверяет наличие маршрута.
        """

        return route in set(
            self.data["route"].unique()
        )

    def has_date(
        self,
        forecast_date: date,
    ) -> bool:
        """
        Проверяет наличие даты.
        """

        return forecast_date in set(
            self.data["date"].unique()
        )
