export function clampPercent(value: number) {
  if (!Number.isFinite(value)) {
    return 0;
  }
  return Math.max(0, Math.min(100, Math.round(value)));
}

export function contextUsagePercent(used: number, limit: number) {
  const safeLimit = Math.max(0, Number(limit) || 0);
  if (safeLimit <= 0) {
    return 0;
  }
  const safeUsed = Math.max(0, Math.min(Number(used) || 0, safeLimit));
  return clampPercent((safeUsed / safeLimit) * 100);
}

export function formatContextUsage(used: number, limit: number, locale: string) {
  const safeLimit = Math.max(0, Number(limit) || 0);
  const safeUsed = Math.max(0, Math.min(Number(used) || 0, safeLimit || Number(used) || 0));
  const formatter = new Intl.NumberFormat(locale);
  if (safeLimit <= 0) {
    return formatter.format(safeUsed);
  }
  return `${formatter.format(safeUsed)} / ${formatter.format(safeLimit)} (${contextUsagePercent(safeUsed, safeLimit)}%)`;
}

export function formatRelativeTime(timestamp: string, now: number, locale: string) {
  if (!timestamp) {
    return "";
  }
  const parsed = new Date(timestamp);
  if (Number.isNaN(parsed.getTime())) {
    return timestamp;
  }

  const diffSeconds = Math.round((parsed.getTime() - now) / 1000);
  const absoluteSeconds = Math.abs(diffSeconds);
  if (absoluteSeconds < 5) {
    return locale.startsWith("zh") ? "刚刚" : "just now";
  }

  const formatter = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
  if (absoluteSeconds < 60) {
    return formatter.format(diffSeconds, "second");
  }

  const diffMinutes = Math.round(diffSeconds / 60);
  if (Math.abs(diffMinutes) < 60) {
    return formatter.format(diffMinutes, "minute");
  }

  const diffHours = Math.round(diffSeconds / 3600);
  if (Math.abs(diffHours) < 24) {
    return formatter.format(diffHours, "hour");
  }

  const diffDays = Math.round(diffSeconds / 86400);
  return formatter.format(diffDays, "day");
}
