import { ConfigSummary } from "../api/types";

export type WorkbenchDomain = "chat" | "evolution";
export type WorkbenchMode = "chat" | "self_evolution" | "supervised_evolution";

export function resolveEvolutionHomePath(
  summary?: Pick<ConfigSummary, "defaultMode" | "modeAvailability"> | null,
): string {
  const selfEnabled = summary?.modeAvailability?.self_evolution ?? true;
  const supervisedEnabled = summary?.modeAvailability?.supervised_evolution ?? true;

  if (summary?.defaultMode === "self_evolution" && selfEnabled) {
    return "/self-evolution";
  }
  if (summary?.defaultMode === "supervised_evolution" && supervisedEnabled) {
    return "/supervised-evolution";
  }
  if (supervisedEnabled) {
    return "/supervised-evolution";
  }
  if (selfEnabled) {
    return "/self-evolution";
  }
  return "/config";
}

export function resolveWorkbenchHomePath(
  summary?: Pick<ConfigSummary, "defaultRoute" | "defaultMode" | "modeAvailability"> | null,
): string {
  const route = summary?.defaultRoute || "/chat";
  return route === "/evolution" ? resolveEvolutionHomePath(summary) : route;
}

export function isWorkbenchDomainEnabled(
  summary: Pick<ConfigSummary, "domainAvailability"> | null | undefined,
  domain: WorkbenchDomain,
): boolean {
  const value = summary?.domainAvailability?.[domain];
  return typeof value === "boolean" ? value : true;
}

export function isWorkbenchModeEnabled(
  summary: Pick<ConfigSummary, "modeAvailability" | "domainAvailability"> | null | undefined,
  mode: WorkbenchMode,
): boolean {
  if (mode === "chat") {
    const chatEnabled = summary?.modeAvailability?.chat;
    return isWorkbenchDomainEnabled(summary, "chat") && (typeof chatEnabled === "boolean" ? chatEnabled : true);
  }

  const evolutionEnabled = isWorkbenchDomainEnabled(summary, "evolution");
  const modeEnabled = summary?.modeAvailability?.[mode];
  return evolutionEnabled && (typeof modeEnabled === "boolean" ? modeEnabled : true);
}
