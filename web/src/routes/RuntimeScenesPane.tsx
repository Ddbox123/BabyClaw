import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleAlert, Check, CheckSquare, Copy, ListFilter, Square, Trash2, TriangleAlert, X } from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type MouseEvent,
  type PointerEvent,
} from "react";

import { fetchJson } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import {
  LogFileContent,
  LogRoot,
  RuntimeSceneDeleteResponse,
  RuntimeSceneDetail,
  RuntimeSceneListItem,
} from "../api/types";
import { FilePreview } from "../components/preview/FilePreview";
import { TranslationKey } from "../i18n/dictionary";
import { classifyRuntimeSceneEvent, type LogSeverityFilter, matchesSeverityFilter } from "../logs/logSeverity";
import styles from "./LogsRoute.module.css";

type ActionNotice = {
  tone: "success" | "error";
  message: string;
};

const RESIZE_HANDLE_WIDTH = 16;
const RUNTIME_SCENES_SIDEBAR_STORAGE_KEY = "vibelution.logs.runtime-scenes-sidebar-width";
const DEFAULT_RUNTIME_SCENES_SIDEBAR_WIDTH = 320;
const MIN_RUNTIME_SCENES_SIDEBAR_WIDTH = 280;
const MAX_RUNTIME_SCENES_SIDEBAR_WIDTH = 560;
const MIN_RUNTIME_SCENES_PREVIEW_WIDTH = 520;
const KEYBOARD_RESIZE_STEP = 24;

type DragState = {
  startX: number;
  startWidth: number;
};

type RuntimeScenesPaneProps = {
  activeRoot: LogRoot;
  lang: "zh" | "en";
  t: (key: TranslationKey) => string;
  statusLabel: (status: string) => string;
};

function filterRuntimeScenes(items: RuntimeSceneListItem[], query: string): RuntimeSceneListItem[] {
  const term = query.trim().toLowerCase();
  if (!term) {
    return items;
  }
  return items.filter((item) =>
    [
      item.runtimeSceneId,
      item.directoryName,
      item.title,
      item.status,
      item.result,
      item.stopReason,
      item.trigger,
      item.backendStatus,
      item.frontendStatus,
      item.browserStatus,
    ]
      .join(" ")
      .toLowerCase()
      .includes(term),
  );
}

function uniqueIds(items: string[]): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const item of items) {
    const value = String(item || "").trim();
    if (!value || seen.has(value)) {
      continue;
    }
    seen.add(value);
    result.push(value);
  }
  return result;
}

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}

function getMaxSidebarWidth(layoutWidth: number) {
  const maxWidth = layoutWidth - RESIZE_HANDLE_WIDTH - MIN_RUNTIME_SCENES_PREVIEW_WIDTH;
  return Math.max(MIN_RUNTIME_SCENES_SIDEBAR_WIDTH, Math.min(MAX_RUNTIME_SCENES_SIDEBAR_WIDTH, maxWidth));
}

function normalizeSidebarWidth(layoutWidth: number, sidebarWidth: number) {
  return Math.round(clamp(sidebarWidth, MIN_RUNTIME_SCENES_SIDEBAR_WIDTH, getMaxSidebarWidth(layoutWidth)));
}

function describeError(error: unknown, fallback: string) {
  if (error instanceof Error && error.message) {
    return `${fallback}: ${error.message}`;
  }
  return fallback;
}

