import { NextResponse } from "next/server";
import { canonical, roboticsEvidenceLimits, type SimulationType } from "@/lib/validation-engine";
import { buildEvidence } from "@/lib/robotics-workflow.js";
import { richValidate } from "@/lib/rich-validate";
import { aiReview, type AiReview } from "@/lib/ai-review";
import { validateFtcLog, type FtcLimits } from "@/lib/ftc-frc.js";

/**
 * POST /api/v1/validate
 *
 * Free public validation endpoint. Runs the deterministic engine on the server
 * (same code the browser uses) and returns the full report shape the dashboard
 * and SDKs consume, plus an optional AI second pass (OPENROUTER_API_KEY).
 */
export const runtime = "nodejs";
export const maxDuration = 60;

interface ValidateBody {
  data?: Record<string, unknown>[];
  simulation_type?: SimulationType;
  conditions?: Record<string, number>;
  robotics_limits?: Record<string, [number, number]>;
  robotics_profile?: string;
  ftc_limits?: Record<string, number | [number, number]>;
  units?: Record<string, string>;
  run_ai?: boolean;
  job_id?: string;
}

function errorBody(code: string, message: string, requestId: string) {
  return { error: { code, message, request_id: requestId } };
}

/** Map the compact AI review into the dashboard's richer AIResult shape. */
function mapAi(review: AiReview): Record<string, unknown> | null {
  if (!review.enabled) return null;

  const concerns = review.concerns ?? [];
  const summary = review.assessment ?? "";
  const recs = review.recommendation ? [review.recommendation] : [];

  // Degraded path: the model failed, but we still surface the physics engine's
  // own finding (ai-review.ts populates `assessment` as a fallback) so the
  // panel is never empty and never blank-with-an-error.
  if (review.error) {
    return {
      status: summary ? "completed" : "error",
      verdict: review.verdict ?? "",
      model: review.model ?? "",
      processing_ms: 0,
      anomaly_score: summary ? 0.42 : 0,
      dataset_summary: summary,
      physics_agreement: "",
      physics_gaps: "",
      findings: summary
        ? [{
            severity: "warning",
            category: "physics_engine",
            title: "Physics engine finding",
            detail: summary,
            trials: [],
            confidence: 0.9,
            source: "physics_engine",
          }]
        : [],
      recommendations: recs,
      timed_out: false,
      error: review.error,
      review_version: review.reviewVersion ?? "",
    };
  }

  const anomaly = review.status === "agree" ? 0.12 : review.status === "concern" ? 0.42 : 0.78;

  return {
    status: "completed",
    verdict: review.verdict ?? "",
    model: review.model ?? "",
    processing_ms: 0,
    anomaly_score: anomaly,
    dataset_summary: summary,
    physics_agreement:
      review.status === "agree"
        ? "Confirms the deterministic findings — no additional physical inconsistencies detected."
        : "",
    // Intentionally NOT a copy of dataset_summary — leaving it empty prevents
    // the same sentence rendering four times in the panel.
    physics_gaps: "",
    findings:
      review.status === "agree"
        ? []
        : [{
            severity: "warning",
            category: "physics_engine",
            title: "Root-cause explanation",
            detail: summary,
            trials: [],
            confidence: 0.8,
            source: "physics_engine",
          }],
    recommendations: recs,
    timed_out: false,
    error: null,
    review_version: review.reviewVersion ?? "",
  };
}

/** Strongest pairwise Pearson correlations among numeric columns (for the AI profile). */
function topCorrelations(rows: Record<string, unknown>[]): { pair: string; r: number }[] {
  if (rows.length < 5) return [];
  const cols: Record<string, number[]> = {};
  for (const row of rows) for (const [k, v] of Object.entries(row)) {
    if (typeof v === "number" && Number.isFinite(v)) (cols[k] ??= []).push(v);
  }
  const names = Object.keys(cols).filter((k) => cols[k].length === rows.length);
  const out: { pair: string; r: number }[] = [];
  for (let i = 0; i < names.length; i++)
    for (let j = i + 1; j < names.length; j++) {
      const r = pearson(cols[names[i]], cols[names[j]]);
      if (Number.isFinite(r) && Math.abs(r) > 0.3) out.push({ pair: `${names[i]}~${names[j]}`, r: Math.round(r * 100) / 100 });
    }
  return out.sort((a, b) => Math.abs(b.r) - Math.abs(a.r)).slice(0, 6);
}
function pearson(a: number[], b: number[]): number {
  const n = a.length, ma = a.reduce((x, y) => x + y, 0) / n, mb = b.reduce((x, y) => x + y, 0) / n;
  let num = 0, da = 0, db = 0;
  for (let i = 0; i < n; i++) { const x = a[i] - ma, y = b[i] - mb; num += x * y; da += x * x; db += y * y; }
  return da && db ? num / Math.sqrt(da * db) : NaN;
}

