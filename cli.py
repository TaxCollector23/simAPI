"""SimAPI batch CLI — streaming, parallel validation of large robotics datasets.

    simapi validate-batch <dir_or_file> [options]

Validates directories of `.parquet` / `.csv` / `.mcap` recordings, or one
multi-gigabyte Parquet dataset, in bounded-memory chunks distributed across
CPU cores. Nothing is ever fully loaded into RAM: Parquet row groups are read
in batches, CSV files stream with a fixed chunk size, and every worker only
materializes the rows it is validating.

Outputs (written to --out, default ./simapi-batch-report):
  dataset_summary.json — per-file status, per-episode verdicts, aggregate
                         counts, and the exact configuration used.
  QUALITY_CARD.md      — a Hugging Face-style dataset quality card with the
                         SimAPI pass-rate badge, ready to paste into a
                         dataset README.

Fail-closed convention: a file that cannot be read or parsed is reported as
an error in the summary (and counts against the dataset verdict) instead of
being silently skipped.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.robotics_validation import check_robotics_limits  # noqa: E402

SUPPORTED_SUFFIXES = {".parquet", ".csv", ".mcap"}
DEFAULT_OUT = "simapi-batch-report"


# ── per-shard validation (runs inside worker processes) ────────────────────────

def _validate_chunk(rows: list[dict], limits: dict, conditions: dict) -> dict:
    """Run the full robotics engine on one bounded chunk of rows."""
    report = check_robotics_limits(pd.DataFrame(rows), limits, source_rows=rows, conditions=conditions)
    episodes = {}
    for episode in report.get("summary", {}).get("episodes", []):
        episodes[str(episode["episode_id"])] = {
            "samples": int(episode.get("samples", 0)),
            "flagged_samples": int(episode.get("flagged_samples", 0)),
        }
    failed = [c["name"] for c in report.get("checks", []) if c.get("status") == "failed"]
    warned = [c["name"] for c in report.get("checks", []) if c.get("status") == "warning"]
    return {
        "rows": len(rows),
        "episodes": episodes,
        "failed_checks": failed,
        "warning_checks": warned,
        "excluded_rows": len(report.get("excluded") or {}),
    }


def _parquet_chunk_tasks(path: Path, batch_rows: int) -> list[dict]:
    """Split one Parquet file into row-group-range tasks sized to batch_rows."""
    import pyarrow.parquet as pq

    parquet = pq.ParquetFile(path)
    groups = parquet.num_row_groups
    metadata = parquet.metadata
    tasks: list[dict] = []
    start = 0
    rows_seen = 0
    for group in range(groups):
        rows_seen += metadata.row_group(group).num_rows
        if rows_seen >= batch_rows or group == groups - 1:
            tasks.append({
                "path": str(path),
                "format": "parquet",
                "row_groups": [start, group + 1],
                "rows": rows_seen,
            })
            start = group + 1
            rows_seen = 0
    return tasks


def _read_chunk(task: dict) -> list[dict]:
    """Materialize exactly one task's rows. Workers only touch their own slice."""
    path = Path(task["path"])
    if task["format"] == "parquet":
        import pyarrow.parquet as pq

        first, last = task["row_groups"]
        parquet = pq.ParquetFile(path)
        table = parquet.read_row_groups(list(range(first, last)))
        return table.to_pandas().replace({pd.NA: None}).to_dict("records")
    if task["format"] == "csv":
        first, last = task["chunk_index"]
        skip = 1 + first * task["chunk_rows"]  # header + previously consumed rows
        frame = pd.read_csv(path, skiprows=range(1, skip) if skip > 1 else None,
                            nrows=task["chunk_rows"])
        return frame.where(pd.notnull(frame), None).to_dict("records")
    raise ValueError(f"Unsupported chunk format {task['format']!r}")


def _validate_task(task: dict, limits: dict, conditions: dict) -> dict:
    """Validate one chunk task and return a JSON-serializable partial result."""
    from integrations.lerobot_loader import load_lerobot
    from integrations.ros2_loader import load_rosbag2

    path = Path(task["path"])
    started = time.perf_counter()
    try:
        if task["format"] == "mcap":
            # rosbags-backed streaming loader; bounded by its own row cap.
            frame = load_rosbag2(path, topic_hint=task.get("topic_hint", "joint_states"),
                                 max_rows=task.get("max_rows", 2_000_000))
            rows = frame.reset_index(drop=True).replace({pd.NA: None}).to_dict("records")
            chunks = [_validate_chunk(rows, limits, conditions)]
        elif task["format"] == "lerobot_dir":
            frame = load_lerobot(path, max_rows=task.get("max_rows", 2_000_000))
            rows = frame.reset_index(drop=True).replace({pd.NA: None}).to_dict("records")
            chunks = [_validate_chunk(rows, limits, conditions)]
        else:
            rows = _read_chunk(task)
            chunks = [_validate_chunk(rows, limits, conditions)]
    except Exception as exc:  # reported, never silent
        return {
            "path": str(path), "format": task["format"], "ok": False,
            "error": f"{type(exc).__name__}: {exc}", "rows": 0, "episodes": {},
            "failed_checks": [], "warning_checks": [], "excluded_rows": 0,
            "seconds": round(time.perf_counter() - started, 3),
        }
    return {
        "path": str(path), "format": task["format"], "ok": True,
        "rows": sum(c["rows"] for c in chunks),
        "episodes": _merge_episode_maps(c["episodes"] for c in chunks),
        "failed_checks": sorted({name for c in chunks for name in c["failed_checks"]}),
        "warning_checks": sorted({name for c in chunks for name in c["warning_checks"]}),
        "excluded_rows": sum(c["excluded_rows"] for c in chunks),
        "seconds": round(time.perf_counter() - started, 3),
    }


