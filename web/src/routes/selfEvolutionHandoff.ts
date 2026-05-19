export type PendingSelfEvolutionHandoff = {
  sessionId: string;
  content: string;
};

const STORAGE_KEY = "vibelution.self-evolution.handoff";

function hasWindow() {
  return typeof window !== "undefined" && typeof window.sessionStorage !== "undefined";
}

export function savePendingSelfEvolutionHandoff(payload: PendingSelfEvolutionHandoff) {
  if (!hasWindow()) {
    return;
  }
  window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
}

export function loadPendingSelfEvolutionHandoff(): PendingSelfEvolutionHandoff | null {
  if (!hasWindow()) {
    return null;
  }
  const raw = window.sessionStorage.getItem(STORAGE_KEY);
  if (!raw) {
    return null;
  }
  try {
    const parsed = JSON.parse(raw) as PendingSelfEvolutionHandoff;
    if (!parsed || typeof parsed.content !== "string") {
      return null;
    }
    return {
      sessionId: typeof parsed.sessionId === "string" ? parsed.sessionId : "",
      content: parsed.content,
    };
  } catch {
    return null;
  }
}

export function clearPendingSelfEvolutionHandoff() {
  if (!hasWindow()) {
    return;
  }
  window.sessionStorage.removeItem(STORAGE_KEY);
}
