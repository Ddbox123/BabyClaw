import { BackendHealth, RuntimeSummary } from "../api/types";

export type SystemStatusTone = "idle" | "running" | "failed" | "caution";

export type FrontendSystemState = "connected" | "background" | "offline";
export type BackendSystemState = "checking" | "healthy" | "offline" | "unhealthy";
export type RuntimeControllerState = "managed" | "closing" | "unmanaged" | "failed";

type RuntimeSnapshot = Pick<RuntimeSummary, "runtimeManager" | "workbench">;

export function deriveFrontendSystemState({
  online,
  visible,
}: {
  online: boolean;
  visible: boolean;
}): FrontendSystemState {
  if (!online) {
    return "offline";
  }
  if (!visible) {
    return "background";
  }
  return "connected";
}

export function deriveBackendSystemState({
  isPending,
  hasData,
  isError,
  health,
}: {
  isPending: boolean;
  hasData: boolean;
  isError: boolean;
  health?: BackendHealth | null;
}): BackendSystemState {
  if (isPending && !hasData) {
    return "checking";
  }
  if (isError) {
    return "offline";
  }
  if (health?.status === "ok") {
    return "healthy";
  }
  return "unhealthy";
}

export function deriveRuntimeControllerState(runtime: RuntimeSnapshot | null | undefined): RuntimeControllerState {
  const managerRunning = Boolean(runtime?.runtimeManager?.running);
  const desiredState = String(runtime?.workbench?.desiredState ?? "closed").trim().toLowerCase();
  const observedState = String(runtime?.workbench?.observedState ?? "closed").trim().toLowerCase();
  const phase = String(runtime?.workbench?.phase ?? "").trim().toLowerCase();
  const failureMessage = String(runtime?.workbench?.failureMessage ?? "").trim();
  const browserManaged = Boolean(runtime?.workbench?.browserManaged);

  if (phase === "failed" || failureMessage) {
    return "failed";
  }
  if (desiredState === "closed" && observedState !== "closed") {
    return "closing";
  }
  if (managerRunning && browserManaged) {
    return "managed";
  }
  return "unmanaged";
}

export function frontendSystemTone(state: FrontendSystemState): SystemStatusTone {
  switch (state) {
    case "offline":
      return "failed";
    case "background":
      return "idle";
    default:
      return "running";
  }
}

export function backendSystemTone(state: BackendSystemState): SystemStatusTone {
  switch (state) {
    case "healthy":
      return "running";
    case "checking":
      return "idle";
    default:
      return "failed";
  }
}

export function runtimeControllerTone(state: RuntimeControllerState): SystemStatusTone {
  switch (state) {
    case "managed":
    case "closing":
      return "running";
    case "unmanaged":
      return "idle";
    default:
      return "failed";
  }
}
