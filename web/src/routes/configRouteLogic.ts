import type { ConfigDraftMeta, ConfigModelOption, ConfigModelPresetOption } from "../api/types";

export type PublicConfigShape = Record<string, unknown>;

export type ModelPresetGroupId = "official" | "relay" | "local";

export type ModelPresetGroup = {
  id: ModelPresetGroupId;
  label: string;
  presets: ConfigModelPresetOption[];
};

export type ModelPresetGroupLabels = Record<ModelPresetGroupId, string>;

export function clonePublicConfig<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

export function asRecord(value: unknown): Record<string, unknown> {
  return isRecord(value) ? value : {};
}

export function getString(value: unknown): string {
  return typeof value === "string" ? value : value == null ? "" : String(value);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function ensureRecord(target: Record<string, unknown>, key: string): Record<string, unknown> {
  const current = target[key];
  if (isRecord(current)) {
    return current;
  }
  const created: Record<string, unknown> = {};
  target[key] = created;
  return created;
}

export function collectModelDetailKeys(options: ConfigModelOption[]): string[] {
  const keys = new Set<string>();
  for (const option of options) {
    for (const key of Object.keys(asRecord(option.details))) {
      keys.add(key);
    }
  }
  return Array.from(keys);
}

export function hasPendingSecretChanges(draftMeta: ConfigDraftMeta): boolean {
  return Boolean(Object.keys(draftMeta.pending_api_keys).length || draftMeta.pending_cleared_api_keys.length);
}

export function presetCategory(preset: ConfigModelPresetOption): ModelPresetGroupId {
  const explicit = getString(preset.category).trim().toLowerCase();
  if (explicit === "relay" || explicit === "local" || explicit === "official") {
    return explicit;
  }
  const provider = asRecord(preset.provider);
  const kind = getString(provider.kind).trim().toLowerCase();
  const baseUrl = getString(provider.base_url).trim().toLowerCase();
  if (kind === "relay" || kind === "openai_compatible") {
    return "relay";
  }
  if (kind === "local" || kind === "ollama" || baseUrl.includes("localhost") || baseUrl.includes("127.0.0.1")) {
    return "local";
  }
  return "official";
}

export function groupModelPresets(
  presets: ConfigModelPresetOption[],
  labels: ModelPresetGroupLabels,
): ModelPresetGroup[] {
  const groups: ModelPresetGroup[] = [
    { id: "official", label: labels.official, presets: [] },
    { id: "relay", label: labels.relay, presets: [] },
    { id: "local", label: labels.local, presets: [] },
  ];
  const groupById = new Map(groups.map((group) => [group.id, group]));
  for (const preset of presets) {
    groupById.get(presetCategory(preset))?.presets.push(preset);
  }
  return groups.filter((group) => group.presets.length);
}

export function applyModelOptionToProfileDraft(
  config: PublicConfigShape,
  profileId: string,
  option: ConfigModelOption,
  modelDetailKeys: string[],
): void {
  const llm = ensureRecord(config, "llm");
  const profiles = ensureRecord(llm, "profiles");
  const profile = ensureRecord(profiles, profileId);

  delete profile.overrides;
  delete profile.model_ref;
  delete profile.provider_id;
  for (const key of modelDetailKeys) {
    delete profile[key];
  }

  profile.provider = clonePublicConfig(asRecord(option.provider));
  profile.model = option.model;
  if (option.api_key_env) {
    profile.api_key_env = option.api_key_env;
  } else {
    delete profile.api_key_env;
  }
  for (const [key, value] of Object.entries(asRecord(option.details))) {
    profile[key] = clonePublicConfig(value);
  }
}
