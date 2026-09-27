"""Bounded Optuna search for the two selected model configurations."""

from __future__ import annotations

import json
import platform
from datetime import datetime, timezone
from pathlib import Path

import lightgbm
import numpy as np
import optuna
import pandas as pd
import xgboost

import model_selection as ms

REFERENCE_PATH = ms.ARTIFACT
ARTIFACT = ms.RESULTS / "hyperparameter_tuning.json"
CONFIGURATION = "calendar_weather"
FAMILIES = ("XGBRegressor", "LightGBM")
SEED = 42
TRIALS_PER_FAMILY = 16  # One frozen control plus 15 sampled configurations.
CLOSE_WAPE_MARGIN = 0.005
SEARCH_SPACES = {
    "XGBRegressor": {
        "n_estimators": (200, 300, 400, 500),
        "max_depth": (4, 5, 6, 7),
        "learning_rate": (0.05, 0.075, 0.1, 0.125),
        "min_child_weight": (1, 3, 6, 10),
    },
    "LightGBM": {
        "n_estimators": (200, 300, 400, 500),
        "max_depth": (6, 7, 8),
        "learning_rate": (0.05, 0.075, 0.1, 0.125),
        "num_leaves": (15, 31, 47, 63),
        "min_child_samples": (10, 20, 40),
    },
}
FROZEN_SEARCH_PARAMS = {
    "XGBRegressor": {"n_estimators": 300, "max_depth": 6,
                     "learning_rate": 0.1, "min_child_weight": 1},
    "LightGBM": {"n_estimators": 300, "max_depth": 6,
                 "learning_rate": 0.1, "num_leaves": 31, "min_child_samples": 20},
}


def load_inputs() -> tuple[pd.DataFrame, list[tuple[pd.DataFrame, pd.DataFrame]], dict]:
    reference = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))
    if reference["hpo_candidates"] != [
        {"family": family, "configuration": CONFIGURATION} for family in FAMILIES
    ]:
        raise ValueError("HPO candidates differ from model selection")
    if reference["features"][CONFIGURATION] != list(ms.FEATURE_CONFIGURATIONS[CONFIGURATION]):
        raise ValueError("Selected feature list differs")
    if reference["folds"] != [
        {"name": fold[0], "train_period": [fold[1], fold[2]],
         "validation_period": [fold[3], fold[4]]} for fold in ms.FOLDS
    ]:
        raise ValueError("Temporal folds differ from model selection")
    for path in (ms.DATA_PATH, ms.JAN_AUG_PATH, ms.SEP_OCT_PATH):
        key = path.relative_to(ms.ROOT).as_posix()
        if ms.sha256(path) != reference["data_sha256"][key]:
            raise ValueError(f"Historical model-ready data changed: {key}")
    rows = ms.load_data()
    folds = [ms.make_fold(rows, spec) for spec in ms.FOLDS]
    return rows, folds, reference


def full_parameters(family: str, selected: dict) -> dict:
    base = ms.XGBOOST_PARAMETERS if family == "XGBRegressor" else ms.MODEL_PARAMETERS
    return {**base, **selected}


def sample_parameters(trial: optuna.Trial, family: str) -> dict:
    selected = {name: trial.suggest_categorical(name, values)
                for name, values in SEARCH_SPACES[family].items()}
    return full_parameters(family, selected)


def evaluate_parameters(folds: list[tuple[pd.DataFrame, pd.DataFrame]],
                        family: str, parameters: dict) -> tuple[list[dict], dict]:
    fold_results = [ms.evaluate_fold(train, valid, CONFIGURATION, family, parameters)
                    for train, valid in folds]
    return fold_results, ms.summarize(fold_results)


def assert_frozen_reproduced(control: optuna.trial.FrozenTrial,
                             reference: dict, family: str) -> None:
    if control.number != 0 or control.params != FROZEN_SEARCH_PARAMS[family]:
        raise ValueError("Frozen control trial was not first")
    expected = reference["results"][family][CONFIGURATION]
    observed = control.user_attrs["fold_results"]
    for index, (actual, prior) in enumerate(zip(observed, expected, strict=True)):
        if actual["absolute_error"] != prior["absolute_error"] or actual["actual_sum"] != prior["actual_sum"]:
            raise ValueError(f"Frozen {family} mismatch on fold {index + 1}")
        for route in ms.ROUTES:
            if actual["per_route"][str(route)]["absolute_error"] != prior["per_route"][str(route)]["absolute_error"]:
                raise ValueError(f"Frozen {family} per-route mismatch on fold {index + 1}")


def trial_record(trial: optuna.trial.FrozenTrial, family: str) -> dict:
    return {
        "number": trial.number,
        "kind": "frozen_control" if trial.number == 0 else "sampled",
        "selected_parameters": trial.params,
        "full_parameters": full_parameters(family, trial.params),
        "fold_results": trial.user_attrs["fold_results"],
        "summary": trial.user_attrs["summary"],
    }


