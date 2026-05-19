export async function fetchJson<T>(input: string, init?: RequestInit): Promise<T> {
  const response = await fetch(input, {
    headers: {
      Accept: "application/json",
      ...(init?.headers ?? {}),
    },
    ...init,
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
