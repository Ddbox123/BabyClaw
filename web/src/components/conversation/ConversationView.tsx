import { ArrowDown, BrainCircuit, ChevronDown, ChevronRight } from "lucide-react";
import { ReactNode, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import { ConversationMessage, MentalStateSnapshot } from "../../api/types";
import { useAppI18n } from "../../i18n/useAppI18n";
import { shouldSubmitComposerOnKeydown } from "./composerShortcuts";
import {
  hasMentalBlock,
  hasResponseBlock,
  hasThoughtBlock,
  hasToolBlock,
  hasUserContent,
} from "./messageSections";
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
  showSessionOverview?: boolean;
  autoScrollToLatest?: boolean;
  composerValue: string;
  composerPlaceholder: string;
  composerDisabled: boolean;
  composerActionDisabled?: boolean;
  composerActionMode?: "send" | "stop";
  composerPending: boolean;
  composerError?: string;
  mentalModelEnabled?: boolean;
  mentalModelOptionDisabled?: boolean;
  submitLabel?: string;
  submitPendingLabel?: string;
  stopLabel?: string;
  stopPendingLabel?: string;
  onComposerChange: (value: string) => void;
  onMentalModelEnabledChange?: (enabled: boolean) => void;
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
  showSessionOverview = true,
  autoScrollToLatest = true,
  composerValue,
  composerPlaceholder,
  composerDisabled,
  composerActionDisabled,
  composerActionMode,
  composerPending,
  composerError,
  mentalModelEnabled,
  mentalModelOptionDisabled,
  submitLabel,
  submitPendingLabel,
  stopLabel,
  stopPendingLabel,
  onComposerChange,
  onMentalModelEnabledChange,
  onSubmit,
  onStop,
}: ConversationViewProps) {
  const { lang, t, statusLabel } = useAppI18n();
  const timelineRef = useRef<HTMLDivElement | null>(null);
  const initializedSessionRef = useRef("");
  const atBottomRef = useRef(true);
  const [sectionExpansion, setSectionExpansion] = useState<Record<string, Record<string, boolean>>>({});
  const [isAtBottom, setIsAtBottom] = useState(true);
  const previousStreamingRef = useRef<Record<string, boolean>>({});
  const resolvedActionMode = composerActionMode ?? "send";
  const showMentalModelOption = typeof mentalModelEnabled === "boolean" && Boolean(onMentalModelEnabledChange);
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
  const latestToolCalls = useMemo(
    () =>
      [...messages]
        .reverse()
        .find((message) => (message.toolCalls?.length ?? 0) > 0)?.toolCalls ?? [],
    [messages],
  );
  const timelineScrollSignal = useMemo(
    () =>
      messages
        .map(
          (message) =>
            `${message.id}:${message.content.length}:${message.thought?.length ?? 0}:${
              message.toolCalls?.length ?? 0
            }:${message.streaming ? 1 : 0}`,
        )
        .join("|"),
    [messages],
  );
  const hasSessionMeta = resolvedStats.length > 0 || latestToolCalls.length > 0 || Boolean(lastMessageTimestamp);
  const hasMetaSection = showSessionOverview && (hasSessionMeta || Boolean(supplementalContent));

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

  useLayoutEffect(() => {
    const timeline = timelineRef.current;
    if (!timeline) {
      return;
    }
    if (initializedSessionRef.current !== sessionId) {
      initializedSessionRef.current = sessionId;
      timeline.scrollTop = timeline.scrollHeight;
      atBottomRef.current = true;
      setIsAtBottom(true);
      return;
    }
    if (autoScrollToLatest && atBottomRef.current) {
      timeline.scrollTop = timeline.scrollHeight;
      setIsAtBottom(true);
    }
  }, [autoScrollToLatest, sessionId, timelineScrollSignal]);

  useEffect(() => {
    const timeline = timelineRef.current;
    if (!timeline) {
      return;
    }
    const handleScroll = () => {
      const distance = timeline.scrollHeight - timeline.scrollTop - timeline.clientHeight;
      const nextAtBottom = distance < 16;
      atBottomRef.current = nextAtBottom;
      setIsAtBottom(nextAtBottom);
    };
    handleScroll();
    timeline.addEventListener("scroll", handleScroll);
    return () => timeline.removeEventListener("scroll", handleScroll);
  }, [sessionId]);

  useEffect(() => {
    const previous = previousStreamingRef.current;
    const nextStreaming: Record<string, boolean> = {};
    let shouldCollapse = false;
    for (const message of messages) {
      if (message.role !== "assistant") {
        continue;
      }
      nextStreaming[message.id] = Boolean(message.streaming);
      if (previous[message.id] && !message.streaming) {
        shouldCollapse = true;
      }
    }
    previousStreamingRef.current = nextStreaming;
    if (!shouldCollapse) {
      return;
    }
    setSectionExpansion((current) => {
      const next = { ...current };
      for (const message of messages) {
        if (message.role !== "assistant" || message.streaming) {
          continue;
        }
        next[message.id] = {
          ...(next[message.id] ?? {}),
          thought: false,
          mental: false,
          tools: false,
        };
      }
      return next;
    });
  }, [messages]);

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

  function getExpansionState(messageId: string, section: string, defaultExpanded: boolean) {
    if (section === "response") {
      return sectionExpansion[messageId]?.[section] ?? true;
    }
    return sectionExpansion[messageId]?.[section] ?? defaultExpanded;
  }

  function toggleSection(messageId: string, section: string, defaultExpanded: boolean) {
    setSectionExpansion((current) => ({
      ...current,
      [messageId]: {
        ...(current[messageId] ?? {}),
        [section]: !getExpansionState(messageId, section, defaultExpanded),
      },
    }));
  }

  function scrollToBottom() {
    const timeline = timelineRef.current;
    if (!timeline) {
      return;
    }
    timeline.scrollTo({ top: timeline.scrollHeight, behavior: "smooth" });
    atBottomRef.current = true;
    setIsAtBottom(true);
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

      {showSessionOverview && resolvedSummaryItems.length > 0 ? (
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
              {hasUserContent(message) ? (
                <p className={styles.messageBody}>{message.content}</p>
              ) : null}

              {hasThoughtBlock(message) ? (
                <section className={styles.sectionBlock}>
                  <button
                    type="button"
                    className={styles.sectionToggle}
                    aria-expanded={getExpansionState(message.id, "thought", Boolean(message.streaming))}
                    onClick={() => toggleSection(message.id, "thought", Boolean(message.streaming))}
                    title={
                      getExpansionState(message.id, "thought", Boolean(message.streaming))
                        ? t("thoughtProcessVisible")
                        : t("thoughtProcessHidden")
                    }
                  >
                    {getExpansionState(message.id, "thought", Boolean(message.streaming)) ? (
                      <ChevronDown size={16} />
                    ) : (
                      <ChevronRight size={16} />
                    )}
                    <BrainCircuit size={16} />
                    <span>{t("thoughtProcess")}</span>
                  </button>
                  {getExpansionState(message.id, "thought", Boolean(message.streaming)) ? (
                    <div className={styles.sectionPanel}>
                      <p className={styles.messageBody}>{message.thought?.trim()}</p>
                    </div>
                  ) : null}
                </section>
              ) : null}

              {hasMentalBlock(message) ? (
                <section className={styles.sectionBlock}>
                  <button
                    type="button"
                    className={styles.sectionToggle}
                    aria-expanded={getExpansionState(message.id, "mental", Boolean(message.streaming))}
                    onClick={() => toggleSection(message.id, "mental", Boolean(message.streaming))}
                    title={
                      getExpansionState(message.id, "mental", Boolean(message.streaming))
                        ? t("mentalProcessVisible")
                        : t("mentalProcessHidden")
                    }
                  >
                    {getExpansionState(message.id, "mental", Boolean(message.streaming)) ? (
                      <ChevronDown size={16} />
                    ) : (
                      <ChevronRight size={16} />
                    )}
                    <BrainCircuit size={16} />
                    <span>{t("mentalProcess")}</span>
                  </button>
                  {getExpansionState(message.id, "mental", Boolean(message.streaming)) ? (
                    <div className={styles.sectionPanel}>
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
                          {message.mentalSnapshot?.source ? (
                            <span className={styles.thoughtMetaPill}>{message.mentalSnapshot.source}</span>
                          ) : null}
                        </div>
                        {message.mentalSnapshot?.intervention ? (
                          <p className={styles.mentalIntervention}>{message.mentalSnapshot.intervention}</p>
                        ) : null}
                      </div>
                    </div>
                  ) : null}
                </section>
              ) : null}

              {hasToolBlock(message) ? (
                <section className={styles.sectionBlock}>
                  <button
                    type="button"
                    className={styles.sectionToggle}
                    aria-expanded={getExpansionState(message.id, "tools", Boolean(message.streaming))}
                    onClick={() => toggleSection(message.id, "tools", Boolean(message.streaming))}
                    title={
                      getExpansionState(message.id, "tools", Boolean(message.streaming))
                        ? t("toolProcessVisible")
                        : t("toolProcessHidden")
                    }
                  >
                    {getExpansionState(message.id, "tools", Boolean(message.streaming)) ? (
                      <ChevronDown size={16} />
                    ) : (
                      <ChevronRight size={16} />
                    )}
                    <span>{t("toolProcess")}</span>
                  </button>
                  {getExpansionState(message.id, "tools", Boolean(message.streaming)) ? (
                    <div className={styles.sectionPanel}>
                      <div className={styles.toolRow}>
                        {message.toolCalls?.map((toolCall, index) => (
                          <span key={`${message.id}-${toolCall.name}-${index}`} className={styles.toolPill}>
                            {toolCall.name} · {statusLabel(toolCall.status)}
                            {toolCall.summary ? ` · ${toolCall.summary}` : ""}
                          </span>
                        ))}
                      </div>
                    </div>
                  ) : null}
                </section>
              ) : null}

              {hasResponseBlock(message) ? (
                <section className={styles.sectionBlock}>
                  <button
                    type="button"
                    className={styles.sectionToggle}
                    aria-expanded={getExpansionState(message.id, "response", true)}
                    onClick={() => toggleSection(message.id, "response", true)}
                    title={getExpansionState(message.id, "response", true) ? t("responseHidden") : t("responseVisible")}
                  >
                    {getExpansionState(message.id, "response", true) ? (
                      <ChevronDown size={16} />
                    ) : (
                      <ChevronRight size={16} />
                    )}
                    <span>{t("responseLabel")}</span>
                  </button>
                  {getExpansionState(message.id, "response", true) ? (
                    <div className={styles.sectionPanel}>
                      <p className={styles.messageBody}>{message.content}</p>
                    </div>
                  ) : null}
                </section>
              ) : null}
            </article>
          ))
        )}
      </div>

      {!isAtBottom ? (
        <button type="button" className={styles.backToBottomButton} onClick={scrollToBottom} title={t("backToBottom")}>
          <ArrowDown size={16} />
          <span>{t("newContent")}</span>
        </button>
      ) : null}

      <div className={styles.composer}>
        <div className={styles.composerField}>
          {composerError ? <p className={styles.composerError}>{composerError}</p> : null}
          {showMentalModelOption ? (
            <div className={styles.composerOptions} aria-label={t("composerOptions")}>
              <label className={styles.optionToggle}>
                <input
                  className={styles.optionCheckbox}
                  type="checkbox"
                  checked={Boolean(mentalModelEnabled)}
                  disabled={Boolean(mentalModelOptionDisabled)}
                  onChange={(event) => onMentalModelEnabledChange?.(event.target.checked)}
                />
                <span className={styles.optionSwitch} aria-hidden="true" />
                <span className={styles.optionText}>{t("mentalModelForNextTurn")}</span>
              </label>
              <span className={styles.optionStatus}>
                {mentalModelEnabled ? t("mentalModelOptionOn") : t("mentalModelOptionOff")}
              </span>
            </div>
          ) : null}
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
