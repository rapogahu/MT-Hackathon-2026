"""Leakage-aware target-history feature builders for temporal experiments."""

from __future__ import annotations

import pandas as pd

KEYS = ("route", "date", "hour")
H19_NAME = "route_weekday_hour_historical_median"
H20_NAME = "route_weekday_hour_historical_mean"


class RouteWeekdayHourHistoricalMedian:
    """H19: past-only train median and Jan-Aug-frozen validation median."""

    @staticmethod
    def build_train(train_rows: pd.DataFrame, history: pd.DataFrame) -> pd.Series:
        if not train_rows[["route", "date", "hour"]].equals(history[["route", "date", "hour"]]):
            raise ValueError("Train history must align with train keys")
        if history["date"].max() > pd.Timestamp("2025-08-31"):
            raise ValueError("Train history extends beyond forecast origin")
        ordered = history.assign(weekday=history["date"].dt.weekday)
        if not ordered.sort_values(["route", "date", "hour"]).index.equals(ordered.index):
            raise ValueError("Train history must be in chronological order within route")
        values = ordered.groupby(["route", "weekday", "hour"], sort=False)["boardings"].transform(
            lambda group: group.shift(1).expanding(min_periods=1).median()
        )
        values.loc[history["route"].eq(5)] = float("nan")
        return values.rename(H19_NAME)

    @staticmethod
    def build_validation(validation_keys: pd.DataFrame, frozen_history: pd.DataFrame) -> pd.Series:
        if "boardings" in validation_keys:
            raise ValueError("Validation feature builder accepts keys only")
        if frozen_history.empty or frozen_history["date"].max() != pd.Timestamp("2025-08-31"):
            raise ValueError("Validation history must end at 2025-08-31")
        if validation_keys["date"].min() <= frozen_history["date"].max():
            raise ValueError("Validation keys overlap target history")
        past = frozen_history.loc[frozen_history["route"].ne(5)].assign(
            weekday=lambda frame: frame["date"].dt.weekday
        )
        medians = past.groupby(["route", "weekday", "hour"])["boardings"].median()
        query = pd.MultiIndex.from_arrays(
            [validation_keys["route"], validation_keys["date"].dt.weekday, validation_keys["hour"]],
            names=["route", "weekday", "hour"],
        )
        return pd.Series(medians.reindex(query).to_numpy(), index=validation_keys.index,
                         name=H19_NAME, dtype="float64")


class RouteWeekdayHourHistoricalMean:
    """H20: past-only train mean and Jan-Aug-frozen validation mean."""

    @staticmethod
    def build_train(train_rows: pd.DataFrame, history: pd.DataFrame) -> pd.Series:
        if not train_rows[["route", "date", "hour"]].equals(history[["route", "date", "hour"]]):
            raise ValueError("Train history must align with train keys")
        if history["date"].max() > pd.Timestamp("2025-08-31"):
            raise ValueError("Train history extends beyond forecast origin")
        ordered = history.assign(weekday=history["date"].dt.weekday)
        if not ordered.sort_values(["route", "date", "hour"]).index.equals(ordered.index):
            raise ValueError("Train history must be in chronological order within route")
        values = ordered.groupby(["route", "weekday", "hour"], sort=False)["boardings"].transform(
            lambda group: group.shift(1).expanding(min_periods=1).mean()
        )
        values.loc[history["route"].eq(5)] = float("nan")
        return values.rename(H20_NAME)

    @staticmethod
    def build_validation(validation_keys: pd.DataFrame, frozen_history: pd.DataFrame) -> pd.Series:
        if "boardings" in validation_keys:
            raise ValueError("Validation feature builder accepts keys only")
        if frozen_history.empty or frozen_history["date"].max() != pd.Timestamp("2025-08-31"):
            raise ValueError("Validation history must end at 2025-08-31")
        if validation_keys["date"].min() <= frozen_history["date"].max():
            raise ValueError("Validation keys overlap target history")
        past = frozen_history.loc[frozen_history["route"].ne(5)].assign(
            weekday=lambda frame: frame["date"].dt.weekday
        )
        means = past.groupby(["route", "weekday", "hour"])["boardings"].mean()
        query = pd.MultiIndex.from_arrays(
            [validation_keys["route"], validation_keys["date"].dt.weekday, validation_keys["hour"]],
            names=["route", "weekday", "hour"],
        )
        return pd.Series(means.reindex(query).to_numpy(), index=validation_keys.index,
                         name=H20_NAME, dtype="float64")


def build_train_lag(
    train_rows: pd.DataFrame,
    history: pd.DataFrame,
    *,
    days: int,
    name: str | None = None,
) -> pd.Series:
    """Build an exact same-route/hour lag; each row reads only earlier targets."""
    if days < 1:
        raise ValueError("days must be positive")
    feature_name = name or f"target_lag_{days}d"
    lookup = history.set_index(["route", "date", "hour"])["boardings"]
    query = pd.MultiIndex.from_arrays(
        [train_rows["route"].to_numpy(), train_rows["date"].sub(pd.Timedelta(days=days)), train_rows["hour"].to_numpy()],
        names=KEYS,
    )
    values = lookup.reindex(query).to_numpy()
    # Enforce availability explicitly, including for callers passing broad history.
    available = history["date"].max() if not history.empty else pd.NaT
    if pd.notna(available) and (train_rows["date"] - pd.Timedelta(days=days) > available).any():
        raise ValueError("Requested lag target is not available in supplied history")
    return pd.Series(values, index=train_rows.index, name=feature_name, dtype="float64")


def build_validation_lag(
    validation_rows: pd.DataFrame,
    frozen_history: pd.DataFrame,
    *,
    days: int,
    name: str | None = None,
) -> pd.Series:
    """Build validation lag using only history ending at the Jan–Aug origin."""
    if days < 1:
        raise ValueError("days must be positive")
    if frozen_history.empty or frozen_history["date"].max() > pd.Timestamp("2025-08-31"):
        raise ValueError("Validation history must be frozen at or before 2025-08-31")
    query_dates = validation_rows["date"] - pd.Timedelta(days=days)
    if (query_dates > frozen_history["date"].max()).any():
        # No recursive predictions are implied: unavailable history remains NaN.
        pass
    lookup = frozen_history.set_index(["route", "date", "hour"])["boardings"]
    query = pd.MultiIndex.from_arrays(
        [validation_rows["route"].to_numpy(), query_dates, validation_rows["hour"].to_numpy()], names=KEYS
    )
    return pd.Series(lookup.reindex(query).to_numpy(), index=validation_rows.index,
                     name=name or f"target_lag_{days}d", dtype="float64")
