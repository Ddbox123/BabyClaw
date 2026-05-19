import { BrainCircuit, ChevronDown, ChevronRight } from "lucide-react";
import { ReactNode, useEffect, useMemo, useRef, useState } from "react";

import { ConversationMessage, MentalStateSnapshot } from "../../api/types";
import { useAppI18n } from "../../i18n/useAppI18n";
import { shouldSubmitComposerOnKeydown } from "./composerShortcuts";
import styles from "./ConversationView.module.css";

type ConversationViewProps = {
  sessionId: string;
  title: string;
  phase: string;
  messages: ConversationMessage[];
  eyebrowLabel?: string;
  taskSummary?: string;
  defaultFileContext: string;
  summaryItems?: Array<{
    label: string;
    value: string;
  }>;
  stats?: Array<{
    label: string;
    value: string | number;
  }>;
  headerActions?: ReactNode;
  supplementalContent?: ReactNode;
  autoScrollToLatest?: boolean;
  composerValue: string;
  composerPlaceholder: string;
  composerDisabled: boolean;
  composerActionDisabled?: boolean;
  composerActionMode?: "send" | "stop";
  composerPending: boolean;
  composerError?: string;
  submitLabel?: string;
  submitPendingLabel?: string;
  stopLabel?: string;
  stopPendingLabel?: string;
  onComposerChange: (value: string) => void;
  onSubmit: () => void;
  onStop?: () => void;
};