def _merge_episode_maps(maps):
    merged: dict[str, dict] = {}
    for mapping in maps:
        for episode_id, stats in mapping.items():
            entry = merged.setdefault(episode_id, {"samples": 0, "flagged_samples": 0})
            entry["samples"] += stats["samples"]
            entry["flagged_samples"] += stats["flagged_samples"]
    return merged


# ── discovery ───────────────────────────────────────────────────────────────────

def _discover(target: Path) -> list[dict]:
    """Expand a file or directory into validation tasks."""
    tasks: list[dict] = []
    files = (
        sorted(p for p in target.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES)
        if target.is_dir()
        else [target]
    )
    if not files:
        raise SystemExit(
            f"No supported recordings found under {target}. "
            f"Supported: {', '.join(sorted(SUPPORTED_SUFFIXES))}."
        )
    for path in files:
        suffix = path.suffix.lower()
        if suffix == ".parquet":
            tasks.append({"path": str(path), "format": "parquet"})
        elif suffix == ".csv":
            tasks.append({"path": str(path), "format": "csv"})
        else:
            tasks.append({"path": str(path), "format": "mcap"})
    return tasks


# ── outputs ─────────────────────────────────────────────────────────────────────

def _episode_verdicts(episodes: dict) -> tuple[list[dict], int, int]:
    rows_out = []
    passed = failed = 0
    for episode_id in sorted(episodes):
        stats = episodes[episode_id]
        bad = stats["flagged_samples"] > 0
        failed += bad
        passed += not bad
        rows_out.append({"episode_id": episode_id, **stats,
                         "verdict": "failed" if bad else "passed"})
    return rows_out, passed, failed


def _quality_card(summary: dict, out_dir: Path) -> None:
    passed_pct = summary["episodes_passed"] / max(1, summary["episodes_total"]) * 100
    color = "brightgreen" if passed_pct >= 95 else "yellow" if passed_pct >= 80 else "red"
    worst = sorted(
        summary["episodes"],
        key=lambda e: (-e["flagged_samples"], e["episode_id"]),
    )[:10]
    worst_rows = "\n".join(
        f"| {e['episode_id']} | {e['samples']} | {e['flagged_samples']} | {e['verdict']} |"
        for e in worst
    ) or "| (none) | 0 | 0 | passed |"
    failed_checks = summary.get("failed_checks") or []
    check_lines = "\n".join(f"- `{name}`" for name in failed_checks) or "- (none)"
    conditions = json.dumps(summary["conditions"], indent=2) if summary["conditions"] else "{}"
    limits = json.dumps(summary["robotics_limits"], indent=2) if summary["robotics_limits"] else "(screening defaults)"
    errors = summary.get("errors") or []
    error_lines = "\n".join(f"- `{e['path']}`: {e['error']}" for e in errors) or "- (none)"
    out_dir.joinpath("QUALITY_CARD.md").write_text(
        f"""---
SimAPI Dataset Quality Card
engine: {summary['engine_version']}
validated: {summary['validated_at']}
---

# Dataset quality card

![SimAPI validation](https://img.shields.io/badge/SimAPI-{summary['episodes_passed']}/{summary['episodes_total']}%20episodes%20passed-{color})

Validated by SimAPI's robotics engine on {summary['validated_at']}.
A passing badge means the configured checks found no violations — it does not
certify the robot, prove sim-to-real transfer, or replace engineering review.

## Results

| Metric | Value |
| --- | --- |
| Files validated | {summary['files_total']} ({summary['files_ok']} ok, {len(errors)} with errors) |
| Rows validated | {summary['rows_total']:,} |
| Rows excluded | {summary['rows_excluded']:,} |
| Episodes | {summary['episodes_total']:,} |
| Episodes passed | {summary['episodes_passed']:,} ({passed_pct:.1f}%) |
| Episodes failed | {summary['episodes_failed']:,} |
| Wall time | {summary['seconds']}s across {summary['workers']} worker(s) |

## Failing checks seen in this dataset

{check_lines}

## Worst episodes

| Episode | Samples | Flagged | Verdict |
| --- | --- | --- | --- |
{worst_rows}

## Files with errors (fail-closed)

{error_lines}

## Configuration used

Conditions:

```json
{conditions}
```

Robotics limits:

```json
{limits}
```

Reproduce with:

```sh
simapi validate-batch {summary['source']}
```
""",
        encoding="utf-8",
    )


