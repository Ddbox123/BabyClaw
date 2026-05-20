import { describe, expect, it } from "vitest";

import { ConversationMessage } from "../../api/types";
import {
  hasMentalBlock,
  hasResponseBlock,
  hasThoughtBlock,
  hasToolBlock,
  hasUserContent,
} from "./messageSections";

function message(overrides: Partial<ConversationMessage>): ConversationMessage {
  return {
    id: "msg",
    role: "user",
    content: "",
    timestamp: "2026-05-20T14:12:39",
    ...overrides,
  };
}

describe("messageSections", () => {
  it("shows operator text as direct message content", () => {
    const userMessage = message({
      role: "user",
      content: "你知道你上文说了什么吗",
    });

    expect(hasUserContent(userMessage)).toBe(true);
    expect(hasResponseBlock(userMessage)).toBe(false);
  });

  it("keeps assistant content in the response block", () => {
    const assistantMessage = message({
      role: "assistant",
      content: "我会先检查日志。",
    });

    expect(hasUserContent(assistantMessage)).toBe(false);
    expect(hasResponseBlock(assistantMessage)).toBe(true);
  });

  it("keeps assistant-only diagnostic sections scoped away from operator messages", () => {
    const userMessage = message({
      role: "user",
      content: "继续",
      thought: "hidden",
      mentalSnapshot: {
        mood: "open",
        feeling: "",
        whisper: "",
        summary: "",
        cognitiveState: "",
        confidence: 0,
        sampleSize: 0,
        interventionCount: 0,
        updatedAt: "",
        source: "",
      },
      toolCalls: [{ name: "rg", status: "completed" }],
    });

    expect(hasThoughtBlock(userMessage)).toBe(false);
    expect(hasMentalBlock(userMessage)).toBe(false);
    expect(hasToolBlock(userMessage)).toBe(false);
  });
});
