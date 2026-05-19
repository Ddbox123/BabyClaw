import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  ArrowUpRight,
  CheckSquare,
  ChevronLeft,
  ChevronRight,
  LoaderCircle,
  Pause,
  Play,
  RotateCcw,
  ScrollText,
  ShieldCheck,
  Square,
  TriangleAlert,
  X,
} from "lucide-react";
import { type PointerEvent as ReactPointerEvent, useEffect, useMemo, useState } from "react";

import { fetchJson } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import {
  ConversationMessage,
  PetSummary,
  SelfEvolutionActiveRun,
  SelfEvolutionOverview,
  SelfEvolutionTransaction,
} from "../api/types";
import { ConversationView } from "../components/conversation/ConversationView";
import { useAppI18n } from "../i18n/useAppI18n";
import styles from "./SelfEvolutionTrack.module.css";

type SelfEvolutionTrackProps = {
  overview?: SelfEvolutionOverview;
  latestRun?: SelfEvolutionActiveRun | null;
  goalInput: string;
  onGoalInputChange: (value: string) => void;
  onStartRun: () => void;
  onPauseRun: () => void;
  onResumeRun: () => void;
  onTerminateRun: () => void;
  onRollbackRun: () => void;
  onHandoffRun: () => void;
  onDeleteHistoryGroups: (txnIds: string[]) => void;
  startPending: boolean;
  pausePending: boolean;
  resumePending: boolean;
  terminatePending: boolean;
  rollbackPending: boolean;
  handoffPending: boolean;
  deleteHistoryPending: boolean;
  startError: string;
  pauseError: string;
  resumeError: string;
  terminateError: string;
  rollbackError: string;
  handoffError: string;
  deleteHistoryError: string;
  actionFeedback: string;
  runLocked: boolean;
  transactions: SelfEvolutionTransaction[];
  loading: boolean;
};

type ConversationTaskSummary = {
  title: string;
  goal: string;
  status: string;
  latestSummary: string;
  nextAction: string;
  verificationStatus: string;
  verificationSummary: string;
  readFiles: string[];
  changedFiles: string[];
  toolNames: string[];
  turnCount: number;
  resumeCount: number;
  updatedAt: string;
};

const WORKTREE_PAGE_SIZE = 10;
const PET_PLACEHOLDER_ART = "https://commons.wikimedia.org/wiki/Special:FilePath/Lobster%20%28NIH%20BioArt%20624%29.png";
const SELF_SIDEBAR_WIDTH_STORAGE_KEY = "vibelution.self.sidebar.width";

function formatRate(value: number | null | undefined) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "--";
  }
  return `${Math.round(value * 100)}%`;
}

function clampPercent(value: number | null | undefined) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return 0;
  }
  return Math.max(0, Math.min(100, Math.round(value)));
}

function compactTimestamp(value: string) {
  const text = String(value || "").trim();
  if (!text) {
    return "--";
  }
  const normalized = text.replace("T", " ");
  return normalized.length > 19 ? normalized.slice(0, 19) : normalized;
}

function compactRevision(value: string) {
  const text = String(value || "").trim();
  if (!text) {
    return "--";
  }
  return text.length > 12 ? text.slice(0, 12) : text;
}

function looksLikeStructuredPayload(value: string) {
  const text = String(value || "").trim();
  return text.startsWith("{") || text.startsWith("[");
}

function isExecutingRunStatus(status: string) {
  return ["queued", "running", "stopping"].includes(String(status || "").trim().toLowerCase());
}

function isPausedRunStatus(status: string) {
  return String(status || "").trim().toLowerCase() === "paused";
}

function readinessIcon(state: string) {
  const normalized = String(state).trim().toLowerCase();
  if (normalized === "ready" || normalized === "done" || normalized === "success") {
    return <ShieldCheck size={16} />;
  }
  if (normalized === "caution" || normalized === "failed" || normalized === "blocked") {
    return <TriangleAlert size={16} />;
  }
  return <Activity size={16} />;
}

function worktreeFileFlags(
  t: ReturnType<typeof useAppI18n>["t"],
  file: SelfEvolutionOverview["worktree"]["files"][number],
) {
  const flags: string[] = [];
  if (file.staged) {
    flags.push(t("worktreeFlagStaged"));
  }
  if (file.unstaged) {
    flags.push(t("worktreeFlagUnstaged"));
  }
  if (file.untracked) {
    flags.push(t("worktreeFlagUntracked"));
  }
  if (file.deleted) {
    flags.push(t("worktreeFlagDeleted"));
  }
  return flags.length > 0 ? flags.join(" / ") : "";
}

function buildPageWindow(currentPage: number, totalPages: number) {
  const start = Math.max(1, currentPage - 2);
  const end = Math.min(totalPages, start + 4);
  const adjustedStart = Math.max(1, end - 4);
  return Array.from({ length: end - adjustedStart + 1 }, (_, index) => adjustedStart + index);
}

function collectUniqueLines(values: Array<string | null | undefined>) {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const raw of values) {
    const value = String(raw || "").trim();
    if (!value || seen.has(value)) {
      continue;
    }
    seen.add(value);
    result.push(value);
  }
  return result;
}

function joinReadableLines(values: Array<string | null | undefined>) {
  return values.map((value) => String(value || "").trim()).filter(Boolean).join("\n");
}

