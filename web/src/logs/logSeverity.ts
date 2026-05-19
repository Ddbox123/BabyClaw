import type { RuntimeSceneEvent } from "../api/types";

export type LogSeverity = "error" | "warning" | "info";
export type LogSeverityFilter = "all" | "error" | "warning";

const ERROR_PATTERNS = [
  /\bERROR\b/i,
  /\bERR\b/i,
  /\bFATAL\b/i,
  /\bSEVERE\b/i,
  /\bCRITICAL\b/i,
  /\bPANIC\b/i,
  /\bCRASH(?:ED)?\b/i,
  /\bEXCEPTION\b/i,
  /\bTRACEBACK\b/i,
  /\bUNCAUGHT\b/i,
  /\bUNHANDLED(?:\s+PROMISE)?\s+REJECTION\b/i,
  /\bFAILED\b/i,
  /\bREFUSED\b/i,
];

const WARNING_PATTERNS = [
  /\bWARN(?:ING)?\b/i,
  /\bCAUTION\b/i,
  /\bDEPRECATED\b/i,
  /\bRETRY(?:ING)?\b/i,
  /\bFALLBACK\b/i,
  /\bSLOW\b/i,
];

function matchesAnyPattern(text: string, patterns: RegExp[]) {
  return patterns.some((pattern) => pattern.test(text));
}

export function classifyLogText(text: string): LogSeverity {
  const normalized = String(text || "").trim();
  if (!normalized) {
    return "info";
  }
  if (matchesAnyPattern(normalized, ERROR_PATTERNS)) {
    return "error";
  }
  if (matchesAnyPattern(normalized, WARNING_PATTERNS)) {
    return "warning";
  }
  return "info";
}

export function classifyRuntimeSceneEvent(event: RuntimeSceneEvent): LogSeverity {
  const level = String(event.level || "").trim().toLowerCase();
  if (level === "error") {
    return "error";
  }
  if (level === "warning" || level === "warn") {
    return "warning";
  }

  const combinedText = [
    event.eventCode,
    event.message,
    event.phase,
    event.component,
    ...Object.values(event.fields || {}).map((value) =>
      Array.isArray(value) ? value.join(" ") : String(value ?? ""),
    ),
  ].join(" ");

  return classifyLogText(combinedText);
}

export function matchesSeverityFilter(severity: LogSeverity, filter: LogSeverityFilter) {
  if (filter === "all") {
    return true;
  }
  return severity === filter;
}
