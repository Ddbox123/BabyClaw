import { beforeEach, describe, expect, it } from "vitest";

import { useChatWorkbenchStore } from "./chatWorkbenchStore";

describe("chatWorkbenchStore", () => {
  beforeEach(() => {
    useChatWorkbenchStore.setState({
      activeSessionId: null,
      sessionWorkspaces: {},
    });
  });

  it("starts a hydrated session on the agent conversation only", () => {
    useChatWorkbenchStore
      .getState()
      .hydrateSession("session-live", ["config/settings.py"], "config/settings.py");

    expect(useChatWorkbenchStore.getState().sessionWorkspaces["session-live"]).toEqual({
      openTabs: [],
      activeTab: "agent",
    });
  });

  it("keeps manual file opens available after the agent-only default", () => {
    const store = useChatWorkbenchStore.getState();

    store.hydrateSession("session-live", ["config/settings.py"], "config/settings.py");
    useChatWorkbenchStore.getState().openPreviewTab("session-live", "config/settings.py");

    expect(useChatWorkbenchStore.getState().sessionWorkspaces["session-live"]).toEqual({
      openTabs: ["config/settings.py"],
      activeTab: "config/settings.py",
    });
  });

  it("removes a deleted session workspace and moves active focus", () => {
    const store = useChatWorkbenchStore.getState();

    store.setActiveSession("session-live");
    store.openPreviewTab("session-live", "config/settings.py");
    store.openPreviewTab("session-next", "core/web/services/session_service.py");

    useChatWorkbenchStore.getState().removeSession("session-live", "session-next");

    expect(useChatWorkbenchStore.getState().activeSessionId).toBe("session-next");
    expect(useChatWorkbenchStore.getState().sessionWorkspaces["session-live"]).toBeUndefined();
    expect(useChatWorkbenchStore.getState().sessionWorkspaces["session-next"]).toEqual({
      openTabs: ["core/web/services/session_service.py"],
      activeTab: "core/web/services/session_service.py",
    });
  });
});