def run_study(folds: list[tuple[pd.DataFrame, pd.DataFrame]], reference: dict,
              family: str) -> dict:
    if family not in FAMILIES:
        raise ValueError("Only selected HPO model families are allowed")
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study = optuna.create_study(direction="minimize",
                                sampler=optuna.samplers.TPESampler(seed=SEED, n_startup_trials=5))
    study.enqueue_trial(FROZEN_SEARCH_PARAMS[family])

    def objective(trial: optuna.Trial) -> float:
        parameters = sample_parameters(trial, family)
        fold_results, summary = evaluate_parameters(folds, family, parameters)
        trial.set_user_attr("fold_results", fold_results)
        trial.set_user_attr("summary", summary)
        return summary["pooled_wape"]

    study.optimize(objective, n_trials=1, show_progress_bar=False)
    assert_frozen_reproduced(study.trials[0], reference, family)
    study.optimize(objective, n_trials=TRIALS_PER_FAMILY - 1, show_progress_bar=False)
    if len(study.trials) != TRIALS_PER_FAMILY or any(
        trial.state != optuna.trial.TrialState.COMPLETE for trial in study.trials
    ):
        raise ValueError(f"Incomplete {family} search")
    records = [trial_record(trial, family) for trial in study.trials]
    frozen = records[0]
    best_tuned = min(records[1:], key=lambda item: (item["summary"]["pooled_wape"], item["number"]))
    delta = best_tuned["summary"]["pooled_wape"] - frozen["summary"]["pooled_wape"]
    return {
        "family": family, "frozen": frozen, "best_tuned": best_tuned,
        "delta_tuned_minus_frozen_wape": delta,
        "hpo_useful": delta < 0,
        "trials": records,
    }


def build_result(studies: dict) -> dict:
    if set(studies) != set(FAMILIES):
        raise ValueError("Both selected model families must be evaluated")
    eligible = {}
    for family in FAMILIES:
        study = studies[family]
        eligible[family] = study["best_tuned"] if study["hpo_useful"] else study["frozen"]
    ranking = sorted(FAMILIES, key=lambda family: eligible[family]["summary"]["pooled_wape"])
    winner, other = ranking
    difference = (eligible[other]["summary"]["pooled_wape"] -
                  eligible[winner]["summary"]["pooled_wape"])
    return {
        "experiment": "HYPERPARAMETER_TUNING",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_sha256": {
            path.relative_to(ms.ROOT).as_posix(): ms.sha256(path)
            for path in (REFERENCE_PATH, ms.DATA_PATH, ms.JAN_AUG_PATH,
                         ms.SEP_OCT_PATH, Path(__file__), Path(ms.__file__))
        },
        "environment": {"python": platform.python_version(), "pandas": pd.__version__,
                        "numpy": np.__version__, "lightgbm": lightgbm.__version__,
                        "xgboost": xgboost.__version__, "optuna": optuna.__version__},
        "configuration": CONFIGURATION,
        "features": list(ms.FEATURE_CONFIGURATIONS[CONFIGURATION]),
        "categorical_features": list(ms.CATEGORICAL),
        "folds": [{"name": f[0], "train_period": [f[1], f[2]],
                   "validation_period": [f[3], f[4]]} for f in ms.FOLDS],
        "postprocessing": "floor(max(raw_prediction, 0) + 0.5); route 5 = 0",
        "sampler": {"name": "Optuna TPESampler", "seed": SEED, "n_startup_trials": 5,
                    "n_trials_per_family": TRIALS_PER_FAMILY, "baseline_trial": 0},
        "search_spaces": {family: {name: list(values) for name, values in space.items()}
                          for family, space in SEARCH_SPACES.items()},
        "studies": studies,
        "final_configuration": {
            "family": winner,
            "kind": eligible[winner]["kind"],
            "parameters": eligible[winner]["full_parameters"],
            "pooled_wape": eligible[winner]["summary"]["pooled_wape"],
        },
        "ensemble_candidate": {
            "family": other,
            "kind": eligible[other]["kind"],
            "parameters": eligible[other]["full_parameters"],
            "pooled_wape": eligible[other]["summary"]["pooled_wape"],
        } if difference <= CLOSE_WAPE_MARGIN else None,
        "ensemble_close_margin_wape": CLOSE_WAPE_MARGIN,
        "nov_dec_used": False,
        "accepted_feature_registry_changed": False,
    }


def save_result(result: dict) -> None:
    ARTIFACT.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                        encoding="utf-8")


def run_hpo() -> dict:
    _, folds, reference = load_inputs()
    studies = {family: run_study(folds, reference, family) for family in FAMILIES}
    result = build_result(studies)
    save_result(result)
    return result


if __name__ == "__main__":
    result = run_hpo()
    for family, study in result["studies"].items():
        print(f"{family}: frozen={study['frozen']['summary']['pooled_wape']:.6f}, "
              f"tuned={study['best_tuned']['summary']['pooled_wape']:.6f}, "
              f"delta={study['delta_tuned_minus_frozen_wape']:+.6f}")
    print(f"Final: {result['final_configuration']['family']}; "
          f"ensemble candidate: {None if result['ensemble_candidate'] is None else result['ensemble_candidate']['family']}")
    print(f"Saved {ARTIFACT.relative_to(ms.ROOT).as_posix()}")