function mapFtcReport(report: ReturnType<typeof validateFtcLog>, rows: Record<string, unknown>[], jobId: string) {
  const failed = report.failed_checks.map((check) => ({
    name: `ftc_frc:${check.name}`,
    human_name: check.name.replaceAll("_", " "),
    status: "failed" as const,
    description: `FTC/FRC check ${check.name}`,
    detail: check.detail,
    value: null,
    category: "ftc_frc",
  }));
  const warned = report.warnings.map((check) => ({
    name: `ftc_frc:${check.name}`,
    human_name: check.name.replaceAll("_", " "),
    status: "warning" as const,
    description: `FTC/FRC check ${check.name}`,
    detail: check.detail,
    value: null,
    category: "ftc_frc",
  }));
  const issues = [...failed, ...warned];
  const exclusions = Object.entries(report.excluded_rows).map(([rawIndex, reasons]) => {
    const trial_index = Number(rawIndex);
    return { trial_index, trial_number: trial_index + 1, reason: reasons.join("; "), severity: "critical" };
  });
  const excluded = exclusions.length;
  const warnings = warned.length;
  const failedCount = failed.length;
  const status = failedCount ? "failed" : warnings ? "warning" : "passed";
  const allChecks = Math.max(1, issues.length);
  const roboticsChecks = issues.map((issue) => ({
    name: issue.name,
    column: issue.name.slice("ftc_frc:".length),
    status: issue.status,
    detail: issue.detail,
    violations: 1,
  }));
  const timeColumn = ["time", "t", "timestamp", "elapsed_time"].find((key) => rows.some((row) => key in row)) ?? null;
  const episodeColumn = ["episode_id", "episode", "match", "segment"].find((key) => rows.some((row) => key in row)) ?? null;
  return {
    job_id: jobId,
    status,
    confidence: failedCount ? "low" : warnings ? "medium" : "high",
    plain_summary: failedCount
      ? `FTC/FRC validation found ${failedCount} failing check(s) across ${rows.length} samples.`
      : warnings
        ? `FTC/FRC validation found ${warnings} warning(s) across ${rows.length} samples.`
        : `All ${rows.length} samples passed the FTC/FRC checks.`,
    trials_submitted: rows.length,
    trials_valid: Math.max(0, rows.length - excluded),
    trials_excluded: excluded,
    exclusion_rate: rows.length ? excluded / rows.length : 0,
    training_ready: failedCount === 0 && excluded === 0,
    processing_ms: 0,
    all_checks: allChecks,
    unique_checks: allChecks,
    passed: allChecks - failedCount - warnings,
    warnings,
    failed: failedCount,
    informational: 0,
    issues,
    physics_checks: issues,
    exclusions,
    statistics: {},
    checks_by_category: { ftc_frc: { passed: allChecks - failedCount - warnings, warning: warnings, failed: failedCount } },
    columns_renamed: {},
    robotics_checks: roboticsChecks,
    robotics_summary: {
      engine_version: "ftc-frc-1",
      episodes: report.episodes,
      time_column: timeColumn,
      episode_column: episodeColumn,
      assumptions: ["Motor power is bounded to the configured range.", "Heading wraps through +/-180 degrees before jump checks."],
      profile: "FTC / FRC",
      ftc_summary: report.summary,
    },
  };
}

