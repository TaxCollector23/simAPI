"""Dynamics check suites: actuator chatter and energy conservation.

Two opt-in suites for the composable robotics engine, enabled through
``conditions`` exactly like ``velocity_tolerance`` so existing runs keep
their current reports:

* :class:`ActuatorChatterSuite` — windowed spectral check on joint velocity
  signals. Simulated policies can show high-frequency control oscillation
  that stays inside every static joint limit yet damages real actuators.
  Each episode window is flagged when the fraction of velocity spectral
  power above ``chatter_min_frequency_hz`` exceeds ``max_chatter_power_ratio``.

* :class:`EnergyConservationSuite` — model-free work/energy consistency
  check on joint velocity and effort signals. Kinetic-energy change between
  samples must be explainable by mechanical work. Without URDF inertials the
  effective inertia is unknown, so the suite calibrates itself per episode:
  a robust linear fit of kinetic-energy change onto work (the slope absorbs
  the unknown effective inertia, the intercept absorbs constant unmodelled
  torques such as gravity). Intervals whose residual kinetic-energy change
  exceeds ``energy_anomaly_factor`` times the episode's robust residual
  scale are flagged — the signature of physics-engine contact-solver energy
  injection ("explosions") that passes every range check.

Both suites follow the fail-closed reporting convention: when they are
requested but cannot evaluate (missing time, non-uniform sampling, too few
samples, missing signals), they emit a ``warning`` check explaining why
instead of silently passing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from core.robotics_trajectory import GROUP_KEYS, TIME_KEYS, normalize, number

# conditions keys
CHATTER_RATIO_KEY = "max_chatter_power_ratio"
CHATTER_FREQUENCY_KEY = "chatter_min_frequency_hz"
ENERGY_FACTOR_KEY = "energy_anomaly_factor"
FOOT_SLIP_KEY = "max_foot_slip_mps"
LEGACY_FOOT_SLIP_KEY = "max_foot_slip_ms"
FOOT_FORCE_KEY = "min_foot_contact_force_n"
SYNC_SKEW_KEY = "max_sync_skew_ms"

# Chatter defaults; the window shrinks to the episode length when shorter.
# The window targets CHATTER_PERIODS_PER_WINDOW periods of the cutoff
# frequency (clamped), so high-rate logs still resolve low-frequency floors.
CHATTER_WINDOW = 64
CHATTER_MIN_WINDOW = 16
CHATTER_WINDOW_MAX = 512
CHATTER_PERIODS_PER_WINDOW = 6.0
CHATTER_DEFAULT_RATIO = 0.25
# Physical chatter floor: 15 Hz catches the 30-50 Hz control oscillations that
# damage real actuators even on 500 Hz+ logs, where the old Nyquist/2 default
# (>= 125 Hz) let them through. Remains configurable per run.
CHATTER_DEFAULT_MIN_FREQUENCY_HZ = 15.0
# A sampling interval more than 25% away from the episode median makes the
# frequency axis of the FFT unreliable, so such episodes are not evaluated.
CHATTER_MAX_DT_DEVIATION = 0.25

# Energy fit needs enough intervals for a stable robust scale estimate.
ENERGY_MIN_INTERVALS = 8
# Sliding-window fit: a single episode-wide fit lets posture-dependent inertia
# shifts absorb local energy injections, so the robust regression runs over
# 32-interval windows instead.
ENERGY_WINDOW = 32
ENERGY_WINDOW_STRIDE = 16
# Low-excitation guard: a window whose kinetic-energy change has (near-)zero
# variance carries no information about the work/energy relationship.
ENERGY_EXCITATION_EPS = 1e-12
# A residual must also reach 0.1% of the episode's largest kinetic-energy
# change, so numerically tiny residuals never fail a clean run.
ENERGY_RESIDUAL_FLOOR = 1e-3

# Foot-contact signals: any prefix ending in "foot" (left_foot, right_foot, ...).
FOOT_FORCE_SUFFIX = "contact_force_z"
FOOT_VELOCITY_SUFFIXES = ("linear_velocity_x", "linear_velocity_y")
CAMERA_TIME_KEYS = ("t_cam", "camera_time", "camera_timestamp")
JOINT_TIME_KEYS = ("t_joint", "joint_time", "joint_timestamp")
DEFAULT_FOOT_CONTACT_FORCE_N = 1.0


@dataclass
class DynamicsSuiteResult:
    """Structurally compatible with ``RoboticsSuiteResult`` (duck-typed)."""

    checks: list[dict[str, Any]] = field(default_factory=list)
    excluded: dict[int, list[str]] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)
    evidence: list[dict[str, Any]] = field(default_factory=list)


def _normalized_rows(source_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{normalize(str(key)): value for key, value in row.items()} for row in source_rows]


def _episode_slices(rows: list[dict[str, Any]]):
    """Return (time_key, group_key, [(episode_id, [row indices])])."""
    keys = set().union(*(row.keys() for row in rows)) if rows else set()
    time_key = next((key for key in TIME_KEYS if key in keys), None)
    group_key = next((key for key in GROUP_KEYS if key in keys), None)
    groups: dict[str, list[int]] = {}
    order: list[str] = []
    for index, row in enumerate(rows):
        name = str(row.get(group_key, "(missing episode)")) if group_key else "Episode 1"
        if name not in groups:
            groups[name] = []
            order.append(name)
        groups[name].append(index)
    return time_key, group_key, [(name, groups[name]) for name in order]


def _column_values(rows: list[dict[str, Any]], column: str) -> np.ndarray:
    return np.fromiter(
        (np.nan if (value := number(row.get(column))) is None else value for row in rows),
        dtype=np.float64,
        count=len(rows),
    )


def _joint_velocity_signals(keys: set[str]) -> list[str]:
    return sorted(key for key in keys if key.startswith("joint") and key.endswith("_velocity"))


def _finding(check: str, signal: str, episode: str, sample: int,
             time: float | None, observed: float, expected: list[float],
             detail: str, unit: str, measurement: str, **interval: float) -> dict[str, Any]:
    """Carry measured quantities and their actual units into evidence."""
    return {
        "check": check, "status": "failed", "signal": signal,
        "episode_id": episode, "sample_index": sample, "time": time,
        "observed": number(observed), "expected": expected, "detail": detail,
        "unit": unit, "measurement": measurement, "point_only": True,
        **interval,
    }


class ActuatorChatterSuite:
    """Flag high-frequency oscillation in joint velocity signals.

    Enabled when ``max_chatter_power_ratio`` or ``chatter_min_frequency_hz``
    is present in ``conditions``.
    """

    name = "actuator_chatter"

    def run(self, context) -> DynamicsSuiteResult:
        conditions = context.conditions
        ratio_limit = conditions.get(CHATTER_RATIO_KEY)
        min_frequency = conditions.get(CHATTER_FREQUENCY_KEY)
        if ratio_limit is None and min_frequency is None:
            return DynamicsSuiteResult(summary={"actuator_chatter": {"enabled": False}})

        if ratio_limit is None:
            ratio_limit = CHATTER_DEFAULT_RATIO
        if not 0 < ratio_limit < 1:
            return DynamicsSuiteResult(
                checks=[{
                    "name": "robotics_chatter:not_evaluated",
                    "column": None,
                    "status": "warning",
                    "indices": [],
                    "violations": 0,
                    "detail": f"{CHATTER_RATIO_KEY} must be between 0 and 1; chatter checking was not run.",
                    "low": None,
                    "high": None,
                }],
                summary={"actuator_chatter": {"enabled": True, "evaluated_signals": 0}},
            )

        rows = _normalized_rows(context.source_rows)
        time_key, _group_key, episodes = _episode_slices(rows)
        keys = set().union(*(row.keys() for row in rows)) if rows else set()
        velocity_signals = _joint_velocity_signals(keys)

        checks: list[dict[str, Any]] = []
        excluded: dict[int, list[str]] = {}
        evidence: list[dict[str, Any]] = []
        if not velocity_signals:
            checks.append({
                "name": "robotics_chatter:not_evaluated",
                "column": None,
                "status": "warning",
                "indices": [],
                "violations": 0,
                "detail": "Chatter checking was requested but no joint velocity signals were found.",
                "low": 0.0,
                "high": float(ratio_limit),
            })
            return DynamicsSuiteResult(
                checks=checks, summary={"actuator_chatter": {"enabled": True, "evaluated_signals": 0}}
            )

        skip_reasons = {
            "missing_time": 0,
            "non_increasing_time": 0,
            "non_uniform_sampling": 0,
            "too_few_samples": 0,
            "non_finite_signal": 0,
            "frequency_above_nyquist": 0,
        }
        evaluated_signals = 0

        for signal in velocity_signals:
            values = _column_values(rows, signal)
            flagged: list[int] = []
            flagged_windows = 0
            evaluated_episodes = 0
            cutoff_hz: float | None = None
            for name, indices in episodes:
                if time_key is None:
                    skip_reasons["missing_time"] += 1
                    continue
                times = _column_values(rows, time_key)[indices]
                segment = values[indices]
                if not np.isfinite(times).all() or not (np.diff(times) > 0).all():
                    skip_reasons["non_increasing_time"] += 1
                    continue
                steps = np.diff(times)
                median_dt = float(np.median(steps))
                if median_dt <= 0 or np.max(np.abs(steps - median_dt)) > CHATTER_MAX_DT_DEVIATION * median_dt:
                    skip_reasons["non_uniform_sampling"] += 1
                    continue
                if not np.isfinite(segment).all():
                    skip_reasons["non_finite_signal"] += 1
                    continue
                nyquist = 0.5 / median_dt
                cutoff = float(min_frequency) if min_frequency is not None else CHATTER_DEFAULT_MIN_FREQUENCY_HZ
                if cutoff <= 0 or cutoff >= nyquist:
                    skip_reasons["frequency_above_nyquist"] += 1
                    continue
                cutoff_hz = cutoff
                # The window must span several periods of the cutoff frequency:
                # at 500 Hz+ a fixed 64-sample window is only ~0.13 s, too
                # short to separate 15 Hz chatter from slow-motion trends.
                window = int(round(CHATTER_PERIODS_PER_WINDOW / (cutoff * median_dt)))
                window = max(CHATTER_MIN_WINDOW, min(CHATTER_WINDOW_MAX, window))
                window = min(window, len(indices))
                if window < CHATTER_MIN_WINDOW:
                    skip_reasons["too_few_samples"] += 1
                    continue

                # Contiguous (non-overlapping) windows: each sample is judged
                # by exactly one window, so flagged indices map 1:1 to the
                # time spans that actually carry chatter.
                step = window
                windows = np.lib.stride_tricks.sliding_window_view(segment, window)[::step]
                frequencies = np.fft.rfftfreq(window, d=median_dt)
                high_band = frequencies >= cutoff
                positions = np.arange(window, dtype=float)
                # Pass 1: detrend every window and collect its residual power.
                detrended = []
                for position, sample in enumerate(windows):
                    # Remove the window's linear trend before the FFT: a slow
                    # (sub-window) motion otherwise leaks ramp-shaped broadband
                    # power into the high band and fails clean 500 Hz+ logs.
                    trend = np.polynomial.polynomial.polyfit(positions, sample, 1)
                    centered = sample - np.polynomial.polynomial.polyval(positions, trend)
                    detrended.append((position, centered, float(centered @ centered)))
                # Windows with (near-)zero residual power are noise-dominated:
                # their spectral ratio says nothing about chatter, so they are
                # skipped rather than judged (a ratio over ~zero power).
                power_floor = 0.01 * float(np.median([power for _, _, power in detrended]))
                for position, centered, total_power in detrended:
                    if total_power <= power_floor:
                        continue
                    power = np.abs(np.fft.rfft(centered)) ** 2
                    ratio = float(power[high_band].sum()) / float(power.sum())
                    if ratio > ratio_limit:
                        start = position * step
                        end = start + window - 1
                        flagged.extend(indices[start:end + 1])
                        flagged_windows += 1
                        evidence.append(_finding(
                            f"robotics_chatter:{signal}", signal, name, indices[end],
                            float(times[end]), ratio, [0.0, float(ratio_limit)],
                            f"Spectral power above {cutoff:g} Hz exceeds the configured ratio.",
                            "ratio", "High-frequency power ratio",
                            interval_start=float(times[start]), interval_end=float(times[end]),
                        ))
                evaluated_episodes += 1

            if evaluated_episodes == 0:
                reasons = ", ".join(f"{reason}: {count}" for reason, count in skip_reasons.items() if count)
                checks.append({
                    "name": f"robotics_chatter:{signal}",
                    "column": signal,
                    "status": "warning",
                    "indices": [],
                    "violations": 0,
                    "detail": f"Chatter was not evaluated for any episode ({reasons}).",
                    "low": 0.0,
                    "high": float(ratio_limit),
                })
                continue
            evaluated_signals += 1
            unique = sorted(set(flagged))
            status = "failed" if unique else "passed"
            detail = (
                f"{len(unique)} sample(s) in {flagged_windows} window(s): more than {ratio_limit:g} "
                f"of velocity spectral power lies above {cutoff_hz:g} Hz."
                if unique
                else f"All windows keep at most {ratio_limit:g} of velocity spectral power above {cutoff_hz:g} Hz."
            )
            checks.append({
                "name": f"robotics_chatter:{signal}",
                "column": signal,
                "status": status,
                "indices": unique,
                "violations": len(unique),
                "detail": detail,
                "low": 0.0,
                "high": float(ratio_limit),
            })
            for index in unique:
                excluded.setdefault(index, []).append(
                    f"high-frequency velocity chatter above {cutoff_hz:g} Hz"
                )

        return DynamicsSuiteResult(
            checks=checks,
            excluded=excluded,
            evidence=evidence,
            summary={
                "actuator_chatter": {
                    "enabled": True,
                    "evaluated_signals": evaluated_signals,
                    "max_power_ratio": float(ratio_limit),
                    "min_frequency_hz": (float(min_frequency) if min_frequency is not None else CHATTER_DEFAULT_MIN_FREQUENCY_HZ),
                    "skipped_episodes": {k: v for k, v in skip_reasons.items() if v},
                }
            },
        )


class EnergyConservationSuite:
    """Flag kinetic-energy changes that no mechanical effort can explain.

    Enabled when ``energy_anomaly_factor`` (> 1) is present in ``conditions``.
    """

    name = "energy_conservation"

    def run(self, context) -> DynamicsSuiteResult:
        factor = context.conditions.get(ENERGY_FACTOR_KEY)
        if factor is None:
            return DynamicsSuiteResult(summary={"energy_conservation": {"enabled": False}})

        checks: list[dict[str, Any]] = []
        excluded: dict[int, list[str]] = {}
        evidence: list[dict[str, Any]] = []
        summary: dict[str, Any] = {"enabled": True, "evaluated_signals": 0}
        if not factor > 1:
            checks.append({
                "name": "robotics_energy:not_evaluated",
                "column": None,
                "status": "warning",
                "indices": [],
                "violations": 0,
                "detail": f"{ENERGY_FACTOR_KEY} must be greater than 1; the energy check was not run.",
                "low": None,
                "high": None,
            })
            summary["evaluated_signals"] = 0
            return DynamicsSuiteResult(checks=checks, summary={"energy_conservation": summary})

        rows = _normalized_rows(context.source_rows)
        time_key, _group_key, episodes = _episode_slices(rows)
        keys = set().union(*(row.keys() for row in rows)) if rows else set()

        for signal in _joint_velocity_signals(keys):
            prefix = signal[: -len("_velocity")]
            effort_signal = next(
                (name for name in (prefix + "_torque", prefix + "_effort") if name in keys),
                None,
            )
            if effort_signal is None:
                checks.append({
                    "name": f"robotics_energy:{prefix}",
                    "column": signal,
                    "status": "warning",
                    "indices": [],
                    "violations": 0,
                    "detail": (
                        f"Energy check was not evaluated because no '{prefix}_torque' or "
                        f"'{prefix}_effort' signal was found."
                    ),
                    "low": None,
                    "high": None,
                })
                continue

            velocities = _column_values(rows, signal)
            efforts = _column_values(rows, effort_signal)
            flagged: dict[int, dict[str, Any]] = {}
            evaluated_episodes = 0
            skipped = {"missing_time": 0, "too_few_samples": 0, "degenerate_fit": 0, "low_excitation": 0}
            for name, indices in episodes:
                if time_key is None:
                    skipped["missing_time"] += 1
                    continue
                times = _column_values(rows, time_key)[indices]
                v = velocities[indices]
                tau = efforts[indices]
                # Intervals stay inside one episode; the recorded effort and
                # both endpoint velocities must be finite.
                finite = (
                    np.isfinite(times[:-1]) & np.isfinite(times[1:])
                    & np.isfinite(v[:-1]) & np.isfinite(v[1:])
                    & np.isfinite(tau[:-1]) & np.isfinite(tau[1:])
                )
                finite &= np.diff(times) > 0
                if int(finite.sum()) < ENERGY_MIN_INTERVALS:
                    skipped["too_few_samples"] += 1
                    continue
                dt = np.diff(times)[finite]
                first_v, last_v = v[:-1][finite], v[1:][finite]
                first_tau, last_tau = tau[:-1][finite], tau[1:][finite]
                # Trapezoidal mechanical work and kinetic-energy change
                # (scaled by 2*I; the fit absorbs the unknown inertia).
                work = 0.5 * (first_tau * first_v + last_tau * last_v) * dt
                ke_change = last_v * last_v - first_v * first_v

                # Sliding 32-interval windows: a single episode-wide fit lets
                # a posture-dependent inertia shift absorb a local energy
                # injection into its slope, masking contact-solver explosions.
                n_intervals = len(work)
                episode_peak = float(np.max(np.abs(ke_change)))
                if n_intervals >= ENERGY_WINDOW:
                    starts = list(range(0, n_intervals - ENERGY_WINDOW + 1, ENERGY_WINDOW_STRIDE))
                    if starts[-1] != n_intervals - ENERGY_WINDOW:
                        starts.append(n_intervals - ENERGY_WINDOW)
                    windows = [(start, start + ENERGY_WINDOW) for start in starts]
                else:
                    windows = [(0, n_intervals)]
                magnitude_floor = ENERGY_RESIDUAL_FLOOR * episode_peak

                episode_evaluated = False
                for start, end in windows:
                    w_work = work[start:end]
                    w_ke = ke_change[start:end]
                    # Low-excitation guard: with (near-)constant kinetic energy
                    # the regression has nothing to explain — reporting a pass
                    # here would be a silent false negative.
                    peak = float(np.max(np.abs(w_ke)))
                    if peak <= 0.0 or float(np.var(w_ke)) < ENERGY_EXCITATION_EPS * peak * peak:
                        skipped["low_excitation"] += 1
                        continue
                    design = np.column_stack((w_work, np.ones_like(w_work)))
                    try:
                        coefficients, _residuals, rank, _singular = np.linalg.lstsq(
                            design, w_ke, rcond=None
                        )
                    except np.linalg.LinAlgError:
                        skipped["degenerate_fit"] += 1
                        continue
                    if rank < 2:
                        skipped["degenerate_fit"] += 1
                        continue
                    residual = w_ke - design @ coefficients
                    center = float(np.median(residual))
                    scale = 1.4826 * float(np.median(np.abs(residual - center)))
                    floor = 1e-12 + 1e-9 * peak
                    scale = max(scale, floor)
                    bad = (np.abs(residual) > factor * scale) & (np.abs(residual) >= magnitude_floor)
                    if bad.any():
                        interval_ends = np.flatnonzero(finite)[start:end][bad] + 1
                        for end_index, residual_value in zip(interval_ends, residual[bad], strict=True):
                            index = indices[end_index]
                            score = float(residual_value) / scale
                            previous = flagged.get(index)
                            if previous is None or abs(score) > abs(previous["observed"]):
                                flagged[index] = _finding(
                                    f"robotics_energy:{prefix}", signal, name, index,
                                    float(times[end_index]), score, [-float(factor), float(factor)],
                                    "Work and kinetic-energy change disagree in this interval.",
                                    "×", "Normalized energy residual",
                                    interval_start=float(times[end_index - 1]),
                                )
                    episode_evaluated = True
                if episode_evaluated:
                    evaluated_episodes += 1

            if evaluated_episodes == 0:
                reasons = ", ".join(f"{reason}: {count}" for reason, count in skipped.items() if count)
                checks.append({
                    "name": f"robotics_energy:{prefix}",
                    "column": signal,
                    "status": "warning",
                    "indices": [],
                    "violations": 0,
                    "detail": f"Energy check was not evaluated for any episode ({reasons}).",
                    "low": None,
                    "high": None,
                })
                continue
            summary["evaluated_signals"] += 1
            unique = sorted(flagged)
            evidence.extend(flagged[index] for index in unique)
            status = "failed" if unique else "passed"
            detail = (
                f"{len(unique)} interval(s): kinetic-energy change deviates from the episode's "
                f"work/energy relationship by more than {factor:g}x the robust residual scale."
                if unique
                else f"All intervals agree with the episode's work/energy relationship within {factor:g}x the robust residual scale."
            )
            checks.append({
                "name": f"robotics_energy:{prefix}",
                "column": signal,
                "status": status,
                "indices": unique,
                "violations": len(unique),
                "detail": detail,
                "low": None,
                "high": None,
            })
            for index in unique:
                excluded.setdefault(index, []).append(
                    "kinetic-energy change not explained by recorded effort"
                )

        summary["anomaly_factor"] = float(factor)
        return DynamicsSuiteResult(checks=checks, excluded=excluded, evidence=evidence,
                                   summary={"energy_conservation": summary})


class HumanoidContactSuite:
    """Opt-in contact and stream-synchronization checks for legged systems.

    Enabled when ``max_foot_slip_ms``, ``max_sync_skew_ms`` (or
    ``min_foot_contact_force_n``) is present in ``conditions``.

    * Foot-contact slip: a foot reporting contact force above
      ``min_foot_contact_force_n`` (default 1 N) is bearing load; if its
      horizontal linear velocity then exceeds ``max_foot_slip_mps`` (m/s), the
      contact solver is letting the support foot slide — the classic
      sim-only failure that transfers badly to hardware.
    * Camera/joint timestamp skew: per-sample ``|t_cam - t_joint|`` beyond
      ``max_sync_skew_ms`` flags misaligned sensor streams, which silently
      poison visuo-motor training pairs.

    Fail-closed: requested but unmeasurable (no foot signals, no timestamp
    columns) emits a ``warning`` explaining why instead of a pass.
    """

    name = "humanoid_contact"

    def run(self, context) -> DynamicsSuiteResult:
        conditions = context.conditions
        max_slip = conditions.get(FOOT_SLIP_KEY, conditions.get(LEGACY_FOOT_SLIP_KEY))
        force_threshold = conditions.get(FOOT_FORCE_KEY, DEFAULT_FOOT_CONTACT_FORCE_N)
        max_skew_ms = conditions.get(SYNC_SKEW_KEY)
        if max_slip is None and max_skew_ms is None and FOOT_FORCE_KEY not in conditions:
            return DynamicsSuiteResult(summary={"humanoid_contact": {"enabled": False}})

        checks: list[dict[str, Any]] = []
        excluded: dict[int, list[str]] = {}
        summary: dict[str, Any] = {"enabled": True}
        evidence: list[dict[str, Any]] = []
        rows = _normalized_rows(context.source_rows)
        time_key, _group_key, episodes = _episode_slices(rows)
        episode_by_index = {index: name for name, indices in episodes for index in indices}
        keys = set().union(*(row.keys() for row in rows)) if rows else set()

        if max_slip is None and max_skew_ms is None and FOOT_FORCE_KEY in conditions:
            checks.append({
                "name": "robotics_foot_slip:not_evaluated",
                "column": None,
                "status": "warning",
                "indices": [],
                "violations": 0,
                "detail": f"{FOOT_FORCE_KEY} sets the contact threshold; also set {FOOT_SLIP_KEY} to run foot-slip checking.",
                "low": None,
                "high": None,
            })

        if max_slip is not None:
            slip_value = float(max_slip)
            if not np.isfinite(slip_value) or slip_value < 0:
                checks.append({
                    "name": "robotics_foot_slip:not_evaluated",
                    "column": None, "status": "warning", "indices": [], "violations": 0,
                    "detail": f"{FOOT_SLIP_KEY} must be a non-negative speed in m/s; the foot-slip check was not run.",
                    "low": None, "high": None,
                })
            else:
                feet = sorted({
                    key[: -len(FOOT_FORCE_SUFFIX)].rstrip("_")
                    for key in keys
                    if key.endswith(FOOT_FORCE_SUFFIX) and "foot" in key
                })
                if not feet:
                    checks.append({
                        "name": "robotics_foot_slip:not_evaluated",
                        "column": None, "status": "warning", "indices": [], "violations": 0,
                        "detail": (
                            "Foot-slip checking was requested but no '*foot*contact_force_z' "
                            "signals were found."
                        ),
                        "low": None, "high": float(slip_value),
                    })
                else:
                    threshold = float(force_threshold)
                    if not np.isfinite(threshold) or threshold < 0:
                        checks.append({
                            "name": "robotics_foot_slip:not_evaluated",
                            "column": None, "status": "warning", "indices": [], "violations": 0,
                            "detail": f"{FOOT_FORCE_KEY} must be a finite non-negative force in newtons.",
                            "low": None, "high": slip_value,
                        })
                        return DynamicsSuiteResult(
                            checks=checks,
                            summary={"humanoid_contact": summary},
                        )
                    summary["foot_slip"] = {"max_slip_mps": slip_value, "contact_force_n": threshold}
                    for foot in feet:
                        force_key = f"{foot}_{FOOT_FORCE_SUFFIX}"
                        vx_key = f"{foot}_{FOOT_VELOCITY_SUFFIXES[0]}"
                        vy_key = f"{foot}_{FOOT_VELOCITY_SUFFIXES[1]}"
                        if vx_key not in keys or vy_key not in keys:
                            checks.append({
                                "name": f"robotics_foot_slip:not_evaluated:{foot}",
                                "column": force_key,
                                "status": "warning",
                                "indices": [],
                                "violations": 0,
                                "detail": (
                                    f"Foot-slip checking for {foot} needs both {vx_key} and {vy_key}."
                                ),
                                "low": 0.0,
                                "high": slip_value,
                            })
                            continue
                        force = _column_values(rows, force_key)
                        vx = _column_values(rows, vx_key)
                        vy = _column_values(rows, vy_key)
                        usable = np.isfinite(force) & np.isfinite(vx) & np.isfinite(vy)
                        in_contact = usable & (force > threshold)
                        speed = np.sqrt(vx * vx + vy * vy)
                        bad = np.flatnonzero(in_contact & (speed > slip_value))
                        missing = int((~usable).sum())
                        status = "failed" if len(bad) else "warning" if missing else "passed"
                        checks.append({
                            "name": f"robotics_foot_slip:{foot}",
                            "column": f"{foot}_{FOOT_FORCE_SUFFIX}",
                            "status": status,
                            "low": 0.0,
                            "high": slip_value,
                            "indices": [int(i) for i in bad],
                            "violations": int(len(bad)),
                            "detail": (
                                f"{len(bad)} sample(s) report contact force above {threshold:g} N while "
                                f"{foot} slides faster than {slip_value:g} m/s."
                                if len(bad)
                                else f"Foot-slip checking for {foot} could not evaluate {missing} sample(s)."
                                if missing
                                else f"No loaded {foot} sample slides faster than {slip_value:g} m/s."
                            ),
                        })
                        for index in map(int, bad):
                            detail = f"{foot} in contact but sliding above {slip_value:g} m/s"
                            excluded.setdefault(index, []).append(detail)
                            evidence.append(_finding(
                                f"robotics_foot_slip:{foot}", vx_key, episode_by_index[index], index,
                                number(rows[index].get(time_key)) if time_key else None,
                                float(speed[index]), [0.0, slip_value], detail,
                                "m/s", "Horizontal foot speed",
                            ))

        if max_skew_ms is not None:
            skew_ms = float(max_skew_ms)
            cam_key = next((key for key in CAMERA_TIME_KEYS if key in keys), None)
            joint_key = next((key for key in JOINT_TIME_KEYS if key in keys), None)
            if not np.isfinite(skew_ms) or skew_ms < 0:
                checks.append({
                    "name": "robotics_stream_skew:not_evaluated",
                    "column": None, "status": "warning", "indices": [], "violations": 0,
                    "detail": f"{SYNC_SKEW_KEY} must be a non-negative duration in milliseconds.",
                    "low": None, "high": None,
                })
            elif cam_key is None or joint_key is None:
                checks.append({
                    "name": "robotics_stream_skew:not_evaluated",
                    "column": None, "status": "warning", "indices": [], "violations": 0,
                    "detail": (
                        "Timestamp-skew checking was requested but camera and joint timestamp "
                        "columns (t_cam/camera_time and t_joint/joint_time) are both required."
                    ),
                    "low": None, "high": skew_ms,
                })
            else:
                cam = _column_values(rows, cam_key)
                joint = _column_values(rows, joint_key)
                n = min(len(cam), len(joint))
                both = np.isfinite(cam[:n]) & np.isfinite(joint[:n])
                skew = np.abs(cam[:n] - joint[:n]) * 1000.0  # seconds -> milliseconds
                bad = np.flatnonzero(both & (skew > skew_ms))
                summary["stream_skew"] = {"max_sync_skew_ms": skew_ms}
                checks.append({
                    "name": "robotics_stream_skew:camera_joint",
                    "column": cam_key,
                    "status": "failed" if len(bad) else "passed",
                    "low": 0.0,
                    "high": skew_ms,
                    "indices": [int(i) for i in bad],
                    "violations": int(len(bad)),
                    "detail": (
                        f"{len(bad)} sample(s) exceed {skew_ms:g} ms of camera/joint timestamp skew."
                        if len(bad)
                        else f"All samples keep camera/joint timestamp skew within {skew_ms:g} ms."
                    ),
                })
                for index in map(int, bad):
                    detail = f"camera/joint timestamp skew above {skew_ms:g} ms"
                    excluded.setdefault(index, []).append(detail)
                    evidence.append(_finding(
                        "robotics_stream_skew:camera_joint", cam_key, episode_by_index[index], index,
                        number(rows[index].get(time_key)) if time_key else float(cam[index]),
                        float(skew[index]), [0.0, skew_ms], detail,
                        "ms", "Camera / joint timestamp skew",
                    ))

        return DynamicsSuiteResult(checks=checks, excluded=excluded, evidence=evidence,
                                   summary={"humanoid_contact": summary})
