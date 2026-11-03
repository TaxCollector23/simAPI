import type { Profile, Row } from "./robotics-workflow.js";
export function profileFromUrdf(xml: string, name?: string): Profile;
export function jointStateRow(
  message: Record<string, unknown>,
  logTime: number,
  episode?: string,
  profile?: Profile,
): Row;
export interface Recording {
  topics: {
    topic: string;
    schema: string;
    encoding: string;
    samples: number;
  }[];
  requires_topic: boolean;
  rows: Row[];
  source: string;
  topic?: string;
}
export function readRecording(
  bytes: Uint8Array,
  filename: string,
  options?: { topic?: string; episode?: string; profile?: Profile },
): Promise<Recording>;
