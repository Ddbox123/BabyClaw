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
});
