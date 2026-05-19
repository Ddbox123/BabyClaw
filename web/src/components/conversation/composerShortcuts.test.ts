import { describe, expect, it } from "vitest";

import { shouldSubmitComposerOnKeydown } from "./composerShortcuts";

describe("composerShortcuts", () => {
  it("submits on plain Enter", () => {
    expect(
      shouldSubmitComposerOnKeydown({
        key: "Enter",
        shiftKey: false,
        ctrlKey: false,
        metaKey: false,
        altKey: false,
        isComposing: false,
      }),
    ).toBe(true);
  });

  it("keeps Shift+Enter for line breaks", () => {
    expect(
      shouldSubmitComposerOnKeydown({
        key: "Enter",
        shiftKey: true,
        ctrlKey: false,
        metaKey: false,
        altKey: false,
        isComposing: false,
      }),
    ).toBe(false);
  });

  it("does not submit during IME composition or on modifier shortcuts", () => {
    expect(
      shouldSubmitComposerOnKeydown({
        key: "Enter",
        shiftKey: false,
        ctrlKey: false,
        metaKey: false,
        altKey: false,
        isComposing: true,
      }),
    ).toBe(false);
    expect(
      shouldSubmitComposerOnKeydown({
        key: "Enter",
        shiftKey: false,
        ctrlKey: true,
        metaKey: false,
        altKey: false,
        isComposing: false,
      }),
    ).toBe(false);
  });
});
