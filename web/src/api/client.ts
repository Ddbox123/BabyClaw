const CONTROL_TOKEN_ENDPOINT = "/api/control-token";
const CONTROL_TOKEN_HEADER_FALLBACK = "X-Vibelution-Control-Token";
const MUTATING_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

let controlTokenPromise: Promise<{ header: string; token: string }> | null = null;

export function resetControlTokenForTests() {
  controlTokenPromise = null;
}

export async function getControlToken(): Promise<{ header: string; token: string }> {
  if (!controlTokenPromise) {
    controlTokenPromise = fetch(CONTROL_TOKEN_ENDPOINT, {
      headers: { Accept: "application/json" },
      credentials: "same-origin",
    })
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(`Control token request failed: ${response.status}`);
        }
        const payload = (await response.json()) as { header?: string; controlToken?: string };
        const token = String(payload.controlToken ?? "").trim();
        if (!token) {
          throw new Error("Control token response was empty");
        }
        return {
          header: String(payload.header ?? CONTROL_TOKEN_HEADER_FALLBACK).trim() || CONTROL_TOKEN_HEADER_FALLBACK,
          token,
        };
      })
      .catch((error) => {
        controlTokenPromise = null;
        throw error;
      });
  }
  return controlTokenPromise;
}

function shouldAttachControlToken(input: string, method: string): boolean {
  return MUTATING_METHODS.has(method) && input.startsWith("/api/");
}

export async function fetchJson<T>(input: string, init?: RequestInit): Promise<T> {
  const method = String(init?.method ?? "GET").toUpperCase();
  const headers = new Headers(init?.headers ?? {});
  headers.set("Accept", headers.get("Accept") ?? "application/json");
  if (shouldAttachControlToken(input, method)) {
    const control = await getControlToken();
    headers.set(control.header, control.token);
  }

  const response = await fetch(input, {
    ...init,
    headers,
    credentials: init?.credentials ?? "same-origin",
  });

  if (!response.ok) {
    const contentType = response.headers.get("content-type") ?? "";
    let message = "";
    if (contentType.includes("application/json")) {
      try {
        const payload = (await response.json()) as { detail?: string; message?: string };
        message = payload.detail || payload.message || "";
      } catch {
        message = "";
      }
    }
    if (!message) {
      message = await response.text();
    }
    throw new Error(message || `Request failed: ${response.status}`);
  }

  return (await response.json()) as T;
}
