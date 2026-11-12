export type Row = Record<string, unknown>;
export interface Profile {
  schema_version: number;
  name: string;
  robotics_profile?: "robotics" | "ftc";
  ftc_limits?: Record<string, number | [number, number]>;
  units?: Record<string, string>;
  robotics_limits: Record<string, [number, number]>;
  conditions: Record<string, number>;
  joints?: Record<string, { stem: string; type: string }>;
  units?: Record<string, string>;
  warnings?: string[];
  source?: string;
}
export interface Evidence {
  check: string;
  status: string;
  signal: string;
  episode_id: string;
  sample_index: number;
  time: number | null;
  observed: number | null;
  expected: [number, number] | null;
  detail: string;
}
export interface RepairPlan {
  proposals: {
    kind: string;
    description: string;
    affected_row_count: number;
    changes: { row: number; column: string; before: unknown; after: unknown }[];
    rows_dropped: number[];
  }[];
  unrepairable: { reason: string }[];
  repaired_data: Row[];
  original_samples: number;
  repaired_samples: number;
}
export interface ReportDiff {
  status_before: string;
  status_after: string;
  context_known: boolean;
  same_configuration: boolean | null;
  introduced: { name: string; before: string; after: string }[];
  resolved: { name: string; before: string; after: string }[];
  persisting: { name: string; before: string; after: string }[];
  episode_changes: {
    episode_id: string;
    before: { samples: number; flagged_samples: number } | null;
    after: { samples: number; flagged_samples: number } | null;
  }[];
  exclusion_delta: number;
  regressed: boolean;
}
export function normalize(name: string): string;
export function jointStem(name: string): string;
export function numeric(v: unknown): number | null;
export function rowKeys(rows: Row[]): {
  time: string | undefined;
  group: string | undefined;
};
export function episodeOf(row: Row, key?: string): string;
export function validateProfile(value: unknown): Profile;
export function parseCsv(source: string): Row[];
export function parseCsvDocument(source: string): {
  rows: Row[];
  sourceLines: number[];
};
export function inspectRows(rows: Row[]): {
  samples: number;
  time_column: string | null;
  episode_column: string | null;
  episodes: {
    episode_id: string;
    samples: number;
    duration_seconds: number | null;
  }[];
  signals: {
    name: string;
    numeric_samples: number;
    missing_or_nonnumeric: number;
    min: number | null;
    max: number | null;
  }[];
};
export function toCsv(rows: Row[]): string;
export function compareReports(before: unknown, after: unknown): ReportDiff;
export function repairPreview(rows: Row[]): RepairPlan;
export function buildEvidence(
  rows: Row[],
  checks?: {
    name: string;
    column: string;
    indices?: number[];
    detail: string;
  }[],
  limits?: Record<string, [number, number]>,
  conditions?: Record<string, number>,
): { entries: Evidence[]; total: number; truncated: boolean };
export function githubAnnotations(
  report: unknown,
  file: string,
  sourceLines?: number[],
): string[];
