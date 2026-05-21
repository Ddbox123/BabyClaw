import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CircleAlert,
  Check,
  CheckSquare,
  Copy,
  Eraser,
  ListFilter,
  Search,
  Square,
  TriangleAlert,
  Trash2,
  X,
} from "lucide-react";
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
  FileTreeNode,
  LogDeleteResponse,
  LogDiagnostics,
  LogFileContent,
  LogRoot,
  LogTreeResponse,
} from "../api/types";
import { FilePreview } from "../components/preview/FilePreview";
import { useAppI18n } from "../i18n/useAppI18n";
import { type LogSeverityFilter } from "../logs/logSeverity";
import { RuntimeScenesPane } from "./RuntimeScenesPane";
import styles from "./LogsRoute.module.css";

const ROOT_LABEL_KEYS = {
  runtime_scenes: "logsRootRuntimeScenes",
  runtime_logs: "logsRootRuntime",
  workspace_logs: "logsRootWorkspace",
  conversation_logs: "logsRootConversation",
} as const;

type RootLabelKey = (typeof ROOT_LABEL_KEYS)[keyof typeof ROOT_LABEL_KEYS];
type ActionNotice = {
  tone: "success" | "error";
  message: string;
};

const RESIZE_HANDLE_WIDTH = 16;
const LOG_SIDEBAR_STORAGE_KEY = "vibelution.logs.sidebar-width";
const LOG_RIGHT_RAIL_STORAGE_KEY = "vibelution.logs.right-rail-width";
const DEFAULT_LOG_SIDEBAR_WIDTH = 320;
const DEFAULT_LOG_RIGHT_RAIL_WIDTH = 280;
const MIN_LOG_SIDEBAR_WIDTH = 280;
const MIN_LOG_RIGHT_RAIL_WIDTH = 220;
const MAX_LOG_SIDEBAR_WIDTH = 560;
const MAX_LOG_RIGHT_RAIL_WIDTH = 520;
const MIN_LOG_PREVIEW_WIDTH = 520;
const MIN_LOG_MAIN_WIDTH = 640;
const KEYBOARD_RESIZE_STEP = 24;

type DragState = {
  startX: number;
  startWidth: number;
};

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}

function getMaxSidebarWidth(layoutWidth: number) {
  const maxWidth = layoutWidth - RESIZE_HANDLE_WIDTH - MIN_LOG_PREVIEW_WIDTH;
  return Math.max(MIN_LOG_SIDEBAR_WIDTH, Math.min(MAX_LOG_SIDEBAR_WIDTH, maxWidth));
}

function normalizeSidebarWidth(layoutWidth: number, sidebarWidth: number) {
  return Math.round(clamp(sidebarWidth, MIN_LOG_SIDEBAR_WIDTH, getMaxSidebarWidth(layoutWidth)));
}

function getMaxRightRailWidth(layoutWidth: number) {
  const maxWidth = layoutWidth - RESIZE_HANDLE_WIDTH - MIN_LOG_MAIN_WIDTH;
  return Math.max(MIN_LOG_RIGHT_RAIL_WIDTH, Math.min(MAX_LOG_RIGHT_RAIL_WIDTH, maxWidth));
}

function normalizeRightRailWidth(layoutWidth: number, rightRailWidth: number) {
  return Math.round(clamp(rightRailWidth, MIN_LOG_RIGHT_RAIL_WIDTH, getMaxRightRailWidth(layoutWidth)));
}

function filterTree(nodes: FileTreeNode[], query: string): FileTreeNode[] {
  const term = query.trim().toLowerCase();
  if (!term) {
    return nodes;
  }
  return nodes.flatMap((node) => {
    const matches = node.name.toLowerCase().includes(term) || node.path.toLowerCase().includes(term);
    if (node.type === "directory") {
      const filteredChildren = filterTree(node.children ?? [], query);
      if (matches) {
        return [{ ...node, children: node.children ?? [] }];
      }
      if (filteredChildren.length > 0) {
        return [{ ...node, children: filteredChildren }];
      }
      return [];
    }
    return matches ? [node] : [];
  });
}

function findFirstFile(nodes: FileTreeNode[]): string | null {
  for (const node of nodes) {
    if (node.type === "file") {
      return node.path;
    }
    const childMatch = findFirstFile(node.children ?? []);
    if (childMatch) {
      return childMatch;
    }
  }
  return null;
}

function treeContainsPath(nodes: FileTreeNode[], targetPath: string): boolean {
  return nodes.some((node) => {
    if (node.path === targetPath) {
      return true;
    }
    if (node.type === "directory") {
      return treeContainsPath(node.children ?? [], targetPath);
    }
    return false;
  });
}

