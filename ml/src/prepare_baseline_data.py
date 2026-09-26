"""Build hourly baseline tables from raw validation transactions."""

import csv
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
RAW_TRAIN = ROOT / "data/raw/train.csv"
RAW_VALIDATION = ROOT / "data/raw/test.csv"
PROCESSED = ROOT / "data/processed"
TRAIN_TABLE = PROCESSED / "baseline_train_hourly.csv"
VALIDATION_TABLE = PROCESSED / "baseline_validation_hourly.csv"
ROUTES = (1, 5, 7, 11, 12, 17, 25, 26, 28, 50)
TRAIN_START, TRAIN_END = date(2025, 1, 1), date(2025, 8, 31)
VALIDATION_START, VALIDATION_END = date(2025, 9, 1), date(2025, 10, 31)
CHUNK_ROWS = 250_000


def dates(start: date, end: date):
    for offset in range((end - start).days + 1):
        yield start + timedelta(days=offset)


def aggregate_boardings(path: Path, start: date, end: date):
    """Count successful raw validations in the requested calendar period."""
    counts = Counter()
    columns = ["tran_date_time", "validation_result", "ngpt_route"]
    chunks = pd.read_csv(
        path,
        sep=";",
        usecols=columns,
        dtype={"tran_date_time": str, "validation_result": "int16", "ngpt_route": str},
        chunksize=CHUNK_ROWS,
    )
    for chunk_number, chunk in enumerate(chunks, start=1):
        selected = chunk.loc[chunk["validation_result"].eq(1), ["tran_date_time", "ngpt_route"]]
        if selected.empty:
            continue
        timestamp = pd.to_datetime(
            selected["tran_date_time"], format="%Y-%m-%d %H:%M:%S", errors="coerce"
        )
        if timestamp.isna().any():
            raise ValueError(f"Invalid successful-validation timestamp in {path.name}")
        in_period = timestamp.ge(pd.Timestamp(start)) & timestamp.lt(pd.Timestamp(end + timedelta(days=1)))
        if in_period.any():
            timestamp = timestamp.loc[in_period]
            route = pd.to_numeric(
                selected.loc[in_period, "ngpt_route"].str.extract(r"^\s*(\d+)\b", expand=False),
                errors="coerce",
            )
            if route.isna().any() or not route.isin(ROUTES).all():
                raise ValueError(f"Unknown successful-validation route in {path.name}")
            hourly = pd.DataFrame(
                {
                    "route": route.astype("int16"),
                    "date": timestamp.dt.date,
                    "hour": timestamp.dt.hour,
                }
            )
            for key, count in hourly.groupby(["route", "date", "hour"]).size().items():
                counts[key] += int(count)
        if chunk_number % 20 == 0:
            print(f"{path.name}: processed {chunk_number * CHUNK_ROWS:,} raw rows", flush=True)
    return counts


def save_hourly_grid(path: Path, counts, start: date, end: date):
    """Write all route/date/hour cells, including zero-boardings cells."""
    with path.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream, delimiter=";")
        writer.writerow(("route", "date", "hour", "boardings"))
        for day in dates(start, end):
            for route in ROUTES:
                for hour in range(24):
                    writer.writerow((route, day.isoformat(), hour, counts.get((route, day, hour), 0)))


def main():
    if TRAIN_TABLE.exists() or VALIDATION_TABLE.exists():
        raise FileExistsError("Baseline processed tables already exist; refusing to overwrite them")

    train_counts = aggregate_boardings(RAW_TRAIN, TRAIN_START, TRAIN_END)
    save_hourly_grid(TRAIN_TABLE, train_counts, TRAIN_START, TRAIN_END)

    validation_counts = aggregate_boardings(RAW_VALIDATION, VALIDATION_START, VALIDATION_END)
    save_hourly_grid(VALIDATION_TABLE, validation_counts, VALIDATION_START, VALIDATION_END)


if __name__ == "__main__":
    main()
