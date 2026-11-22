export const STAGE_STATUSES = ["pass", "fail", "not-run"] as const;

export type StageStatus = (typeof STAGE_STATUSES)[number];

export interface Tally {
  passed: number;
  total: number;
}

export function isStageStatus(value: unknown): value is StageStatus {
  return STAGE_STATUSES.some((status) => status === value);
}

export function tally(statuses: readonly StageStatus[]): Tally {
  return {
    passed: statuses.filter((status) => status === "pass").length,
    total: statuses.length,
  };
}
