"""Episode-aware trajectory checks. Time is seconds; positions are unwrapped."""
from __future__ import annotations

import math
from itertools import chain
from operator import itemgetter
from typing import Any

import numpy as np
import pandas as pd

ENGINE_VERSION = "manipulation-2"
TIME_KEYS = ("time", "t", "timestamp", "simulation_time", "sim_time", "elapsed_time")
GROUP_KEYS = ("episode_id", "episode", "trajectory_id", "sequence_id")
OPTION_KEYS = ("max_time_step", "velocity_tolerance", "acceleration_tolerance")


def normalize(value: str) -> str:
    return value.strip().lower().replace(" ", "_").replace("-", "_").replace(".", "_")


def number(value: Any) -> float | None:
    if value is None or isinstance(value, bool) or (isinstance(value, str) and not value.strip()):
        return None
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    except (ValueError, TypeError):
        return None


def _numeric_values(
    frame: pd.DataFrame, column: str, original_values: list[Any] | None = None
) -> np.ndarray:
    """Convert one column with the same finite-number rules as ``number``.

    Pandas performs the common numeric/string conversion in vectorized code.
    The explicit boolean mask preserves ``number(True) is None`` for mixed
    object columns; a pure boolean column is entirely invalid as a signal.
    """
    series = frame[column]
    if pd.api.types.is_bool_dtype(series.dtype):
        # DataFrame inference turns both Python ``bool`` and ``numpy.bool_``
        # values into a NumPy boolean array. The public ``number`` helper
        # intentionally rejects only Python bool, so consult source values
        # for this uncommon dtype to keep that distinction intact.
        if original_values is None:
            return np.full(len(series), np.nan, dtype=np.float64)
        return np.fromiter(
            (
                np.nan if (parsed := number(value)) is None else parsed
                for value in original_values
            ),
            dtype=np.float64,
            count=len(series),
        )

    if not pd.api.types.is_numeric_dtype(series.dtype) and not pd.api.types.is_object_dtype(series.dtype):
        return np.fromiter(
            (np.nan if (parsed := number(value)) is None else parsed for value in series.array),
            dtype=np.float64,
            count=len(series),
        )

    # pd.to_numeric covers normal numeric/string inputs. Keep the historical
    # float(value) behavior for unusual scalar objects that pandas cannot
    # convert, such as Fraction and custom __float__ implementations.
    supported = (str, int, float, np.number)
    if pd.api.types.is_object_dtype(series.dtype) and any(
        value is not None
        and not isinstance(value, supported)
        and not isinstance(value, bool)
        for value in series.array
    ):
        return np.fromiter(
            (np.nan if (parsed := number(value)) is None else parsed for value in series.array),
            dtype=np.float64,
            count=len(series),
        )

    numeric = pd.to_numeric(series, errors="coerce").to_numpy(
        dtype=np.float64, na_value=np.nan, copy=True
    )
    if pd.api.types.is_object_dtype(series.dtype):
        bool_mask = np.fromiter(
            (isinstance(value, bool) for value in series.array),
            dtype=np.bool_,
            count=len(series),
        )
        if bool_mask.any():
            numeric[bool_mask] = np.nan
    numeric[~np.isfinite(numeric)] = np.nan
    return numeric


def _numeric_object_values(values: np.ndarray) -> np.ndarray:
    """Convert raw object values without building a pandas frame."""
    inferred = pd.api.types.infer_dtype(values, skipna=True)
    if inferred in {"decimal", "floating", "integer", "mixed-integer-float", "string"}:
        try:
            numeric = np.asarray(values, dtype=np.float64)
        except (OverflowError, TypeError, ValueError):
            numeric = np.fromiter(
                (np.nan if (parsed := number(value)) is None else parsed for value in values),
                dtype=np.float64,
                count=len(values),
            )
    else:
        numeric = np.fromiter(
            (np.nan if (parsed := number(value)) is None else parsed for value in values),
            dtype=np.float64,
            count=len(values),
        )
    numeric[~np.isfinite(numeric)] = np.nan
    return numeric


