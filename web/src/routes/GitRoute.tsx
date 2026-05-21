import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Clock3, FileText, GitBranch, GitCommitHorizontal, RefreshCw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { fetchJson } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import { GitCommitsResponse, GitFileDiff, GitStatusFile, GitStatusSummary } from "../api/types";
import { FilePreview } from "../components/preview/FilePreview";
import { useAppI18n } from "../i18n/useAppI18n";
import styles from "./GitRoute.module.css";

type GitFilter = "all" | "staged" | "unstaged" | "untracked" | "deleted";

const FILTERS: GitFilter[] = ["all", "staged", "unstaged", "untracked", "deleted"];
const FILTER_LABEL_KEYS = {
  all: "gitFilterAll",
  staged: "gitFilterStaged",
  unstaged: "gitFilterUnstaged",
  untracked: "gitFilterUntracked",
  deleted: "gitFilterDeleted",
} as const;

function filterMatches(file: GitStatusFile, filter: GitFilter) {
  if (filter === "all") {
    return true;
  }
  return Boolean(file[filter]);
}

function displayPath(path: string) {
  return path.replaceAll("\\", "/");
}

function fileName(path: string) {
  return displayPath(path).split("/").at(-1) || path;
}

function formatDateTime(value: string, locale: string) {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat(locale, {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

export function GitRoute() {
  const { lang, t } = useAppI18n();
  const queryClient = useQueryClient();
  const [activeFilter, setActiveFilter] = useState<GitFilter>("all");
  const [activePath, setActivePath] = useState<string | null>(null);
  const locale = lang === "zh" ? "zh-CN" : "en-US";

  const statusQuery = useQuery({
    queryKey: queryKeys.gitStatus(),
    queryFn: () => fetchJson<GitStatusSummary>("/api/git/status?limit=500"),
    refetchInterval: 6_000,
    refetchIntervalInBackground: true,
  });
  const commitsQuery = useQuery({
    queryKey: queryKeys.gitCommits(),
    queryFn: () => fetchJson<GitCommitsResponse>("/api/git/commits?limit=20"),
    refetchInterval: 30_000,
    refetchIntervalInBackground: true,
  });

  const files = statusQuery.data?.files ?? [];
  const filteredFiles = useMemo(
    () => files.filter((file) => filterMatches(file, activeFilter)),
    [activeFilter, files],
  );
  const activeFile = files.find((file) => file.path === activePath) ?? null;

  useEffect(() => {
    if (!filteredFiles.length) {
      setActivePath(null);
      return;
    }
    if (!activePath || !filteredFiles.some((file) => file.path === activePath)) {
      setActivePath(filteredFiles[0].path);
    }
  }, [activePath, filteredFiles]);

  const diffQuery = useQuery({
    queryKey: queryKeys.gitDiff(activePath ?? ""),
    queryFn: () => fetchJson<GitFileDiff>(`/api/git/diff?path=${encodeURIComponent(activePath ?? "")}`),
    enabled: Boolean(activePath && statusQuery.data?.available),
  });

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.gitStatus() });
    void queryClient.invalidateQueries({ queryKey: queryKeys.gitCommits() });
    if (activePath) {
      void queryClient.invalidateQueries({ queryKey: queryKeys.gitDiff(activePath) });
    }
  };

  const status = statusQuery.data;
  const upstream = status?.upstream;
  const aheadBehind = upstream?.hasUpstream ? `${upstream.ahead} / ${upstream.behind}` : t("gitNoUpstream");
  const previewContent =
    diffQuery.data?.diff ||
    diffQuery.data?.content ||
    (diffQuery.data?.binary ? t("gitBinaryFile") : t("gitDiffEmpty"));

  return (
    <section className={styles.route}>
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>{t("navGit")}</p>
          <h1 className={styles.title}>{t("gitPageTitle")}</h1>
          <p className={styles.subtitle}>{t("gitPageSubtitle")}</p>
        </div>
        <button type="button" className={styles.refreshButton} onClick={refresh}>
          <RefreshCw size={16} />
          {t("gitRefresh")}
        </button>
      </header>

      <div className={styles.summaryGrid}>
        <section className={styles.summaryCard}>
          <span>{t("gitBranch")}</span>
          <strong>{status?.branch || status?.headRevShort || "-"}</strong>
        </section>
        <section className={styles.summaryCard}>
          <span>{t("gitChangedFiles")}</span>
          <strong>{status?.counts.total ?? 0}</strong>
        </section>
        <section className={styles.summaryCard}>
          <span>{t("gitUpstream")}</span>
          <strong>{upstream?.name || upstream?.remote || t("gitNoUpstream")}</strong>
        </section>
        <section className={styles.summaryCard}>
          <span>{t("gitAheadBehind")}</span>
          <strong>{aheadBehind}</strong>
        </section>
      </div>

      {!statusQuery.isPending && status && !status.available ? (
        <p className={styles.notice}>{status.error || t("gitStatusUnavailable")}</p>
      ) : null}

      <div className={styles.workspace}>
        <aside className={styles.changePanel}>
          <div className={styles.panelHeader}>
            <div>
              <p className={styles.panelEyebrow}>{t("gitChangedScope")}</p>
              <h2>{t("gitAllChanges")}</h2>
            </div>
            <span className={styles.countPill}>{filteredFiles.length}</span>
          </div>
          <div className={styles.filterRow}>
            {FILTERS.map((filter) => (
              <button
                key={filter}
                type="button"
                className={filter === activeFilter ? styles.filterButtonActive : styles.filterButton}
                onClick={() => setActiveFilter(filter)}
              >
                {t(FILTER_LABEL_KEYS[filter])}
              </button>
            ))}
          </div>
          <div className={styles.fileList}>
            {filteredFiles.map((file) => (
              <button
                key={`${file.status}-${file.path}`}
                type="button"
                className={file.path === activePath ? styles.fileButtonActive : styles.fileButton}
                onClick={() => setActivePath(file.path)}
              >
                <span className={styles.fileStatus}>{file.status}</span>
                <span className={styles.fileCopy}>
                  <strong>{fileName(file.path)}</strong>
                  <span>{displayPath(file.path)}</span>
                </span>
              </button>
            ))}
            {!filteredFiles.length ? <p className={styles.emptyState}>{t("gitNoMatchingChanges")}</p> : null}
          </div>
        </aside>

        <main className={styles.diffPanel}>
          {activePath ? (
            <FilePreview
              file={{
                path: activePath,
                language: diffQuery.data?.language || "diff",
                content: diffQuery.isPending ? t("loading") : previewContent,
                truncated: Boolean(diffQuery.data?.truncated),
              }}
              changed={Boolean(activeFile)}
              sourceLabel={activeFile?.statusLabel || t("gitFileDiff")}
              headerActions={
                <span className={styles.inlineMeta}>
                  <FileText size={14} />
                  {activeFile?.status || "-"}
                </span>
              }
            />
          ) : (
            <div className={styles.emptyPreview}>
              <GitBranch size={24} />
              <strong>{t("gitFileDiff")}</strong>
              <p>{statusQuery.isPending ? t("loading") : t("gitSelectFile")}</p>
            </div>
          )}
        </main>

        <aside className={styles.commitPanel}>
          <div className={styles.panelHeader}>
            <div>
              <p className={styles.panelEyebrow}>{t("gitHead")}</p>
              <h2>{t("gitRecentCommits")}</h2>
            </div>
            <GitCommitHorizontal size={18} />
          </div>
          <div className={styles.commitList}>
            {(commitsQuery.data?.commits ?? []).map((commit) => (
              <article key={commit.sha} className={styles.commitItem}>
                <div className={styles.commitHeader}>
                  <code>{commit.shortSha}</code>
                  <span>
                    <Clock3 size={13} />
                    {formatDateTime(commit.authoredAt, locale)}
                  </span>
                </div>
                <strong>{commit.subject}</strong>
                <p>{t("gitCommitBy")}: {commit.author}</p>
              </article>
            ))}
            {!commitsQuery.isPending && !(commitsQuery.data?.commits ?? []).length ? (
              <p className={styles.emptyState}>{commitsQuery.data?.error || t("gitNoCommits")}</p>
            ) : null}
          </div>
        </aside>
      </div>
    </section>
  );
}
