import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  ArrowUpRight,
  CheckCircle2,
  Clock3,
  Gauge,
  LibraryBig,
  LoaderCircle,
  Pause,
  Play,
  Sparkles,
  Square,
  Trash2,
  TriangleAlert,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { fetchJson } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import {
  EvolutionActiveRun,
  EvolutionActiveRunStreamEvent,
  EvolutionActionState,
  ConfigSummary,
  EvolutionRunActionResponse,
  EvolutionWorkbench,
  EvolutionProposalBulkDeleteResponse,
  EvolutionProposalDeleteResponse,
  EvolutionProposalDetail,
  EvolutionLibraryEntry,
  EvolutionLibraryPayload,
  SelfEvolutionActiveRun,
  SelfEvolutionHistoryDeleteResponse,
  SelfEvolutionHandoffResponse,
  SelfEvolutionRunStreamEvent,
  EvolutionRun,
  SelfEvolutionOverview,
  SelfEvolutionTransaction,
} from "../api/types";
import { useAppI18n } from "../i18n/useAppI18n";
import { useShellStore } from "../store/shellStore";
import { SelfEvolutionTrack } from "./SelfEvolutionTrack";
import { SupervisedWorkspaceTabs } from "./SupervisedWorkspaceTabs";
import { savePendingSelfEvolutionHandoff } from "./selfEvolutionHandoff";
import styles from "./EvolutionRoute.module.css";

type RunFilter = "all" | "success" | "failed";
type LibraryView = "items" | "pending";
type LibraryStatusFilter =
  | "all"
  | "proposed"
  | "applied"
  | "active"
  | "superseded"
  | "rolled_back"
  | "missing";
type LibraryDeleteFilter = "all" | "deletable" | "blocked";
type EvolutionRouteTrack = "supervised" | "self";
type SupervisedRouteView = "live" | "runs" | "library";
type EvolutionRouteProps = {
  forcedTrack?: EvolutionRouteTrack;
  forcedView?: SupervisedRouteView;
};

const LIBRARY_STATUS_FILTERS: LibraryStatusFilter[] = [
  "all",
  "proposed",
  "applied",
  "active",
  "superseded",
  "rolled_back",
  "missing",
];
const EMPTY_RUNS: EvolutionRun[] = [];
const EMPTY_LIBRARY_ENTRIES: EvolutionLibraryEntry[] = [];

function clampScore(value: number) {
  return Math.max(0, Math.min(100, Math.round(value)));
}

function isSelfRunExecutingStatus(status: string) {
  return ["queued", "running", "stopping"].includes(String(status || "").trim().toLowerCase());
}

function isSelfRunLockedStatus(status: string) {
  return ["queued", "running", "stopping", "paused"].includes(String(status || "").trim().toLowerCase());
}

function statusIcon(status: string) {
  const normalized = String(status).trim().toLowerCase();
  if (normalized === "success") {
    return <CheckCircle2 size={16} />;
  }
  if (normalized === "failed" || normalized === "caution") {
    return <TriangleAlert size={16} />;
  }
  if (normalized === "running" || normalized === "waiting" || normalized === "queued" || normalized === "paused" || normalized === "stopping") {
    return <Clock3 size={16} />;
  }
  if (normalized === "done" || normalized === "cancelled") {
    return <CheckCircle2 size={16} />;
  }
  return <Gauge size={16} />;
}

function toLimitInput(value: number | null | undefined) {
  if (typeof value !== "number" || Number.isNaN(value) || value <= 0) {
    return "";
  }
  return String(value);
}

function compactTimestamp(value: string) {
  const text = String(value || "").trim();
  if (!text) {
    return "--";
  }
  const normalized = text.replace("T", " ");
  if (normalized.length > 19) {
    return normalized.slice(0, 19);
  }
  return normalized;
}

function isLiveSupervisedRunStatus(status: string) {
  return ["queued", "running", "paused", "stopping"].includes(String(status || "").trim().toLowerCase());
}

function formatTurnRange(startTurn: number, endTurn: number) {
  if (startTurn > 0 && endTurn > 0) {
    return `T${startTurn}-${endTurn}`;
  }
  if (startTurn > 0) {
    return `T${startTurn}`;
  }
  return "--";
}

