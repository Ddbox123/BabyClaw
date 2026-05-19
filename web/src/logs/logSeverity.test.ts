import { describe, expect, it } from "vitest";

import { classifyLogText, classifyRuntimeSceneEvent, matchesSeverityFilter } from "./logSeverity";

describe("logSeverity", () => {
  it("classifies error-oriented log lines", () => {
    expect(classifyLogText("ERROR Failed to connect")).toBe("error");
    expect(classifyLogText("Traceback (most recent call last):")).toBe("error");
    expect(classifyLogText("SEVERE browser crashed")).toBe("error");
  });

  it("classifies warning-oriented log lines", () => {
    expect(classifyLogText("WARNING config is deprecated")).toBe("warning");
    expect(classifyLogText("retrying backend probe")).toBe("warning");
  });

  it("prioritizes error over warning when both appear", () => {
    expect(classifyLogText("warning escalated to error")).toBe("error");
  });

  it("classifies runtime scene events from level or message", () => {
    expect(
      classifyRuntimeSceneEvent({
        runtimeSceneId: "run-1",
        component: "browser",
        phase: "console",
        eventCode: "browser.console.warn",
        level: "warning",
        message: "Console warning",
        timestamp: "2025-01-01T00:00:00Z",
        seq: 1,
        outcome: "",
        fields: {},
        rawRefs: [],
      }),
    ).toBe("warning");

    expect(
      classifyRuntimeSceneEvent({
        runtimeSceneId: "run-2",
        component: "backend",
        phase: "startup",
        eventCode: "backend.stderr",
        level: "",
        message: "Unhandled promise rejection",
        timestamp: "2025-01-01T00:00:00Z",
        seq: 2,
        outcome: "",
        fields: {},
        rawRefs: [],
      }),
    ).toBe("error");
  });

  it("matches the selected severity filter", () => {
    expect(matchesSeverityFilter("error", "all")).toBe(true);
    expect(matchesSeverityFilter("error", "error")).toBe(true);
    expect(matchesSeverityFilter("warning", "error")).toBe(false);
  });
});
