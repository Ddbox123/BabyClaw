import { describe, expect, it } from "vitest";

import {
  backendSystemTone,
  deriveBackendSystemState,
  deriveFrontendSystemState,
  deriveRuntimeControllerState,
  frontendSystemTone,
  runtimeControllerTone,
} from "./systemStatus";

describe("systemStatus", () => {
  it("derives frontend state from browser visibility and connectivity", () => {
    expect(deriveFrontendSystemState({ online: true, visible: true })).toBe("connected");
    expect(deriveFrontendSystemState({ online: true, visible: false })).toBe("background");
    expect(deriveFrontendSystemState({ online: false, visible: true })).toBe("offline");
  });

  it("derives backend state from the health query snapshot", () => {
    expect(
      deriveBackendSystemState({
        isPending: true,
        hasData: false,
        isError: false,
        health: null,
      }),
    ).toBe("checking");

    expect(
      deriveBackendSystemState({
        isPending: false,
        hasData: true,
        isError: false,
        health: { status: "ok" },
      }),
    ).toBe("healthy");

    expect(
      deriveBackendSystemState({
        isPending: false,
        hasData: false,
        isError: true,
        health: null,
      }),
    ).toBe("offline");

    expect(
      deriveBackendSystemState({
        isPending: false,
        hasData: true,
        isError: false,
        health: { status: "degraded" },
      }),
    ).toBe("unhealthy");
  });

  it("derives runtime controller state from runtime manager and workbench snapshots", () => {
    expect(
      deriveRuntimeControllerState({
        runtimeManager: {
          running: true,
          runtimeState: "running",
          managerPid: 1001,
          stateVersion: 3,
        },
        workbench: {
          desiredState: "open",
          observedState: "open",
          phase: "steady",
          backendPid: 222,
          browserWindowPid: 333,
          browserManaged: true,
          url: "http://127.0.0.1:8000",
          lastReason: "",
          statusLine: "Workbench is open.",
          failureMessage: "",
        },
      }),
    ).toBe("managed");

    expect(
      deriveRuntimeControllerState({
        runtimeManager: {
          running: true,
          runtimeState: "running",
          managerPid: 1001,
          stateVersion: 3,
        },
        workbench: {
          desiredState: "closed",
          observedState: "open",
          phase: "closing",
          backendPid: 222,
          browserWindowPid: 333,
          browserManaged: true,
          url: "http://127.0.0.1:8000",
          lastReason: "",
          statusLine: "Closing workbench.",
          failureMessage: "",
        },
      }),
    ).toBe("closing");

    expect(
      deriveRuntimeControllerState({
        runtimeManager: {
          running: true,
          runtimeState: "running",
          managerPid: 1001,
          stateVersion: 3,
        },
        workbench: {
          desiredState: "open",
          observedState: "open",
          phase: "failed",
          backendPid: 222,
          browserWindowPid: 333,
          browserManaged: true,
          url: "http://127.0.0.1:8000",
          lastReason: "",
          statusLine: "Failed.",
          failureMessage: "boom",
        },
      }),
    ).toBe("failed");

    expect(
      deriveRuntimeControllerState({
        runtimeManager: {
          running: false,
          runtimeState: "idle",
          managerPid: 0,
          stateVersion: 3,
        },
        workbench: {
          desiredState: "open",
          observedState: "open",
          phase: "steady",
          backendPid: 222,
          browserWindowPid: 333,
          browserManaged: false,
          url: "http://127.0.0.1:8000",
          lastReason: "",
          statusLine: "Workbench is open.",
          failureMessage: "",
        },
      }),
    ).toBe("unmanaged");
  });

  it("maps system states to stable visual tones", () => {
    expect(frontendSystemTone("connected")).toBe("running");
    expect(frontendSystemTone("background")).toBe("idle");
    expect(frontendSystemTone("offline")).toBe("failed");

    expect(backendSystemTone("healthy")).toBe("running");
    expect(backendSystemTone("checking")).toBe("idle");
    expect(backendSystemTone("offline")).toBe("failed");

    expect(runtimeControllerTone("managed")).toBe("running");
    expect(runtimeControllerTone("unmanaged")).toBe("idle");
    expect(runtimeControllerTone("failed")).toBe("failed");
  });
});