function collectFilePaths(nodes: FileTreeNode[]): string[] {
  const paths: string[] = [];
  for (const node of nodes) {
    if (node.type === "file") {
      paths.push(node.path);
      continue;
    }
    paths.push(...collectFilePaths(node.children ?? []));
  }
  return paths;
}

function uniquePaths(items: string[]): string[] {
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

function removePathsFromTree(nodes: FileTreeNode[], deletedPaths: Set<string>): FileTreeNode[] {
  const nextNodes: FileTreeNode[] = [];
  for (const node of nodes) {
    if (node.type === "file") {
      if (!deletedPaths.has(node.path)) {
        nextNodes.push(node);
      }
      continue;
    }
    nextNodes.push({
      ...node,
      children: removePathsFromTree(node.children ?? [], deletedPaths),
    });
  }
  return nextNodes;
}

function renderTree(
  nodes: FileTreeNode[],
  activeFilePath: string | null,
  selectedPaths: Set<string>,
  onOpenFile: (path: string) => void,
  onToggleSelection: (path: string) => void,
  labels: {
    selectFile: string;
    deselectFile: string;
  },
) {
  return nodes.map((node) => {
    if (node.type === "directory") {
      return (
        <details key={node.path} className={styles.treeDir} open>
          <summary>{node.name}</summary>
          <div className={styles.treeChildren}>
            {renderTree(
              node.children ?? [],
              activeFilePath,
              selectedPaths,
              onOpenFile,
              onToggleSelection,
              labels,
            )}
          </div>
        </details>
      );
    }

    const isActive = activeFilePath === node.path;
    const isSelected = selectedPaths.has(node.path);
    const fileName = node.path.split("/").at(-1) ?? node.path;
    return (
      <div
        key={node.path}
        className={
          isActive ? `${styles.treeFileRow} ${styles.treeFileRowActive}` : styles.treeFileRow
        }
      >
        <button
          type="button"
          className={
            isSelected
              ? `${styles.treeSelectButton} ${styles.treeSelectButtonActive}`
              : styles.treeSelectButton
          }
          onClick={() => onToggleSelection(node.path)}
          title={isSelected ? labels.deselectFile : labels.selectFile}
          aria-label={`${isSelected ? labels.deselectFile : labels.selectFile} ${fileName}`}
        >
          {isSelected ? <CheckSquare size={16} /> : <Square size={16} />}
        </button>
        <button
          type="button"
          className={
            isActive ? `${styles.treeFileButton} ${styles.treeFileButtonActive}` : styles.treeFileButton
          }
          onClick={() => onOpenFile(node.path)}
        >
          <span className={styles.treeFileName}>{node.name}</span>
          <span className={styles.treeFilePath}>{node.path}</span>
        </button>
      </div>
    );
  });
}

function describeError(error: unknown, fallback: string) {
  if (error instanceof Error && error.message) {
    return `${fallback}: ${error.message}`;
  }
  return fallback;
}

function formatBytes(size: number) {
  if (!Number.isFinite(size) || size <= 0) {
    return "0 B";
  }
  const units = ["B", "KB", "MB", "GB"];
  let value = size;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  return `${value.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
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
  return new Intl.DateTimeFormat(lang === "zh" ? "zh-CN" : "en-US", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(parsed);
}

function severityLabel(severity: string, lang: "zh" | "en") {
  if (severity === "error") {
    return lang === "zh" ? "有错误" : "Errors";
  }
  if (severity === "warning") {
    return lang === "zh" ? "有警告" : "Warnings";
  }
  return lang === "zh" ? "未见明显异常" : "No obvious issues";
}

function severityClassName(severity: string) {
  if (severity === "error") {
    return `${styles.diagnosticPill} ${styles.diagnosticPillError}`;
  }
  if (severity === "warning") {
    return `${styles.diagnosticPill} ${styles.diagnosticPillWarning}`;
  }
  return `${styles.diagnosticPill} ${styles.diagnosticPillInfo}`;
}

function renderDiagnosticsPanel(diagnostics: LogDiagnostics, lang: "zh" | "en") {
  const firstSignalLabel =
    diagnostics.firstSignalLine === null || diagnostics.firstSignalLine === undefined
      ? lang === "zh"
        ? "无"
        : "None"
      : `${lang === "zh" ? "第" : "Line "}${diagnostics.firstSignalLine}${lang === "zh" ? " 行" : ""}`;
  return (
    <section className={styles.diagnosticsPanel}>
      <div className={styles.diagnosticsHeader}>
        <div>
          <p className={styles.sidebarEyebrow}>{lang === "zh" ? "诊断摘要" : "Diagnostic Summary"}</p>
          <h2 className={styles.sidebarTitle}>
            {lang === "zh" ? "先看这里，再读原文" : "Start here, then inspect raw log"}
          </h2>
        </div>
        <span className={severityClassName(diagnostics.severity)}>
          {severityLabel(diagnostics.severity, lang)}
        </span>
      </div>
      <p className={styles.diagnosticsSummary}>{diagnostics.userSummary}</p>
      <div className={styles.diagnosticMetricGrid}>
        <span>
          <strong>{diagnostics.errorCount}</strong>
          {lang === "zh" ? " 错误" : " errors"}
        </span>
        <span>
          <strong>{diagnostics.warningCount}</strong>
          {lang === "zh" ? " 警告" : " warnings"}
        </span>
        <span>
          <strong>{diagnostics.lineCount}</strong>
          {lang === "zh" ? " 行" : " lines"}
        </span>
        <span>
          <strong>{diagnostics.structuredEventCount}</strong>
          {lang === "zh" ? " 结构事件" : " structured"}
        </span>
      </div>
      <div className={styles.diagnosticHintGrid}>
        <article>
          <span>{lang === "zh" ? "首个信号" : "First signal"}</span>
          <strong>{firstSignalLabel}</strong>
          {diagnostics.firstSignalPreview ? <p>{diagnostics.firstSignalPreview}</p> : null}
        </article>
        <article>
          <span>{lang === "zh" ? "建议动作" : "Suggested next step"}</span>
          <p>{diagnostics.suggestedNextStep}</p>
        </article>
        <article>
          <span>{lang === "zh" ? "Agent 排查锚点" : "Agent investigation anchor"}</span>
          <code>{diagnostics.agentHint}</code>
        </article>
      </div>
      {diagnostics.topEventTypes.length > 0 ? (
        <div className={styles.eventTypeList}>
          {diagnostics.topEventTypes.map((item) => (
            <span key={`${item.type}:${item.count}`} className={styles.metaPill}>
              {item.type} × {item.count}
            </span>
          ))}
        </div>
      ) : null}
    </section>
  );
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

export function LogsRoute() {
  const { lang, t, statusLabel } = useAppI18n();
  const queryClient = useQueryClient();
  const workspaceRef = useRef<HTMLDivElement | null>(null);
  const layoutRef = useRef<HTMLDivElement | null>(null);
  const [activeRootId, setActiveRootId] = useState<string>("");
  const [openPaths, setOpenPaths] = useState<Record<string, string>>({});
  const [selectedLogPathsByRoot, setSelectedLogPathsByRoot] = useState<Record<string, string[]>>({});
  const [fileFilter, setFileFilter] = useState("");
  const [severityFilter, setSeverityFilter] = useState<LogSeverityFilter>("all");
  const [copyState, setCopyState] = useState<"idle" | "copied" | "error">("idle");
  const [actionNotice, setActionNotice] = useState<ActionNotice | null>(null);
  const [dragState, setDragState] = useState<DragState | null>(null);
  const [rightRailDragState, setRightRailDragState] = useState<DragState | null>(null);
  const [sidebarWidth, setSidebarWidth] = useState(() => {
    if (typeof window === "undefined") {
      return DEFAULT_LOG_SIDEBAR_WIDTH;
    }
    const saved = Number(window.localStorage.getItem(LOG_SIDEBAR_STORAGE_KEY) || "");
    return Number.isFinite(saved)
      ? clamp(saved, MIN_LOG_SIDEBAR_WIDTH, MAX_LOG_SIDEBAR_WIDTH)
      : DEFAULT_LOG_SIDEBAR_WIDTH;
  });
  const [rightRailWidth, setRightRailWidth] = useState(() => {
    if (typeof window === "undefined") {
      return DEFAULT_LOG_RIGHT_RAIL_WIDTH;
    }
    const saved = Number(window.localStorage.getItem(LOG_RIGHT_RAIL_STORAGE_KEY) || "");
    return Number.isFinite(saved)
      ? clamp(saved, MIN_LOG_RIGHT_RAIL_WIDTH, MAX_LOG_RIGHT_RAIL_WIDTH)
      : DEFAULT_LOG_RIGHT_RAIL_WIDTH;
  });

  const rootsQuery = useQuery({
    queryKey: queryKeys.logRoots(),
    queryFn: () => fetchJson<LogRoot[]>("/api/logs/roots"),
    refetchInterval: 10_000,
    refetchIntervalInBackground: true,
  });

  useEffect(() => {
    if (!rootsQuery.data?.length) {
      return;
    }
    if (!activeRootId || !rootsQuery.data.some((root) => root.id === activeRootId)) {
      setActiveRootId(rootsQuery.data[0].id);
    }
  }, [activeRootId, rootsQuery.data]);

  const activeRoot = useMemo(
    () => rootsQuery.data?.find((root) => root.id === activeRootId) ?? rootsQuery.data?.[0] ?? null,
    [activeRootId, rootsQuery.data],
  );

  const activeRootLabelKey = activeRoot ? ROOT_LABEL_KEYS[activeRoot.id as keyof typeof ROOT_LABEL_KEYS] : null;
  const isRuntimeScenesRoot = activeRoot?.id === "runtime_scenes";

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

  const syncRightRailWidthToLayout = useCallback(() => {
    const layoutWidth = workspaceRef.current?.getBoundingClientRect().width ?? 0;
    if (!layoutWidth) {
      return;
    }
    const normalized = normalizeRightRailWidth(layoutWidth, rightRailWidth);
    if (normalized !== rightRailWidth) {
      setRightRailWidth(normalized);
    }
  }, [rightRailWidth]);

  const treeQuery = useQuery({
    queryKey: queryKeys.logTree(activeRoot?.id ?? ""),
    enabled: Boolean(activeRoot?.id) && !isRuntimeScenesRoot,
    queryFn: () =>
      fetchJson<LogTreeResponse>(`/api/logs/tree?root=${encodeURIComponent(activeRoot?.id ?? "")}`),
    refetchInterval: 5_000,
    refetchIntervalInBackground: true,
  });

  const activeFilePath = activeRoot ? openPaths[activeRoot.id] ?? "" : "";
  const selectedLogPaths = activeRoot ? selectedLogPathsByRoot[activeRoot.id] ?? [] : [];
  const selectedLogPathSet = useMemo(() => new Set(selectedLogPaths), [selectedLogPaths]);

  useEffect(() => {
    if (isRuntimeScenesRoot || !activeRoot || !treeQuery.data) {
      return;
    }

    const allFilePaths = collectFilePaths(treeQuery.data.nodes);
    const availablePaths = new Set(allFilePaths);

    setSelectedLogPathsByRoot((current) => {
      const existing = current[activeRoot.id] ?? [];
      const next = existing.filter((path) => availablePaths.has(path));
      if (next.length === existing.length && next.every((path, index) => path === existing[index])) {
        return current;
      }
      return {
        ...current,
        [activeRoot.id]: next,
      };
    });

    const currentPath = openPaths[activeRoot.id] ?? "";
    const hasCurrentPath = currentPath ? treeContainsPath(treeQuery.data.nodes, currentPath) : false;
    if (hasCurrentPath) {
      return;
    }
    const firstFile = findFirstFile(treeQuery.data.nodes) ?? "";
    setOpenPaths((current) => {
      if ((current[activeRoot.id] ?? "") === firstFile) {
        return current;
      }
      return {
        ...current,
        [activeRoot.id]: firstFile,
      };
    });
  }, [activeRoot, isRuntimeScenesRoot, openPaths, treeQuery.data]);

  const contentQuery = useQuery({
    queryKey: queryKeys.logContent(activeRoot?.id ?? "", activeFilePath),
    enabled: Boolean(activeRoot?.id && activeFilePath) && !isRuntimeScenesRoot,
    queryFn: () =>
      fetchJson<LogFileContent>(
        `/api/logs/content?root=${encodeURIComponent(activeRoot?.id ?? "")}&path=${encodeURIComponent(activeFilePath)}`,
      ),
    refetchInterval: 5_000,
    refetchIntervalInBackground: true,
  });

  const clearLogMutation = useMutation({
    mutationFn: async ({ root, path }: { root: string; path: string }) =>
      fetchJson<LogFileContent>("/api/logs/clear", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ root, path }),
      }),
    onSuccess: (payload, variables) => {
      queryClient.setQueryData(queryKeys.logContent(variables.root, variables.path), payload);
      setActionNotice({
        tone: "success",
        message: `已清空 ${variables.path.split("/").at(-1) ?? variables.path}`,
      });
    },
    onError: (error) => {
      setActionNotice({
        tone: "error",
        message: describeError(error, t("logActionFailed")),
      });
    },
  });

  const deleteLogsMutation = useMutation({
    mutationFn: async ({ root, paths }: { root: string; paths: string[] }) =>
      fetchJson<LogDeleteResponse>("/api/logs/delete", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ root, paths }),
      }),
    onSuccess: (payload, variables) => {
      const deletedPathSet = new Set(payload.deletedPaths);
      setSelectedLogPathsByRoot((current) => ({
        ...current,
        [variables.root]: (current[variables.root] ?? []).filter((path) => !deletedPathSet.has(path)),
      }));
      setOpenPaths((current) => ({
        ...current,
        [variables.root]: deletedPathSet.has(current[variables.root] ?? "") ? "" : (current[variables.root] ?? ""),
      }));
      queryClient.setQueryData<LogTreeResponse | undefined>(
        queryKeys.logTree(variables.root),
        (current) =>
          current
            ? {
                ...current,
                nodes: removePathsFromTree(current.nodes, deletedPathSet),
              }
            : current,
      );
      for (const path of payload.deletedPaths) {
        queryClient.removeQueries({ queryKey: queryKeys.logContent(variables.root, path) });
      }
      void queryClient.invalidateQueries({ queryKey: queryKeys.logTree(variables.root) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.logRoots() });
      setActionNotice({
        tone: "success",
        message: `已删除 ${payload.deletedCount} 个日志文件`,
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
  }, [activeRoot?.id, activeFilePath, contentQuery.data?.content]);

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

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    window.localStorage.setItem(LOG_SIDEBAR_STORAGE_KEY, String(sidebarWidth));
  }, [sidebarWidth]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    window.localStorage.setItem(LOG_RIGHT_RAIL_STORAGE_KEY, String(rightRailWidth));
  }, [rightRailWidth]);

  useEffect(() => {
    if (isRuntimeScenesRoot) {
      setDragState(null);
      return;
    }

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
  }, [isRuntimeScenesRoot, syncSidebarWidthToLayout]);

  useEffect(() => {
    syncRightRailWidthToLayout();
    const layoutElement = workspaceRef.current;
    if (!layoutElement) {
      return;
    }

    const observer = new ResizeObserver(() => {
      syncRightRailWidthToLayout();
    });
    observer.observe(layoutElement);
    return () => observer.disconnect();
  }, [syncRightRailWidthToLayout]);

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

    return () => {
      document.body.style.cursor = previousCursor;
      document.body.style.userSelect = previousUserSelect;
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", stopDragging);
      window.removeEventListener("pointercancel", stopDragging);
    };
  }, [dragState]);

  useEffect(() => {
    if (!rightRailDragState) {
      return;
    }

    const activeDrag = rightRailDragState;
    const previousCursor = document.body.style.cursor;
    const previousUserSelect = document.body.style.userSelect;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";

    function stopDragging() {
      setRightRailDragState(null);
    }

    function handlePointerMove(event: globalThis.PointerEvent) {
      const layoutWidth = workspaceRef.current?.getBoundingClientRect().width ?? 0;
      if (!layoutWidth) {
        return;
      }
      const delta = activeDrag.startX - event.clientX;
      setRightRailWidth(normalizeRightRailWidth(layoutWidth, activeDrag.startWidth + delta));
    }

    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", stopDragging);
    window.addEventListener("pointercancel", stopDragging);

    return () => {
      document.body.style.cursor = previousCursor;
      document.body.style.userSelect = previousUserSelect;
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", stopDragging);
      window.removeEventListener("pointercancel", stopDragging);
    };
  }, [rightRailDragState]);

  const filteredTree = useMemo(
    () => filterTree(treeQuery.data?.nodes ?? [], fileFilter),
    [fileFilter, treeQuery.data?.nodes],
  );
  const visibleFilePaths = useMemo(() => uniquePaths(collectFilePaths(filteredTree)), [filteredTree]);
  const layoutStyle = useMemo(
    () =>
      ({
        "--logs-sidebar-width": `${sidebarWidth}px`,
        "--logs-right-rail-width": `${rightRailWidth}px`,
      }) as CSSProperties,
    [rightRailWidth, sidebarWidth],
  );

  async function handleCopy() {
    if (!contentQuery.data?.content) {
      return;
    }
    try {
      await copyText(contentQuery.data.content);
      setCopyState("copied");
    } catch {
      setCopyState("error");
    }
  }

  function handleOpenFile(path: string) {
    if (!activeRoot) {
      return;
    }
    setOpenPaths((current) => ({
      ...current,
      [activeRoot.id]: path,
    }));
  }

  function handleToggleSelection(path: string) {
    if (!activeRoot) {
      return;
    }
    setSelectedLogPathsByRoot((current) => {
      const existing = current[activeRoot.id] ?? [];
      const next = existing.includes(path)
        ? existing.filter((item) => item !== path)
        : [...existing, path];
      return {
        ...current,
        [activeRoot.id]: uniquePaths(next),
      };
    });
  }

  function handleSelectVisible() {
    if (!activeRoot || visibleFilePaths.length === 0) {
      return;
    }
    setSelectedLogPathsByRoot((current) => ({
      ...current,
      [activeRoot.id]: visibleFilePaths,
    }));
  }

  function handleClearSelection() {
    if (!activeRoot) {
      return;
    }
    setSelectedLogPathsByRoot((current) => ({
      ...current,
      [activeRoot.id]: [],
    }));
  }

  function buildClearConfirmationLabel(path: string) {
    const fileName = path.split("/").at(-1) ?? path;
    return `确认清空当前日志文件“${fileName}”吗？文件会保留，但内容会被清空。`;
  }

  function buildDeleteConfirmationLabel(paths: string[]) {
    const names = paths.slice(0, 4).map((path) => path.split("/").at(-1) ?? path);
    const tail = paths.length > names.length ? `\n等 ${paths.length} 个文件。` : "";
    return `确认删除这 ${paths.length} 个日志文件吗？\n${names.map((name) => `- ${name}`).join("\n")}${tail}`;
  }

  function handleClearCurrent() {
    if (!activeRoot || !activeFilePath || clearLogMutation.isPending) {
      return;
    }
    if (!window.confirm(buildClearConfirmationLabel(activeFilePath))) {
      return;
    }
    clearLogMutation.mutate({
      root: activeRoot.id,
      path: activeFilePath,
    });
  }

  function handleDeleteSelected() {
    if (!activeRoot || selectedLogPaths.length === 0 || deleteLogsMutation.isPending) {
      return;
    }
    if (!window.confirm(buildDeleteConfirmationLabel(selectedLogPaths))) {
      return;
    }
    deleteLogsMutation.mutate({
      root: activeRoot.id,
      paths: selectedLogPaths,
    });
  }

  function beginResize(clientX: number) {
    setDragState({
      startX: clientX,
      startWidth: sidebarWidth,
    });
  }

  function beginRightRailResize(clientX: number) {
    setRightRailDragState({
      startX: clientX,
      startWidth: rightRailWidth,
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
        ? MIN_LOG_SIDEBAR_WIDTH
        : direction === "max"
          ? maxWidth
          : clamp(sidebarWidth + Number(direction) * KEYBOARD_RESIZE_STEP, MIN_LOG_SIDEBAR_WIDTH, maxWidth);
    setSidebarWidth(Math.round(nextWidth));
  }

  function handleRightRailResizeStart(event: PointerEvent<HTMLButtonElement>) {
    if (event.button !== 0) {
      return;
    }
    event.preventDefault();
    beginRightRailResize(event.clientX);
  }

  function handleRightRailResizeMouseDown(event: MouseEvent<HTMLButtonElement>) {
    if (event.button !== 0) {
      return;
    }
    event.preventDefault();
    beginRightRailResize(event.clientX);
  }

  function handleRightRailResizeKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (!workspaceRef.current) {
      return;
    }

    const { key } = event;
    const direction =
      key === "ArrowLeft" ? 1 : key === "ArrowRight" ? -1 : key === "Home" ? "min" : key === "End" ? "max" : null;
    if (direction === null) {
      return;
    }

    event.preventDefault();
    const layoutWidth = workspaceRef.current.getBoundingClientRect().width;
    const maxWidth = getMaxRightRailWidth(layoutWidth);
    const nextWidth =
      direction === "min"
        ? MIN_LOG_RIGHT_RAIL_WIDTH
        : direction === "max"
          ? maxWidth
          : clamp(
              rightRailWidth + Number(direction) * KEYBOARD_RESIZE_STEP,
              MIN_LOG_RIGHT_RAIL_WIDTH,
              maxWidth,
            );
    setRightRailWidth(Math.round(nextWidth));
  }

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
    lang === "zh"
      ? `${t("selectedFiles")} ${selectedLogPaths.length} 个`
      : `${selectedLogPaths.length} ${t("selectedFiles")}`;
  const destructiveBusy = deleteLogsMutation.isPending;
  const resizeRightRailLabel = lang === "zh" ? "调整右侧日志导航宽度" : "Resize right log navigation";
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
  const previewActions = (
    <div className={styles.previewActions}>
      {severityFilterControl}
      <button type="button" className={styles.copyButton} onClick={handleCopy}>
        {copyState === "copied" ? <Check size={15} /> : <Copy size={15} />}
        <span>{copyLabel}</span>
      </button>
      <button
        type="button"
        className={styles.clearButton}
        onClick={handleClearCurrent}
        disabled={!activeFilePath || clearLogMutation.isPending}
        title={!activeFilePath ? t("clearCurrentDisabled") : undefined}
      >
        <Eraser size={15} />
        <span>{clearLogMutation.isPending ? t("clearingCurrentLog") : t("clearCurrentLog")}</span>
      </button>
    </div>
  );

  return (
    <div className={styles.route}>
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>{t("navLogs")}</p>
          <h1 className={styles.title}>{t("logsTitle")}</h1>
          <p className={styles.subtitle}>{t("logsSubtitle")}</p>
        </div>
        <div className={styles.headerMeta}>
          <span className={styles.metaPill}>{t("readonlyPreview")}</span>
          <span className={styles.metaPill}>{t("copyEnabled")}</span>
          <span className={styles.metaPill}>{t("cleanupEnabled")}</span>
        </div>
      </header>

      <div ref={workspaceRef} className={styles.workspace} style={layoutStyle}>
        {activeRoot && isRuntimeScenesRoot ? (
          <RuntimeScenesPane activeRoot={activeRoot} lang={lang} t={t} statusLabel={statusLabel} />
        ) : (
          <div ref={layoutRef} className={styles.resizableLayout}>
            <aside className={styles.sidebar}>
              <div className={styles.sidebarHeader}>
                <div>
                  <p className={styles.sidebarEyebrow}>{activeRootLabelKey ? t(activeRootLabelKey) : t("navLogs")}</p>
                  <h2 className={styles.sidebarTitle}>{activeRoot?.path ?? t("loading")}</h2>
                </div>
                <div className={styles.selectionToolbar}>
                  <span className={styles.selectionPill}>{selectedCountLabel}</span>
                  <div className={styles.selectionActions}>
                    <button
                      type="button"
                      className={styles.toolbarButton}
                      onClick={handleSelectVisible}
                      disabled={visibleFilePaths.length === 0}
                    >
                      <CheckSquare size={15} />
                      <span>{t("selectVisibleLogs")}</span>
                    </button>
                    <button
                      type="button"
                      className={styles.toolbarButton}
                      onClick={handleClearSelection}
                      disabled={selectedLogPaths.length === 0}
                    >
                      <X size={15} />
                      <span>{t("clearSelection")}</span>
                    </button>
                    <button
                      type="button"
                      className={styles.deleteButton}
                      onClick={handleDeleteSelected}
                      disabled={selectedLogPaths.length === 0 || destructiveBusy}
                      title={selectedLogPaths.length === 0 ? t("deleteSelectedDisabled") : undefined}
                    >
                      <Trash2 size={15} />
                      <span>{destructiveBusy ? t("deletingSelectedLogs") : t("deleteSelectedLogs")}</span>
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
                <Search size={15} />
                <input
                  className={styles.panelSearchInput}
                  type="text"
                  value={fileFilter}
                  onChange={(event) => setFileFilter(event.target.value)}
                  placeholder={t("searchLogsPlaceholder")}
                />
              </div>

              <div className={styles.fileList}>
                {rootsQuery.isError ? (
                  <div className={styles.panelState}>{describeError(rootsQuery.error, t("loadFailed"))}</div>
                ) : rootsQuery.isPending && !rootsQuery.data ? (
                  <div className={styles.panelState}>{t("loadingLogs")}</div>
                ) : !activeRoot ? (
                  <div className={styles.panelState}>{t("loadingLogs")}</div>
                ) : !activeRoot.exists ? (
                  <div className={styles.panelState}>{t("logsRootMissing")}</div>
                ) : treeQuery.isError ? (
                  <div className={styles.panelState}>{describeError(treeQuery.error, t("loadFailed"))}</div>
                ) : treeQuery.isPending && !treeQuery.data ? (
                  <div className={styles.panelState}>{t("loadingLogs")}</div>
                ) : filteredTree.length === 0 ? (
                  <div className={styles.panelState}>
                    {fileFilter.trim() ? t("noLogMatches") : t("noLogsInGroup")}
                  </div>
                ) : (
                  renderTree(
                    filteredTree,
                    activeFilePath || null,
                    selectedLogPathSet,
                    handleOpenFile,
                    handleToggleSelection,
                    {
                      selectFile: lang === "zh" ? "选择文件" : "Select file",
                      deselectFile: lang === "zh" ? "取消选择文件" : "Deselect file",
                    },
                  )
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
              {!activeRoot ? (
                <div className={styles.emptySurface}>{t("loadingLogs")}</div>
              ) : !activeRoot.exists ? (
                <div className={styles.emptySurface}>{t("logsRootMissing")}</div>
              ) : !activeFilePath ? (
                <div className={styles.emptySurface}>{t("selectLogFile")}</div>
              ) : contentQuery.isError ? (
                <div className={styles.emptySurface}>{describeError(contentQuery.error, t("loadFailed"))}</div>
              ) : contentQuery.isPending && !contentQuery.data ? (
                <div className={styles.emptySurface}>{t("loadingFilePreview")}</div>
              ) : contentQuery.data ? (
                <div className={styles.logPreviewStack}>
                  {renderDiagnosticsPanel(contentQuery.data.diagnostics, lang)}
                  <FilePreview
                    file={contentQuery.data}
                    changed={false}
                    sourceLabel={activeRoot.path}
                    headerActions={previewActions}
                    highlightAsLog
                    severityFilter={severityFilter}
                  />
                </div>
              ) : (
                <div className={styles.emptySurface}>{t("loadingFilePreview")}</div>
              )}
            </section>
          </div>
        )}

        <button
          type="button"
          role="separator"
          aria-orientation="vertical"
          aria-label={resizeRightRailLabel}
          title={resizeRightRailLabel}
          tabIndex={0}
          className={
            rightRailDragState
              ? `${styles.resizeHandle} ${styles.resizeHandleActive} ${styles.rightRailResizeHandle}`
              : `${styles.resizeHandle} ${styles.rightRailResizeHandle}`
          }
          onPointerDown={handleRightRailResizeStart}
          onMouseDown={handleRightRailResizeMouseDown}
          onKeyDown={handleRightRailResizeKeyDown}
        />

        <aside className={styles.rightRail}>
          <div className={styles.railHeader}>
            <p className={styles.sidebarEyebrow}>{t("logsRootNavigation")}</p>
            <h2 className={styles.railTitle}>{t("navLogs")}</h2>
            <p className={styles.railText}>{t("logsSubtitle")}</p>
          </div>

          <nav className={styles.rootNav} aria-label={t("logsRootNavigation")}>
            {(rootsQuery.data ?? []).map((root) => {
              const isActive = root.id === activeRoot?.id;
              const labelKey = ROOT_LABEL_KEYS[root.id as keyof typeof ROOT_LABEL_KEYS] as RootLabelKey | undefined;
              const rootLabel = labelKey ? t(labelKey) : root.path;
              const latestLabel = root.summary.latestPath
                ? `${lang === "zh" ? "最近" : "Latest"}: ${root.summary.latestPath}`
                : lang === "zh"
                  ? "暂无最近文件"
                  : "No latest file";
              const stateLabel = root.exists ? t("present") : t("missing");
              const timestampLabel = root.exists ? formatTimestamp(root.summary.lastModifiedAt, lang) : "";
              return (
                <button
                  key={root.id}
                  type="button"
                  className={isActive ? `${styles.rootButton} ${styles.rootButtonActive}` : styles.rootButton}
                  onClick={() => setActiveRootId(root.id)}
                  aria-pressed={isActive}
                >
                  <span className={styles.rootButtonHeader}>
                    <span className={styles.rootButtonLabel}>{rootLabel}</span>
                    <span className={root.exists ? styles.rootState : `${styles.rootState} ${styles.rootStateMissing}`}>
                      {stateLabel}
                    </span>
                  </span>
                  <span className={styles.rootButtonPath} title={root.path}>
                    {root.path}
                  </span>
                  <span className={styles.rootButtonGuide} title={root.summary.userGuide}>
                    {root.summary.userGuide}
                  </span>
                  <span className={styles.rootButtonFooter}>
                    <span className={styles.rootButtonStats}>
                      {root.summary.fileCount} {lang === "zh" ? "个文件" : "files"} · {formatBytes(root.summary.sizeBytes)}
                    </span>
                    {timestampLabel ? <span className={styles.rootButtonTime}>{timestampLabel}</span> : null}
                  </span>
                  <span className={styles.rootButtonLatest} title={latestLabel}>
                    {latestLabel}
                  </span>
                </button>
              );
            })}
          </nav>
        </aside>
      </div>
    </div>
  );
}