export function ConversationView({
  sessionId,
  title,
  phase,
  messages,
  eyebrowLabel,
  taskSummary,
  defaultFileContext,
  summaryItems,
  stats,
  headerActions,
  supplementalContent,
  autoScrollToLatest = true,
  composerValue,
  composerPlaceholder,
  composerDisabled,
  composerActionDisabled,
  composerActionMode,
  composerPending,
  composerError,
  submitLabel,
  submitPendingLabel,
  stopLabel,
  stopPendingLabel,
  onComposerChange,
  onSubmit,
  onStop,
}: ConversationViewProps) {
  const { lang, t, statusLabel } = useAppI18n();
  const timelineRef = useRef<HTMLDivElement | null>(null);
  const [thoughtExpansion, setThoughtExpansion] = useState<Record<string, boolean>>({});
  const resolvedActionMode = composerActionMode ?? "send";
  const resolvedActionDisabled =
    composerActionDisabled
    ?? (resolvedActionMode === "stop" ? composerDisabled : composerDisabled || !composerValue.trim());
  const resolvedActionLabel =
    resolvedActionMode === "stop" ? (stopLabel ?? t("stop")) : (submitLabel ?? t("send"));
  const resolvedPendingLabel =
    resolvedActionMode === "stop"
      ? (stopPendingLabel ?? t("stopPending"))
      : (submitPendingLabel ?? t("sendPending"));
  const handlePrimaryAction = resolvedActionMode === "stop" ? onStop ?? onSubmit : onSubmit;
  const timestampFormatter = useMemo(
    () =>
      new Intl.DateTimeFormat(lang === "zh" ? "zh-CN" : "en-US", {
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      }),
    [lang],
  );

  const latestUserMessage = useMemo(
    () =>
      [...messages]
        .reverse()
        .find((message) => message.role === "user")?.content ?? "",
    [messages],
  );
  const latestToolCalls = useMemo(
    () =>
      [...messages]
        .reverse()
        .find((message) => (message.toolCalls?.length ?? 0) > 0)?.toolCalls ?? [],
    [messages],
  );
  const lastMessageTimestamp = useMemo(
    () => [...messages].reverse().find((message) => message.timestamp)?.timestamp ?? "",
    [messages],
  );

  const taskFocus = compactPreview(taskSummary || latestUserMessage || title);
  const fileContext = defaultFileContext || "workspace";
  const resolvedSummaryItems = summaryItems ?? [
    { label: t("taskFocus"), value: taskFocus },
    { label: t("fileContext"), value: fileContext },
    { label: t("status"), value: statusLabel(phase) },
    { label: t("lastUpdated"), value: lastMessageTimestamp ? formatTimestamp(lastMessageTimestamp) : "--" },
  ];
  const resolvedStats = stats ?? [];
  const hasSessionMeta = resolvedStats.length > 0 || latestToolCalls.length > 0 || Boolean(lastMessageTimestamp);
  const hasMetaSection = hasSessionMeta || Boolean(supplementalContent);

  function formatTimestamp(timestamp: string) {
    if (!timestamp) {
      return "";
    }
    const value = new Date(timestamp);
    if (Number.isNaN(value.getTime())) {
      return timestamp;
    }
    return timestampFormatter.format(value);
  }

  function compactPreview(value: string, maxLength = 180) {
    const normalized = value.replace(/\s+/g, " ").trim();
    if (!normalized) {
      return "";
    }
    if (normalized.length <= maxLength) {
      return normalized;
    }
    return `${normalized.slice(0, maxLength - 1).trimEnd()}...`;
  }

  useEffect(() => {
    const timeline = timelineRef.current;
    if (!timeline) {
      return;
    }
    if (autoScrollToLatest) {
      timeline.scrollTop = timeline.scrollHeight;
      return;
    }
    timeline.scrollTop = 0;
  }, [autoScrollToLatest, sessionId, messages]);

  function cognitiveStateLabel(snapshot: MentalStateSnapshot | undefined) {
    const value = String(snapshot?.cognitiveState ?? "").trim().toLowerCase() || "unknown";
    const keyMap = {
      unknown: "mentalCognitiveState_unknown",
      normal: "mentalCognitiveState_normal",
      productive: "mentalCognitiveState_productive",
      looping: "mentalCognitiveState_looping",
      thrashing: "mentalCognitiveState_thrashing",
      tunnel_vision: "mentalCognitiveState_tunnel_vision",
      disoriented: "mentalCognitiveState_disoriented",
    } as const;
    const key = keyMap[value as keyof typeof keyMap];
    return key ? t(key) : snapshot?.cognitiveState ?? "";
  }

  function hasMentalSnapshot(snapshot: MentalStateSnapshot | undefined) {
    if (!snapshot) {
      return false;
    }
    return [
      snapshot.mood,
      snapshot.feeling,
      snapshot.whisper,
      snapshot.cognitiveState,
    ].some((value) => String(value ?? "").trim().length > 0);
  }

  function hasThoughtBlock(message: ConversationMessage) {
    return message.role === "assistant"
      && (Boolean(message.thought?.trim()) || hasMentalSnapshot(message.mentalSnapshot));
  }

  function isThoughtExpanded(message: ConversationMessage) {
    return thoughtExpansion[message.id] ?? Boolean(message.streaming);
  }

  function toggleThoughtExpansion(messageId: string, currentExpanded: boolean) {
    setThoughtExpansion((current) => ({
      ...current,
      [messageId]: !currentExpanded,
    }));
  }

  return (
    <div className={styles.surface}>
      <div className={styles.header}>
        <div>
          <p className={styles.eyebrow}>{eyebrowLabel ?? t("agentSession")}</p>
          <h2 className={styles.title}>{title}</h2>
        </div>
        <div className={styles.headerControls}>
          {headerActions}
          <span className={styles.phase}>{statusLabel(phase)}</span>
        </div>
      </div>

      {resolvedSummaryItems.length > 0 ? (
        <div className={styles.summaryGrid}>
          {resolvedSummaryItems.map((item) => (
            <section key={item.label} className={styles.summaryCard}>
              <p className={styles.summaryLabel}>{item.label}</p>
              <p className={styles.summaryValue} title={item.value}>
                {item.value}
              </p>
            </section>
          ))}
        </div>
      ) : null}

      {hasMetaSection ? (
        <div className={styles.metaStack}>
          {hasSessionMeta ? (
            <div className={styles.sessionMeta}>
              {resolvedStats.length > 0 ? (
                <div className={styles.statRow}>
                  {resolvedStats.map((item) => (
                    <span key={item.label} className={styles.statPill}>
                      {item.label} {item.value}
                    </span>
                  ))}
                </div>
              ) : null}
              {latestToolCalls.length > 0 ? (
                <div className={styles.toolsBlock}>
                  <span className={styles.toolsLabel}>{t("activeToolsLabel")}</span>
                  <div className={styles.toolRow}>
                    {latestToolCalls.map((toolCall, index) => (
                      <span key={`${toolCall.name}-${index}`} className={styles.toolPill}>
                        {toolCall.name} · {statusLabel(toolCall.status)}
                      </span>
                    ))}
                  </div>
                </div>
              ) : null}
              {lastMessageTimestamp ? (
                <p className={styles.updateLine}>
                  {t("lastUpdated")} {formatTimestamp(lastMessageTimestamp)}
                </p>
              ) : null}
            </div>
          ) : null}

          {supplementalContent ? <div className={styles.supplemental}>{supplementalContent}</div> : null}
        </div>
      ) : null}

      <div ref={timelineRef} className={styles.timeline}>
        {messages.length === 0 ? (
          <div className={styles.emptyState}>{t("sessionNoMessages")}</div>
        ) : (
          messages.map((message) => (
            <article
              key={message.id}
              className={
                message.role === "assistant"
                  ? `${styles.messageCard} ${styles.assistantCard}`
                  : `${styles.messageCard} ${styles.userCard}`
              }
            >
              <div className={styles.messageMeta}>
                <span>{message.role === "assistant" ? t("agent") : t("operator")}</span>
                {message.timestamp ? <span>{formatTimestamp(message.timestamp)}</span> : null}
              </div>
              {hasThoughtBlock(message) ? (
                <section className={styles.thoughtBlock}>
                  <button
                    type="button"
                    className={styles.thoughtToggle}
                    aria-expanded={isThoughtExpanded(message)}
                    onClick={() => toggleThoughtExpansion(message.id, isThoughtExpanded(message))}
                    title={isThoughtExpanded(message) ? t("thoughtProcessVisible") : t("thoughtProcessHidden")}
                  >
                    {isThoughtExpanded(message) ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                    <BrainCircuit size={16} />
                    <span>{t("thoughtProcess")}</span>
                  </button>

                  {isThoughtExpanded(message) ? (
                    <div className={styles.thoughtPanel}>
                      {hasMentalSnapshot(message.mentalSnapshot) ? (
                        <div className={styles.mentalSnapshot}>
                          <div className={styles.thoughtSectionHeader}>
                            <span className={styles.thoughtSectionLabel}>{t("mentalState")}</span>
                            {(message.mentalSnapshot?.mood || cognitiveStateLabel(message.mentalSnapshot)) ? (
                              <span className={styles.thoughtMetaPill}>
                                {message.mentalSnapshot?.mood?.trim() || cognitiveStateLabel(message.mentalSnapshot)}
                              </span>
                            ) : null}
                          </div>
                          {(message.mentalSnapshot?.summary || message.mentalSnapshot?.feeling) ? (
                            <p className={styles.mentalSummary}>
                              {message.mentalSnapshot?.summary?.trim()
                                || message.mentalSnapshot?.feeling?.trim()
                                || t("mentalStatePending")}
                            </p>
                          ) : null}
                          {message.mentalSnapshot?.whisper?.trim() ? (
                            <p className={styles.mentalWhisper}>
                              <span className={styles.thoughtSectionLabel}>{t("mentalWhisper")}</span>
                              {message.mentalSnapshot.whisper.trim()}
                            </p>
                          ) : null}
                          <div className={styles.thoughtMetaRow}>
                            {message.mentalSnapshot?.cognitiveState?.trim() ? (
                              <span className={styles.thoughtMetaPill}>
                                {t("mentalCognitiveState")} {cognitiveStateLabel(message.mentalSnapshot)}
                              </span>
                            ) : null}
                            {Number.isFinite(message.mentalSnapshot?.confidence)
                              && (message.mentalSnapshot?.confidence ?? 0) > 0 ? (
                                <span className={styles.thoughtMetaPill}>
                                  {t("mentalConfidence")} {Math.round((message.mentalSnapshot?.confidence ?? 0) * 100)}%
                                </span>
                              ) : null}
                          </div>
                        </div>
                      ) : null}

                      {message.thought?.trim() ? (
                        <div className={styles.thoughtTextBlock}>
                          <p className={styles.thoughtText}>{message.thought.trim()}</p>
                        </div>
                      ) : null}
                    </div>
                  ) : null}
                </section>
              ) : null}

              {message.content.trim() ? (
                <div className={styles.responseBlock}>
                  {hasThoughtBlock(message) ? (
                    <span className={styles.responseLabel}>{t("responseLabel")}</span>
                  ) : null}
                  <p className={styles.messageBody}>{message.content}</p>
                </div>
              ) : null}
              {message.toolCalls && message.toolCalls.length > 0 ? (
                <div className={styles.toolRow}>
                  {message.toolCalls.map((toolCall, index) => (
                    <span key={`${message.id}-${toolCall.name}-${index}`} className={styles.toolPill}>
                      {toolCall.name} · {statusLabel(toolCall.status)}
                    </span>
                  ))}
                </div>
              ) : null}
            </article>
          ))
        )}
      </div>

      <div className={styles.composer}>
        <div className={styles.composerField}>
          {composerError ? <p className={styles.composerError}>{composerError}</p> : null}
          <textarea
            className={styles.input}
            value={composerValue}
            disabled={composerDisabled}
            placeholder={composerPlaceholder}
            onChange={(event) => onComposerChange(event.target.value)}
            onKeyDown={(event) => {
              if (
                shouldSubmitComposerOnKeydown({
                  key: event.key,
                  shiftKey: event.shiftKey,
                  ctrlKey: event.ctrlKey,
                  metaKey: event.metaKey,
                  altKey: event.altKey,
                  isComposing: event.nativeEvent.isComposing,
                })
              ) {
                event.preventDefault();
                if (
                  resolvedActionMode === "send"
                  && !resolvedActionDisabled
                  && composerValue.trim()
                ) {
                  onSubmit();
                }
              }
            }}
          />
        </div>
        <button
          className={
            resolvedActionMode === "stop" ? `${styles.sendButton} ${styles.stopButton}` : styles.sendButton
          }
          disabled={resolvedActionDisabled}
          type="button"
          onClick={handlePrimaryAction}
        >
          {composerPending ? resolvedPendingLabel : resolvedActionLabel}
        </button>
      </div>
    </div>
  );
}
