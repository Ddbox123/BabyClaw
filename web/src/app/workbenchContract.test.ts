import { describe, expect, it } from "vitest";

import { isWorkbenchDomainEnabled, isWorkbenchModeEnabled, resolveEvolutionHomePath, resolveWorkbenchHomePath } from "./workbenchContract";

describe("workbenchContract", () => {
  it("falls back to chat as the default home path before config loads", () => {
    expect(resolveWorkbenchHomePath()).toBe("/chat");
  });

  it("maps the legacy evolution home route to the default evolution mode", () => {
    expect(
      resolveWorkbenchHomePath({
        defaultRoute: "/evolution",
        defaultMode: "self_evolution",
        modeAvailability: {
          chat: false,
          self_evolution: true,
          supervised_evolution: true,
        },
      }),
    ).toBe("/self-evolution");
  });

  it("prefers supervised evolution when resolving the dedicated evolution home path", () => {
    expect(
      resolveEvolutionHomePath({
        defaultMode: "chat",
        modeAvailability: {
          chat: true,
          self_evolution: true,
          supervised_evolution: true,
        },
      }),
    ).toBe("/supervised-evolution");
  });

  it("treats missing availability as enabled but respects explicit disable flags", () => {
    expect(isWorkbenchDomainEnabled(undefined, "chat")).toBe(true);
    expect(
      isWorkbenchDomainEnabled(
        {
          domainAvailability: {
            chat: false,
            evolution: true,
            config: true,
          },
        },
        "chat",
      ),
    ).toBe(false);
    expect(
      isWorkbenchDomainEnabled(
        {
          domainAvailability: {
            chat: true,
            evolution: false,
            config: true,
          },
        },
        "evolution",
      ),
    ).toBe(false);
  });

  it("requires both the mode flag and evolution domain flag for evolution routes", () => {
    expect(
      isWorkbenchModeEnabled(
        {
          modeAvailability: {
            chat: true,
            self_evolution: true,
            supervised_evolution: false,
          },
          domainAvailability: {
            chat: true,
            evolution: true,
            config: true,
          },
        },
        "supervised_evolution",
      ),
    ).toBe(false);

    expect(
      isWorkbenchModeEnabled(
        {
          modeAvailability: {
            chat: true,
            self_evolution: true,
            supervised_evolution: true,
          },
          domainAvailability: {
            chat: true,
            evolution: false,
            config: true,
          },
        },
        "self_evolution",
      ),
    ).toBe(false);
  });
});
