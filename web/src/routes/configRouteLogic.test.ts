import { describe, expect, it } from "vitest";

import {
  applyModelOptionToProfileDraft,
  collectModelDetailKeys,
  groupModelPresets,
  presetCategory,
  type PublicConfigShape,
} from "./configRouteLogic";
import type { ConfigModelOption, ConfigModelPresetOption } from "../api/types";

function preset(
  presetId: string,
  provider: Record<string, unknown>,
  category?: string,
): ConfigModelPresetOption {
  return {
    preset_id: presetId,
    label: presetId,
    category,
    provider_id: `${presetId}_provider`,
    model_id: presetId,
    provider,
    model: { model: presetId },
  };
}

function option(overrides: Partial<ConfigModelOption> = {}): ConfigModelOption {
  return {
    model_id: "relay_openai_gpt_5_5",
    source: "model_library",
    provider: {
      kind: "relay",
      base_url: "https://pixel.try-chatapi.com/v1",
      compat_mode: "openai",
      requires_api_key: true,
    },
    provider_kind: "relay",
    model: "gpt-5.5",
    label: "GPT-5.5 via relay",
    details: {
      transport: "chat_completions",
      contract: "tool_chat",
      streaming: true,
      timeout: 120,
    },
    api_key_env: "VIBELUTION_LLM_RELAY_OPENAI_GPT_5_5_API_KEY",
    api_key_configured: false,
    api_key_state: "missing",
    ...overrides,
  };
}

describe("configRouteLogic", () => {
  it("classifies model presets from explicit category before provider heuristics", () => {
    expect(presetCategory(preset("relay", { kind: "openai" }, "relay"))).toBe("relay");
    expect(presetCategory(preset("local", { kind: "openai", base_url: "http://127.0.0.1:11434/v1" }))).toBe("local");
    expect(presetCategory(preset("official", { kind: "openai", base_url: "https://api.openai.com/v1" }))).toBe("official");
  });

  it("groups presets in stable official relay local order and drops empty groups", () => {
    const groups = groupModelPresets(
      [
        preset("local_model", { kind: "local", base_url: "http://localhost:11434/v1" }),
        preset("relay_model", { kind: "relay", base_url: "https://pixel.try-chatapi.com/v1" }),
      ],
      {
        official: "Official",
        relay: "Relay",
        local: "Local",
      },
    );

    expect(groups.map((group) => group.id)).toEqual(["relay", "local"]);
    expect(groups.map((group) => group.label)).toEqual(["Relay", "Local"]);
    expect(groups[0].presets.map((item) => item.preset_id)).toEqual(["relay_model"]);
    expect(groups[1].presets.map((item) => item.preset_id)).toEqual(["local_model"]);
  });

  it("applies a model option to a profile draft and removes stale model binding fields", () => {
    const publicConfig: PublicConfigShape = {
      llm: {
        profiles: {
          primary: {
            model_ref: "old_model",
            provider_id: "legacy_provider",
            provider: { kind: "deepseek", base_url: "https://api.deepseek.com" },
            model: "deepseek-v4-pro",
            api_key_env: "OLD_KEY",
            overrides: { temperature: 0.2 },
            transport: "old_transport",
            contract: "old_contract",
            timeout: 5,
          },
        },
      },
    };
    const selected = option();
    const detailKeys = collectModelDetailKeys([selected]);

    applyModelOptionToProfileDraft(publicConfig, "primary", selected, detailKeys);

    const profile = (publicConfig.llm as Record<string, unknown>).profiles as Record<string, Record<string, unknown>>;
    expect(profile.primary.model_ref).toBeUndefined();
    expect(profile.primary.provider_id).toBeUndefined();
    expect(profile.primary.overrides).toBeUndefined();
    expect(profile.primary.provider).toEqual(selected.provider);
    expect(profile.primary.model).toBe("gpt-5.5");
    expect(profile.primary.api_key_env).toBe("VIBELUTION_LLM_RELAY_OPENAI_GPT_5_5_API_KEY");
    expect(profile.primary.transport).toBe("chat_completions");
    expect(profile.primary.contract).toBe("tool_chat");
    expect(profile.primary.timeout).toBe(120);
  });

  it("removes profile api_key_env when the selected model has none", () => {
    const publicConfig: PublicConfigShape = {
      llm: {
        profiles: {
          primary: {
            api_key_env: "OLD_KEY",
          },
        },
      },
    };
    const selected = option({ api_key_env: "" });

    applyModelOptionToProfileDraft(publicConfig, "primary", selected, collectModelDetailKeys([selected]));

    const profile = (publicConfig.llm as Record<string, unknown>).profiles as Record<string, Record<string, unknown>>;
    expect(profile.primary.api_key_env).toBeUndefined();
  });
});
