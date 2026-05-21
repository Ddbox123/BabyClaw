import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckSquare,
  Eye,
  RefreshCw,
  ShieldCheck,
  Square,
  Trash2,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { fetchJson } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import {
  ResetExecuteResponse,
  ResetInventoryItem,
  ResetPathEntry,
  ResetPreviewResponse,
  ResetSummary,
} from "../api/types";
import { useAppI18n } from "../i18n/useAppI18n";
import styles from "./ResetRoute.module.css";

type Notice = {
  tone: "success" | "error";
  message: string;
};

const COPY = {
  zh: {
    title: "Reset 清理面",
    subtitle: "只从后端白名单中选择清理项。保护区不会出现在勾选列表里，运行中的现场和当前浏览器 profile 会自动跳过。",
    inventory: "清理项",
    selected: "已选",
    selectAll: "全选可清理",
    clearSelection: "清空选择",
    preview: "预览清理",
    previewing: "预览中",
    execute: "确认执行",
    executing: "执行中",
    refresh: "刷新盘点",
    noSelection: "先选择至少一个清理项。",
    previewFirst: "先预览本次清理，再确认执行。",
    noPreview: "还没有预览结果。",
    noResult: "还没有执行结果。",
    previewPanel: "预览结果",
    resultPanel: "执行结果",
    protectedPanel: "固定保护区",
    deleteTargets: "将处理",
    deletedTargets: "已处理",
    skippedTargets: "跳过",
    protectedTargets: "受保护",
    failedTargets: "失败",
    files: "文件",
    targets: "目标",
    risk_low: "低风险",
    risk_medium: "中风险",
    risk_high: "高风险",
    missing: "无内容",
    present: "可清理",
    rebuildHint: "重建提示",
    previewFailed: "预览失败",
    executeFailed: "执行失败",
    selectionChanged: "选择已变化，重新预览后才能执行。",
    truncated: "仅显示前 120 条路径。",
  },
  en: {
    title: "Reset Cleanup",
    subtitle: "Choose only from backend allow-list items. Protected zones never appear as checkboxes, and live scenes/current browser profile are skipped automatically.",
    inventory: "Cleanup items",
    selected: "selected",
    selectAll: "Select cleanable",
    clearSelection: "Clear",
    preview: "Preview cleanup",
    previewing: "Previewing",
    execute: "Confirm execute",
    executing: "Executing",
    refresh: "Refresh inventory",
    noSelection: "Select at least one cleanup item first.",
    previewFirst: "Preview this cleanup before confirming execution.",
    noPreview: "No preview yet.",
    noResult: "No execution result yet.",
    previewPanel: "Preview result",
    resultPanel: "Execution result",
    protectedPanel: "Fixed protected zones",
    deleteTargets: "To handle",
    deletedTargets: "Handled",
    skippedTargets: "Skipped",
    protectedTargets: "Protected",
    failedTargets: "Failed",
    files: "files",
    targets: "targets",
    risk_low: "low risk",
    risk_medium: "medium risk",
    risk_high: "high risk",
    missing: "empty",
    present: "cleanable",
    rebuildHint: "Rebuild hint",
    previewFailed: "Preview failed",
    executeFailed: "Execute failed",
    selectionChanged: "Selection changed. Preview again before execution.",
    truncated: "Showing the first 120 paths only.",
  },
} as const;

function describeError(error: unknown, fallback: string) {
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return fallback;
}

function formatCount(value: number, label: string) {
  return `${value.toLocaleString()} ${label}`;
}

function riskClass(risk: string) {
  if (risk === "low") {
    return styles.riskLow;
  }
  if (risk === "high") {
    return styles.riskHigh;
  }
  return styles.riskMedium;
}

function previewSignature(itemIds: string[]) {
  return [...itemIds].sort().join("|");
}

