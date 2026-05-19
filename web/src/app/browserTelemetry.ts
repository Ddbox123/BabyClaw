export type BrowserTelemetryEventInput = {
  phase: string;
  eventCode: string;
  message: string;
  level?: "info" | "warning" | "error";
  fields?: Record<string, unknown>;
};

const TELEMETRY_ENDPOINT = "/api/runtime/browser-telemetry";

function truncateText(value: string, limit: number): string {
  const text = String(value ?? "");
  if (text.length <= limit) {
    return text;
  }
  return `${text.slice(0, Math.max(0, limit - 3))}...`;
}

function compactText(value: string, limit: number): string {
  return truncateText(String(value ?? "").replace(/\s+/g, " ").trim(), limit);
}

function summarizeUnknown(value: unknown, limit = 240): string {
  if (value instanceof Error) {
    return truncateText(value.stack || value.message || value.name, limit);
  }
  if (typeof value === "string") {
    return truncateText(value, limit);
  }
  try {
    return truncateText(JSON.stringify(value), limit);
  } catch {
    return truncateText(String(value), limit);
  }
}

export function summarizeConsoleArgs(args: unknown[], limit = 240): string {
  return truncateText(args.map((item) => summarizeUnknown(item, Math.max(limit, 120))).join(" | "), limit);
}

export function collectBrowserPageSnapshot(): Record<string, unknown> {
  if (typeof window === "undefined" || typeof document === "undefined") {
    return {};
  }

  const activeNav = document.querySelector<HTMLAnchorElement>("header nav a[aria-current='page']");
  const heading = document.querySelector("h1");
  const main = document.querySelector("main");

  return {
    href: window.location.href,
    pathname: window.location.pathname,
    search: window.location.search,
    hash: window.location.hash,
    title: document.title,
    readyState: document.readyState,
    visibilityState: document.visibilityState,
    online: typeof navigator === "undefined" ? true : navigator.onLine,
    activeNavHref: activeNav?.getAttribute("href") ?? "",
    activeNavText: compactText(activeNav?.textContent ?? "", 80),
    heading: compactText(heading?.textContent ?? "", 120),
    mainTextPreview: compactText(main?.textContent ?? "", 320),
  };
}

export function postBrowserTelemetry(
  payload: BrowserTelemetryEventInput,
  options?: { preferBeacon?: boolean },
) {
  if (typeof window === "undefined") {
    return;
  }

  const body = JSON.stringify(payload);
  if (options?.preferBeacon && typeof navigator !== "undefined" && typeof navigator.sendBeacon === "function") {
    try {
      const blob = new Blob([body], { type: "application/json" });
      if (navigator.sendBeacon(TELEMETRY_ENDPOINT, blob)) {
        return;
      }
    } catch {
      // Fall back to fetch below.
    }
  }

  void fetch(TELEMETRY_ENDPOINT, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body,
    credentials: "same-origin",
    keepalive: true,
  }).catch(() => {});
}
