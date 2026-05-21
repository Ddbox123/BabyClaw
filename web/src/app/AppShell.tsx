import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigationType } from "react-router-dom";
import { GitBranch, LoaderCircle, Power, Settings } from "lucide-react";

import { fetchJson, setFetchJsonFailureReporter } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import { BackendHealth, ConfigSummary, GitStatusSummary, RuntimeSummary, ShutdownResponse } from "../api/types";
import { useAppI18n } from "../i18n/useAppI18n";
import {
  collectBrowserPageSnapshot,
  postBrowserTelemetry,
  summarizeConsoleArgs,
  type BrowserTelemetryEventInput,
} from "./browserTelemetry";
import {
  backendSystemTone,
  deriveBackendSystemState,
  deriveFrontendSystemState,
  deriveRuntimeControllerState,
  frontendSystemTone,
  runtimeControllerTone,
  type SystemStatusTone,
} from "./systemStatus";
import { isWorkbenchDomainEnabled, isWorkbenchModeEnabled } from "./workbenchContract";
import styles from "./AppShell.module.css";

function linkClassName({ isActive }: { isActive: boolean }) {
  return isActive ? `${styles.navLink} ${styles.navLinkActive}` : styles.navLink;
}

function formatHistoryTarget(value: string | URL | null | undefined): string {
  if (!value) {
    return "";
  }
  return typeof value === "string" ? value : value.toString();
}

function compactGitPath(path: string): string {
  const normalized = path.replaceAll("\\", "/");
  if (normalized.length <= 52) {
    return normalized;
  }
  const parts = normalized.split("/");
  const fileName = parts.pop() ?? normalized;
  const parent = parts.pop();
  return parent ? `.../${parent}/${fileName}` : `.../${fileName}`;
}