export function ResetRoute() {
  const { lang } = useAppI18n();
  const copy = COPY[lang];
  const queryClient = useQueryClient();
  const resetQuery = useQuery({
    queryKey: queryKeys.resetSummary(),
    queryFn: () => fetchJson<ResetSummary>("/api/reset/summary"),
  });
  const summary = resetQuery.data;
  const items = summary?.items ?? summary?.categories ?? [];
  const selectableIds = useMemo(() => items.filter((item) => item.exists || item.id === "chat_history").map((item) => item.id), [items]);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [preview, setPreview] = useState<ResetPreviewResponse | null>(null);
  const [result, setResult] = useState<ResetExecuteResponse | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [previewedSignature, setPreviewedSignature] = useState("");
  const currentSignature = previewSignature(selectedIds);

  useEffect(() => {
    if (!summary || selectedIds.length > 0) {
      return;
    }
    const defaults = items.filter((item) => item.defaultSelected && (item.exists || item.id === "chat_history")).map((item) => item.id);
    if (defaults.length > 0) {
      setSelectedIds(defaults);
    }
  }, [items, selectedIds.length, summary]);

  const previewMutation = useMutation({
    mutationFn: (itemIds: string[]) =>
      fetchJson<ResetPreviewResponse>("/api/reset/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ itemIds }),
      }),
    onSuccess: (payload, itemIds) => {
      setPreview(payload);
      setResult(null);
      setNotice(null);
      setPreviewedSignature(previewSignature(itemIds));
    },
    onError: (error) => {
      setNotice({ tone: "error", message: describeError(error, copy.previewFailed) });
    },
  });

  const executeMutation = useMutation({
    mutationFn: (itemIds: string[]) =>
      fetchJson<ResetExecuteResponse>("/api/reset/execute", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ itemIds, confirmed: true }),
      }),
    onSuccess: (payload) => {
      setResult(payload);
      setPreview(null);
      setNotice({ tone: "success", message: payload.summary });
      setPreviewedSignature("");
      queryClient.invalidateQueries({ queryKey: queryKeys.resetSummary() });
    },
    onError: (error) => {
      setNotice({ tone: "error", message: describeError(error, copy.executeFailed) });
    },
  });

  const selectedItems = items.filter((item) => selectedIds.includes(item.id));
  const selectedSize = selectedItems.reduce((total, item) => total + Number(item.sizeBytes || 0), 0);
  const selectedTargets = selectedItems.reduce((total, item) => total + Number(item.candidateCount || 0), 0);
  const canPreview = selectedIds.length > 0 && !previewMutation.isPending && !executeMutation.isPending;
  const canExecute =
    selectedIds.length > 0 &&
    preview !== null &&
    currentSignature === previewedSignature &&
    !previewMutation.isPending &&
    !executeMutation.isPending;

  function toggleItem(item: ResetInventoryItem) {
    if (!item.exists && item.id !== "chat_history") {
      return;
    }
    setSelectedIds((current) =>
      current.includes(item.id) ? current.filter((id) => id !== item.id) : [...current, item.id],
    );
    setNotice(null);
  }

  function previewSelection() {
    if (!canPreview) {
      setNotice({ tone: "error", message: copy.noSelection });
      return;
    }
    previewMutation.mutate(selectedIds);
  }

  function executeSelection() {
    if (!canExecute) {
      setNotice({ tone: "error", message: preview ? copy.selectionChanged : copy.previewFirst });
      return;
    }
    executeMutation.mutate(selectedIds);
  }

  return (
    <div className={styles.route}>
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>Reset</p>
          <h1 className={styles.title}>{copy.title}</h1>
          <p className={styles.subtitle}>{summary?.warning ?? copy.subtitle}</p>
        </div>
        <div className={styles.headerActions}>
          <span className={styles.selectionPill}>
            {selectedIds.length} {copy.selected} · {formatSize(selectedSize)} · {formatCount(selectedTargets, copy.targets)}
          </span>
          <button
            type="button"
            className={styles.iconButton}
            onClick={() => resetQuery.refetch()}
            disabled={resetQuery.isFetching}
            title={copy.refresh}
          >
            <RefreshCw size={16} />
          </button>
        </div>
      </header>

      {notice ? <div className={notice.tone === "error" ? styles.errorNotice : styles.successNotice}>{notice.message}</div> : null}

      <main className={styles.workspace}>
        <section className={styles.inventoryPanel}>
          <div className={styles.panelHeader}>
            <div>
              <p className={styles.eyebrow}>{copy.inventory}</p>
              <h2>Allow-list</h2>
            </div>
            <div className={styles.toolbar}>
              <button type="button" className={styles.secondaryButton} onClick={() => setSelectedIds(selectableIds)}>
                <CheckSquare size={15} />
                {copy.selectAll}
              </button>
              <button type="button" className={styles.secondaryButton} onClick={() => setSelectedIds([])}>
                <Square size={15} />
                {copy.clearSelection}
              </button>
            </div>
          </div>

          <div className={styles.itemList}>
            {items.map((item) => {
              const selected = selectedIds.includes(item.id);
              const disabled = !item.exists && item.id !== "chat_history";
              return (
                <button
                  type="button"
                  key={item.id}
                  className={`${styles.itemRow} ${selected ? styles.itemRowSelected : ""}`}
                  onClick={() => toggleItem(item)}
                  disabled={disabled}
                >
                  <span className={styles.checkIcon}>{selected ? <CheckSquare size={18} /> : <Square size={18} />}</span>
                  <span className={styles.itemMain}>
                    <span className={styles.itemTopLine}>
                      <strong>{item.name}</strong>
                      <span className={`${styles.riskBadge} ${riskClass(item.risk)}`}>
                        {copy[`risk_${item.risk as "low" | "medium" | "high"}`] ?? item.risk}
                      </span>
                    </span>
                    <span className={styles.itemDescription}>{item.description}</span>
                    <span className={styles.itemDetail}>{item.detail}</span>
                    {item.rebuildHint ? <span className={styles.rebuildHint}>{item.rebuildHint}</span> : null}
                  </span>
                  <span className={styles.itemStats}>
                    <span>{item.exists ? copy.present : copy.missing}</span>
                    <span>{item.size}</span>
                    <span>{formatCount(item.fileCount, copy.files)}</span>
                    {item.protectedCount > 0 ? <span>{item.protectedCount} {copy.protectedTargets}</span> : null}
                  </span>
                </button>
              );
            })}
          </div>

          <div className={styles.actionBar}>
            <button type="button" className={styles.previewButton} onClick={previewSelection} disabled={!canPreview}>
              <Eye size={16} />
              {previewMutation.isPending ? copy.previewing : copy.preview}
            </button>
            <button type="button" className={styles.executeButton} onClick={executeSelection} disabled={!canExecute}>
              <Trash2 size={16} />
              {executeMutation.isPending ? copy.executing : copy.execute}
            </button>
          </div>
        </section>

        <aside className={styles.sidePanel}>
          <section className={styles.card}>
            <div className={styles.cardTitleRow}>
              <Eye size={16} />
              <h2>{copy.previewPanel}</h2>
            </div>
            {preview ? (
              <ResultContent
                mode="preview"
                summary={preview.summary}
                warnings={preview.rebuildHints}
                items={preview.items.map((item) => ({
                  id: item.id,
                  name: item.name,
                  truncated: item.truncated,
                  groups: [
                    { label: copy.deleteTargets, entries: item.deleteCandidates },
                    { label: copy.protectedTargets, entries: item.protected },
                    { label: copy.skippedTargets, entries: item.skipped },
                  ],
                }))}
                truncatedLabel={copy.truncated}
                emptyLabel={copy.noPreview}
              />
            ) : (
              <p className={styles.emptyState}>{copy.noPreview}</p>
            )}
          </section>

          <section className={styles.card}>
            <div className={styles.cardTitleRow}>
              <Trash2 size={16} />
              <h2>{copy.resultPanel}</h2>
            </div>
            {result ? (
              <ResultContent
                mode="result"
                summary={result.summary}
                warnings={result.rebuildHints}
                items={result.items.map((item) => ({
                  id: item.id,
                  name: item.name,
                  truncated: item.truncated,
                  groups: [
                    { label: copy.deletedTargets, entries: item.deleted },
                    { label: copy.protectedTargets, entries: item.protected },
                    { label: copy.skippedTargets, entries: item.skipped },
                    { label: copy.failedTargets, entries: item.failed },
                  ],
                }))}
                truncatedLabel={copy.truncated}
                emptyLabel={copy.noResult}
              />
            ) : (
              <p className={styles.emptyState}>{copy.noResult}</p>
            )}
          </section>

          <section className={styles.card}>
            <div className={styles.cardTitleRow}>
              <ShieldCheck size={16} />
              <h2>{copy.protectedPanel}</h2>
            </div>
            <div className={styles.protectedList}>
              {(summary?.protected ?? []).map((group) => (
                <div key={group.id} className={styles.protectedItem}>
                  <strong>{group.label}</strong>
                  <span>{group.reason}</span>
                  <code>{group.paths.join(", ")}</code>
                </div>
              ))}
            </div>
          </section>
        </aside>
      </main>
    </div>
  );
}