def analyze_trajectories(
    source_rows: list[dict[str, Any]],
    limits: dict[str, tuple[float, float]],
    conditions: dict[str, float],
) -> dict[str, Any]:
    # Normalize the schema once. For the ordinary one-column-to-one-column
    # case, constructing a frame directly avoids allocating another Python
    # dictionary for every sample. Fall back to the historical per-row
    # normalization only when two source names collapse to the same key; in
    # that case the later key in each row must continue to win.
    # Determine the schema directly from row keys. For a complete rectangular
    # schema, flatten its dictionary values once and view them as columns; this
    # avoids pandas' per-record union and dtype inference on large trajectories.
    raw_columns = list({key for row in source_rows for key in row})
    normalized_columns = [normalize(column) for column in raw_columns]
    normalized_rows: list[dict[str, Any]] | None = None
    column_values: dict[str, np.ndarray] | None = None
    if len(set(normalized_columns)) != len(normalized_columns):
        normalized_rows = [
            {normalize(key): value for key, value in row.items()}
            for row in source_rows
        ]
        frame = pd.DataFrame(normalized_rows)
        keys = set().union(*(row.keys() for row in normalized_rows)) if normalized_rows else set()
    else:
        keys = set(normalized_columns)
        if raw_columns:
            n_rows = len(source_rows)
            try:
                if len(raw_columns) == 1:
                    matrix = np.fromiter(
                        (row[raw_columns[0]] for row in source_rows),
                        dtype=object,
                        count=n_rows,
                    ).reshape(n_rows, 1)
                else:
                    records = map(itemgetter(*raw_columns), source_rows)
                    flat_values = np.fromiter(
                        chain.from_iterable(records),
                        dtype=object,
                        count=n_rows * len(raw_columns),
                    )
                    matrix = flat_values.reshape(n_rows, len(raw_columns))
                column_values = {
                    column: matrix[:, position]
                    for position, column in enumerate(normalized_columns)
                }
            except KeyError:
                # At least one record is missing a schema key. Let pandas fill
                # the absent cells as before.
                frame = pd.DataFrame(source_rows, columns=raw_columns)
        else:
            column_values = {}

    n_rows = len(source_rows)
    time_key = next((key for key in TIME_KEYS if key in keys), None)
    group_key = next((key for key in GROUP_KEYS if key in keys), None)
    bounds = {normalize(key): value for key, value in limits.items()}

    if group_key:
        if normalized_rows is not None:
            group_values = [
                str(row.get(group_key, "(missing episode)"))
                for row in normalized_rows
            ]
        elif column_values is not None:
            group_values = [str(value) for value in column_values[group_key]]
        else:
            raw_group_key = raw_columns[normalized_columns.index(group_key)]
            group_values = [
                str(row.get(raw_group_key, "(missing episode)"))
                for row in source_rows
            ]
        group_codes, group_names = pd.factorize(np.asarray(group_values, dtype=object), sort=False)
    else:
        group_codes = np.zeros(n_rows, dtype=np.int64)
        group_names = np.asarray(["Episode 1"], dtype=object) if n_rows else np.asarray([], dtype=object)

    # Stable sort by factorized episode code groups row positions while
    # retaining their original order within each episode. Adjacent-pair
    # arrays are then constructed episode by episode, so no derivative can
    # cross a reset boundary.
    if n_rows:
        group_order = np.argsort(group_codes, kind="stable")
        group_counts = np.bincount(group_codes, minlength=len(group_names))
        group_offsets = np.concatenate(([0], np.cumsum(group_counts)))
        group_positions = [
            group_order[group_offsets[i]:group_offsets[i + 1]]
            for i in range(len(group_names))
        ]
    else:
        group_positions = []

    checks: list[dict[str, Any]] = []
    excluded: dict[int, list[str]] = {}
    numeric_cache: dict[str, np.ndarray] = {}

    def numeric_column(column: str) -> np.ndarray:
        if column not in numeric_cache:
            if column_values is not None:
                numeric_cache[column] = _numeric_object_values(column_values[column])
            else:
                series = frame[column]
                original_values = None
                if pd.api.types.is_bool_dtype(series.dtype):
                    if normalized_rows is not None:
                        original_values = [row.get(column) for row in normalized_rows]
                    else:
                        raw_column = raw_columns[normalized_columns.index(column)]
                        original_values = [row.get(raw_column) for row in source_rows]
                numeric_cache[column] = _numeric_values(frame, column, original_values)
        return numeric_cache[column]

    def check(name: str, column: str, bad: list[int], detail: str, evaluated: bool = True) -> None:
        unique = sorted(set(bad))
        status = ("failed" if unique else "passed") if evaluated else "warning"
        checks.append({"name": name, "column": column, "status": status, "indices": unique,
                       "violations": len(unique), "detail": detail if evaluated else "Not evaluated. " + detail, "low": None, "high": None})
        for index in unique:
            excluded.setdefault(index, []).append(detail)

    if not time_key:
        check("robotics_time_coverage", "time", [], "No numeric time column: trajectory timing and derivatives were not evaluated.", False)
    else:
        time_values = numeric_column(time_key)
        pair_prev_parts = [indices[:-1] for indices in group_positions if len(indices) > 1]
        pair_curr_parts = [indices[1:] for indices in group_positions if len(indices) > 1]
        if pair_prev_parts:
            pair_prev = np.concatenate(pair_prev_parts)
            pair_curr = np.concatenate(pair_curr_parts)
            pair_dt = time_values[pair_curr] - time_values[pair_prev]
            both_times_valid = np.isfinite(time_values[pair_prev]) & np.isfinite(time_values[pair_curr])
            bad_order = pair_curr[both_times_valid & (pair_dt <= 0)]
            positive_pairs = both_times_valid & (pair_dt > 0)
            pair_prev = pair_prev[positive_pairs]
            pair_curr = pair_curr[positive_pairs]
            pair_dt = pair_dt[positive_pairs]
        else:
            pair_prev = pair_curr = np.asarray([], dtype=np.int64)
            pair_dt = np.asarray([], dtype=np.float64)
            bad_order = np.asarray([], dtype=np.int64)

        missing_time = np.flatnonzero(~np.isfinite(time_values))
        bad_time = np.concatenate((missing_time, bad_order)).tolist()
        check("robotics_time_order", time_key, bad_time,
              f"{len(bad_time)} sample(s) have missing or non-increasing time within their episode.")
        if conditions.get("max_time_step", 0) > 0:
            bad_gap = pair_curr[pair_dt > conditions["max_time_step"]].tolist()
            check("robotics_sample_gaps", time_key, bad_gap,
                  f"{len(bad_gap)} interval(s) exceed the configured maximum time step of {conditions['max_time_step']:g} seconds.", len(pair_curr) > 0)

        evaluated = {"velocity_tolerance": False, "acceleration_tolerance": False}
        for column in sorted(keys):
            # Derivatives only use explicitly named joint state signals.
            if not column.startswith("joint"):
                continue
            for quantity, derivative, option in (
                ("position", "velocity", "velocity_tolerance"),
                ("velocity", "acceleration", "acceleration_tolerance"),
            ):
                if not column.endswith("_" + quantity):
                    continue
                target = column[:-len(quantity)] + derivative
                limit = bounds.get(target)
                tolerance = conditions.get(option, 0)
                compare = tolerance > 0 and target in keys
                if limit is None and not compare:
                    continue
                source_values = numeric_column(column)
                first_values = source_values[pair_prev]
                last_values = source_values[pair_curr]
                usable_pairs = np.isfinite(first_values) & np.isfinite(last_values)
                usable = int(usable_pairs.sum())
                observed = (last_values[usable_pairs] - first_values[usable_pairs]) / pair_dt[usable_pairs]
                usable_indices = pair_curr[usable_pairs]
                if limit is not None:
                    within_bound = (observed >= limit[0]) & (observed <= limit[1])
                    bad_bound = usable_indices[~within_bound].tolist()
                    check(f"robotics_derived_limit:{target}", target, bad_bound,
                          f"{len(bad_bound)} interval(s): {derivative} derived from {column} exceeds [{limit[0]:g}, {limit[1]:g}].", usable > 0)
                if compare:
                    evaluated[option] = evaluated[option] or usable > 0
                    target_values = numeric_column(target)
                    left_values = target_values[pair_prev[usable_pairs]]
                    right_values = target_values[pair_curr[usable_pairs]]
                    bad_consistency_mask = (
                        ~np.isfinite(left_values)
                        | ~np.isfinite(right_values)
                        | (np.abs(observed - (left_values + right_values) / 2) > tolerance)
                    )
                    bad_consistency = usable_indices[bad_consistency_mask].tolist()
                    check(f"robotics_consistency:{target}", target, bad_consistency,
                          f"{len(bad_consistency)} interval(s): finite-difference {derivative} differs from the endpoint-average {target} by more than {tolerance:g}.", usable > 0)
        for option, was_evaluated in evaluated.items():
            if conditions.get(option, 0) > 0 and not was_evaluated:
                check(f"robotics_not_evaluated:{option}", option, [],
                      f"{option} was requested but matching joint signals and valid adjacent timestamps were unavailable.", False)

    episodes = []
    flagged_rows = np.zeros(n_rows, dtype=np.bool_)
    if excluded:
        flagged_rows[np.fromiter(excluded, dtype=np.int64, count=len(excluded))] = True
    for code, indices in enumerate(group_positions):
        duration = None
        if time_key and len(indices) >= 2:
            episode_times = time_values[indices]
            ordered = np.isfinite(episode_times).all() and (np.diff(episode_times) > 0).all()
            if ordered:
                candidate = float(episode_times[-1] - episode_times[0])
                duration = candidate if candidate >= 0 else None
        episodes.append({"episode_id": str(group_names[code]), "samples": len(indices),
                         "duration_seconds": duration,
                         "flagged_samples": int(flagged_rows[indices].sum())})
    return {"checks": checks, "excluded": excluded,
            "summary": {"engine_version": ENGINE_VERSION, "episodes": episodes,
                        "time_column": time_key, "episode_column": group_key,
                        "assumptions": ["Numeric timestamps are seconds.", "Joint positions must be unwrapped; no angle-wrap inference.",
                                        "Finite differences estimate interval-average motion, not peak motion."]}}
