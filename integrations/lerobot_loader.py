"""Convert LeRobot parquet episodes into the SimAPI robotics data shape.

Install parquet support with ``pip install pyarrow``. Hub access is optional
and loaded only by :func:`validate_hf_dataset`. State and action vectors keep
their distinct meanings; the loader does not infer effort from actions. When
an input table supplies an explicit ``*_effort`` signal, the shared robotics
engine can use its corresponding ``*_torque`` limit without renaming it.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from integrations.robotics_validation import validate_robotics_frame


def _flatten_vector(value: Any, *, column: str, row: int) -> list[float]:
    if isinstance(value, dict):
        for key in ("q", "state", "position", "values"):
            if key in value and isinstance(value[key], (list, tuple, np.ndarray)):
                value = value[key]
                break
        else:
            value = next(
                (item for item in value.values() if isinstance(item, (list, tuple, np.ndarray))),
                [],
            )
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return []
    if isinstance(value, np.ndarray):
        value = value.tolist()
    if not isinstance(value, (list, tuple)):
        return []
    try:
        return [float(item) for item in value]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Non-numeric vector value in {column!r} at row {row}") from exc


def _dataset_fps(root: Path) -> float | None:
    candidates = [root / "meta" / "info.json", root / "info.json", root.parent / "meta" / "info.json"]
    for info_path in candidates:
        if not info_path.is_file():
            continue
        try:
            fps = float(json.loads(info_path.read_text(encoding="utf-8")).get("fps"))
            if math.isfinite(fps) and fps > 0:
                return fps
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
    return None


def _central_differences(data: pd.DataFrame, position_columns: list[str]) -> pd.DataFrame:
    for position_column in position_columns:
        velocity_column = position_column.removesuffix("_position") + "_velocity"
        values = np.full(len(data), np.nan, dtype=float)
        for _, group in data.groupby("episode_id", sort=False).indices.items():
            indices = np.asarray(group, dtype=int)
            times = data.iloc[indices]["t"].to_numpy(dtype=float)
            positions = data.iloc[indices][position_column].to_numpy(dtype=float)
            if len(indices) < 2:
                continue
            for i in range(len(indices)):
                left, right = (0, 1) if i == 0 else (len(indices) - 2, len(indices) - 1) if i == len(indices) - 1 else (i - 1, i + 1)
                dt = times[right] - times[left]
                if math.isfinite(dt) and dt > 0 and math.isfinite(positions[left]) and math.isfinite(positions[right]):
                    values[indices[i]] = (positions[right] - positions[left]) / dt
        data[velocity_column] = values
    return data


def load_lerobot(
    dataset: str | Path,
    *,
    max_episodes: int | None = None,
    max_joints: int = 14,
    keep_timestamps: bool = True,
) -> pd.DataFrame:
    """Load local LeRobot parquet shards as episode-aware robotics rows.

    The loader emits measured state as position signals and commands as
    ``action_N``. It does not infer torque/effort from command vectors.
    """
    if max_episodes is not None and max_episodes < 1:
        raise ValueError("max_episodes must be positive or None")
    if max_joints < 1:
        raise ValueError("max_joints must be positive")
    root = Path(dataset).expanduser()
    if not root.exists():
        raise FileNotFoundError(root)
    files = [root] if root.is_file() and root.suffix.lower() == ".parquet" else sorted(root.rglob("*.parquet"))
    if not files:
        raise FileNotFoundError(f"No parquet files found under {root}")

    fps = _dataset_fps(root if root.is_dir() else root.parent)
    chunks: list[pd.DataFrame] = []
    episode_offset = 0
    for parquet_path in files:
        try:
            chunk = pd.read_parquet(parquet_path)
        except ImportError as exc:
            raise RuntimeError("LeRobot parquet support requires the optional 'pyarrow' package") from exc
        if chunk.empty:
            continue
        episode_column = next(
            (name for name in ("episode_index", "episode_id", "ep_idx", "trajectory_index") if name in chunk),
            None,
        )
        if episode_column is None:
            raise ValueError(f"No episode index column found in {parquet_path}")
        codes, unique_values = pd.factorize(chunk[episode_column], sort=True)
        if (codes < 0).any():
            raise ValueError(f"Null episode id found in {parquet_path}")
        chunk["_simapi_episode"] = codes.astype(np.int64) + episode_offset
        episode_offset += len(unique_values)
        chunks.append(chunk)
        if max_episodes is not None and episode_offset >= max_episodes:
            break

    raw = pd.concat(chunks, ignore_index=True)
    if max_episodes is not None:
        raw = raw[raw["_simapi_episode"] < max_episodes].copy()
    if raw.empty:
        raise ValueError("No rows remained after applying max_episodes")

    state_column = next((name for name in ("observation.state", "state") if name in raw), None)
    if state_column is None:
        raise ValueError("LeRobot data must include 'observation.state' or 'state'")
    action_column = "action" if "action" in raw else None

    time_unit = "seconds"
    if keep_timestamps and "timestamp" in raw:
        times = pd.to_numeric(raw["timestamp"], errors="coerce")
    elif "frame_index" in raw:
        times = pd.to_numeric(raw["frame_index"], errors="coerce")
        if fps:
            times = times / fps
        else:
            time_unit = "frames"
    else:
        time_unit = "frames"
        times = raw.groupby("_simapi_episode", sort=False).cumcount().astype(float)

    out = pd.DataFrame({"episode_id": raw["_simapi_episode"].astype(int), "t": times})
    state_vectors = [
        _flatten_vector(value, column=state_column, row=index)
        for index, value in enumerate(raw[state_column].tolist())
    ]
    state_width = min(max((len(vector) for vector in state_vectors), default=0), max_joints)
    if state_width == 0:
        raise ValueError(f"No joint state vectors found in {state_column!r}")
    for joint in range(state_width):
        out[f"joint_{joint + 1}_position"] = [
            vector[joint] if joint < len(vector) else np.nan for vector in state_vectors
        ]

    if action_column:
        action_vectors = [
            _flatten_vector(value, column=action_column, row=index)
            for index, value in enumerate(raw[action_column].tolist())
        ]
        action_width = min(max((len(vector) for vector in action_vectors), default=0), max_joints)
        for action in range(action_width):
            out[f"action_{action + 1}"] = [
                vector[action] if action < len(vector) else np.nan for vector in action_vectors
            ]

    out["t"] = pd.to_numeric(out["t"], errors="coerce")
    out = out[np.isfinite(out["t"])].sort_values(["episode_id", "t"], kind="stable").reset_index(drop=True)
    if out.empty:
        raise ValueError("No rows with valid timestamps were found")
    positions = [column for column in out if column.endswith("_position")]
    out = _central_differences(out, positions)
    out.attrs["time_unit"] = time_unit
    out.attrs["source_files"] = [str(path) for path in files]
    return out


def validate_lerobot(
    dataset: str | Path,
    *,
    max_episodes: int | None = None,
    limits: dict[str, tuple[float, float]] | None = None,
    conditions: dict[str, float] | None = None,
) -> dict[str, Any]:
    frame = load_lerobot(dataset, max_episodes=max_episodes)
    result = validate_robotics_frame(
        frame,
        limits=limits,
        conditions=conditions,
        time_unit=str(frame.attrs.get("time_unit", "seconds")),
    )
    result["source"] = str(dataset)
    result["format"] = "lerobot"
    result["n_episodes"] = int(frame["episode_id"].nunique())
    return result


def validate_hf_dataset(
    repo_id: str,
    *,
    max_episodes: int | None = None,
    cache_dir: str | None = None,
) -> dict[str, Any]:
    """Download LeRobot parquet data from the Hugging Face Hub, then validate."""
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise RuntimeError("Hub downloads require the optional 'huggingface_hub' package") from exc
    local_path = snapshot_download(
        repo_id=repo_id,
        repo_type="dataset",
        allow_patterns=["data/**/*.parquet", "meta/info.json", "info.json"],
        local_dir=cache_dir,
    )
    report = validate_lerobot(local_path, max_episodes=max_episodes)
    report["repo_id"] = repo_id
    return report


def _cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m integrations.lerobot_loader")
    parser.add_argument("dataset", help="Local LeRobot dataset directory or parquet file")
    parser.add_argument("--max-episodes", type=int, default=None)
    parser.add_argument("--out", default="", help="Write the converted rows to CSV")
    parser.add_argument("--report", default="", help="Write the validation report to JSON")
    args = parser.parse_args(argv)
    frame = load_lerobot(args.dataset, max_episodes=args.max_episodes)
    if args.out:
        frame.to_csv(args.out, index=False)
    report = validate_robotics_frame(
        frame, time_unit=str(frame.attrs.get("time_unit", "seconds"))
    )
    report.update({"source": args.dataset, "format": "lerobot"})
    rendered = json.dumps(report, indent=2, default=str)
    print(rendered)
    if args.report:
        Path(args.report).write_text(rendered + "\n", encoding="utf-8")
    return 1 if not report["training_ready"] else 0


if __name__ == "__main__":
    raise SystemExit(_cli(sys.argv[1:]))