function formatTimestamp(value: string, lang: "zh" | "en") {
  const text = String(value || "").trim();
  if (!text) {
    return lang === "zh" ? "未记录" : "Not recorded";
  }
  const parsed = new Date(text);
  if (Number.isNaN(parsed.getTime())) {
    return text;
  }
  return parsed.toLocaleString(lang === "zh" ? "zh-CN" : "en-US", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function formatBytes(size: number) {
  const value = Number(size || 0);
  if (value < 1024) {
    return `${value} B`;
  }
  if (value < 1024 * 1024) {
    return `${(value / 1024).toFixed(1)} KB`;
  }
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

const runtimeSceneTokenZhMap: Record<string, string> = {
  start: "启动",
  "internal-start": "内部启动",
  "internal-restart": "内部重启",
  managed: "托管",
  current: "当前",
  pending: "待处理",
  healthy: "正常",
  stopped: "已停止",
  running: "运行中",
  success: "成功",
  failed: "失败",
  info: "信息",
  error: "错误",
  launcher: "启动器",
  frontend: "前端",
  backend: "后端",
  browser: "浏览器",
  supervisor: "监督器",
  session: "会话",
  startup: "启动",
  shutdown: "关闭",
  build: "构建",
  dependencies: "依赖",
  health: "健康检查",
  window: "窗口",
  browser_window_closed: "应用窗口已关闭",
  "app window closed": "应用窗口已关闭",
};

const runtimeSceneFieldZhMap: Record<string, string> = {
  directory_name: "目录名",
  browser_managed: "浏览器托管",
  trigger: "触发方式",
  port: "端口",
  host: "主机",
  python_label: "Python 环境",
  pid: "进程号",
  url: "地址",
  executable: "可执行文件",
  managed_session_id: "托管会话 ID",
  browser_window_pid: "浏览器窗口进程",
  backend_pid: "后端进程",
  supervisor_pid: "监督器进程",
  browser_stopped: "浏览器已停止",
  backend_stopped: "后端已停止",
  reason: "原因",
  window_pid: "窗口进程",
  launch_pid: "启动进程",
};

function localizeRuntimeSceneText(text: string, lang: "zh" | "en") {
  const normalized = String(text || "").trim();
  if (!normalized || lang !== "zh") {
    return normalized;
  }
  return runtimeSceneTokenZhMap[normalized] ?? normalized;
}

function summarizeFields(fields: Record<string, unknown>) {
  return Object.entries(fields)
    .slice(0, 4)
    .map(([key, value]) => `${key}: ${Array.isArray(value) ? value.join(", ") : String(value)}`);
}

async function copyText(text: string) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }

  const textArea = document.createElement("textarea");
  textArea.value = text;
  textArea.setAttribute("readonly", "true");
  textArea.style.position = "absolute";
  textArea.style.opacity = "0";
  textArea.style.pointerEvents = "none";
  document.body.appendChild(textArea);
  textArea.select();
  const copied = document.execCommand("copy");
  document.body.removeChild(textArea);
  if (!copied) {
    throw new Error("copy failed");
  }
}

export function RuntimeScenesPane({ activeRoot, lang, t, statusLabel }: RuntimeScenesPaneProps) {
  const queryClient = useQueryClient();
  const layoutRef = useRef<HTMLDivElement | null>(null);
  const [sceneSearch, setSceneSearch] = useState("");
  const [selectedSceneIds, setSelectedSceneIds] = useState<string[]>([]);
  const [activeSceneId, setActiveSceneId] = useState("");
  const [severityFilter, setSeverityFilter] = useState<LogSeverityFilter>("all");
  const [openRawLogByScene, setOpenRawLogByScene] = useState<Record<string, string>>({});
  const [copyState, setCopyState] = useState<"idle" | "copied" | "error">("idle");
  const [actionNotice, setActionNotice] = useState<ActionNotice | null>(null);
  const [dragState, setDragState] = useState<DragState | null>(null);
  const [sidebarWidth, setSidebarWidth] = useState(() => {
    if (typeof window === "undefined") {
      return DEFAULT_RUNTIME_SCENES_SIDEBAR_WIDTH;
    }
    const saved = Number(window.localStorage.getItem(RUNTIME_SCENES_SIDEBAR_STORAGE_KEY) || "");
    return Number.isFinite(saved)
      ? clamp(saved, MIN_RUNTIME_SCENES_SIDEBAR_WIDTH, MAX_RUNTIME_SCENES_SIDEBAR_WIDTH)
      : DEFAULT_RUNTIME_SCENES_SIDEBAR_WIDTH;
  });

  const runtimeScenesQuery = useQuery({
    queryKey: queryKeys.runtimeScenes(),
    queryFn: () => fetchJson<RuntimeSceneListItem[]>("/api/logs/runtime-scenes"),
    refetchInterval: 10_000,
    refetchIntervalInBackground: true,
  });

  const filteredScenes = useMemo(
    () => filterRuntimeScenes(runtimeScenesQuery.data ?? [], sceneSearch),
    [runtimeScenesQuery.data, sceneSearch],
  );
  const visibleSceneIds = useMemo(() => filteredScenes.map((item) => item.runtimeSceneId), [filteredScenes]);
  const selectedSceneIdSet = useMemo(() => new Set(selectedSceneIds), [selectedSceneIds]);

  useEffect(() => {
    const availableIds = new Set((runtimeScenesQuery.data ?? []).map((item) => item.runtimeSceneId));
    setSelectedSceneIds((current) => current.filter((id) => availableIds.has(id)));
    if (activeSceneId && availableIds.has(activeSceneId)) {
      return;
    }
    setActiveSceneId((runtimeScenesQuery.data ?? [])[0]?.runtimeSceneId ?? "");
  }, [activeSceneId, runtimeScenesQuery.data]);

  const sceneDetailQuery = useQuery({
    queryKey: queryKeys.runtimeScene(activeSceneId),
    enabled: Boolean(activeSceneId),
    queryFn: () => fetchJson<RuntimeSceneDetail>(`/api/logs/runtime-scenes/${encodeURIComponent(activeSceneId)}`),
    refetchInterval: 5_000,
    refetchIntervalInBackground: true,
  });

  const activeRawLogPath =
    (activeSceneId ? openRawLogByScene[activeSceneId] : "") || sceneDetailQuery.data?.rawFiles[0]?.path || "";

  useEffect(() => {
    if (!activeSceneId || !sceneDetailQuery.data) {
      return;
    }
    const availablePaths = new Set(sceneDetailQuery.data.rawFiles.map((item) => item.path));
    const current = openRawLogByScene[activeSceneId] ?? "";
    if (current && availablePaths.has(current)) {
      return;
    }
    setOpenRawLogByScene((state) => ({
      ...state,
      [activeSceneId]: sceneDetailQuery.data?.rawFiles[0]?.path ?? "",
    }));
  }, [activeSceneId, openRawLogByScene, sceneDetailQuery.data]);

  const sceneContentQuery = useQuery({
    queryKey: queryKeys.runtimeSceneContent(activeSceneId, activeRawLogPath),
    enabled: Boolean(activeSceneId && activeRawLogPath),
    queryFn: () =>
      fetchJson<LogFileContent>(
        `/api/logs/runtime-scenes/${encodeURIComponent(activeSceneId)}/content?path=${encodeURIComponent(activeRawLogPath)}`,
      ),
    refetchInterval: 5_000,
    refetchIntervalInBackground: true,
  });

  const deleteRuntimeScenesMutation = useMutation({
    mutationFn: async (sceneIds: string[]) =>
      fetchJson<RuntimeSceneDeleteResponse>("/api/logs/runtime-scenes/delete", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ sceneIds }),
      }),
    onSuccess: (payload, sceneIds) => {
      const deletedIdSet = new Set(payload.deletedSceneIds);
      setSelectedSceneIds((current) => current.filter((id) => !deletedIdSet.has(id)));
      setOpenRawLogByScene((current) => {
        const next: Record<string, string> = {};
        for (const [key, value] of Object.entries(current)) {
          if (!deletedIdSet.has(key)) {
            next[key] = value;
          }
        }
        return next;
      });
      if (deletedIdSet.has(activeSceneId)) {
        setActiveSceneId("");
      }
      queryClient.setQueryData<RuntimeSceneListItem[] | undefined>(queryKeys.runtimeScenes(), (current) =>
        (current ?? []).filter((item) => !deletedIdSet.has(item.runtimeSceneId)),
      );
      for (const sceneId of payload.deletedSceneIds) {
        queryClient.removeQueries({ queryKey: queryKeys.runtimeScene(sceneId) });
      }
      void queryClient.invalidateQueries({ queryKey: queryKeys.runtimeScenes() });
      setActionNotice({
        tone: "success",
        message: `已删除 ${payload.deletedCount} 组运行现场日志`,
      });
    },
    onError: (error) => {
      setActionNotice({
        tone: "error",
        message: describeError(error, t("logActionFailed")),
      });
    },
  });

  useEffect(() => {
    setCopyState("idle");
  }, [activeSceneId, activeRawLogPath, sceneContentQuery.data?.content]);

  useEffect(() => {
    if (copyState === "idle") {
      return;
    }
    const timeout = window.setTimeout(() => setCopyState("idle"), 1800);
    return () => window.clearTimeout(timeout);
  }, [copyState]);

  useEffect(() => {
    if (!actionNotice) {
      return;
    }
    const timeout = window.setTimeout(() => setActionNotice(null), 2400);
    return () => window.clearTimeout(timeout);
  }, [actionNotice]);

  const syncSidebarWidthToLayout = useCallback(() => {
    const layoutWidth = layoutRef.current?.getBoundingClientRect().width ?? 0;
    if (!layoutWidth) {
      return;
    }
    const normalized = normalizeSidebarWidth(layoutWidth, sidebarWidth);
    if (normalized !== sidebarWidth) {
      setSidebarWidth(normalized);
    }
  }, [sidebarWidth]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    window.localStorage.setItem(RUNTIME_SCENES_SIDEBAR_STORAGE_KEY, String(sidebarWidth));
  }, [sidebarWidth]);

  useEffect(() => {
    syncSidebarWidthToLayout();
    const layoutElement = layoutRef.current;
    if (!layoutElement) {
      return;
    }

    const observer = new ResizeObserver(() => {
      syncSidebarWidthToLayout();
    });
    observer.observe(layoutElement);
    return () => observer.disconnect();
  }, [syncSidebarWidthToLayout]);

  useEffect(() => {
    if (!dragState) {
      return;
    }

    const activeDrag = dragState;
    const previousCursor = document.body.style.cursor;
    const previousUserSelect = document.body.style.userSelect;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";

    function stopDragging() {
      setDragState(null);
    }

    function handlePointerMove(event: globalThis.PointerEvent) {
      const layoutWidth = layoutRef.current?.getBoundingClientRect().width ?? 0;
      if (!layoutWidth) {
        return;
      }
      const delta = event.clientX - activeDrag.startX;
      setSidebarWidth(normalizeSidebarWidth(layoutWidth, activeDrag.startWidth + delta));
    }

    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", stopDragging);
    window.addEventListener("pointercancel", stopDragging);
    window.addEventListener("mousemove", handlePointerMove as EventListener);
    window.addEventListener("mouseup", stopDragging);

    return () => {
      document.body.style.cursor = previousCursor;
      document.body.style.userSelect = previousUserSelect;
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", stopDragging);
      window.removeEventListener("pointercancel", stopDragging);
      window.removeEventListener("mousemove", handlePointerMove as EventListener);
      window.removeEventListener("mouseup", stopDragging);
    };
  }, [dragState]);

  const copyLabel =
    copyState === "copied" ? t("copied") : copyState === "error" ? t("copyFailed") : t("copyContent");
  const severityFilterOptions: Array<{
    value: LogSeverityFilter;
    label: string;
    icon: typeof ListFilter;
  }> = [
    { value: "all", label: t("logSeverityAll"), icon: ListFilter },
    { value: "error", label: t("logSeverityError"), icon: CircleAlert },
    { value: "warning", label: t("logSeverityWarning"), icon: TriangleAlert },
  ];
  const selectedCountLabel =
    lang === "zh" ? `${t("selectedScenes")} ${selectedSceneIds.length} 组` : `${selectedSceneIds.length} ${t("selectedScenes")}`;
  const severityFilterControl = (
    <div className={styles.filterGroup} role="group" aria-label={t("logSeverityFilter")}>
      {severityFilterOptions.map((option) => {
        const Icon = option.icon;
        const active = severityFilter === option.value;
        return (
          <button
            key={option.value}
            type="button"
            className={active ? `${styles.filterButton} ${styles.filterButtonActive}` : styles.filterButton}
            onClick={() => setSeverityFilter(option.value)}
          >
            <Icon size={14} />
            <span>{option.label}</span>
          </button>
        );
      })}
    </div>
  );

  function handleToggleSelection(sceneId: string) {
    setSelectedSceneIds((current) => {
      const next = current.includes(sceneId) ? current.filter((item) => item !== sceneId) : [...current, sceneId];
      return uniqueIds(next);
    });
  }

  function handleSelectVisible() {
    setSelectedSceneIds(uniqueIds(visibleSceneIds));
  }

  function handleClearSelection() {
    setSelectedSceneIds([]);
  }

  function handleOpenRawLog(sceneId: string, path: string) {
    setOpenRawLogByScene((current) => ({
      ...current,
      [sceneId]: path,
    }));
  }

  async function handleCopy() {
    if (!sceneContentQuery.data?.content) {
      return;
    }
    try {
      await copyText(sceneContentQuery.data.content);
      setCopyState("copied");
    } catch {
      setCopyState("error");
    }
  }

  function buildDeleteConfirmationLabel(sceneIds: string[]) {
    const names = sceneIds.slice(0, 4);
    const tail = sceneIds.length > names.length ? `\n等 ${sceneIds.length} 组运行。` : "";
    return `确认删除这 ${sceneIds.length} 组运行现场日志吗？\n${names.map((name) => `- ${name}`).join("\n")}${tail}`;
  }

  function handleDeleteSelected() {
    if (selectedSceneIds.length === 0 || deleteRuntimeScenesMutation.isPending) {
      return;
    }
    if (!window.confirm(buildDeleteConfirmationLabel(selectedSceneIds))) {
      return;
    }
    deleteRuntimeScenesMutation.mutate(selectedSceneIds);
  }

  const previewActions = (
    <div className={styles.previewActions}>
      <button type="button" className={styles.copyButton} onClick={handleCopy} disabled={!sceneContentQuery.data?.content}>
        {copyState === "copied" ? <Check size={15} /> : <Copy size={15} />}
        <span>{copyLabel}</span>
      </button>
    </div>
  );

  const layoutStyle = useMemo(
    () =>
      ({
        "--logs-sidebar-width": `${sidebarWidth}px`,
      }) as CSSProperties,
    [sidebarWidth],
  );

  function beginResize(clientX: number) {
    setDragState({
      startX: clientX,
      startWidth: sidebarWidth,
    });
  }

  function handleResizeStart(event: PointerEvent<HTMLButtonElement>) {
    if (event.button !== 0) {
      return;
    }
    event.preventDefault();
    beginResize(event.clientX);
  }

  function handleResizeMouseDown(event: MouseEvent<HTMLButtonElement>) {
    if (event.button !== 0) {
      return;
    }
    event.preventDefault();
    beginResize(event.clientX);
  }

  function handleResizeKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (!layoutRef.current) {
      return;
    }

    const { key } = event;
    const direction =
      key === "ArrowLeft" ? -1 : key === "ArrowRight" ? 1 : key === "Home" ? "min" : key === "End" ? "max" : null;
    if (direction === null) {
      return;
    }

    event.preventDefault();
    const layoutWidth = layoutRef.current.getBoundingClientRect().width;
    const maxWidth = getMaxSidebarWidth(layoutWidth);
    const nextWidth =
      direction === "min"
        ? MIN_RUNTIME_SCENES_SIDEBAR_WIDTH
        : direction === "max"
          ? maxWidth
          : clamp(
              sidebarWidth + Number(direction) * KEYBOARD_RESIZE_STEP,
              MIN_RUNTIME_SCENES_SIDEBAR_WIDTH,
              maxWidth,
            );
    setSidebarWidth(Math.round(nextWidth));
  }

  return (
    <div ref={layoutRef} className={styles.resizableLayout} style={layoutStyle}>
      <aside className={styles.sidebar}>
        <div className={styles.sidebarHeader}>
          <div>
            <p className={styles.sidebarEyebrow}>{t("logsRootRuntimeScenes")}</p>
            <h2 className={styles.sidebarTitle}>{activeRoot.path}</h2>
            <p className={styles.railText}>{t("runtimeScenesSubtitle")}</p>
          </div>
          <div className={styles.selectionToolbar}>
            <span className={styles.selectionPill}>{selectedCountLabel}</span>
            <div className={styles.selectionActions}>
              <button
                type="button"
                className={styles.toolbarButton}
                onClick={handleSelectVisible}
                disabled={visibleSceneIds.length === 0}
              >
                <CheckSquare size={15} />
                <span>{t("selectVisibleRuntimeScenes")}</span>
              </button>
              <button
                type="button"
                className={styles.toolbarButton}
                onClick={handleClearSelection}
                disabled={selectedSceneIds.length === 0}
              >
                <X size={15} />
                <span>{t("clearSelection")}</span>
              </button>
              <button
                type="button"
                className={styles.deleteButton}
                onClick={handleDeleteSelected}
                disabled={selectedSceneIds.length === 0 || deleteRuntimeScenesMutation.isPending}
                title={selectedSceneIds.length === 0 ? t("deleteSelectedRuntimeScenesDisabled") : undefined}
              >
                <Trash2 size={15} />
                <span>
                  {deleteRuntimeScenesMutation.isPending
                    ? t("deletingSelectedRuntimeScenes")
                    : t("deleteSelectedRuntimeScenes")}
                </span>
              </button>
            </div>
          </div>
          {actionNotice ? (
            <p
              className={
                actionNotice.tone === "success"
                  ? `${styles.notice} ${styles.noticeSuccess}`
                  : `${styles.notice} ${styles.noticeError}`
              }
            >
              {actionNotice.message}
            </p>
          ) : null}
        </div>

        <div className={styles.panelSearch}>
          <input
            className={styles.panelSearchInput}
            type="text"
            value={sceneSearch}
            onChange={(event) => setSceneSearch(event.target.value)}
            placeholder={t("searchRuntimeScenesPlaceholder")}
          />
        </div>

        <div className={styles.fileList}>
          {runtimeScenesQuery.isError ? (
            <div className={styles.panelState}>{describeError(runtimeScenesQuery.error, t("loadFailed"))}</div>
          ) : runtimeScenesQuery.isPending && !runtimeScenesQuery.data ? (
            <div className={styles.panelState}>{t("loadingLogs")}</div>
          ) : filteredScenes.length === 0 ? (
            <div className={styles.panelState}>
              {sceneSearch.trim() ? t("noRuntimeSceneMatches") : t("noRuntimeScenesYet")}
            </div>
          ) : (
            filteredScenes.map((scene) => {
              const isActive = activeSceneId === scene.runtimeSceneId;
              const isSelected = selectedSceneIdSet.has(scene.runtimeSceneId);
              return (
                <div
                  key={scene.runtimeSceneId}
                  className={isActive ? `${styles.sceneCard} ${styles.sceneCardActive}` : styles.sceneCard}
                >
                  <div className={styles.sceneCardTop}>
                    <button
                      type="button"
                      className={
                        isSelected
                          ? `${styles.treeSelectButton} ${styles.treeSelectButtonActive}`
                          : styles.treeSelectButton
                      }
                      onClick={() => handleToggleSelection(scene.runtimeSceneId)}
                      title={isSelected ? t("clearSelection") : t("selectVisibleRuntimeScenes")}
                    >
                      {isSelected ? <CheckSquare size={16} /> : <Square size={16} />}
                    </button>
                    <button
                      type="button"
                      className={styles.sceneCardButton}
                      onClick={() => setActiveSceneId(scene.runtimeSceneId)}
                    >
                      <div className={styles.sceneCardHeader}>
                        <strong>{scene.runtimeSceneId}</strong>
                        <span className={styles.sceneCardStatus}>{statusLabel(scene.status)}</span>
                      </div>
                      <div className={styles.sceneCardMeta}>
                        <span>{formatTimestamp(scene.startedAt, lang)}</span>
                        <span>{scene.eventCount} 条事件</span>
                        <span>{scene.rawLogCount} 个原始日志</span>
                      </div>
                      <p className={styles.sceneCardSummary}>
                        {localizeRuntimeSceneText(
                          scene.stopReason || scene.result || scene.title || scene.directoryName,
                          lang,
                        )}
                      </p>
                    </button>
                  </div>
                  <div className={styles.scenePillRow}>
                    <span className={styles.metaPill}>{localizeRuntimeSceneText(scene.trigger || "start", lang)}</span>
                    <span className={styles.metaPill}>{localizeRuntimeSceneText(scene.frontendStatus || "pending", lang)}</span>
                    <span className={styles.metaPill}>{localizeRuntimeSceneText(scene.backendStatus || "pending", lang)}</span>
                  </div>
                </div>
              );
            })
          )}
        </div>
      </aside>

      <button
        type="button"
        role="separator"
        aria-orientation="vertical"
        aria-label={t("resizeLeftPanel")}
        title={t("resizeLeftPanel")}
        tabIndex={0}
        className={
          dragState ? `${styles.resizeHandle} ${styles.resizeHandleActive}` : styles.resizeHandle
        }
        onPointerDown={handleResizeStart}
        onMouseDown={handleResizeMouseDown}
        onKeyDown={handleResizeKeyDown}
      />

      <section className={styles.previewPane}>
        {!activeSceneId ? (
          <div className={styles.emptySurface}>{t("selectRuntimeScene")}</div>
        ) : sceneDetailQuery.isError ? (
          <div className={styles.emptySurface}>{describeError(sceneDetailQuery.error, t("loadFailed"))}</div>
        ) : sceneDetailQuery.isPending && !sceneDetailQuery.data ? (
          <div className={styles.emptySurface}>{t("loadingFilePreview")}</div>
        ) : sceneDetailQuery.data ? (
          <div className={styles.sceneDetailSurface}>
            <div className={styles.sceneDetailHeader}>
              <div>
                <p className={styles.eyebrow}>{t("logsRootRuntimeScenes")}</p>
                <h2 className={styles.sceneDetailTitle}>{sceneDetailQuery.data.runtimeSceneId}</h2>
                <p className={styles.sceneDetailSummary}>
                  {localizeRuntimeSceneText(
                    sceneDetailQuery.data.stopReason || sceneDetailQuery.data.result || sceneDetailQuery.data.directoryName,
                    lang,
                  )}
                </p>
              </div>
              <div className={styles.scenePillRow}>
                <span className={styles.metaPill}>{statusLabel(sceneDetailQuery.data.status)}</span>
                <span className={styles.metaPill}>
                  {localizeRuntimeSceneText(sceneDetailQuery.data.trigger || "start", lang)}
                </span>
                <span className={styles.metaPill}>
                  {localizeRuntimeSceneText(sceneDetailQuery.data.sessionMode || "managed", lang)}
                </span>
              </div>
            </div>

            <div className={styles.sceneMetricGrid}>
              <article className={styles.sceneMetricCard}>
                <span>{t("runtimeSceneStartedAt")}</span>
                <strong>{formatTimestamp(sceneDetailQuery.data.startedAt, lang)}</strong>
              </article>
              <article className={styles.sceneMetricCard}>
                <span>{t("runtimeSceneEndedAt")}</span>
                <strong>{formatTimestamp(sceneDetailQuery.data.endedAt, lang)}</strong>
              </article>
              <article className={styles.sceneMetricCard}>
                <span>{t("runtimeSceneResult")}</span>
                <strong>
                  {localizeRuntimeSceneText(sceneDetailQuery.data.result || statusLabel(sceneDetailQuery.data.status), lang)}
                </strong>
              </article>
              <article className={styles.sceneMetricCard}>
                <span>{t("runtimeSceneTrigger")}</span>
                <strong>{localizeRuntimeSceneText(sceneDetailQuery.data.trigger || "start", lang)}</strong>
              </article>
            </div>

            <div className={styles.sceneInfoGrid}>
              <article className={styles.sceneInfoCard}>
                <div className={styles.sceneCardHeaderRow}>
                  <h3>{t("runtimeSceneTimeline")}</h3>
                  {severityFilterControl}
                </div>
                <div className={styles.timelineList}>
                  {sceneDetailQuery.data.timeline.length === 0 ? (
                    <div className={styles.panelState}>{t("runtimeSceneNoTimeline")}</div>
                  ) : sceneDetailQuery.data.timeline.filter((event) =>
                      matchesSeverityFilter(classifyRuntimeSceneEvent(event), severityFilter),
                    ).length === 0 ? (
                    <div className={styles.panelState}>{t("logSeverityEmpty")}</div>
                  ) : (
                    sceneDetailQuery.data.timeline
                      .filter((event) => matchesSeverityFilter(classifyRuntimeSceneEvent(event), severityFilter))
                      .map((event) => {
                      const severity = classifyRuntimeSceneEvent(event);
                      const timelineItemClassName =
                        severity === "error"
                          ? `${styles.timelineItem} ${styles.timelineItemError}`
                          : severity === "warning"
                            ? `${styles.timelineItem} ${styles.timelineItemWarning}`
                            : styles.timelineItem;
                      return (
                        <div key={`${event.component}-${event.seq}-${event.timestamp}`} className={timelineItemClassName}>
                          <div className={styles.timelineHeader}>
                            <span>{formatTimestamp(event.timestamp, lang)}</span>
                            <span>{localizeRuntimeSceneText(event.component, lang)}</span>
                            <span>{localizeRuntimeSceneText(event.phase, lang)}</span>
                            <span>{localizeRuntimeSceneText(event.level, lang)}</span>
                          </div>
                          <strong className={styles.timelineCode}>{event.eventCode}</strong>
                          <p className={styles.timelineMessage}>{localizeRuntimeSceneText(event.message, lang)}</p>
                          {summarizeFields(event.fields).length > 0 ? (
                            <div className={styles.timelineFields}>
                              {Object.entries(event.fields)
                                .slice(0, 4)
                                .map(([key, value]) => {
                                  const label = runtimeSceneFieldZhMap[key] ?? key;
                                  const rendered = Array.isArray(value) ? value.join(", ") : String(value);
                                  return (
                                    <span key={`${key}:${rendered}`} className={styles.timelineField}>
                                      {`${label}: ${localizeRuntimeSceneText(rendered, lang)}`}
                                    </span>
                                  );
                                })}
                            </div>
                          ) : null}
                          {event.rawRefs.length > 0 ? (
                            <div className={styles.timelineRawRefs}>
                              {event.rawRefs.map((ref) => (
                                <button
                                  key={`${event.eventCode}-${ref.path}`}
                                  type="button"
                                  className={styles.toolbarButton}
                                  onClick={() => handleOpenRawLog(sceneDetailQuery.data.runtimeSceneId, ref.path)}
                                >
                                  <span>{t("runtimeSceneOpenRaw")}</span>
                                  <span>{ref.path}</span>
                                </button>
                              ))}
                            </div>
                          ) : null}
                        </div>
                      );
                    })
                  )}
                </div>
              </article>

              <article className={styles.sceneInfoCard}>
                <div className={styles.sceneRawHeader}>
                  <div>
                    <h3>{t("runtimeSceneRawLogs")}</h3>
                    <p className={styles.sceneDetailSummary}>{sceneDetailQuery.data.manifestPath}</p>
                  </div>
                  <div className={styles.sceneHeaderControls}>
                    {severityFilterControl}
                    {previewActions}
                  </div>
                </div>

                <div className={styles.rawFileTabs}>
                  {sceneDetailQuery.data.rawFiles.length === 0 ? (
                    <div className={styles.panelState}>{t("runtimeSceneNoRawLogs")}</div>
                  ) : (
                    sceneDetailQuery.data.rawFiles.map((item) => (
                      <button
                        key={item.path}
                        type="button"
                        className={
                          activeRawLogPath === item.path
                            ? `${styles.rawFileButton} ${styles.rawFileButtonActive}`
                            : styles.rawFileButton
                        }
                        onClick={() => handleOpenRawLog(sceneDetailQuery.data.runtimeSceneId, item.path)}
                      >
                        <span>{item.label}</span>
                        <span>{formatBytes(item.size)}</span>
                      </button>
                    ))
                  )}
                </div>

                <div className={styles.sceneRawPreview}>
                  {sceneContentQuery.isError ? (
                    <div className={styles.panelState}>{describeError(sceneContentQuery.error, t("loadFailed"))}</div>
                  ) : sceneContentQuery.isPending && !sceneContentQuery.data ? (
                    <div className={styles.panelState}>{t("loadingFilePreview")}</div>
                  ) : sceneContentQuery.data ? (
                    <FilePreview
                      file={sceneContentQuery.data}
                      changed={false}
                      sourceLabel={activeRoot.path}
                      headerActions={null}
                      highlightAsLog
                      severityFilter={severityFilter}
                    />
                  ) : (
                    <div className={styles.panelState}>{t("runtimeSceneNoRawLogs")}</div>
                  )}
                </div>
              </article>
            </div>
          </div>
        ) : (
          <div className={styles.emptySurface}>{t("loadingFilePreview")}</div>
        )}
      </section>
    </div>
  );
}
