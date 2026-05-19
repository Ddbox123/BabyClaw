import { create } from "zustand";
import { persist } from "zustand/middleware";

type RightPanel = "sessions" | "files";
type EvolutionTrack = "supervised" | "self";
type EvolutionView = "live" | "runs" | "library" | "overview";

type ChatPanelWidths = {
  leftPanelWidth: number;
  rightPanelWidth: number;
};

type ShellState = {
  rightPanel: RightPanel;
  evolutionTrack: EvolutionTrack;
  evolutionView: EvolutionView;
  chatPanelWidths: ChatPanelWidths;
  setRightPanel: (panel: RightPanel) => void;
  setEvolutionTrack: (track: EvolutionTrack) => void;
  setEvolutionView: (view: EvolutionView) => void;
  setChatPanelWidths: (widths: Partial<ChatPanelWidths>) => void;
};

const DEFAULT_CHAT_PANEL_WIDTHS: ChatPanelWidths = {
  leftPanelWidth: 264,
  rightPanelWidth: 340,
};

export const useShellStore = create<ShellState>()(
  persist(
    (set) => ({
      rightPanel: "sessions",
      evolutionTrack: "supervised",
      evolutionView: "live",
      chatPanelWidths: DEFAULT_CHAT_PANEL_WIDTHS,
      setRightPanel: (rightPanel) => set({ rightPanel }),
      setEvolutionTrack: (evolutionTrack) => set({ evolutionTrack }),
      setEvolutionView: (evolutionView) => set({ evolutionView }),
      setChatPanelWidths: (widths) =>
        set((state) => ({
          chatPanelWidths: {
            ...state.chatPanelWidths,
            ...widths,
          },
        })),
    }),
    {
      name: "vibelution-shell-store",
      partialize: (state) => ({
        rightPanel: state.rightPanel,
        evolutionTrack: state.evolutionTrack,
        evolutionView: state.evolutionView,
        chatPanelWidths: state.chatPanelWidths,
      }),
    },
  ),
);
