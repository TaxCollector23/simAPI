export type FtcLimits = {
  motor_power: [number, number];
  battery_voltage: [number, number];
  battery_sag_voltage: number;
  sag_min_total_power: number;
  velocity_tolerance: number;
  min_moving_speed: number;
  max_speed: number;
  heading_jump_deg: number;
};
export const FTC_DEFAULT_LIMITS: Readonly<FtcLimits>;
export const FTC_PROFILE: Readonly<{
  schema_version: number;
  name: string;
  robotics_profile: "ftc";
  robotics_limits: Readonly<Record<string, [number, number]>>;
  ftc_limits: Readonly<FtcLimits>;
  conditions: Readonly<Record<string, number>>;
}>;
export function resolveFtcProfile(name: string): typeof FTC_PROFILE | null;
export function normalizeFtcRows(rows: Record<string, unknown>[]): Record<string, unknown>[];
export function validateFtcLog(rows: Record<string, unknown>[], limits?: Partial<FtcLimits>): {
  verdict: "passed" | "failed";
  failed_checks: { name: string; detail: string }[];
  warnings: { name: string; detail: string }[];
  excluded_rows: Record<string, string[]>;
  episodes: { episode_id: string; samples: number; flagged_samples: number }[];
  summary: { rows: number; flagged_rows?: number; median_dt_seconds?: number | null };
};
