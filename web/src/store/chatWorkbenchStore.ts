import { create } from "zustand";

type SessionWorkspace = {
  openTabs: string[];
  activeTab: string;
};

type ChatWorkbenchState = {
  activeSessionId: string | null;
  sessionWorkspaces: Record<string, SessionWorkspace>;
  setActiveSession: (sessionId: string) => void;
  hydrateSession: (sessionId: string, previewTabs: string[], activePreviewPath?: string) => void;
  removeSession: (sessionId: string, nextActiveSessionId?: string | null) => void;
  openPreviewTab: (sessionId: string, path: string) => void;
  closePreviewTab: (sessionId: string, path: string) => void;
  setActiveTab: (sessionId: string, tabId: string) => void;
};

export const useChatWorkbenchStore = create<ChatWorkbenchState>((set) => ({
  activeSessionId: null,
  sessionWorkspaces: {},
  setActiveSession: (activeSessionId) => set({ activeSessionId }),
  hydrateSession: (sessionId) =>
    set((state) => {
      const existing = state.sessionWorkspaces[sessionId];
      if (existing) {
        return state;
      }
      return {
        sessionWorkspaces: {
          ...state.sessionWorkspaces,
          [sessionId]: {
            openTabs: [],
            activeTab: "agent",
          },
        },
      };
    }),
  removeSession: (sessionId, nextActiveSessionId) =>
    set((state) => {
      const { [sessionId]: _removed, ...sessionWorkspaces } = state.sessionWorkspaces;
      return {
        activeSessionId:
          state.activeSessionId === sessionId
            ? nextActiveSessionId ?? null
            : state.activeSessionId,
        sessionWorkspaces,
      };
    }),
  openPreviewTab: (sessionId, path) =>
    set((state) => {
      const workspace = state.sessionWorkspaces[sessionId] ?? {
        openTabs: [],
        activeTab: "agent",
      };
      const openTabs = workspace.openTabs.includes(path)
        ? workspace.openTabs
        : [...workspace.openTabs, path];
      return {
        sessionWorkspaces: {
          ...state.sessionWorkspaces,
          [sessionId]: {
            openTabs,
            activeTab: path,
          },
        },
      };
    }),
  closePreviewTab: (sessionId, path) =>
    set((state) => {
      const workspace = state.sessionWorkspaces[sessionId];
      if (!workspace) {
        return state;
      }
      const openTabs = workspace.openTabs.filter((tabPath) => tabPath !== path);
      const nextActiveTab =
        workspace.activeTab === path ? openTabs[openTabs.length - 1] ?? "agent" : workspace.activeTab;
      return {
        sessionWorkspaces: {
          ...state.sessionWorkspaces,
          [sessionId]: {
            openTabs,
            activeTab: nextActiveTab,
          },
        },
      };
    }),
  setActiveTab: (sessionId, tabId) =>
    set((state) => {
      const workspace = state.sessionWorkspaces[sessionId] ?? {
        openTabs: [],
        activeTab: "agent",
      };
      return {
        sessionWorkspaces: {
          ...state.sessionWorkspaces,
          [sessionId]: {
            ...workspace,
            activeTab: tabId,
          },
        },
      };
    }),
}));