export async function POST(req: Request) {
  const requestId = crypto.randomUUID().replace(/-/g, "").slice(0, 12);

  let body: ValidateBody;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json(errorBody("validation_failed", "Request body is not valid JSON.", requestId), { status: 422 });
  }

  const simType = (body.simulation_type ?? "aerodynamics") as SimulationType;
  if (body.robotics_profile?.toLowerCase() === "frc") body.robotics_profile = "ftc";
  const rows = Array.isArray(body.data) ? body.data : [];
  if (rows.length === 0) {
    return NextResponse.json(errorBody("bad_request", "`data` must be a non-empty array of trial records.", requestId), { status: 400 });
  }
  if (rows.some((row) => !row || typeof row !== "object" || Array.isArray(row))) {
    return NextResponse.json(errorBody("bad_request", "Each sample must be an object with named signals.", requestId), { status: 400 });
  }
  if (body.conditions !== undefined && (!body.conditions || typeof body.conditions !== "object" || Array.isArray(body.conditions) || Object.values(body.conditions).some((value) => typeof value !== "number" || !Number.isFinite(value)))) {
    return NextResponse.json(errorBody("bad_request", "conditions must be a map of finite numeric values.", requestId), { status: 400 });
  }
  if (rows.length > 10000) {
    return NextResponse.json(errorBody("payload_too_large", "Maximum 10,000 trials per request.", requestId), { status: 413 });
  }
  if (body.robotics_profile !== undefined && !["robotics", "ftc"].includes(body.robotics_profile)) {
    return NextResponse.json(errorBody("bad_request", "robotics_profile must be 'robotics' or 'ftc'.", requestId), { status: 400 });
  }
  if (body.robotics_profile === "ftc" && simType !== "robotics") {
    return NextResponse.json(errorBody("bad_request", "The FTC/FRC profile requires simulation_type 'robotics'.", requestId), { status: 400 });
  }
  if (body.ftc_limits !== undefined) {
    const known = new Set(["motor_power", "battery_voltage", "battery_sag_voltage", "sag_min_total_power", "velocity_tolerance", "min_moving_speed", "max_speed", "heading_jump_deg"]);
    const invalid = !body.ftc_limits || typeof body.ftc_limits !== "object" || Array.isArray(body.ftc_limits) || Object.entries(body.ftc_limits).some(([key, value]) => {
      if (!known.has(key)) return true;
      if (key === "motor_power" || key === "battery_voltage") return !Array.isArray(value) || value.length !== 2 || !value.every((n) => typeof n === "number" && Number.isFinite(n)) || value[0] >= value[1];
      return typeof value !== "number" || !Number.isFinite(value) || value < 0;
    });
    if (invalid) return NextResponse.json(errorBody("bad_request", "ftc_limits contains an invalid or unknown FTC/FRC limit.", requestId), { status: 400 });
  }
  if (body.units !== undefined && (!body.units || typeof body.units !== "object" || Array.isArray(body.units) || Object.values(body.units).some((unit) => typeof unit !== "string"))) {
    return NextResponse.json(errorBody("bad_request", "units must map signal names to unit strings.", requestId), { status: 400 });
  }
  if (body.robotics_limits !== undefined) {
    if (simType !== "robotics" || !body.robotics_limits || typeof body.robotics_limits !== "object" || Array.isArray(body.robotics_limits)) {
      return NextResponse.json(errorBody("bad_request", "`robotics_limits` requires simulation_type `robotics` and a map of signal names to [min, max] pairs.", requestId), { status: 400 });
    }
    const invalid = Object.entries(body.robotics_limits).some(([signal, range]) =>
      !signal.trim() || !Array.isArray(range) || range.length !== 2 ||
      !range.every((value) => typeof value === "number" && Number.isFinite(value)) ||
      !(range[0] < range[1]),
    );
    if (invalid) {
      return NextResponse.json(errorBody("bad_request", "Each `robotics_limits` entry must be a finite [min, max] range with min < max.", requestId), { status: 400 });
    }
  }

  for (const key of ["max_time_step", "velocity_tolerance", "acceleration_tolerance"]) {
    const value = body.conditions?.[key];
    if (value !== undefined && (typeof value !== "number" || !Number.isFinite(value) || value <= 0)) {
      return NextResponse.json(errorBody("bad_request", `${key} must be a finite positive number.`, requestId), { status: 400 });
    }
  }

  const PYTHON_API = process.env.PYTHON_API_URL;
  let result;
  let engineSource: "python" | "typescript" = "typescript";

  if (PYTHON_API) {
    try {
      const upstream = await fetch(`${PYTHON_API}/v1/validate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          data: rows,
          simulation_type: simType,
          conditions: body.conditions ?? {},
          robotics_limits: body.robotics_limits ?? {},
          ...(body.robotics_profile ? { robotics_profile: body.robotics_profile } : {}),
          ...(body.ftc_limits ? { ftc_limits: body.ftc_limits } : {}),
          ...(body.units ? { units: body.units } : {}),
          run_ai: body.run_ai ?? true,
        }),
        signal: AbortSignal.timeout(35_000),
      });
      if (upstream.ok) {
        const pyResult = await upstream.json();
        engineSource = "python";
        result = {
          job_id: requestId.slice(0, 8),
          status: pyResult.status ?? "passed",
          confidence: pyResult.confidence ?? "high",
          trials_submitted: pyResult.trials_submitted ?? rows.length,
          trials_valid: pyResult.trials_valid ?? rows.length,
          trials_excluded: pyResult.trials_excluded ?? 0,
          exclusion_rate: pyResult.exclusion_rate ?? 0,
          training_ready: pyResult.training_ready ?? true,
          processing_ms: pyResult.processing_ms ?? 0,
          all_checks: pyResult.all_checks ?? 0,
          unique_checks: pyResult.all_checks ?? 0,
          passed: pyResult.passed ?? 0,
          warnings: pyResult.warnings ?? 0,
          failed: pyResult.failed ?? 0,
          informational: pyResult.informational ?? 0,
          issues: (pyResult.issues ?? []).map((i: Record<string, unknown>) => ({
            name: i.name, human_name: i.description, status: i.status,
            description: i.detail ?? i.description, detail: i.detail ?? "",
            value: i.value, category: i.category,
          })),
          exclusions: (pyResult.exclusions ?? []).map((e: Record<string, unknown>) => ({
            trial_number: (e.trial_index as number) + 1, trial_index: e.trial_index,
            reason: e.reason, severity: e.severity,
          })),
          statistics: pyResult.statistics ?? {},
          checks_by_category: pyResult.checks_by_category ?? {},
          columns_renamed: {},
          robotics_checks: pyResult.robotics_checks,
          robotics_summary: pyResult.robotics_summary,
        };
      } else {
        result = body.robotics_profile === "ftc"
          ? mapFtcReport(validateFtcLog(rows, (body.ftc_limits ?? {}) as Partial<FtcLimits>), rows, requestId.slice(0, 8))
          : richValidate(rows, simType, requestId.slice(0, 8), body.robotics_limits, body.conditions);
      }
    } catch {
      result = body.robotics_profile === "ftc"
        ? mapFtcReport(validateFtcLog(rows, (body.ftc_limits ?? {}) as Partial<FtcLimits>), rows, requestId.slice(0, 8))
        : richValidate(rows, simType, requestId.slice(0, 8), body.robotics_limits, body.conditions);
    }
  } else {
    result = body.robotics_profile === "ftc"
      ? mapFtcReport(validateFtcLog(rows, (body.ftc_limits ?? {}) as Partial<FtcLimits>), rows, requestId.slice(0, 8))
      : richValidate(rows, simType, requestId.slice(0, 8), body.robotics_limits, body.conditions);
  }

  const excludedIdx = new Set(result.exclusions.map((e: { trial_index: number }) => e.trial_index));
  const profile = {
    trials_submitted: result.trials_submitted,
    trials_excluded: result.trials_excluded,
    statistics: result.statistics,
    correlations: topCorrelations(rows),
    sample_rows: rows.slice(0, 4),
    violating_rows: rows.filter((_, i) => excludedIdx.has(i)).slice(0, 4),
  };

 const failedIssues = result.issues.filter((i: { status: string }) => i.status === "failed");

 const review =
    body.run_ai === false
      ? ({ enabled: false } as AiReview)
      : await aiReview(
          {
            status: result.status,
            score: result.status === "passed" ? 100 : result.status === "warning" ? 70 : 35,
            violations: failedIssues.map((i: { name: string; detail: string; value?: unknown }) => ({
              field: i.name,
              value: i.value != null ? String(i.value) : "",
              reason: i.detail || "",
              severity: "critical" as const,
            })),
            recommendations: result.exclusions
              .slice(0, 6)
              .map((e: { trial_number: number; reason: string }) => `Trial ${e.trial_number}: ${e.reason}`),
            simulationType: simType,
            checks: failedIssues.map((i: { name: string; detail: string; category?: string }) => ({
              name: i.name,
              category: i.category ?? "physics",
              status: "failed" as const,
              detail: i.detail || "",
            })),
          },
          body.conditions ?? {},
          profile,
        );

  const evidence = simType === "robotics" ? buildEvidence(
    rows.map((row) => Object.fromEntries(Object.entries(row).map(([key, value]) => [canonical(key), value]))),
    result.robotics_checks ?? [], roboticsEvidenceLimits(rows, body.robotics_limits), body.conditions ?? {},
  ) : null;
  return NextResponse.json(
    {
      ...result,
      validation_context: { simulation_type: simType, robotics_limits: body.robotics_limits ?? {}, conditions: body.conditions ?? {}, ...(body.robotics_profile ? { robotics_profile: body.robotics_profile } : {}), ...(body.ftc_limits ? { ftc_limits: body.ftc_limits } : {}), ...(body.units ? { units: body.units } : {}) },
      ...(evidence ? { robotics_evidence: evidence.entries, robotics_evidence_total: evidence.total, robotics_evidence_truncated: evidence.truncated } : {}),
      engine: body.robotics_profile === "ftc"
        ? (engineSource === "python" ? "python-ftc-frc-1" : "typescript-ftc-frc-1")
        : engineSource === "python" ? "python-dimensional" : simType === "robotics" ? "typescript-manipulation-2" : "typescript-20-checks",
      python_backend: engineSource === "python",
      ai: mapAi(review),
      ai_status: review.enabled ? (review.error ? "error" : "completed") : "disabled",
      ai_running: false,
      request_id: requestId,
    },
    { headers: { "X-Request-ID": requestId } },
  );
}