export function AppShell() {
  const { lang, t } = useAppI18n();
  const location = useLocation();
  const navigationType = useNavigationType();
  const [shutdownOpen, setShutdownOpen] = useState(false);
  const [shutdownTitle, setShutdownTitle] = useState("");
  const [shutdownDetail, setShutdownDetail] = useState("");
  const [shutdownFailed, setShutdownFailed] = useState(false);
  const [shutdownRequested, setShutdownRequested] = useState(false);
  const [clockNow, setClockNow] = useState(() => Date.now());
  const [frontendVisible, setFrontendVisible] = useState(
    () => (typeof document === "undefined" ? true : document.visibilityState === "visible"),
  );
  const [frontendOnline, setFrontendOnline] = useState(
    () => (typeof navigator === "undefined" ? true : navigator.onLine),
  );
  const shutdownPromiseRef = useRef<Promise<void> | null>(null);
  const telemetrySeqRef = useRef(0);
  const pageInstanceIdRef = useRef(`page-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`);
  const configQuery = useQuery({
    queryKey: queryKeys.configPublic(),
    queryFn: () => fetchJson<ConfigSummary>("/api/config/public"),
  });
  const runtimeRefetchInterval = shutdownOpen || shutdownRequested ? 1_000 : 5_000;
  const runtimeQuery = useQuery({
    queryKey: queryKeys.runtimeSummary(),
    queryFn: () => fetchJson<RuntimeSummary>("/api/runtime/summary"),
    refetchInterval: runtimeRefetchInterval,
    refetchIntervalInBackground: true,
  });
  const backendHealthQuery = useQuery({
    queryKey: queryKeys.backendHealth(),
    queryFn: () =>
      fetchJson<BackendHealth>("/api/health", {
        cache: "no-store",
      }),
    refetchInterval: runtimeRefetchInterval,
    refetchIntervalInBackground: true,
    staleTime: 0,
    retry: false,
  });
  const gitStatusQuery = useQuery({
    queryKey: queryKeys.gitStatus(),
    queryFn: () => fetchJson<GitStatusSummary>("/api/git/status"),
    refetchInterval: 6_000,
    refetchIntervalInBackground: true,
  });

  const workbench = runtimeQuery.data?.workbench;
  const shutdownInFlight = workbench?.desiredState === "closed" && workbench?.observedState !== "closed";
  const chatEnabled = isWorkbenchDomainEnabled(configQuery.data, "chat");
  const supervisedEvolutionEnabled = isWorkbenchModeEnabled(configQuery.data, "supervised_evolution");
  const selfEvolutionEnabled = isWorkbenchModeEnabled(configQuery.data, "self_evolution");
  const closeWorkbenchLabel = lang === "en" ? "Close workbench" : "关闭工作台";
  const shutdownHeading = lang === "en" ? "Closing workbench" : "正在关闭工作台";
  const shutdownBody = lang === "en"
    ? "Please keep this window open. The runtime manager will close the backend and app window."
    : "请先保持这个窗口打开。运行时管理器会负责关闭后端和应用窗口。";
  const shutdownErrorBody = lang === "en"
    ? "The runtime manager could not close the workbench. Check the launcher and runtime-manager logs."
    : "运行时管理器没有成功关闭工作台。请检查 launcher 和 runtime-manager 日志。";
  const locale = lang === "zh" ? "zh-CN" : "en-US";
  const timezone = useMemo(
    () => Intl.DateTimeFormat().resolvedOptions().timeZone || (lang === "en" ? "Local time" : "本地时间"),
    [lang],
  );
  const clockFormatter = useMemo(
    () =>
      new Intl.DateTimeFormat(locale, {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false,
      }),
    [locale],
  );
  const fullClockFormatter = useMemo(
    () =>
      new Intl.DateTimeFormat(locale, {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false,
      }),
    [locale],
  );

  const frontendState = deriveFrontendSystemState({
    online: frontendOnline,
    visible: frontendVisible,
  });
  const backendState = deriveBackendSystemState({
    isPending: backendHealthQuery.isPending,
    hasData: Boolean(backendHealthQuery.data),
    isError: backendHealthQuery.isError,
    health: backendHealthQuery.data,
  });
  const runtimeControllerState = deriveRuntimeControllerState(runtimeQuery.data);
  const currentTime = clockFormatter.format(clockNow);
  const fullCurrentTime = fullClockFormatter.format(clockNow);
  const buildId = __VIBELUTION_BUILD_ID__;
  const gitStatus = gitStatusQuery.data;
  const gitAvailable = Boolean(gitStatus?.available);
  const gitDirty = Boolean(gitStatus?.dirty);
  const gitTone: SystemStatusTone = gitAvailable ? (gitDirty ? "caution" : "running") : "idle";
  const gitBranch = gitStatus?.branch || gitStatus?.headRevShort || "-";
  const gitValue = gitAvailable
    ? gitDirty
      ? `${gitStatus?.counts.total ?? 0}`
      : t("gitClean")
    : gitStatusQuery.isPending
      ? t("gitChecking")
      : t("gitUnavailable");
  const gitTitle = gitAvailable
    ? `${t("gitStatus")}: ${gitStatus?.summary ?? ""}`
    : gitStatus?.error || t("gitUnavailable");

  const frontendStateLabel = {
    connected: t("systemFrontend_connected"),
    background: t("systemFrontend_background"),
    offline: t("systemFrontend_offline"),
  }[frontendState];
  const backendStateLabel = {
    healthy: t("backendHealthy"),
    checking: t("backendChecking"),
    offline: t("backendOffline"),
    unhealthy: t("backendUnhealthy"),
  }[backendState];
  const runtimeControllerLabel = {
    managed: t("systemRuntime_managed"),
    closing: t("systemRuntime_closing"),
    unmanaged: t("systemRuntime_unmanaged"),
    failed: t("systemRuntime_failed"),
  }[runtimeControllerState];

  const emitBrowserTelemetry = useCallback((
    payload: BrowserTelemetryEventInput,
    options?: { preferBeacon?: boolean },
  ) => {
    telemetrySeqRef.current += 1;
    postBrowserTelemetry(
      {
        ...payload,
        fields: {
          pageInstanceId: pageInstanceIdRef.current,
          seq: telemetrySeqRef.current,
          ...collectBrowserPageSnapshot(),
          ...(payload.fields ?? {}),
        },
      },
      options,
    );
  }, []);

  const beginShutdown = useCallback(() => {
    if (shutdownPromiseRef.current) {
      return shutdownPromiseRef.current;
    }

    const task = (async () => {
      setShutdownRequested(true);
      setShutdownFailed(false);
      setShutdownOpen(true);
      setShutdownTitle(shutdownHeading);
      setShutdownDetail(shutdownBody);

      const payload = await fetchJson<ShutdownResponse>("/api/runtime/shutdown", {
        method: "POST",
      });
      if (payload.message) {
        setShutdownDetail(payload.message);
      }
    })().catch(() => {
      setShutdownRequested(false);
      setShutdownOpen(true);
      setShutdownFailed(true);
      setShutdownTitle(shutdownHeading);
      setShutdownDetail(shutdownErrorBody);
    }).finally(() => {
      shutdownPromiseRef.current = null;
    });

    shutdownPromiseRef.current = task;
    return task;
  }, [shutdownBody, shutdownErrorBody, shutdownHeading]);

  useEffect(() => {
    document.documentElement.lang = lang === "zh" ? "zh-CN" : "en";
    document.title = t("appTitle");
  }, [lang, t]);

  useEffect(() => {
    setFetchJsonFailureReporter((failure) => {
      emitBrowserTelemetry({
        phase: "api",
        eventCode: failure.failureKind === "network" ? "browser.api.network_error" : "browser.api.request_failed",
        message: `${failure.method} ${failure.endpoint} failed${failure.status === null ? "" : ` (${failure.status})`}`,
        level: "error",
        fields: {
          endpoint: failure.endpoint,
          method: failure.method,
          status: failure.status,
          failureKind: failure.failureKind,
          failureMessage: failure.message,
        },
      });
    });
    return () => setFetchJsonFailureReporter(null);
  }, [emitBrowserTelemetry]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      setClockNow(Date.now());
    }, 1_000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    function handleVisibilityChange() {
      setFrontendVisible(document.visibilityState === "visible");
      emitBrowserTelemetry({
        phase: "lifecycle",
        eventCode: "browser.visibility.changed",
        message: `Visibility changed to ${document.visibilityState}`,
        fields: {
          visibilityState: document.visibilityState,
        },
      });
    }

    function handleOnline() {
      setFrontendOnline(true);
      emitBrowserTelemetry({
        phase: "network",
        eventCode: "browser.network.changed",
        message: "Browser is online",
        fields: {
          online: true,
        },
      });
    }

    function handleOffline() {
      setFrontendOnline(false);
      emitBrowserTelemetry({
        phase: "network",
        eventCode: "browser.network.changed",
        message: "Browser is offline",
        level: "warning",
        fields: {
          online: false,
        },
      });
    }

    document.addEventListener("visibilitychange", handleVisibilityChange);
    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);

    return () => {
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
    };
  }, [emitBrowserTelemetry]);

  useEffect(() => {
    const snapshotTimer = window.setTimeout(() => {
      emitBrowserTelemetry({
        phase: "page",
        eventCode: "browser.page.snapshot",
        message: `Page snapshot for ${window.location.pathname || "/"}`,
        fields: {
          reason: "app_shell_mounted",
        },
      });
    }, 0);

    function handlePageHide(event: PageTransitionEvent) {
      emitBrowserTelemetry(
        {
          phase: "lifecycle",
          eventCode: "browser.page.hide",
          message: `Page hide at ${window.location.pathname || "/"}`,
          fields: {
            persisted: event.persisted,
          },
        },
        { preferBeacon: true },
      );
    }

    window.addEventListener("pagehide", handlePageHide);
    return () => {
      window.clearTimeout(snapshotTimer);
      window.removeEventListener("pagehide", handlePageHide);
    };
  }, [emitBrowserTelemetry]);

  useEffect(() => {
    emitBrowserTelemetry({
      phase: "navigation",
      eventCode: "browser.route.changed",
      message: `React route changed to ${location.pathname || "/"}`,
      fields: {
        routerPathname: location.pathname,
        routerSearch: location.search,
        routerHash: location.hash,
        navigationType,
      },
    });
  }, [emitBrowserTelemetry, location.hash, location.pathname, location.search, navigationType]);

  useEffect(() => {
    const originalPushState = window.history.pushState.bind(window.history) as History["pushState"];
    const originalReplaceState = window.history.replaceState.bind(window.history) as History["replaceState"];

    const logHistoryMutation = (eventCode: string, targetUrl: string) => {
      window.setTimeout(() => {
        emitBrowserTelemetry({
          phase: "navigation",
          eventCode,
          message: `${eventCode} -> ${window.location.pathname || "/"}`,
          fields: {
            targetUrl,
          },
        });
      }, 0);
    };

    window.history.pushState = ((...args: Parameters<History["pushState"]>) => {
      const result = originalPushState(...args);
      logHistoryMutation("browser.history.push_state", formatHistoryTarget(args[2]));
      return result;
    }) as History["pushState"];

    window.history.replaceState = ((...args: Parameters<History["replaceState"]>) => {
      const result = originalReplaceState(...args);
      logHistoryMutation("browser.history.replace_state", formatHistoryTarget(args[2]));
      return result;
    }) as History["replaceState"];

    function handlePopState() {
      emitBrowserTelemetry({
        phase: "navigation",
        eventCode: "browser.history.pop_state",
        message: `popstate -> ${window.location.pathname || "/"}`,
      });
    }

    window.addEventListener("popstate", handlePopState);
    return () => {
      window.history.pushState = originalPushState;
      window.history.replaceState = originalReplaceState;
      window.removeEventListener("popstate", handlePopState);
    };
  }, [emitBrowserTelemetry]);

  useEffect(() => {
    const originalWarn = window.console.warn.bind(window.console) as Console["warn"];
    const originalError = window.console.error.bind(window.console) as Console["error"];

    window.console.warn = ((...args: Parameters<Console["warn"]>) => {
      emitBrowserTelemetry({
        phase: "console",
        eventCode: "browser.console.warn",
        message: summarizeConsoleArgs(args as unknown[], 240) || "Console warn",
        level: "warning",
        fields: {
          argsPreview: summarizeConsoleArgs(args as unknown[], 1200),
        },
      });
      originalWarn(...args);
    }) as Console["warn"];

    window.console.error = ((...args: Parameters<Console["error"]>) => {
      emitBrowserTelemetry({
        phase: "console",
        eventCode: "browser.console.error",
        message: summarizeConsoleArgs(args as unknown[], 240) || "Console error",
        level: "error",
        fields: {
          argsPreview: summarizeConsoleArgs(args as unknown[], 1200),
        },
      });
      originalError(...args);
    }) as Console["error"];

    return () => {
      window.console.warn = originalWarn;
      window.console.error = originalError;
    };
  }, [emitBrowserTelemetry]);

  useEffect(() => {
    function handleWindowError(event: ErrorEvent) {
      const target = event.target;
      if (target instanceof Element && target !== document.documentElement && target !== document.body) {
        const resourceUrl = target instanceof HTMLLinkElement
          ? target.href
          : target instanceof HTMLScriptElement
            ? target.src
            : target instanceof HTMLImageElement
              ? target.currentSrc || target.src
              : target.getAttribute("src") || target.getAttribute("href") || "";

        emitBrowserTelemetry({
          phase: "error",
          eventCode: "browser.resource.error",
          message: resourceUrl ? `Resource failed to load: ${resourceUrl}` : "Resource failed to load",
          level: "error",
          fields: {
            resourceUrl,
            tagName: target.tagName.toLowerCase(),
          },
        });
        return;
      }

      const stack = event.error instanceof Error ? event.error.stack || "" : "";
      emitBrowserTelemetry({
        phase: "error",
        eventCode: "browser.page.error",
        message: event.message || "Uncaught browser error",
        level: "error",
        fields: {
          filename: event.filename,
          lineno: event.lineno,
          colno: event.colno,
          stack: stack || summarizeConsoleArgs([event.error], 1200),
        },
      });
    }

    function handleUnhandledRejection(event: PromiseRejectionEvent) {
      emitBrowserTelemetry({
        phase: "error",
        eventCode: "browser.promise.rejected",
        message: summarizeConsoleArgs([event.reason], 240) || "Unhandled promise rejection",
        level: "error",
        fields: {
          reason: summarizeConsoleArgs([event.reason], 1200),
        },
      });
    }

    window.addEventListener("error", handleWindowError, true);
    window.addEventListener("unhandledrejection", handleUnhandledRejection);
    return () => {
      window.removeEventListener("error", handleWindowError, true);
      window.removeEventListener("unhandledrejection", handleUnhandledRejection);
    };
  }, [emitBrowserTelemetry]);

  useEffect(() => {
    if (!workbench) {
      return;
    }

    const closing = workbench.desiredState === "closed" && workbench.observedState !== "closed";
    const failed = workbench.phase === "failed" && workbench.desiredState === "closed";

    if (failed) {
      setShutdownRequested(false);
      setShutdownOpen(true);
      setShutdownFailed(true);
      setShutdownTitle(shutdownHeading);
      setShutdownDetail(workbench.failureMessage || shutdownErrorBody);
      return;
    }

    if (closing) {
      setShutdownOpen(true);
      setShutdownFailed(false);
      setShutdownTitle(shutdownHeading);
      setShutdownDetail(workbench.statusLine || shutdownBody);
      return;
    }

    if (!shutdownRequested) {
      return;
    }

    if (workbench.desiredState === "closed" && workbench.observedState === "closed") {
      setShutdownOpen(true);
      setShutdownFailed(false);
      setShutdownTitle(shutdownHeading);
      setShutdownDetail(workbench.statusLine || shutdownBody);
    }
  }, [shutdownBody, shutdownErrorBody, shutdownHeading, shutdownRequested, workbench]);

  const systemStatusCards: Array<{
    id: string;
    label: string;
    value: string;
    tone: SystemStatusTone;
    note: string;
    states: Array<{ label: string; tone: SystemStatusTone; detail: string }>;
  }> = [
    {
      id: "frontend",
      label: t("systemFrontend"),
      value: frontendStateLabel,
      tone: frontendSystemTone(frontendState),
      note: `${t("systemFrontendHint")} · ${t("frontendBuild")} ${buildId}`,
      states: [
        {
          label: t("systemFrontend_connected"),
          tone: frontendSystemTone("connected"),
          detail: t("systemFrontendPossible_connected"),
        },
        {
          label: t("systemFrontend_background"),
          tone: frontendSystemTone("background"),
          detail: t("systemFrontendPossible_background"),
        },
        {
          label: t("systemFrontend_offline"),
          tone: frontendSystemTone("offline"),
          detail: t("systemFrontendPossible_offline"),
        },
      ],
    },
    {
      id: "backend",
      label: t("systemBackend"),
      value: backendStateLabel,
      tone: backendSystemTone(backendState),
      note:
        backendState === "healthy"
          ? t("backendReachable")
          : backendState === "checking"
            ? t("backendNeverReached")
            : backendState === "offline"
              ? t("backendNoResponse")
              : t("systemBackendHint"),
      states: [
        {
          label: t("backendHealthy"),
          tone: backendSystemTone("healthy"),
          detail: t("systemBackendPossible_healthy"),
        },
        {
          label: t("backendChecking"),
          tone: backendSystemTone("checking"),
          detail: t("systemBackendPossible_checking"),
        },
        {
          label: t("backendOffline"),
          tone: backendSystemTone("offline"),
          detail: t("systemBackendPossible_offline"),
        },
        {
          label: t("backendUnhealthy"),
          tone: backendSystemTone("unhealthy"),
          detail: t("systemBackendPossible_unhealthy"),
        },
      ],
    },
    {
      id: "runtime",
      label: t("systemRuntime"),
      value: runtimeControllerLabel,
      tone: runtimeControllerTone(runtimeControllerState),
      note: workbench?.statusLine || t("systemRuntimeHint"),
      states: [
        {
          label: t("systemRuntime_managed"),
          tone: runtimeControllerTone("managed"),
          detail: t("systemRuntimePossible_managed"),
        },
        {
          label: t("systemRuntime_closing"),
          tone: runtimeControllerTone("closing"),
          detail: t("systemRuntimePossible_closing"),
        },
        {
          label: t("systemRuntime_unmanaged"),
          tone: runtimeControllerTone("unmanaged"),
          detail: t("systemRuntimePossible_unmanaged"),
        },
        {
          label: t("systemRuntime_failed"),
          tone: runtimeControllerTone("failed"),
          detail: t("systemRuntimePossible_failed"),
        },
      ],
    },
    {
      id: "time",
      label: t("systemTime"),
      value: currentTime,
      tone: "idle",
      note: `${fullCurrentTime} · ${timezone}`,
      states: [
        {
          label: t("systemTimeLive"),
          tone: "idle",
          detail: t("systemTimePossible_live"),
        },
      ],
    },
  ];

  return (
    <div className={styles.shell}>
      {shutdownOpen ? (
        <div className={styles.shutdownOverlay} role="status" aria-live="polite" aria-busy={!shutdownFailed}>
          <div className={styles.shutdownPanel}>
            <LoaderCircle size={22} className={shutdownFailed ? styles.shutdownIconStill : styles.shutdownIconSpin} />
            <div className={styles.shutdownCopy}>
              <strong>{shutdownTitle}</strong>
              <p>{shutdownDetail}</p>
            </div>
          </div>
        </div>
      ) : null}
      <header className={styles.topBar}>
        <div className={styles.brandBlock}>
          <span className={styles.brand}>Vibelution</span>
          <span className={styles.brandSubtle}>{t("brandSubtle")}</span>
        </div>

        <nav className={styles.nav}>
          {chatEnabled ? (
            <NavLink to="/chat" className={linkClassName} reloadDocument>
              {t("navChat")}
            </NavLink>
          ) : (
            <span className={`${styles.navLink} ${styles.navLinkDisabled}`} aria-disabled="true">
              {t("navChat")}
            </span>
          )}
          {supervisedEvolutionEnabled ? (
            <NavLink to="/supervised-evolution" className={linkClassName} reloadDocument>
              {t("navSupervisedEvolution")}
            </NavLink>
          ) : (
            <span className={`${styles.navLink} ${styles.navLinkDisabled}`} aria-disabled="true">
              {t("navSupervisedEvolution")}
            </span>
          )}
          {selfEvolutionEnabled ? (
            <NavLink to="/self-evolution" className={linkClassName} reloadDocument>
              {t("navSelfEvolution")}
            </NavLink>
          ) : (
            <span className={`${styles.navLink} ${styles.navLinkDisabled}`} aria-disabled="true">
              {t("navSelfEvolution")}
            </span>
          )}
          <NavLink to="/logs" className={linkClassName} reloadDocument>
            {t("navLogs")}
          </NavLink>
        </nav>

        <div className={styles.topActions}>
          <div className={styles.gitCluster} tabIndex={0} aria-label={t("gitStatusGuide")} title={gitTitle}>
            <div className={styles.gitChip}>
              <GitBranch size={14} />
              <span className={`${styles.statusDot} ${styles[`status_${gitTone}`]}`} />
              <span className={styles.gitBranchName}>{gitBranch}</span>
              <strong className={styles.gitCount}>{gitValue}</strong>
            </div>
            <div className={styles.gitPanel} role="note" aria-live="polite">
              <div className={styles.statusGuideHeader}>
                <strong>{t("gitStatusGuide")}</strong>
                <span>{t("gitStatusGuideHint")}</span>
              </div>
              <div className={styles.gitMetaGrid}>
                <span>{t("gitBranch")}</span>
                <strong>{gitBranch}</strong>
                <span>{t("gitHead")}</span>
                <strong>{gitStatus?.headRevShort || "-"}</strong>
                <span>{t("gitChangedFiles")}</span>
                <strong>{gitStatus?.counts.total ?? 0}</strong>
              </div>
              <div className={styles.gitCountGrid}>
                <span>{t("gitStaged")} <strong>{gitStatus?.counts.staged ?? 0}</strong></span>
                <span>{t("gitUnstaged")} <strong>{gitStatus?.counts.unstaged ?? 0}</strong></span>
                <span>{t("gitUntracked")} <strong>{gitStatus?.counts.untracked ?? 0}</strong></span>
                <span>{t("gitDeleted")} <strong>{gitStatus?.counts.deleted ?? 0}</strong></span>
              </div>
              <div className={styles.gitFileSection}>
                <strong>{t("gitRecentChanges")}</strong>
                {gitStatus?.files.length ? (
                  <ul className={styles.gitFileList}>
                    {gitStatus.files.slice(0, 10).map((file) => (
                      <li key={`${file.status}-${file.path}`}>
                        <span className={styles.gitFileStatus}>{file.status}</span>
                        <span className={styles.gitFilePath} title={file.path}>{compactGitPath(file.path)}</span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className={styles.gitEmpty}>{gitAvailable ? t("gitNoChanges") : gitTitle}</p>
                )}
                {gitStatus?.truncated ? <p className={styles.gitEmpty}>{t("gitTruncated")}</p> : null}
              </div>
            </div>
          </div>
          <div className={styles.statusCluster} tabIndex={0} aria-label={t("systemStatusGuide")}>
            <div className={styles.statusChipRow}>
              {systemStatusCards.map((item) => (
                <span key={item.id} className={styles.statusBadge}>
                  <span className={`${styles.statusDot} ${styles[`status_${item.tone}`]}`} />
                  <span className={styles.statusBadgeLabel}>{item.label}</span>
                  <strong className={styles.statusBadgeValue}>{item.value}</strong>
                </span>
              ))}
            </div>
            <div className={styles.statusGuidePanel} role="note" aria-live="polite">
              <div className={styles.statusGuideHeader}>
                <strong>{t("systemStatusGuide")}</strong>
                <span>{t("systemStatusGuideHint")}</span>
              </div>
              <div className={styles.statusGuideGrid}>
                {systemStatusCards.map((item) => (
                  <section key={item.id} className={styles.statusGuideCard}>
                    <div className={styles.statusGuideCardHeader}>
                      <span>{item.label}</span>
                      <strong>{item.value}</strong>
                    </div>
                    <p className={styles.statusGuideNote}>{item.note}</p>
                    <ul className={styles.statusGuideList}>
                      {item.states.map((state) => (
                        <li key={`${item.id}-${state.label}`} className={styles.statusGuideListItem}>
                          <span className={`${styles.statusDot} ${styles[`status_${state.tone}`]}`} />
                          <span className={styles.statusGuideStateLabel}>{state.label}</span>
                          <span className={styles.statusGuideStateDetail}>{state.detail}</span>
                        </li>
                      ))}
                    </ul>
                  </section>
                ))}
              </div>
            </div>
          </div>
          <button
            type="button"
            className={styles.actionIconButton}
            aria-label={closeWorkbenchLabel}
            title={closeWorkbenchLabel}
            onClick={() => {
              void beginShutdown();
            }}
            disabled={shutdownInFlight && !shutdownFailed}
          >
            <Power size={16} />
          </button>
          <NavLink
            to="/config"
            className={styles.actionIconButton}
            aria-label={t("navConfig")}
            title={t("navConfig")}
            reloadDocument
          >
            <Settings size={16} />
          </NavLink>
        </div>
      </header>

      <main className={styles.mainArea}>
        <Outlet />
      </main>
    </div>
  );
}