function ResultContent({
  summary,
  warnings,
  items,
  truncatedLabel,
  emptyLabel,
}: {
  mode: "preview" | "result";
  summary: string;
  warnings: string[];
  items: Array<{
    id: string;
    name: string;
    truncated: boolean;
    groups: Array<{ label: string; entries: ResetPathEntry[] }>;
  }>;
  truncatedLabel: string;
  emptyLabel: string;
}) {
  if (items.length === 0) {
    return <p className={styles.emptyState}>{emptyLabel}</p>;
  }
  return (
    <div className={styles.resultContent}>
      <p className={styles.resultSummary}>{summary}</p>
      {warnings.map((warning) => (
        <div key={warning} className={styles.warningLine}>
          <AlertTriangle size={15} />
          <span>{warning}</span>
        </div>
      ))}
      {items.map((item) => (
        <details key={item.id} className={styles.resultItem} open>
          <summary>
            <span>{item.name}</span>
            {item.truncated ? <em>{truncatedLabel}</em> : null}
          </summary>
          <div className={styles.resultGroups}>
            {item.groups.map((group) => (
              <PathGroup key={group.label} label={group.label} entries={group.entries} />
            ))}
          </div>
        </details>
      ))}
    </div>
  );
}

function PathGroup({ label, entries }: { label: string; entries: ResetPathEntry[] }) {
  if (entries.length === 0) {
    return null;
  }
  return (
    <div className={styles.pathGroup}>
      <p>{label} · {entries.length}</p>
      <div className={styles.pathList}>
        {entries.map((entry) => (
          <div key={`${label}-${entry.path}-${entry.status ?? ""}`} className={styles.pathRow}>
            <code>{entry.path}</code>
            {entry.message ? <span>{entry.message}</span> : null}
          </div>
        ))}
      </div>
    </div>
  );
}

function formatSize(sizeBytes: number) {
  let value = Math.max(0, Number(sizeBytes || 0));
  const units = ["B", "KB", "MB", "GB"];
  for (const unit of units) {
    if (value < 1024 || unit === units[units.length - 1]) {
      return unit === "B" ? `${Math.round(value)} B` : `${value.toFixed(1)} ${unit}`;
    }
    value /= 1024;
  }
  return `${Math.round(sizeBytes)} B`;
}