export function EvolutionRoute({ forcedTrack, forcedView }: EvolutionRouteProps) {
  const {
    lang,
    t,
    statusLabel,
    intakeModeLabel,
    viewLabel,
    decisionLabel,
    riskLabel,
    workbenchSourceLabel,
    proposalActionLabel,
    sourceKindLabel,
  } = useAppI18n();
  const location = useLocation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const evolutionTrack = useShellStore((state) => state.evolutionTrack);
  const setEvolutionTrack = useShellStore((state) => state.setEvolutionTrack);
  const rawEvolutionView = useShellStore((state) => state.evolutionView);
  const setEvolutionView = useShellStore((state) => state.setEvolutionView);
  const evolutionView = forcedView ?? (rawEvolutionView === "overview" ? "live" : rawEvolutionView);
  const selfTrackQueriesEnabled = forcedTrack === "self" || forcedTrack === undefined;
  const supervisedTrackQueriesEnabled = forcedTrack !== "self";
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [runFilter, setRunFilter] = useState<RunFilter>("all");
  const [libraryView, setLibraryView] = useState<LibraryView>("items");
  const [selectedLibraryItemId, setSelectedLibraryItemId] = useState<string | null>(null);
  const [selectedPendingItemId, setSelectedPendingItemId] = useState<string | null>(null);
  const [selectedProposalRunIds, setSelectedProposalRunIds] = useState<string[]>([]);
  const [librarySearchInput, setLibrarySearchInput] = useState("");
  const [libraryStatusFilter, setLibraryStatusFilter] = useState<LibraryStatusFilter>("all");
  const [libraryDeleteFilter, setLibraryDeleteFilter] = useState<LibraryDeleteFilter>("all");
  const [formInitialized, setFormInitialized] = useState(false);
  const [sourceKind, setSourceKind] = useState<"dataset" | "bundle">("dataset");
  const [datasetName, setDatasetName] = useState("");
  const [datasetLimitInput, setDatasetLimitInput] = useState("");
  const [bundleNameInput, setBundleNameInput] = useState("");
  const [keepWorktree, setKeepWorktree] = useState(false);
  const [liveActiveRun, setLiveActiveRun] = useState<EvolutionActiveRun | null>(null);
  const [selfGoalInput, setSelfGoalInput] = useState("");
  const [selfGoalInitialized, setSelfGoalInitialized] = useState(false);
  const [liveSelfRun, setLiveSelfRun] = useState<SelfEvolutionActiveRun | null>(null);
  const [actionFeedback, setActionFeedback] = useState("");
  const [selfActionFeedback, setSelfActionFeedback] = useState("");
  const [libraryFeedback, setLibraryFeedback] = useState("");
  const configQuery = useQuery({
    queryKey: queryKeys.configPublic(),
    queryFn: () => fetchJson<ConfigSummary>("/api/config/public"),
    refetchInterval: 8_000,
    refetchIntervalInBackground: true,
  });

  const runsQuery = useQuery({
    queryKey: queryKeys.evolutionRuns(),
    queryFn: () => fetchJson<EvolutionRun[]>("/api/evolution/runs"),
    refetchInterval: 8_000,
    refetchIntervalInBackground: true,
    enabled: supervisedTrackQueriesEnabled,
  });
  const libraryQuery = useQuery({
    queryKey: queryKeys.evolutionLibrary(),
    queryFn: () => fetchJson<EvolutionLibraryPayload>("/api/evolution/library"),
    refetchInterval: 8_000,
    refetchIntervalInBackground: true,
    enabled: supervisedTrackQueriesEnabled,
  });
  const workbenchQuery = useQuery({
    queryKey: queryKeys.evolutionWorkbench(),
    queryFn: () => fetchJson<EvolutionWorkbench>("/api/evolution/workbench"),
    refetchInterval: 8_000,
    refetchIntervalInBackground: true,
    enabled: supervisedTrackQueriesEnabled,
  });
  const activeRunQuery = useQuery({
    queryKey: queryKeys.evolutionActiveRun(),
    queryFn: () => fetchJson<EvolutionActiveRun | null>("/api/evolution/active-run"),
    refetchInterval: 4_000,
    refetchIntervalInBackground: true,
    enabled: supervisedTrackQueriesEnabled,
  });
  const selfOverviewQuery = useQuery({
    queryKey: queryKeys.evolutionSelfOverview(),
    queryFn: () => fetchJson<SelfEvolutionOverview>("/api/evolution/self/overview"),
    refetchInterval: 8_000,
    refetchIntervalInBackground: true,
    enabled: selfTrackQueriesEnabled && (configQuery.data ? configQuery.data.modeAvailability.self_evolution : true),
  });
  const selfLatestRunQuery = useQuery({
    queryKey: queryKeys.evolutionSelfLatestRun(),
    queryFn: () => fetchJson<SelfEvolutionActiveRun | null>("/api/evolution/self/latest-run"),
    refetchInterval: 4_000,
    refetchIntervalInBackground: true,
    enabled: selfTrackQueriesEnabled && (configQuery.data ? configQuery.data.modeAvailability.self_evolution : true),
  });
  const selfTransactionsQuery = useQuery({
    queryKey: queryKeys.evolutionSelfTransactions(),
    queryFn: () => fetchJson<SelfEvolutionTransaction[]>("/api/evolution/self/transactions"),
    refetchInterval: 8_000,
    refetchIntervalInBackground: true,
    enabled: selfTrackQueriesEnabled && (configQuery.data ? configQuery.data.modeAvailability.self_evolution : true),
  });
  const intakeModeMutation = useMutation({
    mutationFn: (intakeMode: "manual_review" | "auto") =>
      fetchJson<ConfigSummary>("/api/config/intake-mode", {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ intakeMode }),
      }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.configPublic() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.runtimeSummary() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionOverview() }),
      ]);
    },
  });
  const startRunMutation = useMutation({
    mutationFn: () =>
      fetchJson<EvolutionActiveRun>("/api/evolution/runs", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          sourceKind,
          datasetName: sourceKind === "dataset" ? datasetName : "",
          datasetLimit:
            sourceKind === "dataset" && datasetLimitInput.trim()
              ? Number(datasetLimitInput.trim())
              : null,
          bundleName: sourceKind === "bundle" ? bundleNameInput : "",
          keepWorktree,
        }),
      }),
    onSuccess: async (snapshot) => {
      setActionFeedback("");
      setLiveActiveRun(snapshot);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionWorkbench() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionActiveRun() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionOverview() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionRuns() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionLibrary() }),
      ]);
    },
  });
  const invalidateSupervisedEvolution = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.evolutionWorkbench() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.evolutionActiveRun() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.evolutionOverview() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.evolutionRuns() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.evolutionLibrary() }),
    ]);
  };
  const pauseRunMutation = useMutation({
    onMutate: () => {
      setActionFeedback("");
    },
    mutationFn: (runId: string) =>
      fetchJson<EvolutionActiveRun>(`/api/evolution/runs/${runId}/pause`, {
        method: "POST",
      }),
    onSuccess: async (snapshot) => {
      setActionFeedback(snapshot.latestMessage || "");
      setLiveActiveRun(snapshot);
      await invalidateSupervisedEvolution();
    },
  });
  const resumeRunMutation = useMutation({
    onMutate: () => {
      setActionFeedback("");
    },
    mutationFn: (runId: string) =>
      fetchJson<EvolutionActiveRun>(`/api/evolution/runs/${runId}/resume`, {
        method: "POST",
      }),
    onSuccess: async (snapshot) => {
      setActionFeedback(snapshot.latestMessage || "");
      setLiveActiveRun(snapshot);
      await invalidateSupervisedEvolution();
    },
  });
  const terminateRunMutation = useMutation({
    onMutate: () => {
      setActionFeedback("");
    },
    mutationFn: (runId: string) =>
      fetchJson<EvolutionActiveRun>(`/api/evolution/runs/${runId}/terminate`, {
        method: "POST",
      }),
    onSuccess: async (snapshot) => {
      setActionFeedback(snapshot.latestMessage || snapshot.reason || "");
      setLiveActiveRun(snapshot);
      await invalidateSupervisedEvolution();
    },
  });
  const invalidateSelfEvolution = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.evolutionSelfOverview() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.evolutionSelfActiveRun() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.evolutionSelfLatestRun() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.evolutionSelfTransactions() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.evolutionSelfAudit() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.runtimeSummary() }),
    ]);
  };
  const startSelfRunMutation = useMutation({
    onMutate: () => {
      setSelfActionFeedback("");
    },
    mutationFn: () =>
      fetchJson<SelfEvolutionActiveRun>("/api/evolution/self/runs", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          goal: selfGoalInput.trim(),
        }),
      }),
    onSuccess: async (snapshot) => {
      setSelfActionFeedback("");
      setLiveSelfRun(snapshot);
      await invalidateSelfEvolution();
    },
  });
  const stopSelfRunMutation = useMutation({
    onMutate: () => {
      setSelfActionFeedback("");
    },
    mutationFn: (runId: string) =>
      fetchJson<SelfEvolutionActiveRun>(`/api/evolution/self/runs/${runId}/terminate`, {
        method: "POST",
      }),
    onSuccess: async (snapshot) => {
      setSelfActionFeedback(snapshot.latestMessage || snapshot.stopReason || "");
      setLiveSelfRun(snapshot);
      await invalidateSelfEvolution();
    },
  });
  const pauseSelfRunMutation = useMutation({
    onMutate: () => {
      setSelfActionFeedback("");
    },
    mutationFn: (runId: string) =>
      fetchJson<SelfEvolutionActiveRun>(`/api/evolution/self/runs/${runId}/pause`, {
        method: "POST",
      }),
    onSuccess: async (snapshot) => {
      setSelfActionFeedback(snapshot.latestMessage || snapshot.stopReason || "");
      setLiveSelfRun(snapshot);
      await invalidateSelfEvolution();
    },
  });
  const resumeSelfRunMutation = useMutation({
    onMutate: () => {
      setSelfActionFeedback("");
    },
    mutationFn: (runId: string) =>
      fetchJson<SelfEvolutionActiveRun>(`/api/evolution/self/runs/${runId}/resume`, {
        method: "POST",
      }),
    onSuccess: async (snapshot) => {
      setSelfActionFeedback(snapshot.latestMessage || "");
      setLiveSelfRun(snapshot);
      await invalidateSelfEvolution();
    },
  });
  const rollbackSelfRunMutation = useMutation({
    onMutate: () => {
      setSelfActionFeedback("");
    },
    mutationFn: (runId: string) =>
      fetchJson<SelfEvolutionActiveRun>(`/api/evolution/self/runs/${runId}/rollback`, {
        method: "POST",
      }),
    onSuccess: async (snapshot) => {
      setSelfActionFeedback(snapshot.rollback?.reason || snapshot.latestMessage || "");
      setLiveSelfRun(snapshot);
      await invalidateSelfEvolution();
    },
  });
  const handoffSelfRunMutation = useMutation({
    onMutate: () => {
      setSelfActionFeedback("");
    },
    mutationFn: (runId: string) =>
      fetchJson<SelfEvolutionHandoffResponse>(`/api/evolution/self/runs/${runId}/handoff`, {
        method: "POST",
      }),
    onSuccess: async (payload) => {
      setSelfActionFeedback(payload.message || "");
      if (payload.run) {
        setLiveSelfRun(payload.run);
      }
      await Promise.all([
        invalidateSelfEvolution(),
        queryClient.invalidateQueries({ queryKey: queryKeys.sessions() }),
      ]);
      if (payload.status === "ready" && payload.content) {
        savePendingSelfEvolutionHandoff({
          sessionId: payload.sessionId || "",
          content: payload.content,
        });
        void navigate("/chat");
      }
    },
  });
  const deleteSelfHistoryMutation = useMutation({
    onMutate: () => {
      setSelfActionFeedback("");
    },
    mutationFn: (txnIds: string[]) =>
      fetchJson<SelfEvolutionHistoryDeleteResponse>("/api/evolution/self/history/delete", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ txnIds }),
      }),
    onSuccess: async (payload) => {
      setSelfActionFeedback(payload.summary || "");
      await invalidateSelfEvolution();
    },
  });
  const actionMutation = useMutation({
    mutationFn: (variables: { sessionId: string; action: string }) =>
      fetchJson<EvolutionRunActionResponse>(`/api/evolution/runs/${variables.sessionId}/actions`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ action: variables.action }),
      }),
    onSuccess: async (payload) => {
      setActionFeedback(payload.summary);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionOverview() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionRuns() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionLibrary() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionWorkbench() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionActiveRun() }),
      ]);
    },
  });
  const runs = runsQuery.data ?? EMPTY_RUNS;
  const libraryItems = libraryQuery.data?.items ?? EMPTY_LIBRARY_ENTRIES;
  const pendingItems = libraryQuery.data?.pending ?? EMPTY_LIBRARY_ENTRIES;
  const workbenchControl = workbenchQuery.data;
  const workbenchState = workbenchControl?.savedState;
  const activeRunSnapshot = activeRunQuery.data;
  const latestSelfRunSnapshot = selfLatestRunQuery.data;
  const latestRun = runs[0] ?? null;
  const selfTrackEnabled = configQuery.data?.modeAvailability.self_evolution ?? false;
  const supervisedTrackEnabled = configQuery.data?.modeAvailability.supervised_evolution ?? true;
  const activeTrack = forcedTrack ?? (
    evolutionTrack === "self" && selfTrackEnabled
      ? "self"
      : supervisedTrackEnabled
        ? "supervised"
        : selfTrackEnabled
          ? "self"
          : "supervised"
  );
  const showTrackToggle = !forcedTrack && selfTrackEnabled && supervisedTrackEnabled;
  const routeEyebrow = activeTrack === "self" ? t("navSelfEvolution") : t("navSupervisedEvolution");
  const routeTitle =
    activeTrack === "self" ? t("selfEvolutionMode") : t("supervisedEvolutionMode");
  const routeSubtitle =
    activeTrack === "self" ? t("selfEvolutionSubtitle") : t("supervisedEvolutionSubtitle");
  const currentIntakeMode =
    configQuery.data?.intakeMode === "auto" ? "auto" : "manual_review";
  const nextIntakeMode = currentIntakeMode === "auto" ? "manual_review" : "auto";
  const monitoredRun = activeRunSnapshot
    ?? (liveActiveRun && ["done", "failed", "cancelled"].includes(String(liveActiveRun.status || "").toLowerCase())
      ? liveActiveRun
      : null);
  const runningRun = activeRunSnapshot ?? (liveActiveRun && isLiveSupervisedRunStatus(liveActiveRun.status)
    ? liveActiveRun
    : null);
  const runLocked = Boolean(runningRun && isLiveSupervisedRunStatus(runningRun.status));
  const monitoredRunStatus = String(monitoredRun?.status || "").toLowerCase();
  const monitoredCaseTranscript = monitoredRun?.currentCaseIo?.transcript ?? [];
  const monitoredCaseHasOutput = Boolean(
    monitoredRun?.currentCaseIo?.latestOutput || monitoredCaseTranscript.length > 0,
  );
  const monitoredCaseHasVisibleIo = Boolean(
    monitoredRun?.currentCasePrompt || monitoredRun?.currentCaseIo?.latestInput || monitoredCaseHasOutput,
  );
  const runPauseRequested = Boolean(monitoredRun?.pauseRequested) && monitoredRunStatus !== "paused";
  const runPaused = monitoredRunStatus === "paused";
  const runStopping = monitoredRunStatus === "stopping" || Boolean(monitoredRun?.stopRequested);
  const pauseSupervisedAction = monitoredRun?.actionStates?.pause;
  const resumeSupervisedAction = monitoredRun?.actionStates?.resume;
  const terminateSupervisedAction = monitoredRun?.actionStates?.terminate;
  const canPauseSupervisedRun = Boolean(monitoredRun && pauseSupervisedAction?.enabled);
  const canResumeSupervisedRun = Boolean(monitoredRun && resumeSupervisedAction?.enabled);
  const canTerminateSupervisedRun = Boolean(monitoredRun && terminateSupervisedAction?.enabled);
  const supervisedControlError =
    pauseRunMutation.error?.message
    ?? resumeRunMutation.error?.message
    ?? terminateRunMutation.error?.message
    ?? startRunMutation.error?.message
    ?? "";
  const monitoredSelfRun = latestSelfRunSnapshot ?? liveSelfRun;
  const lockedSelfRun =
    monitoredSelfRun
    && isSelfRunLockedStatus(monitoredSelfRun.status || "")
      ? monitoredSelfRun
      : null;
  const selfRunLocked = Boolean(lockedSelfRun);
  const selectedDataset = workbenchControl?.datasets.find((item) => item.name === datasetName) ?? null;
  const normalizedLibrarySearch = librarySearchInput.trim().toLowerCase();
  const filterLibraryEntries = (entries: EvolutionLibraryEntry[]) =>
    entries.filter((item) => {
      if (libraryStatusFilter !== "all" && item.proposalStatus !== libraryStatusFilter) {
        return false;
      }
      if (libraryDeleteFilter === "deletable" && !item.canDelete) {
        return false;
      }
      if (libraryDeleteFilter === "blocked" && item.canDelete) {
        return false;
      }
      if (!normalizedLibrarySearch) {
        return true;
      }
      const searchHaystack = [
        item.title,
        item.sourceRun,
        item.targetLabel,
        item.targetKey,
        item.headline,
        item.changeSummary,
        item.summary,
        item.reason ?? "",
      ]
        .join(" ")
        .toLowerCase();
      return searchHaystack.includes(normalizedLibrarySearch);
    });
  const filteredLibraryItems = useMemo(
    () => filterLibraryEntries(libraryItems),
    [libraryItems, libraryStatusFilter, libraryDeleteFilter, normalizedLibrarySearch],
  );
  const filteredPendingItems = useMemo(
    () => filterLibraryEntries(pendingItems),
    [pendingItems, libraryStatusFilter, libraryDeleteFilter, normalizedLibrarySearch],
  );
  const visibleLibraryEntries = libraryView === "items"
    ? filteredLibraryItems
    : filteredPendingItems;
  const currentLibraryEntries = libraryView === "items"
    ? libraryItems
    : pendingItems;
  const hasLibraryFilters = Boolean(normalizedLibrarySearch)
    || libraryStatusFilter !== "all"
    || libraryDeleteFilter !== "all";
  const selectedLibraryItem =
    filteredLibraryItems.find((item) => item.id === selectedLibraryItemId) ?? filteredLibraryItems[0] ?? null;
  const selectedPendingItem =
    filteredPendingItems.find((item) => item.id === selectedPendingItemId) ?? filteredPendingItems[0] ?? null;
  const selectedProposalSummary = libraryView === "items" ? selectedLibraryItem : selectedPendingItem;
  const selectedProposalRunId = selectedProposalSummary?.sourceRun ?? null;
  const libraryPaneEmpty = currentLibraryEntries.length === 0;
  const libraryFilteredEmpty = !libraryPaneEmpty && visibleLibraryEntries.length === 0;
  const libraryDeletableCount = currentLibraryEntries.filter((item) => item.canDelete).length;
  const libraryBlockedCount = currentLibraryEntries.length - libraryDeletableCount;
  const proposalDetailQuery = useQuery({
    queryKey: queryKeys.evolutionProposal(selectedProposalRunId ?? "__none__"),
    queryFn: () =>
      fetchJson<EvolutionProposalDetail>(`/api/evolution/proposals/${selectedProposalRunId}`),
    enabled:
      activeTrack === "supervised"
      && evolutionView === "library"
      && Boolean(selectedProposalRunId),
    refetchInterval: 8_000,
    refetchIntervalInBackground: true,
  });
  const deleteProposalMutation = useMutation({
    mutationFn: (sessionId: string) =>
      fetchJson<EvolutionProposalDeleteResponse>(`/api/evolution/proposals/${sessionId}`, {
        method: "DELETE",
      }),
    onSuccess: async (payload) => {
      setLibraryFeedback(payload.summary);
      setSelectedProposalRunIds((current) => current.filter((item) => item !== payload.sessionId));
      if (selectedRunId === payload.sessionId) {
        setSelectedRunId(null);
      }
      if (selectedLibraryItemId === payload.sessionId) {
        setSelectedLibraryItemId(null);
      }
      if (selectedPendingItemId === payload.sessionId) {
        setSelectedPendingItemId(null);
      }
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionOverview() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionRuns() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionLibrary() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionProposal(payload.sessionId) }),
      ]);
    },
  });
  const bulkDeleteMutation = useMutation({
    mutationFn: (sessionIds: string[]) =>
      fetchJson<EvolutionProposalBulkDeleteResponse>("/api/evolution/proposals/delete", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ sessionIds }),
      }),
    onSuccess: async (payload) => {
      setLibraryFeedback(payload.summary);
      setSelectedProposalRunIds([]);
      if (
        selectedProposalRunId
        && payload.results.some(
          (item) => item.sessionId === selectedProposalRunId && item.status === "deleted",
        )
      ) {
        if (libraryView === "items") {
          setSelectedLibraryItemId(null);
        } else {
          setSelectedPendingItemId(null);
        }
      }
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionOverview() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionRuns() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionLibrary() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionProposal(selectedProposalRunId ?? "__none__") }),
      ]);
    },
  });

  useEffect(() => {
    if (formInitialized || !workbenchControl) {
      return;
    }
    const savedState = workbenchControl.savedState;
    setSourceKind(savedState.source === "bundle" ? "bundle" : "dataset");
    setDatasetName(savedState.datasetName || workbenchControl.datasets[0]?.name || "");
    setDatasetLimitInput(toLimitInput(savedState.datasetLimit));
    setBundleNameInput(savedState.bundleName || workbenchControl.defaultBundleName || "");
    setKeepWorktree(Boolean(savedState.keepWorktree));
    setFormInitialized(true);
  }, [formInitialized, workbenchControl]);

  useEffect(() => {
    const datasetParam = new URLSearchParams(location.search).get("dataset");
    if (!datasetParam || activeTrack !== "supervised") {
      return;
    }
    const known = workbenchControl?.datasets.some((item) => item.name === datasetParam);
    if (!known) {
      return;
    }
    setSourceKind("dataset");
    setDatasetName(datasetParam);
  }, [activeTrack, location.search, workbenchControl]);

  useEffect(() => {
    if (activeRunSnapshot) {
      setLiveActiveRun(activeRunSnapshot);
      return;
    }
    setLiveActiveRun((current) => {
      if (current && ["done", "failed", "cancelled"].includes(String(current.status || "").toLowerCase())) {
        return current;
      }
      return null;
    });
  }, [activeRunSnapshot]);

  useEffect(() => {
    if (!forcedTrack || evolutionTrack === forcedTrack) {
      return;
    }
    setEvolutionTrack(forcedTrack);
  }, [evolutionTrack, forcedTrack, setEvolutionTrack]);

  useEffect(() => {
    if (!forcedView && rawEvolutionView === "overview") {
      setEvolutionView("live");
    }
  }, [forcedView, rawEvolutionView, setEvolutionView]);

  useEffect(() => {
    if (selfGoalInitialized || !selfOverviewQuery.data?.goal) {
      return;
    }
    setSelfGoalInput(selfOverviewQuery.data.goal);
    setSelfGoalInitialized(true);
  }, [selfGoalInitialized, selfOverviewQuery.data?.goal]);

  useEffect(() => {
    if (latestSelfRunSnapshot) {
      setLiveSelfRun(latestSelfRunSnapshot);
      return;
    }
    setLiveSelfRun((current) => {
      if (current && !isSelfRunLockedStatus(current.status || "")) {
        return current;
      }
      return null;
    });
  }, [latestSelfRunSnapshot]);

  useEffect(() => {
    const target = monitoredSelfRun;
    if (!target || !isSelfRunExecutingStatus(target.status || "")) {
      return;
    }
    if (typeof EventSource === "undefined") {
      return;
    }

    const source = new EventSource(`/api/evolution/self/runs/${target.runId}/events`);
    const handleSnapshot = (message: MessageEvent) => {
      const payload = JSON.parse(message.data) as SelfEvolutionRunStreamEvent;
      setLiveSelfRun(payload.snapshot);
      if (payload.terminal) {
        void Promise.all([
          queryClient.invalidateQueries({ queryKey: queryKeys.evolutionSelfOverview() }),
          queryClient.invalidateQueries({ queryKey: queryKeys.evolutionSelfActiveRun() }),
          queryClient.invalidateQueries({ queryKey: queryKeys.evolutionSelfLatestRun() }),
          queryClient.invalidateQueries({ queryKey: queryKeys.evolutionSelfTransactions() }),
          queryClient.invalidateQueries({ queryKey: queryKeys.evolutionSelfAudit() }),
          queryClient.invalidateQueries({ queryKey: queryKeys.runtimeSummary() }),
        ]);
        source.close();
      }
    };

    source.addEventListener("self_evolution_run", handleSnapshot as EventListener);
    source.onerror = () => {
      source.close();
      void queryClient.invalidateQueries({ queryKey: queryKeys.evolutionSelfLatestRun() });
    };

    return () => {
      source.removeEventListener("self_evolution_run", handleSnapshot as EventListener);
      source.close();
    };
  }, [monitoredSelfRun?.runId, monitoredSelfRun?.status, queryClient]);

  useEffect(() => {
    const target = activeRunSnapshot
      ?? (liveActiveRun && isLiveSupervisedRunStatus(liveActiveRun.status)
        ? liveActiveRun
        : null);
    if (!target || !isLiveSupervisedRunStatus(target.status)) {
      return;
    }

    const source = new EventSource("/api/evolution/active-run/events");
    const handleSnapshot = (message: MessageEvent) => {
      const payload = JSON.parse(message.data) as EvolutionActiveRunStreamEvent;
      setLiveActiveRun(payload.snapshot);
      if (payload.terminal) {
        void Promise.all([
          queryClient.invalidateQueries({ queryKey: queryKeys.evolutionActiveRun() }),
          queryClient.invalidateQueries({ queryKey: queryKeys.evolutionOverview() }),
          queryClient.invalidateQueries({ queryKey: queryKeys.evolutionRuns() }),
          queryClient.invalidateQueries({ queryKey: queryKeys.evolutionLibrary() }),
          queryClient.invalidateQueries({ queryKey: queryKeys.evolutionWorkbench() }),
        ]);
        source.close();
      }
    };

    source.addEventListener("supervised_run", handleSnapshot as EventListener);
    source.onerror = () => {
      source.close();
      void queryClient.invalidateQueries({ queryKey: queryKeys.evolutionActiveRun() });
    };

    return () => {
      source.removeEventListener("supervised_run", handleSnapshot as EventListener);
      source.close();
    };
  }, [activeRunSnapshot?.runId, activeRunSnapshot?.status, liveActiveRun?.runId, liveActiveRun?.status, queryClient]);

  useEffect(() => {
    const visibleIds = new Set(
      visibleLibraryEntries.map((item) => item.sourceRun),
    );
    setSelectedProposalRunIds((current) => {
      const next = current.filter((item) => visibleIds.has(item));
      if (
        next.length === current.length
        && next.every((item, index) => item === current[index])
      ) {
        return current;
      }
      return next;
    });
  }, [visibleLibraryEntries]);

  const filteredRuns = useMemo(() => {
    if (runFilter === "all") {
      return runs;
    }
    return runs.filter((run) => run.status === runFilter);
  }, [runFilter, runs]);
  const hasRuns = runs.length > 0;
  const hasFilteredRuns = filteredRuns.length > 0;
  const filteredRunsEmpty = hasRuns && !hasFilteredRuns;
  const runSuccessCount = runs.filter((run) => run.status === "success").length;
  const runFailedCount = runs.filter((run) => run.status === "failed").length;
  const runPendingCount = runs.filter((run) => run.status === "waiting").length;
  const runHeaderMessage = !hasRuns
    ? t("noRunsRecordedHint")
    : filteredRunsEmpty
      ? t("runFilterEmptyHint")
      : t("runQueueHint");
  const libraryHeaderMessage = libraryPaneEmpty
    ? (libraryView === "items" ? t("emptyLibraryItems") : t("emptyPendingItems"))
    : libraryFilteredEmpty
      ? t("noProposalMatches")
      : t("chooseProposalDetail");

  const selectedRun = useMemo(() => {
    return filteredRuns.find((run) => run.id === selectedRunId) ?? filteredRuns[0] ?? null;
  }, [filteredRuns, selectedRunId]);

  const relatedLibraryItems = selectedRun
    ? libraryItems.filter((item) => item.sourceRun === selectedRun.id)
    : [];
  const relatedPendingItems = selectedRun
    ? pendingItems.filter((item) => item.sourceRun === selectedRun.id)
    : [];
  const relatedProposalCount = relatedLibraryItems.length + relatedPendingItems.length;

  function goToSupervisedView(view: SupervisedRouteView) {
    if (forcedTrack === "supervised" && forcedView) {
      navigate(
        view === "live"
          ? "/supervised-evolution"
          : view === "runs"
            ? "/supervised-evolution/runs"
            : "/supervised-evolution/library",
      );
      return;
    }
    setEvolutionView(view);
  }

  function openRun(runId: string | null) {
    if (!runId) {
      return;
    }
    setSelectedRunId(runId);
    goToSupervisedView("runs");
  }

  function openProposalFromRun(item: EvolutionLibraryEntry, view: LibraryView) {
    goToSupervisedView("library");
    setLibraryView(view);
    setLibraryFeedback("");
    if (view === "items") {
      setSelectedLibraryItemId(item.id);
      setSelectedPendingItemId(null);
    } else {
      setSelectedPendingItemId(item.id);
      setSelectedLibraryItemId(null);
    }
  }

  function formatAvailableActions(actions: string[] | undefined) {
    if (!actions || actions.length === 0) {
      return "--";
    }
    return actions.map((action) => proposalActionLabel(action)).join(", ");
  }

  function disabledReason(state: EvolutionActionState | undefined) {
    if (!state || state.enabled) {
      return "";
    }
    return state.reason || "";
  }

  function runRoleLabel(role: string | undefined) {
    const normalized = String(role || "").trim().toLowerCase();
    if (normalized === "baseline") {
      return t("roleBaseline");
    }
    if (normalized === "candidate") {
      return t("roleCandidate");
    }
    return normalized || "--";
  }

  function formatRunEventTitle(event: EvolutionActiveRun["eventTail"][number]) {
    const normalized = String(event.event || "").trim().toLowerCase();
    if (normalized === "queued") {
      return t("runEventQueued");
    }
    if (normalized === "session_start") {
      return t("runEventStarted");
    }
    if (normalized === "role_start") {
      return t("runEventCaseStarted");
    }
    if (normalized === "role_finish") {
      return t("runEventCaseFinished");
    }
    if (normalized === "pause_requested") {
      return t("runEventPauseRequested");
    }
    if (normalized === "run_paused") {
      return t("runEventPaused");
    }
    if (normalized === "run_resumed") {
      return t("runEventResumed");
    }
    if (normalized === "stop_requested") {
      return t("runEventStopRequested");
    }
    if (normalized === "run_cancelled") {
      return t("runEventCancelled");
    }
    if (normalized === "session_error") {
      return t("runEventError");
    }
    if (normalized === "session_finish") {
      return t("runEventFinished");
    }
    if (normalized === "run_completed") {
      return t("runEventCompleted");
    }
    if (normalized === "run_failed") {
      return t("runEventFailed");
    }
    return event.title || event.event;
  }

  function formatRunEventSummary(event: EvolutionActiveRun["eventTail"][number]) {
    const eventType = String(event.event || "").trim().toLowerCase();
    const casePrefix =
      event.caseIndex && event.caseTotal
        ? lang === "zh"
          ? `第 ${event.caseIndex}/${event.caseTotal} 个 case`
          : `Case ${event.caseIndex}/${event.caseTotal}`
        : "";
    const roleText = runRoleLabel(event.role);
    const reasonText = String(event.reason || "").trim();
    const elapsedText =
      typeof event.elapsedSeconds === "number" && Number.isFinite(event.elapsedSeconds)
        ? event.elapsedSeconds.toFixed(1)
        : "";

    if (eventType === "queued") {
      if (String(event.sourceKind || "").trim().toLowerCase() === "dataset") {
        const limitText =
          typeof event.datasetLimit === "number" && event.datasetLimit > 0
            ? String(event.datasetLimit)
            : lang === "zh"
              ? "全部"
              : "all";
        return lang === "zh"
          ? `已加入队列，来源数据集 ${event.datasetName || "--"}，样本上限 ${limitText}，bundle ${event.bundleName || "--"}。`
          : `Queued from dataset ${event.datasetName || "--"} with limit ${limitText} and bundle ${event.bundleName || "--"}.`;
      }
      return lang === "zh"
        ? `已加入队列，来源 bundle ${event.bundleName || "--"}。`
        : `Queued from bundle ${event.bundleName || "--"}.`;
    }

    if (eventType === "session_start") {
      return lang === "zh"
        ? `监督会话 ${event.sessionId || "--"} 已启动，bundle ${event.bundleName || "--"}，共 ${event.caseTotal ?? 0} 个 case。`
        : `Session ${event.sessionId || "--"} started with bundle ${event.bundleName || "--"} across ${event.caseTotal ?? 0} cases.`;
    }

    if (eventType === "role_start") {
      return lang === "zh"
        ? `${casePrefix || "当前 case"} ${event.caseId || "--"} 开始执行 ${roleText}，场景 ${event.scenario || "--"}，模式 ${event.mode || "--"}。`
        : `${casePrefix || "Current case"} ${event.caseId || "--"} started for ${roleText} in scenario ${event.scenario || "--"} and mode ${event.mode || "--"}.`;
    }

    if (eventType === "role_finish") {
      const statusText = statusLabel(event.resultStatus || event.status);
      return lang === "zh"
        ? `${casePrefix || "当前 case"} ${event.caseId || "--"} 的 ${roleText} 已完成，结果 ${statusText}${reasonText ? `，原因：${reasonText}` : ""}${elapsedText ? `，耗时 ${elapsedText}s` : ""}。`
        : `${casePrefix || "Current case"} ${event.caseId || "--"} finished for ${roleText} with ${statusText}${reasonText ? `, reason: ${reasonText}` : ""}${elapsedText ? `, elapsed ${elapsedText}s` : ""}.`;
    }

    if (eventType === "session_error") {
      const errorLabel = String(event.errorType || "").trim() || (lang === "zh" ? "异常" : "error");
      return lang === "zh"
        ? `${casePrefix || "当前 case"} ${event.caseId || "--"} 的 ${roleText} 出现 ${errorLabel}：${reasonText || event.summary}`
        : `${casePrefix || "Current case"} ${event.caseId || "--"} hit ${errorLabel} during ${roleText}: ${reasonText || event.summary}`;
    }

    if (
      eventType === "pause_requested"
      || eventType === "run_paused"
      || eventType === "run_resumed"
      || eventType === "stop_requested"
      || eventType === "run_cancelled"
    ) {
      return event.summary;
    }

    if (eventType === "session_finish" || eventType === "run_completed") {
      const decisionText = event.decision ? decisionLabel(event.decision) : "--";
      return lang === "zh"
        ? `监督结论为 ${decisionText}${reasonText ? `，原因：${reasonText}` : ""}。`
        : `The supervised decision is ${decisionText}${reasonText ? `, reason: ${reasonText}` : ""}.`;
    }

    if (eventType === "run_failed") {
      return lang === "zh"
        ? `这一轮监督运行失败了：${reasonText || event.summary}`
        : `This supervised run failed: ${reasonText || event.summary}`;
    }

    return event.summary;
  }

  function caseIoEntryLabel(kind: string, label: string) {
    const normalizedKind = String(kind || "").trim().toLowerCase();
    const normalizedLabel = String(label || "").trim();
    if (normalizedKind === "tool") {
      return normalizedLabel || t("ioEntryTool");
    }
    if (normalizedKind === "assistant") {
      return t("ioEntryAssistant");
    }
    if (normalizedKind === "error") {
      return normalizedLabel || t("ioEntryError");
    }
    return normalizedLabel || t("ioEntryPrompt");
  }

  function currentCaseOutputLabel(run: EvolutionActiveRun | null) {
    const outputKind = String(run?.currentCaseIo?.latestOutputKind || "").trim().toLowerCase();
    const outputLabel = String(run?.currentCaseIo?.latestOutputLabel || "").trim();
    if (outputKind === "tool") {
      return outputLabel || t("ioEntryTool");
    }
    if (outputKind === "assistant") {
      return t("ioEntryAssistant");
    }
    if (outputKind === "error") {
      return outputLabel || t("ioEntryError");
    }
    return t("currentCaseOutput");
  }

  function triggerRunAction(sessionId: string, action: string) {
    setActionFeedback("");
    actionMutation.mutate({ sessionId, action });
  }

  function toggleProposalSelection(sessionId: string) {
    setSelectedProposalRunIds((current) =>
      current.includes(sessionId)
        ? current.filter((item) => item !== sessionId)
        : [...current, sessionId],
    );
  }

  function proposalSelected(sessionId: string) {
    return selectedProposalRunIds.includes(sessionId);
  }

  function triggerProposalDelete(sessionId: string) {
    setLibraryFeedback("");
    deleteProposalMutation.mutate(sessionId);
  }

  function triggerBulkDelete() {
    if (selectedProposalRunIds.length === 0) {
      return;
    }
    setLibraryFeedback("");
    bulkDeleteMutation.mutate(selectedProposalRunIds);
  }

  function clearLibraryFilters() {
    setLibrarySearchInput("");
    setLibraryStatusFilter("all");
    setLibraryDeleteFilter("all");
  }

  function renderReviewList(lines: string[]) {
    if (lines.length === 0) {
      return <p>--</p>;
    }
    return (
      <ul className={styles.detailList}>
        {lines.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
    );
  }

  function renderRawJson(title: string, payload: Record<string, unknown> | null) {
    return (
      <details className={styles.rawBlock}>
        <summary>{title}</summary>
        <pre className={styles.rawJson}>{JSON.stringify(payload ?? {}, null, 2)}</pre>
      </details>
    );
  }

  return (
    <div className={styles.page}>
      <section className={styles.toolbar}>
        <div className={styles.toolbarIntro}>
          <p className={styles.eyebrow}>{routeEyebrow}</p>
          <h1 className={styles.title}>{routeTitle}</h1>
          <p className={styles.subtitle}>{routeSubtitle}</p>
        </div>

        <div className={styles.toolbarControls}>
          {showTrackToggle ? (
            <div className={styles.segmented}>
              {([
                { key: "supervised", label: t("supervisedEvolutionMode") },
                { key: "self", label: t("selfEvolutionMode") },
              ] as const).map((track) => (
                <button
                  key={track.key}
                  type="button"
                  className={
                    activeTrack === track.key
                      ? `${styles.segmentButton} ${styles.segmentButtonActive}`
                      : styles.segmentButton
                  }
                  onClick={() => setEvolutionTrack(track.key)}
                >
                  {track.label}
                </button>
              ))}
            </div>
          ) : null}

          {activeTrack === "supervised" ? (
            <>
              <SupervisedWorkspaceTabs activeView={evolutionView} />

              <div className={styles.intakeControl}>
                <span className={styles.controlLabel}>{t("intakeMode")}</span>
                <div className={styles.intakeSegmented}>
                  {(["manual_review", "auto"] as const).map((mode) => (
                    <button
                      key={mode}
                      type="button"
                      className={
                        currentIntakeMode === mode
                          ? `${styles.intakeButton} ${styles.intakeButtonActive}`
                          : styles.intakeButton
                      }
                      disabled={intakeModeMutation.isPending}
                      onClick={() => intakeModeMutation.mutate(mode)}
                    >
                      {intakeModeLabel(mode)}
                    </button>
                  ))}
                </div>
              </div>
            </>
          ) : null}
        </div>
      </section>

      {activeTrack === "self" ? (
        <SelfEvolutionTrack
          overview={selfOverviewQuery.data}
          latestRun={monitoredSelfRun}
          goalInput={selfGoalInput}
          onGoalInputChange={setSelfGoalInput}
          onStartRun={() => startSelfRunMutation.mutate()}
          onPauseRun={() => monitoredSelfRun && pauseSelfRunMutation.mutate(monitoredSelfRun.runId)}
          onResumeRun={() => monitoredSelfRun && resumeSelfRunMutation.mutate(monitoredSelfRun.runId)}
          onTerminateRun={() => monitoredSelfRun && stopSelfRunMutation.mutate(monitoredSelfRun.runId)}
          onRollbackRun={() => monitoredSelfRun && rollbackSelfRunMutation.mutate(monitoredSelfRun.runId)}
          onHandoffRun={() => monitoredSelfRun && handoffSelfRunMutation.mutate(monitoredSelfRun.runId)}
          onDeleteHistoryGroups={(txnIds) => deleteSelfHistoryMutation.mutate(txnIds)}
          startPending={startSelfRunMutation.isPending}
          pausePending={pauseSelfRunMutation.isPending}
          resumePending={resumeSelfRunMutation.isPending}
          terminatePending={stopSelfRunMutation.isPending}
          rollbackPending={rollbackSelfRunMutation.isPending}
          handoffPending={handoffSelfRunMutation.isPending}
          deleteHistoryPending={deleteSelfHistoryMutation.isPending}
          startError={startSelfRunMutation.error?.message ?? ""}
          pauseError={pauseSelfRunMutation.error?.message ?? ""}
          resumeError={resumeSelfRunMutation.error?.message ?? ""}
          terminateError={stopSelfRunMutation.error?.message ?? ""}
          rollbackError={rollbackSelfRunMutation.error?.message ?? ""}
          handoffError={handoffSelfRunMutation.error?.message ?? ""}
          deleteHistoryError={deleteSelfHistoryMutation.error?.message ?? ""}
          actionFeedback={selfActionFeedback}
          runLocked={selfRunLocked}
          transactions={selfTransactionsQuery.data ?? []}
          loading={selfOverviewQuery.isLoading || selfLatestRunQuery.isLoading || selfTransactionsQuery.isLoading}
        />
      ) : null}

      {activeTrack === "supervised" && evolutionView === "live" ? (
        <div className={styles.overviewGrid}>
          <section className={`${styles.surface} ${styles.launchSurface} ${styles.dashboardLaunch}`}>
              <div className={styles.surfaceHeaderCompact}>
                <div>
                  <p className={styles.eyebrow}>{t("supervisedControl")}</p>
                  <h2 className={styles.sectionTitle}>{t("launchSupervisedRun")}</h2>
                </div>
                <span className={styles.secondaryPill}>
                  {sourceKindLabel(sourceKind)}
                </span>
              </div>
              <p className={styles.noticeText}>{t("launchSupervisedRunHint")}</p>

              <div className={styles.metricStrip}>
                <article className={styles.stripItem}>
                  <span>{t("availableDatasets")}</span>
                  <strong>{workbenchState?.availableDatasets ?? 0}</strong>
                </article>
                <article className={styles.stripItem}>
                  <span>{t("runnableDatasets")}</span>
                  <strong>{workbenchState?.runnableDatasets ?? 0}</strong>
                </article>
                <article className={styles.stripItem}>
                  <span>{t("blockedDatasets")}</span>
                  <strong>{workbenchState?.blockedDatasets ?? 0}</strong>
                </article>
              </div>

              <div className={styles.segmented}>
                {(["dataset", "bundle"] as const).map((value) => (
                  <button
                    key={value}
                    type="button"
                    className={
                      sourceKind === value
                        ? `${styles.segmentButton} ${styles.segmentButtonActive}`
                        : styles.segmentButton
                    }
                    onClick={() => setSourceKind(value)}
                  >
                    {sourceKindLabel(value)}
                  </button>
                ))}
              </div>

              <div className={styles.formGrid}>
                {sourceKind === "dataset" ? (
                  <>
                    <div className={styles.compactFieldGrid}>
                      <div className={styles.formField}>
                        <label htmlFor="supervised-dataset">{t("selectedDataset")}</label>
                        <select
                          id="supervised-dataset"
                          className={styles.selectInput}
                          value={datasetName}
                          onChange={(event) => setDatasetName(event.target.value)}
                        >
                          {workbenchControl?.datasets.map((item) => (
                            <option key={item.name} value={item.name}>
                              {item.name} [{item.runnable ? "ready" : item.adapterStatus}]
                            </option>
                          ))}
                        </select>
                      </div>
                      <div className={styles.formField}>
                        <label htmlFor="supervised-limit">{t("caseLimit")}</label>
                        <input
                          id="supervised-limit"
                          className={styles.textInput}
                          type="number"
                          min={1}
                          placeholder="all"
                          value={datasetLimitInput}
                          onChange={(event) => setDatasetLimitInput(event.target.value)}
                        />
                      </div>
                    </div>
                    {selectedDataset ? (
                      <div className={styles.datasetMetaCompact}>
                        <div className={styles.listRowTop}>
                          <strong>{selectedDataset.bundleName}</strong>
                          <span className={styles.secondaryPill}>
                            {selectedDataset.runnable ? "ready" : selectedDataset.adapterStatus}
                          </span>
                        </div>
                        <p>{selectedDataset.description}</p>
                      </div>
                    ) : null}
                  </>
                ) : (
                  <div className={styles.formField}>
                    <label htmlFor="supervised-bundle">{t("selectedBundle")}</label>
                    <input
                      id="supervised-bundle"
                      className={styles.textInput}
                      type="text"
                      value={bundleNameInput}
                      onChange={(event) => setBundleNameInput(event.target.value)}
                    />
                  </div>
                )}

                <label className={styles.checkboxRow}>
                  <input
                    type="checkbox"
                    checked={keepWorktree}
                    onChange={(event) => setKeepWorktree(event.target.checked)}
                  />
                  <span className={styles.checkboxLabel}>{t("keepWorktreeLabel")}</span>
                </label>
              </div>

              <div className={styles.controlFooter}>
                <div className={styles.controlActions}>
                  <button
                    type="button"
                    className={styles.inlineAction}
                    disabled={runLocked || startRunMutation.isPending}
                    onClick={() => startRunMutation.mutate()}
                  >
                    {startRunMutation.isPending ? <LoaderCircle size={15} /> : <Play size={15} />}
                    {t("startSupervisedRun")}
                  </button>
                </div>
                {runLocked ? <p className={styles.noticeText}>{t("runningLockHint")}</p> : null}
                {supervisedControlError ? (
                  <p className={styles.errorText}>{supervisedControlError}</p>
                ) : null}
              </div>
          </section>

          <section className={`${styles.surface} ${styles.liveSurface} ${styles.dashboardRun}`}>
              <div className={styles.surfaceHeaderCompact}>
                <div>
                  <p className={styles.eyebrow}>{t("activeSupervisedRun")}</p>
                  <h2 className={styles.sectionTitle}>
                    {monitoredRun?.sessionId || monitoredRun?.runId || t("activeSupervisedRun")}
                  </h2>
                </div>
                {monitoredRun ? (
                  <div className={styles.heroHeadingRow}>
                    <span className={styles.statusPill}>{statusLabel(monitoredRun.status)}</span>
                    <span className={styles.secondaryPill}>{sourceKindLabel(monitoredRun.sourceKind)}</span>
                  </div>
                ) : (
                  <span className={styles.secondaryPill}>
                    {workbenchSourceLabel(workbenchState?.source ?? "unknown")}
                  </span>
                )}
              </div>

              {monitoredRun ? (
                <div className={styles.runMonitorDense}>
                  <div className={styles.controlActions}>
                    <button
                      type="button"
                      className={styles.inlineAction}
                      disabled={!canPauseSupervisedRun || pauseRunMutation.isPending}
                      title={disabledReason(pauseSupervisedAction) || undefined}
                      onClick={() => monitoredRun && pauseRunMutation.mutate(monitoredRun.runId)}
                    >
                      {pauseRunMutation.isPending ? <LoaderCircle size={15} /> : <Pause size={15} />}
                      {t("pauseSupervisedRun")}
                    </button>
                    <button
                      type="button"
                      className={styles.inlineAction}
                      disabled={!canResumeSupervisedRun || resumeRunMutation.isPending}
                      title={disabledReason(resumeSupervisedAction) || undefined}
                      onClick={() => monitoredRun && resumeRunMutation.mutate(monitoredRun.runId)}
                    >
                      {resumeRunMutation.isPending ? <LoaderCircle size={15} /> : <Play size={15} />}
                      {t("resumeSupervisedRun")}
                    </button>
                    <button
                      type="button"
                      className={styles.inlineAction}
                      disabled={!canTerminateSupervisedRun || terminateRunMutation.isPending}
                      title={disabledReason(terminateSupervisedAction) || undefined}
                      onClick={() => monitoredRun && terminateRunMutation.mutate(monitoredRun.runId)}
                    >
                      {terminateRunMutation.isPending ? <LoaderCircle size={15} /> : <Square size={15} />}
                      {t("terminateSupervisedRun")}
                    </button>
                  </div>

                  {actionFeedback ? <p className={styles.feedbackText}>{actionFeedback}</p> : null}
                  {supervisedControlError ? <p className={styles.errorText}>{supervisedControlError}</p> : null}
                  {!canPauseSupervisedRun && disabledReason(pauseSupervisedAction) ? (
                    <p className={styles.noticeText}>{disabledReason(pauseSupervisedAction)}</p>
                  ) : null}
                  {!canResumeSupervisedRun && disabledReason(resumeSupervisedAction) && (runPaused || runPauseRequested) ? (
                    <p className={styles.noticeText}>{disabledReason(resumeSupervisedAction)}</p>
                  ) : null}
                  {!canTerminateSupervisedRun && disabledReason(terminateSupervisedAction) && runStopping ? (
                    <p className={styles.noticeText}>{disabledReason(terminateSupervisedAction)}</p>
                  ) : null}

                  <div className={styles.monitorSummary}>
                    <div className={styles.heroHeadingRow}>
                      <span className={styles.statusIcon}>{statusIcon(monitoredRun.status)}</span>
                      <p className={styles.heroSummary}>{monitoredRun.latestMessage}</p>
                    </div>
                  </div>

                  <div className={styles.monitorMetricsDense}>
                    <article className={styles.metricTile}>
                      <span>{t("activeRunSession")}</span>
                      <strong>{monitoredRun.sessionId || monitoredRun.runId}</strong>
                    </article>
                    <article className={styles.metricTile}>
                      <span>{t("activeRunPhase")}</span>
                      <strong>{statusLabel(monitoredRun.currentPhase || monitoredRun.status)}</strong>
                    </article>
                    <article className={styles.metricTile}>
                      <span>{t("activeRunCurrentCase")}</span>
                      <strong>
                        {monitoredRun.currentCaseId
                          ? `${monitoredRun.currentCaseIndex}/${monitoredRun.caseTotal} ${monitoredRun.currentCaseId}`
                          : "--"}
                      </strong>
                    </article>
                    <article className={styles.metricTile}>
                      <span>{t("activeRunCurrentRole")}</span>
                      <strong>{monitoredRun.currentRole || "--"}</strong>
                    </article>
                    <article className={styles.metricTile}>
                      <span>{t("activeRunCurrentTask")}</span>
                      <strong>{monitoredRun.currentTask || monitoredRun.latestMessage || "--"}</strong>
                    </article>
                    <article className={styles.metricTile}>
                      <span>{t("latestLiveMessage")}</span>
                      <strong>{compactTimestamp(monitoredRun.updatedAt)}</strong>
                    </article>
                  </div>

                  <div className={`${styles.detailSection} ${styles.detailSectionCompact}`}>
                    <h3>{t("activeRunTimeline")}</h3>
                    <div className={`${styles.eventList} ${styles.eventListScrollable}`}>
                      {monitoredRun.eventTail.map((item) => (
                        <article key={`${item.timestamp}-${item.event}-${item.summary}`} className={styles.eventRow}>
                          <div className={styles.eventHeader}>
                            <strong>{formatRunEventTitle(item)}</strong>
                            <span className={styles.secondaryPill}>{statusLabel(item.status)}</span>
                          </div>
                          <p className={styles.eventSummary}>{formatRunEventSummary(item)}</p>
                          <span className={styles.formHint}>{compactTimestamp(item.timestamp)}</span>
                        </article>
                      ))}
                    </div>
                  </div>

                  {monitoredRun.sessionId ? (
                    <button
                      type="button"
                      className={styles.inlineAction}
                      onClick={() => openRun(monitoredRun.sessionId)}
                    >
                      <Activity size={15} />
                      {t("openLatestRuns")}
                    </button>
                  ) : null}
                </div>
              ) : (
                <div className={styles.idleMonitor}>
                  <p className={styles.noticeText}>{t("noActiveSupervisedRun")}</p>
                  <div className={styles.metricStrip}>
                    <article className={styles.stripItem}>
                      <span>{t("latestRun")}</span>
                      <strong>{latestRun?.id ?? "--"}</strong>
                    </article>
                    <article className={styles.stripItem}>
                      <span>{t("pendingCandidates")}</span>
                      <strong>{pendingItems.length}</strong>
                    </article>
                    <article className={styles.stripItem}>
                      <span>{t("selectedBundle")}</span>
                      <strong>{workbenchState?.bundleName || "--"}</strong>
                    </article>
                  </div>
                  <div className={styles.relatedList}>
                    <article className={styles.relatedRow}>
                      <strong>{t("latestScore")}</strong>
                      <span>{latestRun ? clampScore(latestRun.candidateScore) : "--"}</span>
                    </article>
                    <article className={styles.relatedRow}>
                      <strong>{t("selectedDataset")}</strong>
                      <span>{workbenchState?.datasetName || "--"}</span>
                    </article>
                  </div>
                  <div className={styles.actionRow}>
                    <button
                      type="button"
                      className={styles.inlineAction}
                      disabled={!latestRun}
                      onClick={() => openRun(latestRun?.id ?? null)}
                    >
                      <Activity size={15} />
                      {t("openLatestRuns")}
                    </button>
                    <button
                      type="button"
                      className={styles.inlineAction}
                      onClick={() => {
                        setLibraryView("items");
                        goToSupervisedView("library");
                      }}
                    >
                      <LibraryBig size={15} />
                      {t("openLibraryQueue")}
                    </button>
                  </div>
                </div>
              )}
          </section>

          <section className={`${styles.surface} ${styles.ioSurface} ${styles.dashboardIo}`}>
              <div className={styles.surfaceHeaderCompact}>
                <div>
                  <p className={styles.eyebrow}>{t("currentCaseTranscript")}</p>
                  <h2 className={styles.sectionTitle}>
                    {monitoredRun?.currentCaseId || t("currentCaseOutput")}
                  </h2>
                </div>
                <div className={styles.heroHeadingRow}>
                  {monitoredRun?.currentRole ? (
                    <span className={styles.secondaryPill}>{runRoleLabel(monitoredRun.currentRole)}</span>
                  ) : null}
                  {monitoredRun?.currentCaseScenario ? (
                    <span className={styles.secondaryPill}>{monitoredRun.currentCaseScenario}</span>
                  ) : null}
                  {monitoredRun?.currentCaseMode ? (
                    <span className={styles.secondaryPill}>{monitoredRun.currentCaseMode}</span>
                  ) : null}
                </div>
              </div>

              {monitoredCaseHasVisibleIo ? (
                <div className={styles.ioStack}>
                  {monitoredRun?.currentCasePrompt ? (
                    <div className={`${styles.detailSection} ${styles.detailSectionCompact}`}>
                      <h3>{t("currentCasePrompt")}</h3>
                      <div className={styles.rawBlock}>
                        <pre className={styles.ioContent}>{monitoredRun.currentCasePrompt}</pre>
                      </div>
                    </div>
                  ) : null}

                  <div className={`${styles.detailSection} ${styles.detailSectionCompact}`}>
                    <h3>{currentCaseOutputLabel(monitoredRun)}</h3>
                    {monitoredRun?.currentCaseIo?.latestOutput ? (
                      <div className={styles.rawBlock}>
                        <pre className={styles.ioContent}>{monitoredRun.currentCaseIo.latestOutput}</pre>
                      </div>
                    ) : (
                      <p className={styles.noticeText}>{t("caseIoWaiting")}</p>
                    )}
                  </div>

                  <div className={`${styles.detailSection} ${styles.detailSectionCompact}`}>
                    <h3>{t("currentCaseTranscript")}</h3>
                    {monitoredCaseTranscript.length > 0 ? (
                      <div className={styles.ioTranscript}>
                        {monitoredCaseTranscript.map((entry, index) => (
                          <article
                            key={`${entry.timestamp}-${entry.kind}-${entry.label}-${index}`}
                            className={styles.ioEntry}
                          >
                            <div className={styles.ioMetaRow}>
                              <strong>{caseIoEntryLabel(entry.kind, entry.label)}</strong>
                              <span className={styles.formHint}>{compactTimestamp(entry.timestamp)}</span>
                            </div>
                            <pre className={styles.ioContent}>{entry.content}</pre>
                          </article>
                        ))}
                      </div>
                    ) : (
                      <p className={styles.noticeText}>{t("caseIoWaiting")}</p>
                    )}
                  </div>
                </div>
              ) : (
                <div className={styles.ioWaitingState}>
                  <p className={styles.noticeText}>{t("noCurrentCaseIo")}</p>
                </div>
              )}
          </section>

          <section className={`${styles.surface} ${styles.sourceSurface} ${styles.dashboardSource}`}>
              <div className={styles.surfaceHeader}>
                <div>
                  <p className={styles.eyebrow}>{t("workbenchContext")}</p>
                  <h2 className={styles.sectionTitle}>{t("selectedSource")}</h2>
                </div>
                <span className={styles.secondaryPill}>
                  {workbenchSourceLabel(workbenchState?.source ?? "unknown")}
                </span>
              </div>
              <div className={styles.listStack}>
                <article className={styles.listRow}>
                  <div className={styles.metaRow}>
                    <span>{t("datasetNameLabel")}</span>
                    <span>{workbenchState?.datasetName || "--"}</span>
                  </div>
                  <div className={styles.metaRow}>
                    <span>{t("bundleNameLabel")}</span>
                    <span>{workbenchState?.bundleName || "--"}</span>
                  </div>
                  <div className={styles.metaRow}>
                    <span>{t("datasetLimitLabel")}</span>
                    <span>{workbenchState?.datasetLimit ?? "--"}</span>
                  </div>
                </article>
                <div className={styles.actionGridCompact}>
                  <button
                    type="button"
                    className={styles.actionButton}
                    disabled={intakeModeMutation.isPending}
                    onClick={() => intakeModeMutation.mutate(nextIntakeMode)}
                  >
                    <Sparkles size={16} />
                    <span>{t("switchIntakeMode")}</span>
                  </button>
                  <button
                    type="button"
                    className={styles.actionButton}
                    disabled={!latestRun}
                    onClick={() => openRun(latestRun?.id ?? null)}
                  >
                    <ArrowUpRight size={16} />
                    <span>{t("openLatestRuns")}</span>
                  </button>
                  <button
                    type="button"
                    className={styles.actionButton}
                    onClick={() => {
                      setLibraryView("items");
                      goToSupervisedView("library");
                    }}
                  >
                    <LibraryBig size={16} />
                    <span>{t("openLibraryQueue")}</span>
                  </button>
                </div>
              </div>
          </section>
        </div>
      ) : null}

      {activeTrack === "supervised" && evolutionView === "runs" ? (
        <div className={styles.viewStack}>
          <div className={styles.overviewWorkspace}>
            <section className={`${styles.surface} ${styles.summarySurface}`}>
              <div className={styles.surfaceHeaderCompact}>
                <div>
                  <p className={styles.eyebrow}>{t("recentRunPerformance")}</p>
                  <h2 className={styles.sectionTitle}>{t("runList")}</h2>
                </div>
                <div className={styles.filterSegmented}>
                  {(["all", "success", "failed"] as const).map((filter) => (
                    <button
                      key={filter}
                      type="button"
                      className={
                        runFilter === filter
                          ? `${styles.filterButton} ${styles.filterButtonActive}`
                          : styles.filterButton
                      }
                      onClick={() => setRunFilter(filter)}
                    >
                      {filter === "all" ? t("allRuns") : statusLabel(filter)}
                    </button>
                  ))}
                </div>
              </div>
              <div className={styles.summaryMetricStrip}>
                <article className={styles.stripItem}>
                  <span>{t("runs")}</span>
                  <strong>{runs.length}</strong>
                </article>
                <article className={styles.stripItem}>
                  <span>{statusLabel("success")}</span>
                  <strong>{runSuccessCount}</strong>
                </article>
                <article className={styles.stripItem}>
                  <span>{statusLabel("failed")}</span>
                  <strong>{runFailedCount}</strong>
                </article>
                <article className={styles.stripItem}>
                  <span>{t("pendingReview")}</span>
                  <strong>{runPendingCount}</strong>
                </article>
              </div>
              <p className={styles.noticeText}>{t("runQueueHint")}</p>
            </section>

            <section className={`${styles.surface} ${styles.summarySurface}`}>
              <div className={styles.surfaceHeaderCompact}>
                <div>
                  <p className={styles.eyebrow}>{t("runQueue")}</p>
                  <h2 className={styles.sectionTitle}>{t("runs")}</h2>
                </div>
                <span className={styles.secondaryPill}>
                  {hasRuns ? `${filteredRuns.length} / ${runs.length}` : "0 / 0"}
                </span>
              </div>
              <p className={styles.statusLead}>{runHeaderMessage}</p>
              <div className={styles.relatedList}>
                <article className={styles.relatedRow}>
                  <strong>{t("latestRun")}</strong>
                  <span>{latestRun?.id ?? "--"}</span>
                </article>
                <article className={styles.relatedRow}>
                  <strong>{t("pendingReview")}</strong>
                  <span>{runPendingCount}</span>
                </article>
              </div>
              {!hasRuns ? (
                <div className={styles.actionRow}>
                  <button
                    type="button"
                    className={styles.inlineAction}
                    onClick={() => goToSupervisedView("live")}
                  >
                    <ArrowUpRight size={15} />
                    {t("returnToOverview")}
                  </button>
                </div>
              ) : filteredRunsEmpty ? (
                <div className={styles.actionRow}>
                  <button
                    type="button"
                    className={styles.inlineAction}
                    onClick={() => setRunFilter("all")}
                  >
                    {t("allRuns")}
                  </button>
                </div>
              ) : null}
            </section>

            <section className={`${styles.surface} ${styles.summarySurface}`}>
              <div className={styles.surfaceHeaderCompact}>
                <div>
                  <p className={styles.eyebrow}>{t("runDetail")}</p>
                  <h2 className={styles.sectionTitle}>{selectedRun?.id ?? "--"}</h2>
                </div>
                <span className={selectedRun ? styles.statusPill : styles.secondaryPill}>
                  {selectedRun
                    ? decisionLabel(selectedRun.decision)
                    : runFilter === "all"
                      ? t("allRuns")
                      : statusLabel(runFilter)}
                </span>
              </div>
              <p className={styles.statusLead}>
                {selectedRun
                  ? selectedRun.summary
                  : hasRuns
                    ? t("runDetailFilterHint")
                    : t("runDetailPlaceholder")}
              </p>
              <div className={styles.statusMetricGrid}>
                <article className={styles.metricTile}>
                  <span>{t("latestScore")}</span>
                  <strong>{selectedRun ? clampScore(selectedRun.candidateScore) : "--"}</strong>
                </article>
                <article className={styles.metricTile}>
                  <span>{t("runLayer")}</span>
                  <strong>{selectedRun ? selectedRun.runSemantics.runStatusLabel : "--"}</strong>
                </article>
                <article className={styles.metricTile}>
                  <span>{t("proposalLayer")}</span>
                  <strong>{selectedRun ? selectedRun.outcomeSemantics.proposalStatusLabel : "--"}</strong>
                </article>
                <article className={styles.metricTile}>
                  <span>{t("runtimeLayer")}</span>
                  <strong>{selectedRun ? selectedRun.outcomeSemantics.runtimeEffectLabel : "--"}</strong>
                </article>
              </div>
            </section>
          </div>

          <div className={styles.runsWorkspace}>
            <section className={`${styles.surface} ${styles.runQueuePanel}`}>
              <div className={styles.panelHeader}>
                <div>
                  <p className={styles.eyebrow}>{t("runQueue")}</p>
                  <h2 className={styles.sectionTitle}>{t("runs")}</h2>
                </div>
                <span className={styles.secondaryPill}>{filteredRuns.length}</span>
              </div>
              <p className={styles.noticeText}>{t("runQueueHint")}</p>
              {!hasRuns ? (
                <div className={styles.structuredEmptyState}>
                  <h3>{t("noSupervisedRunsYet")}</h3>
                  <p>{t("noRunsRecordedHint")}</p>
                  <div className={styles.actionRow}>
                    <button
                      type="button"
                      className={styles.inlineAction}
                      onClick={() => goToSupervisedView("live")}
                    >
                      <ArrowUpRight size={15} />
                      {t("returnToOverview")}
                    </button>
                  </div>
                </div>
              ) : filteredRunsEmpty ? (
                <div className={styles.structuredEmptyState}>
                  <h3>{t("noRunMatches")}</h3>
                  <p>{t("runFilterEmptyHint")}</p>
                  <div className={styles.actionRow}>
                    <button
                      type="button"
                      className={styles.inlineAction}
                      onClick={() => setRunFilter("all")}
                    >
                      {t("allRuns")}
                    </button>
                  </div>
                </div>
              ) : (
                <div className={styles.runListScrollable}>
                  {filteredRuns.map((run) => (
                    <button
                      key={run.id}
                      type="button"
                      className={
                        selectedRun?.id === run.id
                          ? `${styles.runItem} ${styles.runItemActive}`
                          : styles.runItem
                      }
                      onClick={() => setSelectedRunId(run.id)}
                    >
                      <div className={styles.listRowTop}>
                        <strong>{run.id}</strong>
                        <span className={styles.secondaryPill}>{decisionLabel(run.decision)}</span>
                      </div>
                      <div className={styles.metaRow}>
                        <span>{statusLabel(run.status)}</span>
                        <span>{run.outcomeSemantics.proposalStatusLabel}</span>
                      </div>
                      <div className={styles.scoreRow}>
                        <span>{run.bundleName || "--"}</span>
                        <strong>{run.candidateScore}</strong>
                      </div>
                      <p>{run.summary}</p>
                      <div className={styles.cardFooter}>
                        <span>{riskLabel(run.riskLevel)}</span>
                        <span>{run.nextAction || "--"}</span>
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </section>

            <section className={`${styles.surface} ${styles.runDetailPanel}`}>
              {selectedRun ? (
                <>
                  <div className={styles.detailHeader}>
                    <div>
                      <p className={styles.eyebrow}>{t("runDetail")}</p>
                      <h2 className={styles.detailTitle}>{selectedRun.id}</h2>
                    </div>
                    <div className={styles.detailHeaderActions}>
                      <span className={styles.statusPill}>{decisionLabel(selectedRun.decision)}</span>
                      <span className={styles.secondaryPill}>{selectedRun.outcomeSemantics.proposalStatusLabel}</span>
                    </div>
                  </div>

                  <div className={styles.runDetailOverview}>
                    <div>
                      <p className={styles.detailLead}>{selectedRun.candidateScore}</p>
                      <p className={styles.reviewLead}>{selectedRun.summary}</p>
                    </div>
                    <div className={styles.runDetailMetricGrid}>
                      <article className={styles.metricTile}>
                        <span>{t("baselineScore")}</span>
                        <strong>{selectedRun.baselineScore}</strong>
                      </article>
                      <article className={styles.metricTile}>
                        <span>{t("candidateScore")}</span>
                        <strong>{selectedRun.candidateScore}</strong>
                      </article>
                      <article className={styles.metricTile}>
                        <span>{t("scoreDelta")}</span>
                        <strong>{selectedRun.deltaScore}</strong>
                      </article>
                      <article className={styles.metricTile}>
                        <span>{t("linkedItems")}</span>
                        <strong>{relatedProposalCount}</strong>
                      </article>
                    </div>
                  </div>

                  <div className={styles.detailSection}>
                    <h3>{t("diagnosis")}</h3>
                    <p className={styles.reviewLead}>{selectedRun.diagnosis}</p>
                  </div>

                  <div className={styles.detailSection}>
                    <h3>{t("resultLayersTitle")}</h3>
                    <div className={styles.detailFactGrid}>
                      <article className={styles.relatedRow}>
                        <strong>{t("runLayer")}</strong>
                        <span>{selectedRun.runSemantics.runStatusLabel}</span>
                      </article>
                      <article className={styles.relatedRow}>
                        <strong>{t("decision")}</strong>
                        <span>{selectedRun.outcomeSemantics.decisionLabel}</span>
                      </article>
                      <article className={styles.relatedRow}>
                        <strong>{t("proposalLayer")}</strong>
                        <span>{selectedRun.outcomeSemantics.proposalStatusLabel}</span>
                      </article>
                      <article className={styles.relatedRow}>
                        <strong>{t("runtimeLayer")}</strong>
                        <span>{selectedRun.outcomeSemantics.runtimeEffectLabel}</span>
                      </article>
                      <article className={styles.relatedRow}>
                        <strong>{t("nextRecommendedAction")}</strong>
                        <span>{selectedRun.runSemantics.nextAction}</span>
                      </article>
                      <article className={styles.relatedRow}>
                        <strong>{t("riskLevel")}</strong>
                        <span>{riskLabel(selectedRun.riskLevel)}</span>
                      </article>
                    </div>
                    <p className={styles.noticeText}>{selectedRun.outcomeSemantics.runtimeExplanation}</p>
                    {selectedRun.riskReasons.length > 0 ? (
                      <p>{selectedRun.riskReasons.join(" / ")}</p>
                    ) : null}
                    {selectedRun.availableActions.length > 0 ? (
                      <div className={styles.actionRow}>
                        {selectedRun.availableActions.map((action) => (
                          <button
                            key={action}
                            type="button"
                            className={styles.inlineAction}
                            disabled={runLocked || actionMutation.isPending}
                            onClick={() => triggerRunAction(selectedRun.id, action)}
                          >
                            <Sparkles size={15} />
                            {proposalActionLabel(action)}
                          </button>
                        ))}
                      </div>
                    ) : null}
                    {actionFeedback ? <p className={styles.feedbackText}>{actionFeedback}</p> : null}
                    {actionMutation.error ? <p className={styles.errorText}>{actionMutation.error.message}</p> : null}
                  </div>

                  <div className={styles.detailSection}>
                    <h3>{t("deleteAndCleanup")}</h3>
                    <div className={styles.relatedList}>
                      <article className={styles.relatedRow}>
                        <strong>{selectedRun.canDelete ? t("deletionAllowed") : t("deletionBlocked")}</strong>
                        <span>
                          {selectedRun.canDelete
                            ? t("deleteRunRecord")
                            : selectedRun.deleteBlockReason || "--"}
                        </span>
                      </article>
                    </div>
                    <p>{t("runDeleteImpact")}</p>
                    <div className={styles.actionRow}>
                      <button
                        type="button"
                        className={styles.inlineAction}
                        disabled={!selectedRun.canDelete || deleteProposalMutation.isPending}
                        onClick={() => triggerProposalDelete(selectedRun.id)}
                      >
                        <Trash2 size={15} />
                        {t("deleteRunRecord")}
                      </button>
                    </div>
                  </div>

                  <div className={styles.detailSection}>
                    <h3>{t("outputsWorthPromoting")}</h3>
                    {relatedLibraryItems.length === 0 && relatedPendingItems.length === 0 ? (
                      <p>{t("noPromotionCandidates")}</p>
                    ) : (
                      <div className={styles.relatedList}>
                        {relatedLibraryItems.map((item) => (
                          <article key={item.id} className={styles.relatedRow}>
                            <div className={styles.listRowTop}>
                              <strong>{item.title}</strong>
                              <span>{statusLabel(item.proposalStatus)}</span>
                            </div>
                            <p>{item.changeSummary || item.headline}</p>
                            <div className={styles.actionRow}>
                              <button
                                type="button"
                                className={styles.inlineAction}
                                onClick={() => openProposalFromRun(item, "items")}
                              >
                                <ArrowUpRight size={15} />
                                {t("openProposal")}
                              </button>
                              <button
                                type="button"
                                className={styles.inlineAction}
                                disabled={!item.canDelete || deleteProposalMutation.isPending}
                                onClick={() => triggerProposalDelete(item.sourceRun)}
                              >
                                <Trash2 size={15} />
                                {t("deleteProposal")}
                              </button>
                            </div>
                            {!item.canDelete && item.deleteBlockReason ? (
                              <p>{item.deleteBlockReason}</p>
                            ) : null}
                          </article>
                        ))}
                        {relatedPendingItems.map((item) => (
                          <article key={item.id} className={styles.relatedRow}>
                            <div className={styles.listRowTop}>
                              <strong>{item.title}</strong>
                              <span>{statusLabel(item.proposalStatus)}</span>
                            </div>
                            <p>{item.changeSummary || item.headline}</p>
                            <div className={styles.actionRow}>
                              <button
                                type="button"
                                className={styles.inlineAction}
                                onClick={() => openProposalFromRun(item, "pending")}
                              >
                                <ArrowUpRight size={15} />
                                {t("openProposal")}
                              </button>
                              <button
                                type="button"
                                className={styles.inlineAction}
                                disabled={!item.canDelete || deleteProposalMutation.isPending}
                                onClick={() => triggerProposalDelete(item.sourceRun)}
                              >
                                <Trash2 size={15} />
                                {t("deleteProposal")}
                              </button>
                            </div>
                            {!item.canDelete && item.deleteBlockReason ? (
                              <p>{item.deleteBlockReason}</p>
                            ) : null}
                          </article>
                        ))}
                      </div>
                    )}
                    {libraryFeedback ? <p className={styles.feedbackText}>{libraryFeedback}</p> : null}
                    {deleteProposalMutation.error ? <p className={styles.errorText}>{deleteProposalMutation.error.message}</p> : null}
                  </div>
                </>
              ) : (
                <div className={styles.structuredEmptyState}>
                  <p className={styles.eyebrow}>{t("runDetail")}</p>
                  <h3>{hasRuns ? t("noRunMatches") : t("noSupervisedRunsYet")}</h3>
                  <p>{hasRuns ? t("runDetailFilterHint") : t("runDetailPlaceholder")}</p>
                  <div className={styles.detailFactGrid}>
                    <article className={styles.relatedRow}>
                      <strong>{t("score")}</strong>
                      <span>--</span>
                    </article>
                    <article className={styles.relatedRow}>
                      <strong>{t("proposalStatus")}</strong>
                      <span>--</span>
                    </article>
                  </div>
                  <div className={styles.actionRow}>
                    {!hasRuns ? (
                      <button
                        type="button"
                        className={styles.inlineAction}
                        onClick={() => goToSupervisedView("live")}
                      >
                        <ArrowUpRight size={15} />
                        {t("returnToOverview")}
                      </button>
                    ) : (
                      <button
                        type="button"
                        className={styles.inlineAction}
                        onClick={() => setRunFilter("all")}
                      >
                        {t("allRuns")}
                      </button>
                    )}
                  </div>
                </div>
              )}
            </section>
          </div>
        </div>
      ) : null}

      {activeTrack === "supervised" && evolutionView === "library" ? (
        <div className={styles.viewStack}>
          <div className={styles.overviewWorkspace}>
            <section className={`${styles.surface} ${styles.summarySurface}`}>
              <div className={styles.surfaceHeaderCompact}>
                <div>
                  <p className={styles.eyebrow}>{t("recentLibraryAdditions")}</p>
                  <h2 className={styles.sectionTitle}>{t("library")}</h2>
                </div>
                <div className={styles.filterSegmented}>
                  {(["items", "pending"] as const).map((view) => (
                    <button
                      key={view}
                      type="button"
                      className={
                        libraryView === view
                          ? `${styles.filterButton} ${styles.filterButtonActive}`
                          : styles.filterButton
                      }
                      onClick={() => setLibraryView(view)}
                    >
                      {view === "items" ? t("libraryItems") : t("pendingReview")}
                    </button>
                  ))}
                </div>
              </div>
              <div className={styles.summaryMetricStrip}>
                <article className={styles.stripItem}>
                  <span>{t("libraryItems")}</span>
                  <strong>{libraryItems.length}</strong>
                </article>
                <article className={styles.stripItem}>
                  <span>{t("pendingReview")}</span>
                  <strong>{pendingItems.length}</strong>
                </article>
                <article className={styles.stripItem}>
                  <span>{t("intakeMode")}</span>
                  <strong>{intakeModeLabel(currentIntakeMode)}</strong>
                </article>
                <article className={styles.stripItem}>
                  <span>{t("selectedCount")}</span>
                  <strong>{selectedProposalRunIds.length}</strong>
                </article>
              </div>
              <p className={styles.noticeText}>{t("batchDeleteHint")}</p>
            </section>

            <section className={`${styles.surface} ${styles.summarySurface}`}>
              <div className={styles.surfaceHeaderCompact}>
                <div>
                  <p className={styles.eyebrow}>{t("selectedCount")}</p>
                  <h2 className={styles.sectionTitle}>
                    {libraryView === "items" ? t("libraryItems") : t("pendingReview")}
                  </h2>
                </div>
                <span className={styles.secondaryPill}>{selectedProposalRunIds.length}</span>
              </div>
              <p className={styles.statusLead}>{libraryHeaderMessage}</p>
              <div className={styles.statusMetricGrid}>
                <article className={styles.metricTile}>
                  <span>{t("filterResults")}</span>
                  <strong>{`${visibleLibraryEntries.length} / ${currentLibraryEntries.length}`}</strong>
                </article>
                <article className={styles.metricTile}>
                  <span>{t("selectedCount")}</span>
                  <strong>{selectedProposalRunIds.length}</strong>
                </article>
                <article className={styles.metricTile}>
                  <span>{t("deletionAllowed")}</span>
                  <strong>{libraryDeletableCount}</strong>
                </article>
                <article className={styles.metricTile}>
                  <span>{t("deletionBlocked")}</span>
                  <strong>{libraryBlockedCount}</strong>
                </article>
              </div>
              {hasLibraryFilters ? (
                <div className={styles.actionRow}>
                  <button
                    type="button"
                    className={styles.inlineAction}
                    onClick={clearLibraryFilters}
                  >
                    {t("clearFilters")}
                  </button>
                </div>
              ) : null}
            </section>

            <section className={`${styles.surface} ${styles.summarySurface}`}>
              <div className={styles.surfaceHeaderCompact}>
                <div>
                  <p className={styles.eyebrow}>{t("proposalStatus")}</p>
                  <h2 className={styles.sectionTitle}>
                    {selectedProposalSummary?.title
                      || (libraryView === "items" ? t("libraryItems") : t("pendingReview"))}
                  </h2>
                </div>
                <span className={selectedProposalSummary ? styles.statusPill : styles.secondaryPill}>
                  {selectedProposalSummary
                    ? selectedProposalSummary.outcomeSemantics.proposalStatusLabel
                    : intakeModeLabel(currentIntakeMode)}
                </span>
              </div>
              <p className={styles.statusLead}>
                {selectedProposalSummary
                  ? (selectedProposalSummary.summary || selectedProposalSummary.reason || selectedProposalSummary.headline)
                  : libraryHeaderMessage}
              </p>
              <div className={styles.relatedList}>
                <article className={styles.relatedRow}>
                  <strong>{t("latestRun")}</strong>
                  <span>{selectedProposalSummary?.sourceRun || latestRun?.id || "--"}</span>
                </article>
                <article className={styles.relatedRow}>
                  <strong>{t("intakeMode")}</strong>
                  <span>{intakeModeLabel(currentIntakeMode)}</span>
                </article>
              </div>
              {selectedProposalSummary ? (
                <div className={styles.actionRow}>
                  <button
                    type="button"
                    className={styles.inlineAction}
                    onClick={() => openRun(selectedProposalSummary.sourceRun)}
                  >
                    <ArrowUpRight size={15} />
                    {t("openSourceRun")}
                  </button>
                </div>
              ) : null}
            </section>
          </div>

          <div className={styles.masterDetail}>
            <section className={`${styles.surface} ${styles.listPanel}`}>
              <>
                <div className={styles.bulkToolbar}>
                  <div className={styles.bulkToolbarText}>
                    <strong>{t("selectedCount")}</strong>
                    <span>{selectedProposalRunIds.length}</span>
                  </div>
                  <div className={styles.actionRow}>
                    <button
                      type="button"
                      className={styles.inlineAction}
                      disabled={selectedProposalRunIds.length === 0}
                      onClick={() => setSelectedProposalRunIds([])}
                    >
                      {t("clearSelection")}
                    </button>
                    <button
                      type="button"
                      className={styles.inlineAction}
                      disabled={selectedProposalRunIds.length === 0 || bulkDeleteMutation.isPending}
                      onClick={triggerBulkDelete}
                    >
                      <Trash2 size={15} />
                      {t("deleteSelected")}
                    </button>
                  </div>
                </div>
                <div className={styles.libraryFilters}>
                  <div className={styles.filterRow}>
                    <label className={styles.filterField}>
                      <span>{t("proposalTarget")}</span>
                      <input
                        type="text"
                        className={styles.textInput}
                        value={librarySearchInput}
                        placeholder={t("proposalSearchPlaceholder")}
                        onChange={(event) => setLibrarySearchInput(event.target.value)}
                      />
                    </label>
                    <label className={styles.filterField}>
                      <span>{t("filterByStatus")}</span>
                      <select
                        className={styles.selectInput}
                        value={libraryStatusFilter}
                        onChange={(event) => setLibraryStatusFilter(event.target.value as LibraryStatusFilter)}
                      >
                        {LIBRARY_STATUS_FILTERS.map((status) => (
                          <option key={status} value={status}>
                            {status === "all" ? t("filterAll") : statusLabel(status)}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className={styles.filterField}>
                      <span>{t("filterByDeleteState")}</span>
                      <select
                        className={styles.selectInput}
                        value={libraryDeleteFilter}
                        onChange={(event) => setLibraryDeleteFilter(event.target.value as LibraryDeleteFilter)}
                      >
                        <option value="all">{t("filterAll")}</option>
                        <option value="deletable">{t("filterDeletableOnly")}</option>
                        <option value="blocked">{t("filterBlockedOnly")}</option>
                      </select>
                    </label>
                  </div>
                  <div className={styles.filterMeta}>
                    <div className={styles.selectionSummary}>
                      <span>{t("filterResults")}</span>
                      <strong>{visibleLibraryEntries.length} / {currentLibraryEntries.length}</strong>
                    </div>
                    {hasLibraryFilters ? (
                      <button
                        type="button"
                        className={styles.inlineAction}
                        onClick={clearLibraryFilters}
                      >
                        {t("clearFilters")}
                      </button>
                    ) : null}
                  </div>
                </div>
                {libraryFeedback ? <p className={styles.feedbackText}>{libraryFeedback}</p> : null}
                {bulkDeleteMutation.error ? <p className={styles.errorText}>{bulkDeleteMutation.error.message}</p> : null}
                {libraryView === "items"
                ? libraryItems.length === 0
                  ? <div className={styles.emptyState}>{t("emptyLibraryItems")}</div>
                  : filteredLibraryItems.length === 0
                    ? <div className={styles.emptyState}>{t("noProposalMatches")}</div>
                    : filteredLibraryItems.map((item) => (
                      <article
                        key={item.id}
                        className={
                          selectedLibraryItem?.id === item.id
                            ? `${styles.proposalCard} ${styles.runItemActive}`
                            : styles.proposalCard
                        }
                      >
                        <div className={styles.selectionBar}>
                          <label className={styles.batchToggle}>
                            <input
                              type="checkbox"
                              checked={proposalSelected(item.sourceRun)}
                              onChange={() => toggleProposalSelection(item.sourceRun)}
                            />
                            <span>{t("selectForBatchDelete")}</span>
                          </label>
                          <span className={item.canDelete ? styles.secondaryPill : styles.statusPill}>
                            {item.canDelete ? t("deletionAllowed") : t("deletionBlocked")}
                          </span>
                        </div>
                        <button
                          type="button"
                          className={styles.proposalCardButton}
                          onClick={() => setSelectedLibraryItemId(item.id)}
                        >
                          <div className={styles.listRowTop}>
                            <strong>{item.title}</strong>
                            <span className={styles.secondaryPill}>{item.outcomeSemantics.proposalStatusLabel}</span>
                          </div>
                          <div className={styles.metaRow}>
                            <span>{decisionLabel(item.decision)}</span>
                            <span>{item.sourceRun}</span>
                          </div>
                          <p className={styles.cardHeadline}>{item.changeSummary || item.headline}</p>
                          <p>{item.summary}</p>
                          <div className={styles.cardFooter}>
                            <span>{item.targetLabel || item.targetKey || "--"}</span>
                            <span>{compactTimestamp(item.updatedAt)}</span>
                          </div>
                        </button>
                      </article>
                    ))
                : pendingItems.length === 0
                  ? <div className={styles.emptyState}>{t("emptyPendingItems")}</div>
                  : filteredPendingItems.length === 0
                    ? <div className={styles.emptyState}>{t("noProposalMatches")}</div>
                    : filteredPendingItems.map((item) => (
                      <article
                        key={item.id}
                        className={
                          selectedPendingItem?.id === item.id
                            ? `${styles.proposalCard} ${styles.runItemActive}`
                            : styles.proposalCard
                        }
                      >
                        <div className={styles.selectionBar}>
                          <label className={styles.batchToggle}>
                            <input
                              type="checkbox"
                              checked={proposalSelected(item.sourceRun)}
                              onChange={() => toggleProposalSelection(item.sourceRun)}
                            />
                            <span>{t("selectForBatchDelete")}</span>
                          </label>
                          <span className={item.canDelete ? styles.secondaryPill : styles.statusPill}>
                            {item.canDelete ? t("deletionAllowed") : t("deletionBlocked")}
                          </span>
                        </div>
                        <button
                          type="button"
                          className={styles.proposalCardButton}
                          onClick={() => setSelectedPendingItemId(item.id)}
                        >
                          <div className={styles.listRowTop}>
                            <strong>{item.title}</strong>
                            <span className={styles.secondaryPill}>{item.outcomeSemantics.proposalStatusLabel}</span>
                          </div>
                          <div className={styles.metaRow}>
                            <span>{decisionLabel(item.decision)}</span>
                            <span>{item.sourceRun}</span>
                          </div>
                          <p className={styles.cardHeadline}>{item.changeSummary || item.headline}</p>
                          <p>{item.reason || item.summary}</p>
                          <div className={styles.cardFooter}>
                            <span>{item.targetLabel || item.targetKey || "--"}</span>
                            <span>{compactTimestamp(item.updatedAt)}</span>
                          </div>
                        </button>
                      </article>
                    ))}
              </>
            </section>

            <section className={`${styles.surface} ${styles.detailPanel}`}>
              {selectedProposalSummary ? (
                proposalDetailQuery.data ? (
                  <>
                    <div className={styles.detailHeader}>
                      <div>
                        <p className={styles.eyebrow}>
                          {libraryView === "items" ? t("libraryItems") : t("pendingReview")}
                        </p>
                        <h2 className={styles.detailTitle}>{proposalDetailQuery.data.title}</h2>
                      </div>
                      <span className={styles.statusPill}>
                        {proposalDetailQuery.data.outcomeSemantics.proposalStatusLabel}
                      </span>
                    </div>

                    <div className={styles.detailSection}>
                      <h3>{t("reviewHeadline")}</h3>
                      <p className={styles.reviewLead}>{proposalDetailQuery.data.review.headline}</p>
                      <p>{proposalDetailQuery.data.review.changeSummary}</p>
                    </div>

                    <div className={styles.detailSection}>
                      <h3>{t("whatChangedTitle")}</h3>
                      {renderReviewList(proposalDetailQuery.data.review.whatChanged)}
                    </div>

                    <div className={styles.detailSection}>
                      <h3>{t("whyCreatedTitle")}</h3>
                      {renderReviewList(proposalDetailQuery.data.review.whyCreated)}
                    </div>

                    <div className={styles.detailSection}>
                      <h3>{t("currentStateTitle")}</h3>
                      {renderReviewList([
                        ...proposalDetailQuery.data.review.currentState,
                        proposalDetailQuery.data.review.nextAction,
                      ])}
                    </div>

                    <div className={styles.detailSection}>
                      <h3>{t("resultLayersTitle")}</h3>
                      <div className={styles.relatedList}>
                        <article className={styles.relatedRow}>
                          <strong>{t("sourceRun")}</strong>
                          <span>{proposalDetailQuery.data.sourceRun}</span>
                        </article>
                        <article className={styles.relatedRow}>
                          <strong>{t("proposalUpdatedAt")}</strong>
                          <span>{compactTimestamp(proposalDetailQuery.data.updatedAt)}</span>
                        </article>
                        <article className={styles.relatedRow}>
                          <strong>{t("runLayer")}</strong>
                          <span>{proposalDetailQuery.data.runSemantics.runStatusLabel}</span>
                        </article>
                        <article className={styles.relatedRow}>
                          <strong>{t("decision")}</strong>
                          <span>{proposalDetailQuery.data.outcomeSemantics.decisionLabel}</span>
                        </article>
                        <article className={styles.relatedRow}>
                          <strong>{t("proposalLayer")}</strong>
                          <span>{proposalDetailQuery.data.outcomeSemantics.proposalStatusLabel}</span>
                        </article>
                        <article className={styles.relatedRow}>
                          <strong>{t("runtimeLayer")}</strong>
                          <span>{proposalDetailQuery.data.outcomeSemantics.runtimeEffectLabel}</span>
                        </article>
                        <article className={styles.relatedRow}>
                          <strong>{t("targetLabelTitle")}</strong>
                          <span>
                            {proposalDetailQuery.data.targetLabel
                              || proposalDetailQuery.data.targetKey
                              || "--"}
                          </span>
                        </article>
                        <article className={styles.relatedRow}>
                          <strong>{t("baselineScore")}</strong>
                          <span>{proposalDetailQuery.data.supervised.baselineScore}</span>
                        </article>
                        <article className={styles.relatedRow}>
                          <strong>{t("candidateScore")}</strong>
                          <span>{proposalDetailQuery.data.supervised.candidateScore}</span>
                        </article>
                        <article className={styles.relatedRow}>
                          <strong>{t("scoreDelta")}</strong>
                          <span>{proposalDetailQuery.data.supervised.deltaScore}</span>
                        </article>
                        <article className={styles.relatedRow}>
                          <strong>{t("riskLevel")}</strong>
                          <span>{riskLabel(proposalDetailQuery.data.supervised.riskLevel)}</span>
                        </article>
                      </div>
                      <p className={styles.noticeText}>{proposalDetailQuery.data.outcomeSemantics.runtimeExplanation}</p>
                      <p>{proposalDetailQuery.data.supervised.decisionReason}</p>
                      {proposalDetailQuery.data.supervised.riskReasons.length > 0 ? (
                        <p>{proposalDetailQuery.data.supervised.riskReasons.join(" / ")}</p>
                      ) : null}
                    </div>

                    <div className={styles.detailSection}>
                      <h3>{t("availableActions")}</h3>
                      <p>{formatAvailableActions(proposalDetailQuery.data.availableActions)}</p>
                      {proposalDetailQuery.data.availableActions.length > 0 ? (
                        <div className={styles.actionRow}>
                          {proposalDetailQuery.data.availableActions.map((action) => (
                            <button
                              key={action}
                              type="button"
                              className={styles.inlineAction}
                              disabled={runLocked || actionMutation.isPending}
                              onClick={() => triggerRunAction(proposalDetailQuery.data.sourceRun, action)}
                            >
                              <Sparkles size={15} />
                              {proposalActionLabel(action)}
                            </button>
                          ))}
                        </div>
                      ) : null}
                      {actionFeedback ? <p className={styles.feedbackText}>{actionFeedback}</p> : null}
                      {actionMutation.error ? <p className={styles.errorText}>{actionMutation.error.message}</p> : null}
                    </div>

                    <div className={styles.detailSection}>
                      <h3>{t("deleteAndCleanup")}</h3>
                      <div className={styles.relatedList}>
                        <article className={styles.relatedRow}>
                          <strong>{proposalDetailQuery.data.canDelete ? t("deletionAllowed") : t("deletionBlocked")}</strong>
                          <span>
                            {proposalDetailQuery.data.canDelete
                              ? t("deleteProposal")
                              : proposalDetailQuery.data.deleteBlockReason || "--"}
                          </span>
                        </article>
                      </div>
                      <p>{proposalDetailQuery.data.review.deleteImpact}</p>
                      {proposalDetailQuery.data.review.evidenceNotes.length > 0
                        ? renderReviewList(proposalDetailQuery.data.review.evidenceNotes)
                        : null}
                      <div className={styles.actionRow}>
                        <button
                          type="button"
                          className={styles.inlineAction}
                          disabled={!proposalDetailQuery.data.canDelete || deleteProposalMutation.isPending}
                          onClick={() => triggerProposalDelete(proposalDetailQuery.data.sourceRun)}
                        >
                          <Trash2 size={15} />
                          {t("deleteProposal")}
                        </button>
                      </div>
                      {deleteProposalMutation.error ? <p className={styles.errorText}>{deleteProposalMutation.error.message}</p> : null}
                    </div>

                    <div className={styles.detailSection}>
                      <h3>{t("evidencePaths")}</h3>
                      <div className={styles.relatedList}>
                        {Object.entries(proposalDetailQuery.data.paths)
                          .filter(([, value]) => Boolean(value))
                          .map(([key, value]) => (
                            <article key={key} className={styles.relatedRow}>
                              <strong>{key}</strong>
                              <span className={styles.pathText}>{value}</span>
                            </article>
                          ))}
                      </div>
                    </div>

                    <div className={styles.detailSection}>
                      <h3>{t("navEvolution")}</h3>
                      <button
                        type="button"
                        className={styles.inlineAction}
                        onClick={() => openRun(proposalDetailQuery.data.sourceRun)}
                      >
                        <ArrowUpRight size={15} />
                        {t("openSourceRun")}
                      </button>
                    </div>

                    <div className={styles.detailSection}>
                      <div className={styles.rawBlockStack}>
                        {renderRawJson(t("rawProposalJson"), proposalDetailQuery.data.rawProposal)}
                        {renderRawJson(t("rawGymDecisionJson"), proposalDetailQuery.data.rawGymDecision)}
                        {renderRawJson(t("rawSupervisedDecisionJson"), proposalDetailQuery.data.rawSupervisedDecision)}
                      </div>
                    </div>
                  </>
                ) : proposalDetailQuery.error ? (
                  <div className={styles.emptyState}>{proposalDetailQuery.error.message}</div>
                ) : (
                  <div className={styles.emptyState}>{t("loadingRunDetails")}</div>
                )
              ) : (
                <div className={styles.emptyState}>{t("chooseProposalDetail")}</div>
              )}
            </section>
          </div>
        </div>
      ) : null}
    </div>
  );
}
