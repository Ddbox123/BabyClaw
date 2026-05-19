import { describe, expect, it } from "vitest";

import { clampPercent, contextUsagePercent, formatContextUsage, formatRelativeTime } from "./chatShellFormat";

describe("chatShellFormat", () => {
  it("formats context usage with exact numbers and percent", () => {
    expect(formatContextUsage(24_300, 128_000, "en-US")).toBe("24,300 / 128,000 (19%)");
    expect(formatContextUsage(6_302, 1_000_000, "zh-CN")).toBe("6,302 / 1,000,000 (1%)");
  });

  it("clamps percent values into a valid progress range", () => {
    expect(clampPercent(-8)).toBe(0);
    expect(clampPercent(52.6)).toBe(53);
    expect(clampPercent(120)).toBe(100);
  });

  it("derives context usage percent from the bounded token window", () => {
    expect(contextUsagePercent(450, 1_000)).toBe(45);
    expect(contextUsagePercent(1_400, 1_000)).toBe(100);
    expect(contextUsagePercent(450, 0)).toBe(0);
  });

  it("formats relative timestamps for recent and older updates", () => {
    const now = Date.UTC(2026, 4, 18, 12, 0, 0);
    expect(formatRelativeTime("2026-05-18T11:59:58Z", now, "en-US")).toBe("just now");
    expect(formatRelativeTime("2026-05-18T11:58:00Z", now, "en-US")).toBe("2 minutes ago");
    expect(formatRelativeTime("2026-05-18T10:00:00Z", now, "zh-CN")).toBe("2小时前");
  });
});
