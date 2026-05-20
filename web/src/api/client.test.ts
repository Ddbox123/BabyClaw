import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchJson, resetControlTokenForTests } from "./client";

describe("fetchJson control token", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    resetControlTokenForTests();
  });

  it("adds the web control token header to mutating requests", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          header: "X-Vibelution-Control-Token",
          controlToken: "test-token",
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ ok: true }),
      });
    vi.stubGlobal("fetch", fetchMock);

    const payload = await fetchJson<{ ok: boolean }>("/api/runtime/shutdown", { method: "POST" });

    expect(payload.ok).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const requestInit = fetchMock.mock.calls[1][1] as RequestInit;
    const headers = requestInit.headers as Headers;
    expect(headers.get("X-Vibelution-Control-Token")).toBe("test-token");
    expect(requestInit.credentials).toBe("same-origin");
  });

  it("does not request a control token for read-only requests", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce({
      ok: true,
      json: async () => ({ status: "ok" }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const payload = await fetchJson<{ status: string }>("/api/health");

    expect(payload.status).toBe("ok");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/health");
  });

  it("does not attach the local control token to external writes", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce({
      ok: true,
      json: async () => ({ ok: true }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const payload = await fetchJson<{ ok: boolean }>("https://example.invalid/api/probe", { method: "POST" });

    expect(payload.ok).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const requestInit = fetchMock.mock.calls[0][1] as RequestInit;
    const headers = requestInit.headers as Headers;
    expect(headers.get("X-Vibelution-Control-Token")).toBeNull();
  });
});