export function SelfEvolutionTrack({
  overview,
  latestRun,
  goalInput,
  onGoalInputChange,
  onStartRun,
  onPauseRun,
  onResumeRun,
  onTerminateRun,
  onRollbackRun,
  onHandoffRun,
  onDeleteHistoryGroups,
  startPending,
  pausePending,
  resumePending,
  terminatePending,
  rollbackPending,
  handoffPending,
  deleteHistoryPending,
  startError,
  pauseError,
  resumeError,
  terminateError,
  rollbackError,
  handoffError,
  deleteHistoryError,
  actionFeedback,
  runLocked,
  transactions,
  loading,
}: SelfEvolutionTrackProps) {
  const { t, statusLabel } = useAppI18n();
  const [worktreePage, setWorktreePage] = useState(1);
  const [activePage, setActivePage] = useState<"workspace" | "status">("workspace");
  const [selectedHistoryTxnIds, setSelectedHistoryTxnIds] = useState<string[]>([]);
  const [sidebarWidth, setSidebarWidth] = useState(() => {
    if (typeof window === "undefined") {
      return 320;
    }
    const saved = Number(window.localStorage.getItem(SELF_SIDEBAR_WIDTH_STORAGE_KEY) || "");
    return Number.isFinite(saved) ? Math.max(280, Math.min(420, saved)) : 320;
  });
  const petQuery = useQuery({
    queryKey: queryKeys.petSummary(),
    queryFn: () => fetchJson<PetSummary>("/api/pet/summary"),
    refetchInterval: 10_000,
    refetchIntervalInBackground: true,
  });
  const pet = petQuery.data;

  useEffect(() => {
    if (typeof window !== "undefined") {
      window.localStorage.setItem(SELF_SIDEBAR_WIDTH_STORAGE_KEY, String(sidebarWidth));
    }
  }, [sidebarWidth]);

  const worktreeFiles = useMemo(() => {
    const files = overview?.worktree.files ?? [];
    return [...files].sort((left, right) => {
      const leftStatus = String(left.status || "");
      const rightStatus = String(right.status || "");
      if (leftStatus !== rightStatus) {
        return leftStatus.localeCompare(rightStatus);
      }
      return left.path.localeCompare(right.path);
    });
  }, [overview?.worktree.files]);

  const totalWorktreePages = Math.max(1, Math.ceil(worktreeFiles.length / WORKTREE_PAGE_SIZE));
  const clampedWorktreePage = Math.min(worktreePage, totalWorktreePages);
  const pageNumbers = buildPageWindow(clampedWorktreePage, totalWorktreePages);
  const worktreePageStart = worktreeFiles.length === 0 ? 0 : (clampedWorktreePage - 1) * WORKTREE_PAGE_SIZE + 1;
  const worktreePageEnd = worktreeFiles.length === 0
    ? 0
    : Math.min(worktreeFiles.length, clampedWorktreePage * WORKTREE_PAGE_SIZE);
  const currentWorktreeFiles = worktreeFiles.slice(
    (clampedWorktreePage - 1) * WORKTREE_PAGE_SIZE,
    clampedWorktreePage * WORKTREE_PAGE_SIZE,
  );

  useEffect(() => {
    if (worktreePage !== clampedWorktreePage) {
      setWorktreePage(clampedWorktreePage);
    }
  }, [clampedWorktreePage, worktreePage]);

  const gitStatusSummary = String(overview?.gitStatus.summary || "").trim();
  const gitStatusLines = (overview?.gitStatus.lines ?? [])
    .map((line) => String(line || "").trim())
    .filter(Boolean)
    .filter((line) => !looksLikeStructuredPayload(line))
    .slice(0, 4);
  const currentStateNotes = overview
    ? overview.readiness.reasons.length > 0
      ? overview.readiness.reasons
      : gitStatusLines.length > 0
        ? gitStatusLines
        : [gitStatusSummary || t("loading")]
    : [];
  const worktreeFlags = [
    overview?.worktree.hasStaged ? t("worktreeFlagStaged") : "",
    overview?.worktree.hasUnstaged ? t("worktreeFlagUnstaged") : "",
    overview?.worktree.hasUntracked ? t("worktreeFlagUntracked") : "",
  ].filter(Boolean);
  const compactWorktreeSummary = !overview
    ? t("loading")
    : gitStatusSummary && !looksLikeStructuredPayload(gitStatusSummary)
      ? gitStatusSummary
      : overview.worktree.error
        ? overview.worktree.error
        : overview.worktree.isDirty
          ? [worktreeFlags.join(" / "), `${t("filesChanged")} ${overview.worktree.dirtyFileCount}`]
            .filter(Boolean)
            .join(" · ")
          : t("worktreeClean");
  const transactionItems = transactions.length > 0 ? transactions : overview?.recentTransactions ?? [];
  const runIsActive = latestRun ? isExecutingRunStatus(latestRun.status) : false;
  const runIsPaused = latestRun ? isPausedRunStatus(latestRun.status) : false;
  const rollback = latestRun?.rollback;
  const rollbackFiles = rollback?.touchedFiles ?? [];
  const rollbackConflicts = rollback?.conflictFiles ?? [];
  const rollbackReady = rollback?.status === "available";
  const rollbackBlocked = rollback?.status === "blocked";
  const sceneSemantics = overview?.sceneSemantics;
  const runSemantics = latestRun?.runSemantics ?? overview?.runSemantics;
  const startSelfAction = overview?.actionStates?.start;
  const pauseSelfAction = latestRun?.actionStates?.pause;
  const resumeSelfAction = latestRun?.actionStates?.resume;
  const terminateSelfAction = latestRun?.actionStates?.terminate;
  const rollbackSelfAction = latestRun?.actionStates?.rollback;
  const handoffSelfAction = latestRun?.actionStates?.handoff;
  const controlAction = String(latestRun?.controlAction || "").trim().toLowerCase();
  const terminateRequested = controlAction === "terminate" || String(latestRun?.status || "").toLowerCase() === "stopping";
  const pauseRequested = controlAction === "pause" || String(latestRun?.runtimeStatus || "").toLowerCase() === "pausing";
  const errorMessage =
    startError || pauseError || resumeError || terminateError || rollbackError || handoffError || deleteHistoryError;
  const visibleTransactions = transactionItems.slice(0, 8);
  const visibleAuditTrail = (overview?.auditTail ?? []).slice(-8).reverse();
  const visibleTransactionIds = useMemo(
    () => visibleTransactions.map((item) => item.txnId).filter(Boolean),
    [visibleTransactions],
  );
  const auditCountByTxnId = useMemo(() => {
    const counts = new Map<string, number>();
    for (const item of overview?.auditTail ?? []) {
      const txnId = String(item.txnId || "").trim();
      if (!txnId) {
        continue;
      }
      counts.set(txnId, (counts.get(txnId) || 0) + 1);
    }
    return counts;
  }, [overview?.auditTail]);
  const petVitals = useMemo(
    () => [
      { key: "mood", label: t("mood"), value: clampPercent(pet?.mood ?? 0) },
      { key: "hunger", label: t("hunger"), value: clampPercent(pet?.hunger ?? 0) },
      { key: "energy", label: t("energy"), value: clampPercent(pet?.energy ?? 0) },
      { key: "health", label: t("health"), value: clampPercent(pet?.health ?? 0) },
      { key: "love", label: t("love"), value: clampPercent(pet?.love ?? 0) },
    ],
    [pet?.energy, pet?.health, pet?.hunger, pet?.love, pet?.mood, t],
  );
  const petCompanionLine = petQuery.isError
    ? t("loadFailed")
    : pet?.inDream
      ? t("petCompanionDreaming")
      : (pet?.health ?? 0) < 35
        ? t("petCompanionLowHealth")
        : (pet?.hunger ?? 0) < 30
          ? t("petCompanionLowFuel")
          : (pet?.energy ?? 0) < 35
            ? t("petCompanionLowEnergy")
            : t("petCompanionStable");

  function disabledReason(state: { enabled: boolean; reason: string } | undefined) {
    if (!state || state.enabled) {
      return "";
    }
    return state.reason || "";
  }
  const conversationTask = useMemo<ConversationTaskSummary>(() => {
    if (!overview) {
      return {
        title: t("launchSelfRun"),
        goal: latestRun?.currentGoal || latestRun?.goal || goalInput || t("selfGoalPlaceholder"),
        status: latestRun?.phase || latestRun?.status || "loading",
        latestSummary: latestRun?.currentTask || latestRun?.latestMessage || latestRun?.summary || latestRun?.error || t("loading"),
        nextAction: terminateRequested ? t("selfStopRequested") : pauseRequested ? t("selfPauseRequested") : t("loading"),
        verificationStatus: rollback?.status || latestRun?.runtimeStatus || latestRun?.status || "loading",
        verificationSummary: latestRun?.error || rollback?.reason || latestRun?.summary || t("loading"),
        readFiles: [],
        changedFiles: [],
        toolNames: collectUniqueLines([latestRun?.lastToolName]),
        turnCount: latestRun?.turnCount ?? 0,
        resumeCount: latestRun?.resumeCount ?? 0,
        updatedAt: latestRun?.updatedAt || "",
      };
    }
    const readFiles = collectUniqueLines(overview.auditTail.flatMap((item) => item.targetPaths));
    const changedFiles = collectUniqueLines([
      ...overview.recentChanges.map((item) => item.path),
      ...rollbackFiles.map((item) => item.path),
      ...overview.worktree.files.filter((item) => item.staged || item.unstaged || item.untracked || item.deleted).map((item) => item.path),
    ]);
    const toolNames = collectUniqueLines([
      latestRun?.lastToolName,
      ...overview.auditTail.map((item) => item.toolName),
    ]);
    return {
      title: t("launchSelfRun"),
      goal: latestRun?.currentGoal || latestRun?.goal || overview.goal || t("selfGoalPlaceholder"),
      status: latestRun?.phase || latestRun?.status || overview.readiness.state,
      latestSummary:
        latestRun?.currentTask || latestRun?.latestMessage || latestRun?.summary || latestRun?.error || overview.readiness.summary,
      nextAction: terminateRequested
        ? t("selfStopRequested")
        : pauseRequested
          ? t("selfPauseRequested")
        : latestRun?.nextToolIntent
          ? latestRun.nextToolIntent
        : rollbackBlocked && rollback?.blockedHint
          ? rollback.blockedHint
        : latestRun?.readingHint
            ? latestRun.readingHint
          : sceneSemantics?.nextAction || overview.readiness.nextAction || overview.readiness.summary,
      verificationStatus: rollback?.status || latestRun?.runtimeStatus || latestRun?.status || overview.readiness.state,
      verificationSummary:
        latestRun?.error || rollback?.reason || latestRun?.summary || overview.readiness.summary,
      readFiles,
      changedFiles,
      toolNames,
      turnCount: latestRun?.turnCount ?? transactionItems.length,
      resumeCount: latestRun?.resumeCount ?? 0,
      updatedAt: latestRun?.updatedAt || overview.worktree.createdAt || "",
    };
  }, [
    goalInput,
    latestRun?.currentGoal,
    latestRun?.error,
    latestRun?.goal,
    latestRun?.lastToolName,
    latestRun?.latestMessage,
    latestRun?.phase,
    latestRun?.resumeCount,
    latestRun?.runtimeStatus,
    latestRun?.status,
    latestRun?.summary,
    latestRun?.turnCount,
    latestRun?.updatedAt,
    overview,
    pauseRequested,
    rollback?.blockedHint,
    rollback?.reason,
    rollback?.status,
    rollbackBlocked,
    rollbackFiles,
    sceneSemantics?.nextAction,
    t,
    terminateRequested,
    transactionItems.length,
  ]);
  const conversationMessages = useMemo<ConversationMessage[]>(() => {
    if (latestRun?.messages?.length) {
      return latestRun.messages;
    }
    if (!overview) {
      return [];
    }
    return [
      {
        id: "self-readiness",
        role: "assistant",
        content: joinReadableLines([overview.readiness.summary, overview.readiness.nextAction]),
        timestamp: "",
      },
    ];
  }, [latestRun?.messages, overview]);

  useEffect(() => {
    setSelectedHistoryTxnIds((current) => current.filter((txnId) => visibleTransactionIds.includes(txnId)));
  }, [visibleTransactionIds]);

  function beginSidebarResize(event: ReactPointerEvent<HTMLButtonElement>) {
    const startX = event.clientX;
    const startWidth = sidebarWidth;

    const handleMove = (moveEvent: PointerEvent) => {
      const nextWidth = startWidth + (moveEvent.clientX - startX);
      setSidebarWidth(Math.max(280, Math.min(420, nextWidth)));
    };

    const handleUp = () => {
      window.removeEventListener("pointermove", handleMove);
      window.removeEventListener("pointerup", handleUp);
    };

    window.addEventListener("pointermove", handleMove);
    window.addEventListener("pointerup", handleUp);
  }

  function toggleHistorySelection(txnId: string) {
    if (!txnId) {
      return;
    }
    setSelectedHistoryTxnIds((current) => (
      current.includes(txnId)
        ? current.filter((item) => item !== txnId)
        : [...current, txnId]
    ));
  }

  function toggleAllVisibleHistoryGroups() {
    if (visibleTransactionIds.length === 0) {
      return;
    }
    const allSelected = visibleTransactionIds.every((txnId) => selectedHistoryTxnIds.includes(txnId));
    setSelectedHistoryTxnIds(allSelected ? [] : visibleTransactionIds);
  }

  if (loading && !overview) {
    return (
      <section className={styles.surface}>
        <div className={styles.emptyState}>{t("loading")}</div>
      </section>
    );
  }

  if (!overview) {
    return (
      <section className={styles.surface}>
        <div className={styles.emptyState}>{t("loadFailed")}</div>
      </section>
    );
  }

  const allVisibleHistorySelected = visibleTransactionIds.length > 0
    && visibleTransactionIds.every((txnId) => selectedHistoryTxnIds.includes(txnId));
  const selectedHistorySet = new Set(selectedHistoryTxnIds);

  return (
    <div className={styles.pageStack}>
      <div className={styles.pageTabsRow}>
        <div className={styles.segmentedTabs}>
          <button
            type="button"
            className={activePage === "workspace" ? `${styles.tabButton} ${styles.tabButtonActive}` : styles.tabButton}
            onClick={() => setActivePage("workspace")}
          >
            {t("selfWorkspacePage")}
          </button>
          <button
            type="button"
            className={activePage === "status" ? `${styles.tabButton} ${styles.tabButtonActive}` : styles.tabButton}
            onClick={() => setActivePage("status")}
          >
            {t("selfStatusPage")}
          </button>
        </div>
      </div>

      {activePage === "workspace" ? (
        <div className={styles.workspaceLayout} style={{ ["--self-sidebar-width" as string]: `${sidebarWidth}px` }}>
          <aside className={`${styles.sideColumn} ${styles.sideColumnScrollable}`}>
            <section className={styles.surface}>
              <div className={styles.sectionHeader}>
                <div>
                  <p className={styles.eyebrow}>{t("selfEvolutionMode")}</p>
                  <h3 className={styles.sectionTitle}>{t("selfWorkspacePage")}</h3>
                </div>
                <span className={styles.statusPill}>{statusLabel(conversationTask.status)}</span>
              </div>

              <p className={styles.sectionSummary}>{conversationTask.goal}</p>

                <div className={styles.detailStack}>
                  <div className={styles.detailRow}>
                    <span>{t("sceneStateTitle")}</span>
                    <strong>{sceneSemantics?.sceneTitle || statusLabel(overview.readiness.state)}</strong>
                  </div>
                  <div className={styles.detailRow}>
                    <span>{t("currentRunTitle")}</span>
                    <strong>{runSemantics?.phaseLabel || statusLabel(latestRun?.runtimeStatus || latestRun?.status || overview.readiness.state)}</strong>
                  </div>
                  <div className={styles.detailRow}>
                    <span>{t("rollbackStateTitle")}</span>
                    <strong>{runSemantics?.rollbackStateLabel || statusLabel(conversationTask.verificationStatus)}</strong>
                  </div>
                  <div className={styles.detailRow}>
                    <span>{t("lastUpdated")}</span>
                    <strong>{compactTimestamp(conversationTask.updatedAt)}</strong>
                  </div>
                </div>

              <div className={styles.noticeStack}>
                <p className={styles.noticeText}>{sceneSemantics?.sceneSummary || conversationTask.latestSummary}</p>
                <p className={styles.noticeText}>
                  {runSemantics?.rollbackSummary || conversationTask.nextAction}
                </p>
                {sceneSemantics?.nextAction ? <p className={styles.noticeText}>{sceneSemantics.nextAction}</p> : null}
                {!startSelfAction?.enabled && disabledReason(startSelfAction) ? (
                  <p className={styles.noticeText}>{disabledReason(startSelfAction)}</p>
                ) : null}
                {runLocked ? <p className={styles.noticeText}>{t("selfRunningLockHint")}</p> : null}
                {actionFeedback ? <p className={styles.feedbackText}>{actionFeedback}</p> : null}
                {errorMessage ? <p className={styles.errorText}>{errorMessage}</p> : null}
              </div>
            </section>

            <section className={styles.surface}>
              <div className={styles.sectionHeader}>
                <div>
                  <p className={styles.eyebrow}>{t("petSpace")}</p>
                  <h3 className={styles.sectionTitle}>{pet?.name ?? t("loadingPetState")}</h3>
                </div>
                <span className={styles.secondaryPill}>Lv. {pet?.level ?? 0}</span>
              </div>

              <div className={styles.petAvatarStage}>
                <div className={styles.petAvatarHalo} />
                <img
                  src={PET_PLACEHOLDER_ART}
                  alt={pet?.name ?? "pet"}
                  className={styles.petAvatarImage}
                />
                <div className={styles.petAvatarBadge}>{pet?.avatarPreset ?? "lobster"} {t("preset")}</div>
              </div>

              <p className={styles.noticeText}>{pet?.statusLine ?? t("readingCompanionState")}</p>
              <p className={styles.noticeText}>{petCompanionLine}</p>
            </section>

            <section className={styles.surface}>
              <div className={styles.sectionHeader}>
                <div>
                  <p className={styles.eyebrow}>{t("petSpace")}</p>
                  <h3 className={styles.sectionTitle}>{t("mood")} / {t("heart")}</h3>
                </div>
                <span className={styles.secondaryPill}>{pet?.mood ?? 0}</span>
              </div>

              <div className={styles.compactMetricGrid}>
                <article className={styles.stripItem}>
                  <span>{t("tokens")}</span>
                  <strong>{pet?.totalTokens ?? 0}</strong>
                </article>
                <article className={styles.stripItem}>
                  <span>{t("dailyTokens")}</span>
                  <strong>{pet?.dailyTokens ?? 0}</strong>
                </article>
                <article className={styles.stripItem}>
                  <span>{t("heart")}</span>
                  <strong>{pet?.heartActive ? t("heartActive") : t("heartIdle")}</strong>
                </article>
                <article className={styles.stripItem}>
                  <span>{t("dream")}</span>
                  <strong>{pet?.inDream ? t("dreamSleeping") : t("dreamAwake")}</strong>
                </article>
              </div>

              <div className={styles.vitalList}>
                {petVitals.map((vital) => (
                  <div key={vital.key} className={styles.vitalItem}>
                    <div className={styles.itemTop}>
                      <strong>{vital.label}</strong>
                      <span className={styles.secondaryPill}>{vital.value}</span>
                    </div>
                    <div className={styles.vitalTrack}>
                      <div className={styles.vitalFill} style={{ width: `${vital.value}%` }} />
                    </div>
                  </div>
                ))}
              </div>
            </section>
          </aside>

          <button
            type="button"
            className={styles.sidebarResizer}
            aria-label={t("petSpace")}
            onPointerDown={beginSidebarResize}
          />

          <main className={styles.centerColumn}>
            <div className={styles.conversationShell}>
              <ConversationView
                sessionId={latestRun?.runId || "self-evolution"}
                eyebrowLabel={t("selfEvolutionMode")}
                title={t("selfWorkspacePage")}
                phase={runSemantics?.phase || latestRun?.status || overview.readiness.state}
                messages={conversationMessages}
                taskSummary={conversationTask.latestSummary}
                defaultFileContext={conversationTask.changedFiles.at(-1) || conversationTask.readFiles.at(-1) || "workspace"}
                summaryItems={[]}
                stats={[
                  { label: t("selfGoal"), value: conversationTask.goal },
                  { label: t("selfTransactions"), value: transactionItems.length },
                  { label: t("filesChanged"), value: overview.worktree.dirtyFileCount },
                  { label: t("lastUpdated"), value: compactTimestamp(conversationTask.updatedAt) },
                ]}
                headerActions={(
                  <div className={styles.conversationActions}>
                    {runIsActive && latestRun ? (
                      <>
                        <button
                          type="button"
                          className={styles.secondaryAction}
                          disabled={pausePending || !pauseSelfAction?.enabled}
                          title={disabledReason(pauseSelfAction) || undefined}
                          onClick={onPauseRun}
                        >
                          {pausePending ? <LoaderCircle size={15} className={styles.spinning} /> : <Pause size={15} />}
                          {pauseRequested ? t("selfPauseRequested") : t("pauseSelfRun")}
                        </button>
                        <button
                          type="button"
                          className={styles.secondaryAction}
                          disabled={terminatePending || !terminateSelfAction?.enabled}
                          title={disabledReason(terminateSelfAction) || undefined}
                          onClick={onTerminateRun}
                        >
                          {terminatePending ? <LoaderCircle size={15} className={styles.spinning} /> : <Square size={15} />}
                          {terminateRequested ? t("selfStopRequested") : t("stopSelfRun")}
                        </button>
                      </>
                    ) : null}

                    {runIsPaused && latestRun ? (
                      <>
                        <button
                          type="button"
                          className={styles.secondaryAction}
                          disabled={resumePending || !resumeSelfAction?.enabled}
                          title={disabledReason(resumeSelfAction) || undefined}
                          onClick={onResumeRun}
                        >
                          {resumePending ? <LoaderCircle size={15} className={styles.spinning} /> : <Play size={15} />}
                          {t("resumeSelfRun")}
                        </button>
                        <button
                          type="button"
                          className={styles.secondaryAction}
                          disabled={terminatePending || !terminateSelfAction?.enabled}
                          title={disabledReason(terminateSelfAction) || undefined}
                          onClick={onTerminateRun}
                        >
                          {terminatePending ? <LoaderCircle size={15} className={styles.spinning} /> : <Square size={15} />}
                          {t("stopSelfRun")}
                        </button>
                      </>
                    ) : null}

                    {!runIsActive && !runIsPaused && latestRun && rollbackReady ? (
                      <button
                        type="button"
                        className={styles.secondaryAction}
                        disabled={rollbackPending || !rollbackSelfAction?.enabled}
                        title={disabledReason(rollbackSelfAction) || undefined}
                        onClick={onRollbackRun}
                      >
                        {rollbackPending ? <LoaderCircle size={15} className={styles.spinning} /> : <RotateCcw size={15} />}
                        {t("rollbackSelfRun")}
                      </button>
                    ) : null}

                    {!runIsActive && !runIsPaused && latestRun && rollbackBlocked ? (
                      <button
                        type="button"
                        className={styles.secondaryAction}
                        disabled={handoffPending || !handoffSelfAction?.enabled}
                        title={disabledReason(handoffSelfAction) || undefined}
                        onClick={onHandoffRun}
                      >
                        {handoffPending ? <LoaderCircle size={15} className={styles.spinning} /> : <ArrowUpRight size={15} />}
                        {t("handoffSelfRollback")}
                      </button>
                    ) : null}
                  </div>
                )}
                autoScrollToLatest={runIsActive}
                composerValue={goalInput}
                composerPlaceholder={t("selfGoalPlaceholder")}
                composerDisabled={!startSelfAction?.enabled || runLocked || startPending}
                composerPending={startPending}
                submitLabel={t("startSelfRun")}
                submitPendingLabel={t("loading")}
                onComposerChange={onGoalInputChange}
                onSubmit={onStartRun}
              />
            </div>
          </main>
        </div>
      ) : (
        <div className={styles.statusPage}>
          <div className={styles.panelStack}>
            <div className={styles.metricStrip}>
              <article className={styles.stripItem}>
                <span>{t("sceneStateTitle")}</span>
                <strong>{sceneSemantics?.sceneTitle || statusLabel(overview.readiness.state)}</strong>
              </article>
              <article className={styles.stripItem}>
                <span>{t("currentRunTitle")}</span>
                <strong>{runSemantics?.phaseLabel || runSemantics?.runStatusLabel || "--"}</strong>
              </article>
              <article className={styles.stripItem}>
                <span>{t("rollbackStateTitle")}</span>
                <strong>{runSemantics?.rollbackStateLabel || statusLabel(rollback?.status || "unavailable")}</strong>
              </article>
              <article className={styles.stripItem}>
                <span>{t("selfTransactions")}</span>
                <strong>{transactionItems.length}</strong>
              </article>
            </div>

            {actionFeedback || errorMessage ? (
              <div className={styles.noticeBanner}>
                {actionFeedback ? <p className={styles.feedbackText}>{actionFeedback}</p> : null}
                {errorMessage ? <p className={styles.errorText}>{errorMessage}</p> : null}
              </div>
            ) : null}

            <div className={styles.supportColumns}>
              <section className={styles.subsurface}>
                <div className={styles.subsurfaceHeader}>
                  <div>
                    <p className={styles.eyebrow}>{t("sceneStateTitle")}</p>
                    <h4 className={styles.subsurfaceTitle}>{sceneSemantics?.sceneTitle || t("selfWorktree")}</h4>
                  </div>
                  <span className={styles.secondaryPill}>
                    {overview.worktree.snapshotId || compactRevision(overview.worktree.baseRev)}
                  </span>
                </div>

                <div className={styles.detailStack}>
                  <div className={styles.detailRow}>
                    <span>{t("sceneStateTitle")}</span>
                    <strong>{sceneSemantics?.sceneTitle || statusLabel(overview.readiness.state)}</strong>
                  </div>
                  <div className={styles.detailRow}>
                    <span>{t("currentRunTitle")}</span>
                    <strong>{runSemantics?.phaseLabel || runSemantics?.runStatusLabel || "--"}</strong>
                  </div>
                  <div className={styles.detailRow}>
                    <span>{t("rollbackStateTitle")}</span>
                    <strong>{runSemantics?.rollbackStateLabel || statusLabel(rollback?.status || "unavailable")}</strong>
                  </div>
                  <div className={styles.detailRow}>
                    <span>{t("dirtyFlags")}</span>
                    <strong>{worktreeFlags.join(" / ") || t("worktreeClean")}</strong>
                  </div>
                </div>

                <div className={styles.subsection}>
                  <h5 className={styles.subsectionTitle}>{t("selfCurrentState")}</h5>
                  <div className={styles.listBlock}>
                    {currentStateNotes.map((item) => (
                      <div key={item} className={styles.listItem}>
                        {item}
                      </div>
                    ))}
                  </div>
                </div>

                <div className={styles.subsection}>
                  <div className={styles.paginationBar}>
                    <h5 className={styles.subsectionTitle}>{t("filesChanged")}</h5>
                    <div className={styles.paginationGroup}>
                      <span className={styles.mutedText}>
                        {worktreeFiles.length > 0
                          ? `${worktreePageStart}-${worktreePageEnd} / ${worktreeFiles.length}`
                          : `0 / ${worktreeFiles.length}`}
                      </span>
                      <button
                        type="button"
                        className={styles.paginationButton}
                        disabled={clampedWorktreePage <= 1}
                        onClick={() => setWorktreePage((current) => Math.max(1, current - 1))}
                        title={t("pagePrevious")}
                      >
                        <ChevronLeft size={15} />
                      </button>
                      {pageNumbers.map((page) => (
                        <button
                          key={page}
                          type="button"
                          className={page === clampedWorktreePage ? `${styles.paginationButton} ${styles.paginationButtonActive}` : styles.paginationButton}
                          onClick={() => setWorktreePage(page)}
                        >
                          {page}
                        </button>
                      ))}
                      <button
                        type="button"
                        className={styles.paginationButton}
                        disabled={clampedWorktreePage >= totalWorktreePages}
                        onClick={() => setWorktreePage((current) => Math.min(totalWorktreePages, current + 1))}
                        title={t("pageNext")}
                      >
                        <ChevronRight size={15} />
                      </button>
                    </div>
                  </div>

                  <div className={styles.worktreeFiles}>
                    {currentWorktreeFiles.length === 0 ? (
                      <div className={styles.listItem}>{overview.worktree.error || compactWorktreeSummary}</div>
                    ) : (
                      currentWorktreeFiles.map((file) => (
                        <div key={`${file.status}-${file.path}`} className={styles.listItem}>
                          <div className={styles.itemTop}>
                            <strong>{file.path}</strong>
                            <span className={styles.secondaryPill}>{file.status}</span>
                          </div>
                          <span className={styles.mutedText}>{worktreeFileFlags(t, file) || t("worktreeClean")}</span>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              </section>

              <section className={styles.subsurface}>
                <div className={styles.subsurfaceHeader}>
                  <div>
                    <p className={styles.eyebrow}>{t("selfRollback")}</p>
                    <h4 className={styles.subsurfaceTitle}>{latestRun?.runId || t("selfRollbackWaiting")}</h4>
                  </div>
                  <RotateCcw size={16} className={styles.headerIcon} />
                </div>

                {latestRun && rollback ? (
                  <>
                    <p className={styles.sectionSummary}>{rollback.reason || t("selfRollbackWaiting")}</p>
                    <div className={styles.detailStack}>
                      <div className={styles.detailRow}>
                        <span>{t("sourceRun")}</span>
                        <strong>{compactRevision(rollback.baseRev)}</strong>
                      </div>
                      <div className={styles.detailRow}>
                        <span>{t("filesChanged")}</span>
                        <strong>{rollback.entryCount}</strong>
                      </div>
                      <div className={styles.detailRow}>
                        <span>{t("selfConflictFiles")}</span>
                        <strong>{rollbackConflicts.length}</strong>
                      </div>
                      <div className={styles.detailRow}>
                        <span>{t("selfFinishedAt")}</span>
                        <strong>{compactTimestamp(rollback.rolledBackAt)}</strong>
                      </div>
                    </div>
                    <div className={styles.listBlock}>
                      {rollbackFiles.length === 0 ? (
                        <div className={styles.listItem}>{t("selfRollbackNoFiles")}</div>
                      ) : (
                        rollbackFiles.slice(0, 8).map((item) => (
                          <div key={`${item.path}-${item.changeType}`} className={styles.listItem}>
                            <div className={styles.itemTop}>
                              <strong>{item.path}</strong>
                              <span className={styles.secondaryPill}>{item.changeType}</span>
                            </div>
                            <span className={styles.mutedText}>
                              {item.conflict ? item.conflictReason || t("status_blocked") : item.statusAfter || "--"}
                            </span>
                          </div>
                        ))
                      )}
                    </div>
                  </>
                ) : (
                  <div className={styles.emptyState}>{t("selfRollbackWaiting")}</div>
                )}
              </section>
            </div>

            <div className={styles.supportColumns}>
              <section className={styles.subsurface}>
                <div className={styles.subsurfaceHeader}>
                  <div>
                    <p className={styles.eyebrow}>{t("selfTransactions")}</p>
                    <h4 className={styles.subsurfaceTitle}>{t("selfTransactions")}</h4>
                  </div>
                  <div className={styles.headerActionCluster}>
                    <span className={styles.counter}>{transactionItems.length}</span>
                    <button
                      type="button"
                      className={styles.selectionToggle}
                      disabled={visibleTransactionIds.length === 0}
                      onClick={toggleAllVisibleHistoryGroups}
                    >
                      <CheckSquare size={14} />
                      {allVisibleHistorySelected ? t("clearSelection") : t("selectForBatchDelete")}
                    </button>
                  </div>
                </div>

                <div className={styles.historyToolbar}>
                  <span className={styles.noticeText}>
                    {t("selfHistoryGroup")} {t("selectedCount")} {selectedHistoryTxnIds.length}
                  </span>
                  <div className={styles.toolbarActions}>
                    <button
                      type="button"
                      className={styles.secondaryAction}
                      disabled={selectedHistoryTxnIds.length === 0 || deleteHistoryPending}
                      onClick={() => setSelectedHistoryTxnIds([])}
                    >
                      <X size={14} />
                      {t("clearSelection")}
                    </button>
                    <button
                      type="button"
                      className={styles.secondaryAction}
                      disabled={selectedHistoryTxnIds.length === 0 || deleteHistoryPending}
                      title={selectedHistoryTxnIds.length === 0 ? t("deleteSelectedDisabledHistory") : undefined}
                      onClick={() => onDeleteHistoryGroups(selectedHistoryTxnIds)}
                    >
                      {deleteHistoryPending ? <LoaderCircle size={15} className={styles.spinning} /> : <ScrollText size={15} />}
                      {deleteHistoryPending ? t("deletingSelectedHistory") : t("deleteSelected")}
                    </button>
                  </div>
                </div>
                <p className={styles.noticeText}>{t("batchDeleteHint")}</p>

                <div className={styles.listBlock}>
                  {visibleTransactions.length === 0 ? (
                    <div className={styles.emptyState}>{t("selfNoTransactions")}</div>
                  ) : (
                    visibleTransactions.map((item) => (
                      <div
                        key={item.txnId}
                        className={
                          selectedHistorySet.has(item.txnId)
                            ? `${styles.listItem} ${styles.listItemSelected}`
                            : styles.listItem
                        }
                      >
                        <div className={styles.itemTop}>
                          <label className={styles.checkboxRow}>
                            <input
                              type="checkbox"
                              checked={selectedHistorySet.has(item.txnId)}
                              onChange={() => toggleHistorySelection(item.txnId)}
                            />
                            <strong>{item.txnId}</strong>
                          </label>
                          <div className={styles.pillRow}>
                            <span className={styles.secondaryPill}>{t("selfLinkedAuditCount")} {auditCountByTxnId.get(item.txnId) || 0}</span>
                            <span className={styles.secondaryPill}>{statusLabel(item.status)}</span>
                          </div>
                        </div>
                        <span className={styles.mutedText}>
                          {compactTimestamp(item.closedAt || item.openedAt)} · {compactRevision(item.baseRevShort || item.baseRev)}
                        </span>
                        <span className={styles.mutedText}>{item.summary || "--"}</span>
                      </div>
                    ))
                  )}
                </div>
              </section>

              <section className={styles.subsurface}>
                <div className={styles.subsurfaceHeader}>
                  <div>
                    <p className={styles.eyebrow}>{t("selfAuditTrail")}</p>
                    <h4 className={styles.subsurfaceTitle}>{t("selfAuditTrail")}</h4>
                  </div>
                  <span className={styles.counter}>{overview.auditTail.length}</span>
                </div>

                <div className={styles.listBlock}>
                  {visibleAuditTrail.length === 0 ? (
                    <div className={styles.emptyState}>{t("selfNoAudit")}</div>
                  ) : (
                    visibleAuditTrail.map((item) => (
                      <div
                        key={`${item.timestamp}-${item.event}-${item.txnId}`}
                        className={
                          item.txnId && selectedHistorySet.has(item.txnId)
                            ? `${styles.listItem} ${styles.listItemSelected}`
                            : styles.listItem
                        }
                      >
                        <div className={styles.itemTop}>
                          <strong>{item.event}</strong>
                          <div className={styles.pillRow}>
                            {item.txnId ? (
                              <span className={styles.secondaryPill}>{t("selfHistoryGroup")} {item.txnId}</span>
                            ) : null}
                            <span className={styles.secondaryPill}>{item.txnId || "--"}</span>
                          </div>
                        </div>
                        <span className={styles.mutedText}>{item.summary}</span>
                      </div>
                    ))
                  )}
                </div>
              </section>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