# ── command ─────────────────────────────────────────────────────────────────────

def _parse_json_option(raw: str | None, name: str) -> dict:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{name} is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit(f"{name} must be a JSON object.")
    return value


def cmd_validate_batch(args: argparse.Namespace) -> int:
    target = Path(args.source).expanduser()
    if not target.exists():
        raise SystemExit(f"No such file or directory: {target}")
    # Only user-configured limits reach the engine as configured_limits — the
    # engine applies its own screening defaults for everything else, and
    # treats a configured limit whose column is missing as a failure.
    configured = _parse_json_option(args.limits, "--limits")
    conditions = _parse_json_option(args.conditions, "--conditions")

    file_tasks = _discover(target)
    # Parquet files split into row-group-range tasks; everything else is one
    # task per file so each worker streams a bounded slice.
    tasks: list[dict] = []
    for task in file_tasks:
        path = Path(task["path"])
        if task["format"] == "parquet":
            tasks.extend(_parquet_chunk_tasks(path, args.batch_rows))
        elif task["format"] == "csv":
            total_rows = sum(1 for _ in path.open("rb")) - 1
            stride = args.batch_rows
            index = 0
            while index * stride < total_rows:
                tasks.append({
                    "path": str(path), "format": "csv", "chunk_index": [index, index + 1],
                    "chunk_rows": stride, "rows": min(stride, total_rows - index * stride),
                })
                index += 1
        else:
            task["topic_hint"] = args.topic_hint
            tasks.append(task)

    workers = max(1, min(args.workers, os.cpu_count() or 1, len(tasks)))
    started = time.perf_counter()
    results: list[dict] = []
    if workers == 1:
        for task in tasks:
            results.append(_validate_task(task, configured, conditions))
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_validate_task, task, configured, conditions) for task in tasks]
            for future in as_completed(futures):
                results.append(future.result())
    seconds = round(time.perf_counter() - started, 3)

    episodes = _merge_episode_maps(r["episodes"] for r in results)
    episode_rows, passed, failed = _episode_verdicts(episodes)
    errors = [r for r in results if not r["ok"]]
    failed_checks = sorted({name for r in results for name in r["failed_checks"]})
    warning_checks = sorted({name for r in results for name in r["warning_checks"]})
    summary = {
        "source": str(target),
        "engine_version": "batch-1",
        "validated_at": time.strftime("%Y-%m-%d"),
        "workers": workers,
        "seconds": seconds,
        "files_total": len(file_tasks),
        "files_ok": len(file_tasks) - len({e["path"] for e in errors}),
        "rows_total": sum(r["rows"] for r in results),
        "rows_excluded": sum(r["excluded_rows"] for r in results),
        "episodes_total": len(episodes),
        "episodes_passed": passed,
        "episodes_failed": failed,
        "episodes": episode_rows,
        "failed_checks": failed_checks,
        "warning_checks": warning_checks,
        "errors": [{"path": e["path"], "error": e["error"]} for e in errors],
        "robotics_limits": {k: list(v) for k, v in configured.items()},
        "conditions": conditions,
        "verdict": "failed" if (failed_checks or errors) else "passed",
    }

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_dir.joinpath("dataset_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    _quality_card(summary, out_dir)

    print(f"Validated {summary['rows_total']:,} rows in {summary['files_total']} file(s) "
          f"using {workers} worker(s) in {seconds}s")
    print(f"Episodes: {passed} passed, {failed} failed; verdict: {summary['verdict']}")
    if errors:
        for error in errors:
            print(f"  ERROR {error['path']}: {error['error']}", file=sys.stderr)
    print(f"Report: {out_dir / 'dataset_summary.json'}")
    print(f"Card:   {out_dir / 'QUALITY_CARD.md'}")
    return 1 if summary["verdict"] == "failed" else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="simapi", description="SimAPI command-line tools.")
    sub = parser.add_subparsers(dest="command", required=True)

    batch = sub.add_parser(
        "validate-batch",
        help="Validate a dataset directory or large Parquet/CSV/MCAP file in bounded-memory parallel chunks.",
    )
    batch.add_argument("source", help="Directory of recordings, or one .parquet/.csv/.mcap file.")
    batch.add_argument("--out", default=DEFAULT_OUT, help="Output directory (default ./simapi-batch-report).")
    batch.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2)), help="Parallel workers (default: all cores).")
    batch.add_argument("--batch-rows", type=int, default=50_000, help="Approximate rows per validation chunk (default 50000).")
    batch.add_argument("--limits", help="JSON object of per-signal [min, max] robotics limits.")
    batch.add_argument("--limits-file", dest="limits", help="JSON file of robotics limits (arm-profile.json).")
    batch.add_argument("--conditions", help="JSON object of check conditions (max_time_step, chatter/energy keys, ...).")
    batch.add_argument("--topic-hint", dest="topic_hint", default="joint_states", help="ROS topic substring for MCAP JointState messages.")
    batch.set_defaults(func=cmd_validate_batch)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
