import { useQuery } from "@tanstack/react-query";

import { fetchJson } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import { ConfigSummary } from "../api/types";
import { dictionary, Language, TranslationKey } from "./dictionary";

const statusKeyMap: Record<string, TranslationKey> = {
  idle: "status_idle",
  running: "status_running",
  failed: "status_failed",
  waiting: "status_waiting",
  done: "status_done",
  success: "status_success",
  queued: "status_queued",
  pending: "status_pending",
  planning: "status_planning",
  ready: "status_ready",
  reading: "status_reading",
  editing: "status_editing",
  verifying: "status_verifying",
  paused: "status_paused",
  pause_requested: "status_pause_requested",
  preparing: "status_preparing",
  evaluating: "status_evaluating",
  thinking: "status_thinking",
  tooling: "status_tooling",
  answering: "status_answering",
  blocked: "status_blocked",
  caution: "status_caution",
  disabled: "status_disabled",
  stopping: "status_stopping",
  cancelled: "status_cancelled",
  available: "status_available",
  unavailable: "status_unavailable",
  submitted: "status_submitted",
  needs_input: "status_needs_input",
  "manual-approved": "status_manual_approved",
  "manual_approved": "status_manual_approved",
  approved: "status_approved",
  rejected: "status_rejected",
  positive: "status_positive",
  negative: "status_negative",
  discard: "status_discard",
  proposed: "status_proposed",
  applied: "status_applied",
  active: "status_active",
  superseded: "status_superseded",
  rolled_back: "status_rolled_back",
  missing: "status_missing",
};

const intakeModeKeyMap: Record<string, TranslationKey> = {
  auto: "intakeAuto",
  manual_review: "intakeManualReview",
};

const viewKeyMap: Record<string, TranslationKey> = {
  live: "live",
  overview: "live",
  runs: "runs",
  library: "library",
  review: "reviewWorkspace",
};

const decisionKeyMap: Record<string, TranslationKey> = {
  PROMOTE: "decision_promote",
  HOLD: "decision_hold",
  ROLLBACK: "decision_rollback",
  REJECT: "decision_reject",
  INCONCLUSIVE: "decision_inconclusive",
};

const riskKeyMap: Record<string, TranslationKey> = {
  none: "risk_none",
  low: "risk_low",
  medium: "risk_medium",
  high: "risk_high",
};

const workbenchSourceKeyMap: Record<string, TranslationKey> = {
  bundle: "workbenchSourceBundle",
  dataset: "workbenchSourceDataset",
  unknown: "workbenchSourceUnknown",
};

const proposalActionKeyMap: Record<string, TranslationKey> = {
  apply: "actionApply",
  activate: "actionActivate",
  rollback: "actionRollback",
};

const sourceKindKeyMap: Record<string, TranslationKey> = {
  dataset: "sourceDataset",
  bundle: "sourceBundle",
};

export function useAppI18n() {
  const configQuery = useQuery({
    queryKey: queryKeys.configPublic(),
    queryFn: () => fetchJson<ConfigSummary>("/api/config/public"),
  });

  const lang: Language = configQuery.data?.language === "en" ? "en" : "zh";
  const table = dictionary[lang];

  function t(key: TranslationKey): string {
    return table[key];
  }

  function statusLabel(status: string): string {
    const key = statusKeyMap[status];
    return key ? table[key] : status.replaceAll("_", " ");
  }

  function intakeModeLabel(mode: string): string {
    const key = intakeModeKeyMap[mode];
    return key ? table[key] : mode.replaceAll("_", " ");
  }

  function viewLabel(view: string): string {
    const key = viewKeyMap[view];
    return key ? table[key] : view;
  }

  function decisionLabel(decision: string): string {
    const key = decisionKeyMap[String(decision || "").trim().toUpperCase()];
    return key ? table[key] : decision;
  }

  function riskLabel(risk: string): string {
    const key = riskKeyMap[String(risk || "").trim().toLowerCase()];
    return key ? table[key] : risk.replaceAll("_", " ");
  }

  function workbenchSourceLabel(source: string): string {
    const key = workbenchSourceKeyMap[String(source || "").trim().toLowerCase()];
    return key ? table[key] : source.replaceAll("_", " ");
  }

  function proposalActionLabel(action: string): string {
    const key = proposalActionKeyMap[String(action || "").trim().toLowerCase()];
    return key ? table[key] : action.replaceAll("_", " ");
  }

  function sourceKindLabel(source: string): string {
    const key = sourceKindKeyMap[String(source || "").trim().toLowerCase()];
    return key ? table[key] : source.replaceAll("_", " ");
  }

  return {
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
  };
}
