import { createBrowserRouter, Navigate } from "react-router-dom";

import { AppShell } from "./AppShell";
import { ChatCodingRoute } from "../routes/ChatCodingRoute";
import { ConfigRoute } from "../routes/ConfigRoute";
import { EvolutionRoute } from "../routes/EvolutionRoute";
import { GitRoute } from "../routes/GitRoute";
import { HomeRedirect } from "../routes/HomeRedirect";
import { LegacyEvolutionRedirect } from "../routes/LegacyEvolutionRedirect";
import { LogsRoute } from "../routes/LogsRoute";
import { PetRoute } from "../routes/PetRoute";
import { ResetRoute } from "../routes/ResetRoute";
import { SupervisedReviewRoute } from "../routes/SupervisedReviewRoute";
import { WorkbenchDomainRoute } from "../routes/WorkbenchDomainRoute";
import { WorkbenchModeRoute } from "../routes/WorkbenchModeRoute";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <AppShell />,
    children: [
      { index: true, element: <HomeRedirect /> },
      {
        path: "chat",
        element: (
          <WorkbenchDomainRoute domain="chat">
            <ChatCodingRoute />
          </WorkbenchDomainRoute>
        ),
      },
      {
        path: "supervised-evolution",
        element: (
          <WorkbenchModeRoute mode="supervised_evolution">
            <EvolutionRoute forcedTrack="supervised" forcedView="live" />
          </WorkbenchModeRoute>
        ),
      },
      {
        path: "supervised-evolution/runs",
        element: (
          <WorkbenchModeRoute mode="supervised_evolution">
            <EvolutionRoute forcedTrack="supervised" forcedView="runs" />
          </WorkbenchModeRoute>
        ),
      },
      {
        path: "supervised-evolution/library",
        element: (
          <WorkbenchModeRoute mode="supervised_evolution">
            <EvolutionRoute forcedTrack="supervised" forcedView="library" />
          </WorkbenchModeRoute>
        ),
      },
      {
        path: "supervised-evolution/review",
        element: (
          <WorkbenchModeRoute mode="supervised_evolution">
            <SupervisedReviewRoute />
          </WorkbenchModeRoute>
        ),
      },
      {
        path: "self-evolution",
        element: (
          <WorkbenchModeRoute mode="self_evolution">
            <EvolutionRoute forcedTrack="self" />
          </WorkbenchModeRoute>
        ),
      },
      { path: "evolution", element: <LegacyEvolutionRedirect /> },
      { path: "git", element: <GitRoute /> },
      { path: "logs", element: <LogsRoute /> },
      { path: "pet", element: <PetRoute /> },
      { path: "reset", element: <ResetRoute /> },
      { path: "config", element: <ConfigRoute /> },
    ],
  },
]);
