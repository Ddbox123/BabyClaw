import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUpRight, CheckCircle2, LibraryBig, LoaderCircle, Search, Trash2, TriangleAlert } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { NavLink } from "react-router-dom";

import { fetchJson } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import { EvolutionChatReviewCandidate, EvolutionChatReviewDecisionResponse, EvolutionChatReviewQueue, EvolutionWorkbench } from "../api/types";
import { useAppI18n } from "../i18n/useAppI18n";
import { SupervisedWorkspaceTabs } from "./SupervisedWorkspaceTabs";
import styles from "./SupervisedReviewRoute.module.css";

type ReviewDecision = "positive" | "negative" | "discard";
type ReviewFilter = "all" | "pending" | "positive" | "negative" | "discard";

const REVIEW_FILTERS: ReviewFilter[] = ["all", "pending", "positive", "negative", "discard"];
const EMPTY_REVIEW_ITEMS: EvolutionChatReviewCandidate[] = [];

export function SupervisedReviewRoute() {
  const { lang, t, statusLabel } = useAppI18n();
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState<ReviewFilter>("pending");
  const [searchInput, setSearchInput] = useState("");
  const [selectedCandidateId, setSelectedCandidateId] = useState<string | null>(null);
  const [draftDecision, setDraftDecision] = useState<ReviewDecision>("positive");
  const [reviewerNote, setReviewerNote] = useState("");
  const [reasonCode, setReasonCode] = useState("");
  const [errorType, setErrorType] = useState("");
  const [correctPrinciple, setCorrectPrinciple] = useState("");
  const [idealBehavior, setIdealBehavior] = useState("");
  const [actionFeedback, setActionFeedback] = useState("");

  const reviewQuery = useQuery({
    queryKey: queryKeys.evolutionChatReview(),
    queryFn: () => fetchJson<EvolutionChatReviewQueue>("/api/evolution/chat-review"),
    refetchInterval: 8_000,
    refetchIntervalInBackground: true,
  });
  const workbenchQuery = useQuery({
    queryKey: queryKeys.evolutionWorkbench(),
    queryFn: () => fetchJson<EvolutionWorkbench>("/api/evolution/workbench"),
    refetchInterval: 8_000,
    refetchIntervalInBackground: true,
  });

  const decisionMutation = useMutation({
    mutationFn: () => {
      if (!selectedCandidate) {
        throw new Error(lang === "zh" ? "当前没有选中的样本。" : "There is no selected sample.");
      }
      return fetchJson<EvolutionChatReviewDecisionResponse>(
        `/api/evolution/chat-review/${selectedCandidate.candidateId}/decision`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            decision: draftDecision,
            reviewerNote,
            reasonCode,
            errorType,
            correctPrinciple,
            idealBehavior,
          }),
        },
      );
    },
    onMutate: () => {
      setActionFeedback("");
    },
    onSuccess: async (payload) => {
      setActionFeedback(payload.summary);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionChatReview() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionWorkbench() }),
      ]);
    },
  });

  const reviewData = reviewQuery.data;
  const items = reviewData?.items ?? EMPTY_REVIEW_ITEMS;
  const positiveDatasetVisible = workbenchQuery.data?.datasets.some(
    (item) => item.name === reviewData?.positiveDatasetName && item.available,
  ) ?? false;
  const consoleTarget = reviewData?.positiveDatasetName
    ? `/supervised-evolution?dataset=${encodeURIComponent(reviewData.positiveDatasetName)}`
    : "/supervised-evolution";
  const normalizedSearch = searchInput.trim().toLowerCase();
  const visibleItems = useMemo(() => {
    return items.filter((item) => {
      if (filter !== "all" && item.status !== filter) {
        return false;
      }
      if (!normalizedSearch) {
        return true;
      }
      const haystack = [
        item.topicSummary,
        item.structuredSample.promptSeed,
        item.sessionId,
        item.sourceLogPath,
        item.reviewProfile.suggestedReason,
      ]
        .join(" ")
        .toLowerCase();
      return haystack.includes(normalizedSearch);
    });
  }, [filter, items, normalizedSearch]);
  const selectedCandidate =
    visibleItems.find((item) => item.candidateId === selectedCandidateId)
    ?? visibleItems[0]
    ?? null;
  const evidenceTurns = useMemo(() => {
    if (!selectedCandidate) {
      return [];
    }
    const highlightSet = new Set(selectedCandidate.reviewProfile.evidenceTurnNumbers);
    const matching = selectedCandidate.conversationTurns.filter((turn) => highlightSet.has(turn.turnNumber));
    return matching.length > 0 ? matching : selectedCandidate.conversationTurns.slice(0, 3);
  }, [selectedCandidate]);

  useEffect(() => {
    if (!visibleItems.some((item) => item.candidateId === selectedCandidateId)) {
      setSelectedCandidateId(visibleItems[0]?.candidateId ?? null);
    }
  }, [selectedCandidateId, visibleItems]);

  useEffect(() => {
    if (!selectedCandidate) {
      setDraftDecision("positive");
      setReviewerNote("");
      setReasonCode("");
      setErrorType("");
      setCorrectPrinciple("");
      setIdealBehavior("");
      return;
    }
    setDraftDecision((selectedCandidate.reviewProfile.suggestedDecision as ReviewDecision) || "positive");
    setReviewerNote(selectedCandidate.reviewerNote || "");
    setReasonCode(selectedCandidate.reviewDecision.reasonCode || "");
    setErrorType(selectedCandidate.reviewDecision.errorType || "");
    setCorrectPrinciple(selectedCandidate.reviewDecision.correctPrinciple || "");
    setIdealBehavior(selectedCandidate.reviewDecision.idealBehavior || "");
  }, [selectedCandidate?.candidateId]);

  const decisionError = decisionMutation.error?.message ?? "";
  const pendingOnlyCount = reviewData?.pendingCount ?? 0;
  const lifecycle = reviewData?.lifecycle;

  function levelLabel(level: string) {
    if (level === "high") {
      return lang === "zh" ? "高" : "High";
    }
    if (level === "medium") {
      return lang === "zh" ? "中" : "Medium";
    }
    return lang === "zh" ? "低" : "Low";
  }

  function filterLabel(value: ReviewFilter) {
    if (value === "all") {
      return lang === "zh" ? "全部" : "All";
    }
    if (value === "pending") {
      return lang === "zh" ? "待审" : "Pending";
    }
    if (value === "positive") {
      return lang === "zh" ? "正例" : "Positive";
    }
    if (value === "negative") {
      return lang === "zh" ? "负例" : "Negative";
    }
    return lang === "zh" ? "丢弃" : "Discard";
  }

  function decisionLabel(value: ReviewDecision) {
    if (value === "positive") {
      return lang === "zh" ? "纳入正例" : "Positive example";
    }
    if (value === "negative") {
      return lang === "zh" ? "纳入负例" : "Negative example";
    }
    return lang === "zh" ? "丢弃" : "Discard";
  }

  function statusTone(status: string) {
    if (status === "positive") {
      return styles.statusPositive;
    }
    if (status === "negative") {
      return styles.statusNegative;
    }
    if (status === "discard") {
      return styles.statusDiscard;
    }
    return styles.statusPending;
  }

  function submitCurrentDecision() {
    if (!selectedCandidate || selectedCandidate.status !== "pending") {
      return;
    }
    decisionMutation.mutate();
  }

  const reasonOptions = draftDecision === "positive"
    ? [
      { value: "grounded_workflow", label: lang === "zh" ? "过程扎实" : "Grounded workflow" },
      { value: "strong_closure", label: lang === "zh" ? "收束清楚" : "Strong closure" },
      { value: "reusable_pattern", label: lang === "zh" ? "可复用模式" : "Reusable pattern" },
    ]
    : draftDecision === "negative"
      ? [
        { value: "missing_evidence", label: lang === "zh" ? "缺少证据" : "Missing evidence" },
        { value: "weak_verification", label: lang === "zh" ? "验证不足" : "Weak verification" },
        { value: "repetitive_no_progress", label: lang === "zh" ? "重复但没推进" : "Repeated without progress" },
      ]
      : [
        { value: "thin_signal", label: lang === "zh" ? "信号太薄" : "Signal too thin" },
        { value: "duplicate_sample", label: lang === "zh" ? "样本重复" : "Duplicate sample" },
        { value: "too_noisy", label: lang === "zh" ? "噪声过多" : "Too noisy" },
      ];

  return (
    <div className={styles.page}>
      <section className={styles.toolbar}>
        <div className={styles.toolbarIntro}>
          <p className={styles.eyebrow}>{t("navSupervisedEvolution")}</p>
          <h1 className={styles.title}>{t("reviewWorkspace")}</h1>
          <p className={styles.subtitle}>{t("reviewWorkspaceSubtitle")}</p>
        </div>

        <div className={styles.toolbarControls}>
          <SupervisedWorkspaceTabs activeView="review" />
        </div>
      </section>

      <section className={styles.summaryStrip}>
        <article className={styles.summaryCard}>
          <span>{lang === "zh" ? "待审样本" : "Pending cases"}</span>
          <strong>{reviewData?.pendingCount ?? 0}</strong>
        </article>
        <article className={styles.summaryCard}>
          <span>{lang === "zh" ? "正例" : "Positive"}</span>
          <strong>{reviewData?.positiveCount ?? 0}</strong>
        </article>
        <article className={styles.summaryCard}>
          <span>{lang === "zh" ? "负例" : "Negative"}</span>
          <strong>{reviewData?.negativeCount ?? 0}</strong>
        </article>
        <article className={styles.summaryCard}>
          <span>{lang === "zh" ? "已丢弃" : "Discarded"}</span>
          <strong>{reviewData?.discardCount ?? 0}</strong>
        </article>
        <article className={styles.summaryCard}>
          <span>{lang === "zh" ? "正例数据集" : "Positive dataset"}</span>
          <strong>{reviewData?.positiveDatasetName ?? "--"}</strong>
        </article>
      </section>

      <section className={styles.lifecyclePanel}>
        <div>
          <p className={styles.eyebrow}>{lang === "zh" ? "生命周期边界" : "Lifecycle boundary"}</p>
          <h2 className={styles.sectionTitle}>
            {lifecycle?.candidateStage || "pending_review"}{" -> "}{lifecycle?.reviewedCaseStage || "reviewed_chat_case"}
          </h2>
        </div>
        <div className={styles.lifecyclePills}>
          <span className={styles.secondaryPill}>
            {lifecycle?.rawChatDirectTrainingAllowed
              ? (lang === "zh" ? "raw chat 可直训" : "raw chat training allowed")
              : (lang === "zh" ? "raw chat 不直训" : "no raw-chat training")}
          </span>
          <span className={styles.secondaryPill}>
            {lang === "zh" ? "正例" : "positive"}: {lifecycle?.datasetTarget || reviewData?.positiveDatasetName || "--"}
          </span>
          <span className={styles.secondaryPill}>
            {lang === "zh" ? "负例" : "negative"}: {lifecycle?.negativeTarget || reviewData?.negativeDatasetName || "--"}
          </span>
          {(lifecycle?.allowedDownstreamUses ?? []).map((use) => (
            <span key={use} className={styles.signalPill}>{use}</span>
          ))}
        </div>
      </section>

      <div className={styles.workspace}>
        <aside className={styles.queuePanel}>
          <div className={styles.panelHeader}>
            <div>
              <p className={styles.eyebrow}>{lang === "zh" ? "待审队列" : "Review queue"}</p>
              <h2 className={styles.sectionTitle}>{lang === "zh" ? "样本列表" : "Cases"}</h2>
            </div>
            <span className={styles.secondaryPill}>{visibleItems.length}</span>
          </div>

          <div className={styles.queueControls}>
            <div className={styles.filterSegmented}>
              {REVIEW_FILTERS.map((value) => (
                <button
                  key={value}
                  type="button"
                  className={filter === value ? `${styles.filterButton} ${styles.filterButtonActive}` : styles.filterButton}
                  onClick={() => setFilter(value)}
                >
                  {filterLabel(value)}
                </button>
              ))}
            </div>
            <label className={styles.searchField}>
              <Search size={14} />
              <input
                type="text"
                value={searchInput}
                onChange={(event) => setSearchInput(event.target.value)}
                placeholder={lang === "zh" ? "搜索标题、提示种子或日志" : "Search title, prompt seed, or log"}
              />
            </label>
          </div>

          <div className={styles.queueMeta}>
            <span>{lang === "zh" ? "默认先处理待审样本" : "Pending items stay at the front"}</span>
            <strong>{pendingOnlyCount}</strong>
          </div>

          {visibleItems.length === 0 ? (
            <div className={styles.emptyState}>
              <h3>{lang === "zh" ? "当前没有匹配样本" : "No matching samples"}</h3>
              <p>{lang === "zh" ? "换个筛选条件，或者等新的多轮片段进入审核队列。" : "Try another filter or wait for new multi-turn excerpts to enter the queue."}</p>
            </div>
          ) : (
            <div className={styles.queueList}>
              {visibleItems.map((item) => (
                <button
                  key={item.candidateId}
                  type="button"
                  className={
                    selectedCandidate?.candidateId === item.candidateId
                      ? `${styles.queueItem} ${styles.queueItemActive}`
                      : styles.queueItem
                  }
                  onClick={() => setSelectedCandidateId(item.candidateId)}
                >
                  <div className={styles.queueItemTop}>
                    <strong>{item.topicSummary || item.candidateId}</strong>
                    <span className={`${styles.statusBadge} ${statusTone(item.status)}`}>{statusLabel(item.status)}</span>
                  </div>
                  <p className={styles.queueHeadline}>{item.structuredSample.promptSeed || "--"}</p>
                  <div className={styles.signalRow}>
                    {item.qualitySignals.slice(0, 3).map((signal) => (
                      <span key={`${item.candidateId}-${signal}`} className={styles.signalPill}>{signal}</span>
                    ))}
                  </div>
                  <div className={styles.queueFooter}>
                    <span>{`T${item.startTurn}-${item.endTurn}`}</span>
                    <span>{decisionLabel((item.reviewProfile.suggestedDecision as ReviewDecision) || "positive")}</span>
                  </div>
                </button>
              ))}
            </div>
          )}
        </aside>

        <section className={styles.detailPanel}>
          {selectedCandidate ? (
            <>
              <div className={styles.detailHeader}>
                <div>
                  <p className={styles.eyebrow}>{lang === "zh" ? "当前裁决样本" : "Current review case"}</p>
                  <h2 className={styles.detailTitle}>{selectedCandidate.topicSummary || selectedCandidate.candidateId}</h2>
                  <p className={styles.detailLead}>{selectedCandidate.reviewProfile.suggestedReason}</p>
                </div>
                <div className={styles.detailHeaderActions}>
                  <span className={`${styles.statusBadge} ${statusTone(selectedCandidate.status)}`}>{statusLabel(selectedCandidate.status)}</span>
                  <span className={styles.secondaryPill}>{decisionLabel((selectedCandidate.reviewProfile.suggestedDecision as ReviewDecision) || "positive")}</span>
                </div>
              </div>

              <div className={styles.factGrid}>
                <article className={styles.factCard}>
                  <span>{lang === "zh" ? "学习重点" : "Learning focus"}</span>
                  <strong>{selectedCandidate.reviewProfile.learningFocus}</strong>
                </article>
                <article className={styles.factCard}>
                  <span>{lang === "zh" ? "轮次范围" : "Turn range"}</span>
                  <strong>{`T${selectedCandidate.startTurn}-${selectedCandidate.endTurn}`}</strong>
                </article>
                <article className={styles.factCard}>
                  <span>{lang === "zh" ? "来源会话" : "Source session"}</span>
                  <strong>{selectedCandidate.sessionId || "--"}</strong>
                </article>
                <article className={styles.factCard}>
                  <span>{lang === "zh" ? "训练层级" : "Training tier"}</span>
                  <strong>{selectedCandidate.structuredSample.trainingTier || "--"}</strong>
                </article>
              </div>

              <div className={styles.metricGrid}>
                {[
                  { label: lang === "zh" ? "任务清晰度" : "Task clarity", item: selectedCandidate.reviewProfile.taskClarity },
                  { label: lang === "zh" ? "目标稳定性" : "Goal stability", item: selectedCandidate.reviewProfile.goalStability },
                  { label: lang === "zh" ? "输出可学性" : "Learning value", item: selectedCandidate.reviewProfile.assistantLearningValue },
                  { label: lang === "zh" ? "反模式风险" : "Anti-pattern risk", item: selectedCandidate.reviewProfile.antiPatternRisk },
                ].map((metric) => (
                  <article key={metric.label} className={styles.metricCard}>
                    <span>{metric.label}</span>
                    <strong>{levelLabel(metric.item.level)}</strong>
                    <p>{metric.item.note}</p>
                  </article>
                ))}
              </div>

              <div className={styles.signalColumns}>
                <section className={styles.signalSection}>
                  <h3>{lang === "zh" ? "正向信号" : "Positive signals"}</h3>
                  <ul>
                    {selectedCandidate.reviewProfile.positiveSignals.map((signal) => (
                      <li key={signal}>{signal}</li>
                    ))}
                  </ul>
                </section>
                <section className={styles.signalSection}>
                  <h3>{lang === "zh" ? "反向信号" : "Negative signals"}</h3>
                  <ul>
                    {selectedCandidate.reviewProfile.negativeSignals.map((signal) => (
                      <li key={signal}>{signal}</li>
                    ))}
                  </ul>
                </section>
              </div>

              <section className={styles.detailSection}>
                <div className={styles.sectionHeader}>
                  <div>
                    <p className={styles.eyebrow}>{lang === "zh" ? "关键证据" : "Key evidence"}</p>
                    <h3>{lang === "zh" ? "先判断，再读完整对话" : "Judge first, then inspect the full transcript"}</h3>
                  </div>
                  <span className={styles.secondaryPill}>{evidenceTurns.length}</span>
                </div>
                <div className={styles.evidenceList}>
                  {evidenceTurns.map((turn) => (
                    <article key={`${selectedCandidate.candidateId}-${turn.turnNumber}`} className={styles.evidenceCard}>
                      <div className={styles.evidenceTop}>
                        <strong>{`Turn ${turn.turnNumber}`}</strong>
                        <span>{turn.toolCalls.join(", ") || "--"}</span>
                      </div>
                      <p>{lang === "zh" ? `用户：${turn.userMessage}` : `User: ${turn.userMessage}`}</p>
                      <p>{lang === "zh" ? `助手：${turn.assistantMessage}` : `Assistant: ${turn.assistantMessage}`}</p>
                    </article>
                  ))}
                </div>
              </section>

              <section className={styles.detailSection}>
                <div className={styles.sectionHeader}>
                  <div>
                    <p className={styles.eyebrow}>{lang === "zh" ? "裁决" : "Decision"}</p>
                    <h3>{lang === "zh" ? "把样本归进正例、负例或丢弃" : "Send the sample to positive, negative, or discard"}</h3>
                  </div>
                  {selectedCandidate.status !== "pending" ? (
                    <span className={styles.secondaryPill}>{lang === "zh" ? "已处理" : "Already reviewed"}</span>
                  ) : null}
                </div>

                <div className={styles.decisionSegmented}>
                  {(["positive", "negative", "discard"] as ReviewDecision[]).map((value) => (
                    <button
                      key={value}
                      type="button"
                      className={draftDecision === value ? `${styles.decisionButton} ${styles.decisionButtonActive}` : styles.decisionButton}
                      disabled={selectedCandidate.status !== "pending"}
                      onClick={() => setDraftDecision(value)}
                    >
                      {value === "positive" ? <CheckCircle2 size={15} /> : value === "negative" ? <TriangleAlert size={15} /> : <Trash2 size={15} />}
                      {decisionLabel(value)}
                    </button>
                  ))}
                </div>

                <div className={styles.formGrid}>
                  <label className={styles.formField}>
                    <span>{lang === "zh" ? "原因分类" : "Reason code"}</span>
                    <select
                      value={reasonCode}
                      disabled={selectedCandidate.status !== "pending"}
                      onChange={(event) => setReasonCode(event.target.value)}
                    >
                      <option value="">{lang === "zh" ? "未填写" : "Not set"}</option>
                      {reasonOptions.map((option) => (
                        <option key={option.value} value={option.value}>{option.label}</option>
                      ))}
                    </select>
                  </label>

                  {draftDecision === "negative" ? (
                    <label className={styles.formField}>
                      <span>{lang === "zh" ? "错误类型" : "Error type"}</span>
                      <input
                        type="text"
                        value={errorType}
                        disabled={selectedCandidate.status !== "pending"}
                        onChange={(event) => setErrorType(event.target.value)}
                        placeholder={lang === "zh" ? "例如：ungrounded_inference" : "For example: ungrounded_inference"}
                      />
                    </label>
                  ) : null}

                  {draftDecision === "negative" ? (
                    <label className={styles.formField}>
                      <span>{lang === "zh" ? "正确原则" : "Correct principle"}</span>
                      <input
                        type="text"
                        value={correctPrinciple}
                        disabled={selectedCandidate.status !== "pending"}
                        onChange={(event) => setCorrectPrinciple(event.target.value)}
                        placeholder={lang === "zh" ? "例如：先查日志再下判断" : "For example: inspect logs before concluding"}
                      />
                    </label>
                  ) : null}

                  {draftDecision === "negative" ? (
                    <label className={styles.formField}>
                      <span>{lang === "zh" ? "理想做法" : "Ideal behavior"}</span>
                      <input
                        type="text"
                        value={idealBehavior}
                        disabled={selectedCandidate.status !== "pending"}
                        onChange={(event) => setIdealBehavior(event.target.value)}
                        placeholder={lang === "zh" ? "补一句理想的处理方式" : "Describe the better behavior"}
                      />
                    </label>
                  ) : null}
                </div>

                <label className={styles.textAreaField}>
                  <span>{lang === "zh" ? "评审备注" : "Reviewer note"}</span>
                  <textarea
                    value={reviewerNote}
                    disabled={selectedCandidate.status !== "pending"}
                    onChange={(event) => setReviewerNote(event.target.value)}
                    placeholder={lang === "zh" ? "给未来的 agent 留一句人话提醒" : "Leave one human-readable reminder for the future agent"}
                  />
                </label>

                <div className={styles.actionRow}>
                  <button
                    type="button"
                    className={styles.primaryAction}
                    disabled={selectedCandidate.status !== "pending" || decisionMutation.isPending}
                    onClick={submitCurrentDecision}
                  >
                    {decisionMutation.isPending ? <LoaderCircle size={15} className={styles.spin} /> : <LibraryBig size={15} />}
                    {lang === "zh" ? "保存裁决" : "Save decision"}
                  </button>
                  <NavLink to={consoleTarget} className={styles.secondaryAction}>
                    <ArrowUpRight size={15} />
                    {positiveDatasetVisible
                      ? (lang === "zh" ? "回控制台并预选正例集" : "Return with positive dataset")
                      : (lang === "zh" ? "回到监督控制台" : "Back to supervised console")}
                  </NavLink>
                </div>

                {actionFeedback ? <p className={styles.feedbackText}>{actionFeedback}</p> : null}
                {decisionError ? <p className={styles.errorText}>{decisionError}</p> : null}
                {positiveDatasetVisible ? (
                  <p className={styles.hintText}>
                    {lang === "zh"
                      ? "当前正例数据集已经可用，回到监督控制台后可以直接基于它发起下一轮监督运行。"
                      : "The positive dataset is already available. Return to the supervised console to launch the next run with it."}
                  </p>
                ) : null}
              </section>

              <details className={styles.transcriptSection}>
                <summary>{lang === "zh" ? "完整对话与来源" : "Full transcript and provenance"}</summary>
                <div className={styles.transcriptMeta}>
                  <article className={styles.metaRow}>
                    <strong>{lang === "zh" ? "来源日志" : "Source log"}</strong>
                    <span>{selectedCandidate.sourceLogPath || "--"}</span>
                  </article>
                  <article className={styles.metaRow}>
                    <strong>{lang === "zh" ? "正例数据集" : "Positive dataset"}</strong>
                    <span>{reviewData?.positiveDatasetPath || "--"}</span>
                  </article>
                  <article className={styles.metaRow}>
                    <strong>{lang === "zh" ? "负例数据集" : "Negative dataset"}</strong>
                    <span>{reviewData?.negativeDatasetPath || "--"}</span>
                  </article>
                </div>
                <div className={styles.transcriptList}>
                  {selectedCandidate.conversationTurns.map((turn) => (
                    <article key={`${selectedCandidate.candidateId}-transcript-${turn.turnNumber}`} className={styles.transcriptCard}>
                      <div className={styles.evidenceTop}>
                        <strong>{`Turn ${turn.turnNumber}`}</strong>
                        <span>{turn.toolCalls.join(", ") || "--"}</span>
                      </div>
                      <p>{lang === "zh" ? `用户：${turn.userMessage}` : `User: ${turn.userMessage}`}</p>
                      <p>{lang === "zh" ? `助手：${turn.assistantMessage}` : `Assistant: ${turn.assistantMessage}`}</p>
                    </article>
                  ))}
                </div>
              </details>
            </>
          ) : (
            <div className={styles.emptyState}>
              <h3>{lang === "zh" ? "还没有可审的样本" : "No reviewable samples yet"}</h3>
              <p>{lang === "zh" ? "先在对话 / 编码里积累几轮真实任务，多轮样本会自动进入这里。" : "Accumulate a few real turns in Chat / Coding and reusable multi-turn samples will appear here."}</p>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
