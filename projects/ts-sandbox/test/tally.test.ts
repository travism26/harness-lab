import { describe, expect, it } from "vitest";
import { isStageStatus, tally } from "../src/tally.ts";

describe("tally", () => {
  it("counts an empty list", () => {
    expect(tally([])).toEqual({ passed: 0, total: 0 });
  });

  it("counts all passes", () => {
    expect(tally(["pass", "pass"])).toEqual({ passed: 2, total: 2 });
  });

  it("counts a mix", () => {
    expect(tally(["pass", "fail", "not-run"])).toEqual({ passed: 1, total: 3 });
  });
});

describe("isStageStatus", () => {
  it("accepts the three statuses", () => {
    for (const status of ["pass", "fail", "not-run"]) {
      expect(isStageStatus(status)).toBe(true);
    }
  });

  it("rejects anything else", () => {
    for (const value of ["", "PASS", "skipped", 1, null, undefined, {}, ["pass"]]) {
      expect(isStageStatus(value)).toBe(false);
    }
  });
});
