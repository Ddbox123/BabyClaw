import { useQuery, useQueryClient } from "@tanstack/react-query";
import CodeMirror from "@uiw/react-codemirror";
import {
  Blocks,
  ChevronRight,
  Database,
  Languages,
  Pencil,
  Play,
  Plus,
  RefreshCw,
  RotateCcw,
  Save,
  ShieldAlert,
  SlidersHorizontal,
  Trash2,
} from "lucide-react";
import { type CSSProperties, type PointerEvent as ReactPointerEvent, type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { json } from "@codemirror/lang-json";
import { EditorView } from "@codemirror/view";
import { oneDark } from "@codemirror/theme-one-dark";

import { fetchJson } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import {
  ConfigEditorMeta,
  ConfigEditorSection,
  ConfigDraftMeta,
  ConfigLlmTestResult,
  ConfigModelOption,
  ConfigModelPresetOption,
  ConfigWorkspace,
} from "../api/types";
import {
  applyModelOptionToProfileDraft,
  asRecord,
  clonePublicConfig,
  collectModelDetailKeys,
  getString,
  groupModelPresets,
  type ModelPresetGroupLabels,
  type PublicConfigShape,
} from "./configRouteLogic";
import styles from "./ConfigRoute.module.css";

type ConfigLanguage = "zh" | "en";
type NoticeTone = "neutral" | "success" | "error";

type ProviderDraft = {
  kind: string;
  api_key_env: string;
  base_url: string;
  compat_mode: string;
  requires_api_key: boolean;
  context_window: string;
};

type ModelDetailsDraft = {
  transport: string;
  contract: string;
  reasoning_state_field: string;
  strict_compatibility: boolean;
  temperature: string;
  max_output_tokens: string;
  timeout: string;
  connect_timeout: string;
  streaming: boolean;
  tool_calling_mode: string;
  discovery_enabled: boolean;
};

type ModelEditorState = {
  mode: "create" | "edit";
  preset_id: string;
  model_id: string;
  label: string;
  model: string;
  api_key_env: string;
  api_key: string;
  clear_api_key: boolean;
  provider: ProviderDraft;
  details: ModelDetailsDraft;
};

type ProfileDraft = {
  profile_id: string;
  source_profile_id: string;
  model_id: string;
};

type ProfileEditState = {
  modelId: string;
};

type ConfigSectionUiState = {
  expanded: boolean;
  editing: boolean;
  expandedPaths: Record<string, boolean>;
  draftValue?: unknown;
};

type ConfigSidebarGroup = {
  id: string;
  title: string;
  summary: string;
  memberSectionIds: string[];
};

const SIDEBAR_WIDTH_STORAGE_KEY = "vibelution.config.sidebar.width";
const SIDEBAR_HEIGHT_STORAGE_KEY = "vibelution.config.sidebar.height";
const SIDEBAR_INDEX_COLLAPSED_STORAGE_KEY = "vibelution.config.sidebar.indexCollapsed";
const SIDEBAR_WIDTH_DEFAULT = 320;
const SIDEBAR_WIDTH_MIN = 280;
const SIDEBAR_WIDTH_MAX = 520;
const SIDEBAR_HEIGHT_MIN = 420;
const SIDEBAR_VIEWPORT_OFFSET = 44;

function clampValue(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function readStoredNumber(key: string): number | null {
  if (typeof window === "undefined") {
    return null;
  }
  const raw = window.localStorage.getItem(key);
  if (!raw) {
    return null;
  }
  const parsed = Number(raw);
  return Number.isFinite(parsed) ? parsed : null;
}

function readStoredFlag(key: string): boolean | null {
  if (typeof window === "undefined") {
    return null;
  }
  const raw = window.localStorage.getItem(key);
  if (raw == null) {
    return null;
  }
  if (raw === "1") {
    return true;
  }
  if (raw === "0") {
    return false;
  }
  return null;
}

function clampSidebarWidth(value: number, viewportWidth: number): number {
  const max = Math.max(
    SIDEBAR_WIDTH_MIN,
    Math.min(SIDEBAR_WIDTH_MAX, Math.floor(viewportWidth * 0.42), viewportWidth - 720),
  );
  return clampValue(value, SIDEBAR_WIDTH_MIN, max);
}

function clampSidebarHeight(value: number, viewportHeight: number): number {
  const max = Math.max(SIDEBAR_HEIGHT_MIN, viewportHeight - SIDEBAR_VIEWPORT_OFFSET);
  return clampValue(value, SIDEBAR_HEIGHT_MIN, max);
}

function defaultSectionUiState(): ConfigSectionUiState {
  return {
    expanded: true,
    editing: false,
    expandedPaths: {},
  };
}

const CONFIG_COPY = {
  zh: {
    pageTitle: "统一配置工作台",
    subtitle: "这里是唯一配置网页入口。结构化编辑、整份草稿校验和最终写回，都收口到同一份 config.toml。",
    loading: "正在加载统一配置工作区...",
    loadFailed: "配置工作区加载失败",
    sourceTitle: "配置源",
    sourceBody: "当前页面直接读取共享 public config 工作流，最终只写回同一个 config.toml。",
    runtimeTitle: "运行时与界面",
    runtimeBody: "语言、默认入口和 intake mode 现在都先走草稿，再统一应用。",
    profilesTitle: "配置档现场",
    profilesBody: "先看每个配置档当前在用什么模型、走哪条路由、密钥状态如何；需要修改时先点编辑，确认后只写入草稿。",
    modelsTitle: "模型库编辑",
    modelsBody: "新增、编辑、删除模型库项会继续复用旧配置页背后的共享变更内核。",
    draftTitle: "JSON 草稿",
    draftBody: "如果结构化面板不够用，可以直接校验整份 JSON 草稿；应用时仍只写 config.toml。",
    diagnosticsTitle: "诊断与应用",
    diagnosticsBody: "阻塞问题、警告和 base hash 冲突保护会在应用前保持可见。",
    configPath: "配置路径",
    rawToml: "当前 config.toml",
    rawTomlHint: "这里只读显示真实配置源，编辑与保存统一走上面的工作区。",
    persistedHash: "已保存快照",
    baseHash: "草稿起点",
    draftHash: "当前草稿",
    syncedDraft: "草稿与已保存配置一致",
    unsavedDraft: "草稿尚未应用",
    refresh: "重新读取",
    validateDraft: "校验草稿",
    resetDraft: "撤回本地文本",
    applyConfig: "应用到 config.toml",
    applying: "应用中",
    interfaceLanguage: "界面语言",
    intakeMode: "引入方式",
    languageChinese: "中文",
    languageEnglish: "English",
    groupOverviewApplyTitle: "总览与应用",
    groupOverviewApplySummary: "配置源、草稿校验与诊断应用统一收口。",
    groupWorkbenchTitle: "工作台与界面",
    groupWorkbenchSummary: "默认入口、语言与运行界面相关设置。",
    groupAvatarPetTitle: "形象与陪伴体",
    groupAvatarPetSummary: "统一管理形象、宠物与陪伴体相关配置。",
    groupModelingTitle: "模型与配置档",
    groupModelingSummary: "模型库、配置档与模型发现放在同一组里。",
    groupAgentEvolutionTitle: "Agent 与进化",
    groupAgentEvolutionSummary: "Agent 运行、自进化与上下文策略相关设置。",
    groupToolingTitle: "工具与诊断",
    groupToolingSummary: "工具、网络、安全、日志、提示词与调试相关设置。",
    runtimeProfile: "运行档位",
    defaultMode: "默认模式",
    defaultRoute: "默认入口",
    modelLibrary: "模型库",
    profiles: "配置档",
    profileAdd: "新增配置档",
    profileId: "配置档 ID",
    sourceProfile: "参考配置档",
    assignModel: "模型",
    createProfile: "加入草稿",
    modelEditorCreate: "新增模型",
    modelEditorEdit: "编辑模型",
    preset: "预设",
    presetGroupOfficial: "官方供应商",
    presetGroupRelay: "中转站 API",
    presetGroupLocal: "本地模型",
    customEntry: "手填",
    modelId: "模型 ID",
    label: "显示名",
    modelName: "模型名",
    providerKind: "服务商类型",
    providerKeyEnv: "服务商密钥环境变量",
    modelKeyEnv: "模型密钥环境变量",
    baseUrl: "基础地址",
    compatMode: "兼容模式",
    contextWindow: "上下文窗口",
    requiresApiKey: "需要 API Key",
    transport: "传输协议",
    contract: "交互契约",
    reasoningStateField: "推理状态字段",
    toolCallingMode: "工具调用",
    strictCompatibility: "严格兼容",
    streaming: "流式",
    discoveryEnabled: "发现能力",
    temperature: "温度",
    maxOutputTokens: "最大输出令牌数",
    timeout: "超时（秒）",
    connectTimeout: "连接超时（秒）",
    pendingSecret: "待写入新密钥",
    clearSecret: "应用时清除此密钥",
    saveModel: "写入草稿",
    deleteModel: "删除模型",
    cancelEditing: "清空表单",
    modelCards: "现有模型",
    profileCards: "现有配置档",
    testConnection: "测试连接",
    selectedModel: "使用模型",
    applySelectedModel: "确认修改",
    testSelectedModel: "测试当前内容",
    profileApplyPending: "保存配置档草稿中",
    profilePrepared: "已准备好新增配置档草稿",
    profilePreparedHint: "可以在这里新增配置档。确认后只会加入草稿，点页面底部应用后才会写入 config.toml。",
    currentRoute: "当前配置",
    stagedRoute: "本次修改预览",
    apiKeySource: "密钥来源",
    editProfile: "编辑",
    cancelProfileEdit: "取消",
    profileDraftSaved: "本次修改已写入草稿，应用后才会落盘。",
    routeSummary: "路由信息",
    expandSection: "展开内容",
    collapseSection: "收起内容",
    keyConfigured: "已配置",
    keyPending: "待写入",
    keyClearPending: "待清除",
    keyMissing: "缺失",
    sourceLibrary: "模型库",
    sourceProfileGenerated: "来自 profile",
    requiredModelMissing: "未设置可用模型",
    noBlocking: "当前没有阻塞问题。",
    noWarnings: "当前没有警告。",
    noSuggestions: "当前没有额外建议动作。",
    blockingIssues: "阻塞问题",
    warningSignals: "警告信号",
    suggestedActions: "建议动作",
    editorDirtyHint: "JSON 文本有未校验改动。先校验草稿，再继续结构化编辑或测试。",
    editorCleanHint: "当前结构化草稿和 JSON 文本一致。",
    saveSourceHint: "应用成功后，这里会刷新为新的已保存快照。",
    modelSavePending: "保存模型草稿中",
    profileSavePending: "保存配置档草稿中",
    testPending: "测试连接中",
    testScopeDraft: "按当前草稿测试",
    testScopeSaved: "按已保存配置测试",
    testRouteLabel: "测试路由",
    testKeyLabel: "API key",
    testKeyNotRequired: "当前路由不要求",
    testKeySourceLabel: "来源",
    validationPending: "校验草稿中",
    refreshPending: "重新读取中",
    editSection: "编辑分区",
    saveSection: "确认分区草稿",
    cancelSection: "取消编辑",
    sectionSavePending: "保存分区草稿中",
    fieldCountLabel: "字段",
    emptyValue: "空",
    itemLabel: "条目",
    yes: "是",
    no: "否",
  },
  en: {
    pageTitle: "Unified Config Workbench",
    subtitle: "This is the single config web entry. Structured editing, full-draft validation, and final writes now converge on one config.toml.",
    loading: "Loading unified config workspace...",
    loadFailed: "Failed to load config workspace",
    sourceTitle: "Config Source",
    sourceBody: "This page reads the shared public-config workflow directly and writes back to the same config.toml only.",
    runtimeTitle: "Runtime and Interface",
    runtimeBody: "Language, default route, and intake mode now move through the draft/apply flow together.",
    profilesTitle: "Profile State",
    profilesBody: "Review the current model, route, and key state for each profile here. Click edit before making changes; confirm only saves to the draft.",
    modelsTitle: "Model Library",
    modelsBody: "Add, edit, and delete model-library entries through the same kernel the old config page used.",
    draftTitle: "JSON Draft",
    draftBody: "When the structured panel is not enough, validate the full JSON draft here while persistence still writes only config.toml.",
    diagnosticsTitle: "Diagnostics and Apply",
    diagnosticsBody: "Blocking issues, warnings, and base-hash protection stay visible before apply.",
    configPath: "Config path",
    rawToml: "Current config.toml",
    rawTomlHint: "This is a read-only view of the real config source. Editing and persistence stay in the workspace above.",
    persistedHash: "Saved snapshot",
    baseHash: "Draft base",
    draftHash: "Current draft",
    syncedDraft: "Draft matches the saved config",
    unsavedDraft: "Draft has unapplied changes",
    refresh: "Reload",
    validateDraft: "Validate draft",
    resetDraft: "Reset local text",
    applyConfig: "Apply to config.toml",
    applying: "Applying",
    interfaceLanguage: "Interface language",
    intakeMode: "Intake mode",
    languageChinese: "Chinese",
    languageEnglish: "English",
    groupOverviewApplyTitle: "Overview and Apply",
    groupOverviewApplySummary: "Keep config source, draft validation, and diagnostics in one place.",
    groupWorkbenchTitle: "Workbench and Interface",
    groupWorkbenchSummary: "Default entry, language, and runtime-facing interface settings.",
    groupAvatarPetTitle: "Avatar and Companion",
    groupAvatarPetSummary: "Manage avatar, pet, and companion-facing settings together.",
    groupModelingTitle: "Models and Profiles",
    groupModelingSummary: "Keep model library, profiles, and model discovery together.",
    groupAgentEvolutionTitle: "Agent and Evolution",
    groupAgentEvolutionSummary: "Agent runtime, self-evolution, and context strategy settings.",
    groupToolingTitle: "Tooling and Diagnostics",
    groupToolingSummary: "Tooling, network, security, logging, prompt, and debug settings.",
    runtimeProfile: "Runtime profile",
    defaultMode: "Default mode",
    defaultRoute: "Default route",
    modelLibrary: "Model library",
    profiles: "Profiles",
    profileAdd: "Add profile",
    profileId: "Profile ID",
    sourceProfile: "Based on profile",
    assignModel: "Model",
    createProfile: "Add to draft",
    modelEditorCreate: "Create model",
    modelEditorEdit: "Edit model",
    preset: "Preset",
    presetGroupOfficial: "Official providers",
    presetGroupRelay: "Relay APIs",
    presetGroupLocal: "Local models",
    customEntry: "Manual",
    modelId: "Model ID",
    label: "Label",
    modelName: "Model",
    providerKind: "Provider kind",
    providerKeyEnv: "Provider API key env",
    modelKeyEnv: "Model API key env",
    baseUrl: "Base URL",
    compatMode: "Compat mode",
    contextWindow: "Context window",
    requiresApiKey: "Requires API key",
    transport: "Transport",
    contract: "Contract",
    reasoningStateField: "Reasoning state field",
    toolCallingMode: "Tool calling",
    strictCompatibility: "Strict compatibility",
    streaming: "Streaming",
    discoveryEnabled: "Discovery enabled",
    temperature: "Temperature",
    maxOutputTokens: "Max output tokens",
    timeout: "Timeout (s)",
    connectTimeout: "Connect timeout (s)",
    pendingSecret: "Pending new secret",
    clearSecret: "Clear this secret on apply",
    saveModel: "Write to draft",
    deleteModel: "Delete model",
    cancelEditing: "Clear form",
    modelCards: "Current models",
    profileCards: "Current profiles",
    testConnection: "Test connection",
    selectedModel: "Model",
    applySelectedModel: "Confirm changes",
    testSelectedModel: "Test current values",
    profileApplyPending: "Saving profile draft",
    profilePrepared: "Profile draft is ready",
    profilePreparedHint: "Add a new profile here. Confirm only saves to the draft until you apply the page.",
    currentRoute: "Current values",
    stagedRoute: "Draft preview",
    apiKeySource: "API key source",
    editProfile: "Edit",
    cancelProfileEdit: "Cancel",
    profileDraftSaved: "Changes were saved to the draft. Apply the page to write config.toml.",
    routeSummary: "Route details",
    expandSection: "Expand",
    collapseSection: "Collapse",
    keyConfigured: "configured",
    keyPending: "pending",
    keyClearPending: "clear pending",
    keyMissing: "missing",
    sourceLibrary: "model library",
    sourceProfileGenerated: "from profile",
    requiredModelMissing: "No usable model selected",
    noBlocking: "No blocking issues right now.",
    noWarnings: "No warnings right now.",
    noSuggestions: "No extra suggested actions right now.",
    blockingIssues: "Blocking issues",
    warningSignals: "Warnings",
    suggestedActions: "Suggested actions",
    editorDirtyHint: "The JSON editor has unvalidated changes. Validate it before more structured edits or tests.",
    editorCleanHint: "Structured draft and JSON editor are in sync.",
    saveSourceHint: "After apply succeeds, the saved snapshot here will refresh.",
    modelSavePending: "Saving model draft",
    profileSavePending: "Saving profile draft",
    testPending: "Testing connection",
    testScopeDraft: "Testing current draft",
    testScopeSaved: "Testing saved config",
    testRouteLabel: "Route",
    testKeyLabel: "API key",
    testKeyNotRequired: "not required for this route",
    testKeySourceLabel: "source",
    validationPending: "Validating draft",
    refreshPending: "Reloading",
    editSection: "Edit section",
    saveSection: "Save section draft",
    cancelSection: "Cancel editing",
    sectionSavePending: "Saving section draft",
    fieldCountLabel: "fields",
    emptyValue: "Empty",
    itemLabel: "Item",
    yes: "Yes",
    no: "No",
  },
} as const;

type ConfigCopy = Record<keyof (typeof CONFIG_COPY)["zh"], string>;

function emptyDraftMeta(): ConfigDraftMeta {
  return {
    pending_api_keys: {},
    pending_cleared_api_keys: [],
  };
}

function emptyProviderDraft(): ProviderDraft {
  return {
    kind: "",
    api_key_env: "",
    base_url: "",
    compat_mode: "openai",
    requires_api_key: true,
    context_window: "",
  };
}

function emptyModelDetailsDraft(): ModelDetailsDraft {
  return {
    transport: "chat_completions",
    contract: "tool_chat",
    reasoning_state_field: "",
    strict_compatibility: false,
    temperature: "",
    max_output_tokens: "",
    timeout: "",
    connect_timeout: "",
    streaming: true,
    tool_calling_mode: "auto",
    discovery_enabled: true,
  };
}

function emptyModelEditorState(): ModelEditorState {
  return {
    mode: "create",
    preset_id: "",
    model_id: "",
    label: "",
    model: "",
    api_key_env: "",
    api_key: "",
    clear_api_key: false,
    provider: emptyProviderDraft(),
    details: emptyModelDetailsDraft(),
  };
}

function buildConfigSidebarGroups(copy: ConfigCopy): ConfigSidebarGroup[] {
  return [
    {
      id: "overview-apply",
      title: copy.groupOverviewApplyTitle,
      summary: copy.groupOverviewApplySummary,
      memberSectionIds: ["overview", "draft", "diagnostics"],
    },
    {
      id: "workbench-interface",
      title: copy.groupWorkbenchTitle,
      summary: copy.groupWorkbenchSummary,
      memberSectionIds: ["shell", "runtime", "ui"],
    },
    {
      id: "avatar-pet",
      title: copy.groupAvatarPetTitle,
      summary: copy.groupAvatarPetSummary,
      memberSectionIds: ["avatar", "pet"],
    },
    {
      id: "models-profiles",
      title: copy.groupModelingTitle,
      summary: copy.groupModelingSummary,
      memberSectionIds: ["profiles", "models", "llm-profiles", "llm-discovery"],
    },
    {
      id: "agent-evolution",
      title: copy.groupAgentEvolutionTitle,
      summary: copy.groupAgentEvolutionSummary,
      memberSectionIds: ["agent", "context-compression", "memory", "strategy", "analysis", "evolution"],
    },
    {
      id: "tooling-diagnostics",
      title: copy.groupToolingTitle,
      summary: copy.groupToolingSummary,
      memberSectionIds: ["tools", "security", "network", "log", "prompt", "parser", "debug"],
    },
  ];
}

function emptyProfileDraft(sourceProfileId = "primary"): ProfileDraft {
  return {
    profile_id: "",
    source_profile_id: sourceProfileId,
    model_id: "",
  };
}

function emptyProfileEditState(modelId = ""): ProfileEditState {
  return {
    modelId,
  };
}

function formatJson(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

function getBoolean(value: unknown, fallback = false): boolean {
  return typeof value === "boolean" ? value : fallback;
}

function getDraftLanguage(config: PublicConfigShape | null, fallback: ConfigLanguage): ConfigLanguage {
  const ui = asRecord(config?.ui);
  return ui.language === "en" ? "en" : fallback;
}

function buildProviderDraft(providerInput: Record<string, unknown>): ProviderDraft {
  return {
    kind: getString(providerInput.kind),
    api_key_env: getString(providerInput.api_key_env),
    base_url: getString(providerInput.base_url),
    compat_mode: getString(providerInput.compat_mode) || "openai",
    requires_api_key: getBoolean(providerInput.requires_api_key, true),
    context_window: getString(providerInput.context_window),
  };
}

function buildModelDetailsDraft(detailsInput: Record<string, unknown>): ModelDetailsDraft {
  return {
    transport: getString(detailsInput.transport) || "chat_completions",
    contract: getString(detailsInput.contract) || "tool_chat",
    reasoning_state_field: getString(detailsInput.reasoning_state_field),
    strict_compatibility: getBoolean(detailsInput.strict_compatibility, false),
    temperature: getString(detailsInput.temperature),
    max_output_tokens: getString(detailsInput.max_output_tokens),
    timeout: getString(detailsInput.timeout),
    connect_timeout: getString(detailsInput.connect_timeout),
    streaming: getBoolean(detailsInput.streaming, true),
    tool_calling_mode: getString(detailsInput.tool_calling_mode) || "auto",
    discovery_enabled: getBoolean(detailsInput.discovery_enabled, true),
  };
}

function hydrateModelEditorFromOption(option: ConfigModelOption): ModelEditorState {
  return {
    mode: "edit",
    preset_id: "",
    model_id: option.model_id,
    label: option.label,
    model: option.model,
    api_key_env: option.api_key_env,
    api_key: "",
    clear_api_key: false,
    provider: buildProviderDraft(asRecord(option.provider)),
    details: buildModelDetailsDraft(asRecord(option.details)),
  };
}

function buildProviderPayload(draft: ProviderDraft): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    kind: draft.kind.trim(),
    api_key_env: draft.api_key_env.trim(),
    base_url: draft.base_url.trim(),
    compat_mode: draft.compat_mode.trim(),
    requires_api_key: draft.requires_api_key,
  };
  if (draft.context_window.trim()) {
    payload.context_window = Number(draft.context_window.trim());
  }
  return payload;
}

function buildModelDetailsPayload(draft: ModelDetailsDraft): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    strict_compatibility: draft.strict_compatibility,
    streaming: draft.streaming,
    discovery_enabled: draft.discovery_enabled,
  };
  if (draft.transport.trim()) {
    payload.transport = draft.transport.trim();
  }
  if (draft.contract.trim()) {
    payload.contract = draft.contract.trim();
  }
  if (draft.reasoning_state_field.trim()) {
    payload.reasoning_state_field = draft.reasoning_state_field.trim();
  }
  if (draft.tool_calling_mode.trim()) {
    payload.tool_calling_mode = draft.tool_calling_mode.trim();
  }
  if (draft.temperature.trim()) {
    payload.temperature = Number(draft.temperature.trim());
  }
  if (draft.max_output_tokens.trim()) {
    payload.max_output_tokens = Number(draft.max_output_tokens.trim());
  }
  if (draft.timeout.trim()) {
    payload.timeout = Number(draft.timeout.trim());
  }
  if (draft.connect_timeout.trim()) {
    payload.connect_timeout = Number(draft.connect_timeout.trim());
  }
  return payload;
}

function splitConfigPath(path: string): string[] {
  return path.split(".").filter(Boolean);
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function getConfigValueAtPath(root: unknown, path: string): unknown {
  let current = root;
  for (const token of splitConfigPath(path)) {
    if (Array.isArray(current)) {
      current = current[Number(token)];
      continue;
    }
    if (isPlainObject(current)) {
      current = current[token];
      continue;
    }
    return undefined;
  }
  return current;
}

function setConfigValueAtPath<T>(root: T, path: string, nextValue: unknown): T {
  if (!path) {
    return nextValue as T;
  }
  const cloned = clonePublicConfig(root);
  const tokens = splitConfigPath(path);
  let current: unknown = cloned;
  for (let index = 0; index < tokens.length - 1; index += 1) {
    const token = tokens[index];
    if (Array.isArray(current)) {
      current = current[Number(token)];
      continue;
    }
    if (isPlainObject(current)) {
      current = current[token];
      continue;
    }
    throw new Error(`Unknown config path: ${path}`);
  }
  const leaf = tokens[tokens.length - 1];
  if (Array.isArray(current)) {
    current[Number(leaf)] = nextValue;
  } else if (isPlainObject(current)) {
    current[leaf] = nextValue;
  }
  return cloned;
}

function humanizeConfigToken(token: string): string {
  return token
    .split("_")
    .filter(Boolean)
    .map((part) => (part.toUpperCase() === part ? part : `${part.charAt(0).toUpperCase()}${part.slice(1)}`))
    .join(" ");
}

function configLabel(metaMap: Record<string, ConfigEditorMeta>, path: string): string {
  return metaMap[path]?.label ?? humanizeConfigToken(splitConfigPath(path).at(-1) ?? path);
}

function configHint(metaMap: Record<string, ConfigEditorMeta>, path: string): string {
  return metaMap[path]?.hint ?? "";
}

function formatConfigDisplayValue(value: unknown, kind: ConfigEditorMeta["kind"] | undefined, copy: ConfigCopy): string {
  if (kind === "secret") {
    return getString(value) ? "******" : copy.emptyValue;
  }
  if (typeof value === "boolean") {
    return value ? copy.yes : copy.no;
  }
  if (Array.isArray(value)) {
    if (value.length === 0) {
      return copy.emptyValue;
    }
    return value
      .map((item) => (typeof item === "string" ? item : JSON.stringify(item)))
      .join(", ");
  }
  if (value == null || value === "") {
    return copy.emptyValue;
  }
  return String(value);
}

type ConfigSectionEditorProps = {
  section: ConfigEditorSection;
  value: unknown;
  metaMap: Record<string, ConfigEditorMeta>;
  copy: ConfigCopy;
  disabled: boolean;
  active: boolean;
  uiState: ConfigSectionUiState;
  onUiStateChange: (sectionId: string, nextState: ConfigSectionUiState) => void;
  onSaveSection: (path: string, nextValue: unknown) => Promise<boolean>;
};

function ConfigSectionEditor({
  section,
  value,
  metaMap,
  copy,
  disabled,
  active,
  uiState,
  onUiStateChange,
  onSaveSection,
}: ConfigSectionEditorProps) {
  const sectionExpanded = uiState.expanded;
  const editing = uiState.editing;
  const expandedPaths = uiState.expandedPaths;
  const draftValue = editing ? clonePublicConfig(uiState.draftValue ?? value) : clonePublicConfig(value);

  useEffect(() => {
    if (active && !sectionExpanded) {
      onUiStateChange(section.id, { ...uiState, expanded: true });
    }
  }, [active, onUiStateChange, section.id, sectionExpanded, uiState]);

  function updateSectionDraft(absolutePath: string, nextValue: unknown) {
    const prefix = `${section.path}.`;
    const relativePath = absolutePath === section.path ? "" : absolutePath.startsWith(prefix) ? absolutePath.slice(prefix.length) : absolutePath;
    const currentDraft = editing ? draftValue : clonePublicConfig(value);
    onUiStateChange(section.id, {
      ...uiState,
      editing: true,
      expanded: true,
      draftValue: setConfigValueAtPath(currentDraft, relativePath, nextValue),
    });
  }

  function toggleObjectPath(path: string) {
    onUiStateChange(section.id, {
      ...uiState,
      expandedPaths: { ...expandedPaths, [path]: !expandedPaths[path] },
    });
  }

  async function handleSave() {
    const ok = await onSaveSection(section.path, draftValue);
    if (ok) {
      onUiStateChange(section.id, {
        ...uiState,
        editing: false,
        draftValue: undefined,
      });
    }
  }

  function renderFieldView(fieldValue: unknown, absolutePath: string) {
    const meta = metaMap[absolutePath];
    return (
      <article key={absolutePath} className={styles.treeFieldCard}>
        <div className={styles.treeFieldHead}>
          <span className={styles.treeFieldLabel}>{configLabel(metaMap, absolutePath)}</span>
          {meta?.badge ? <span className={styles.inlineBadge}>{meta.badge}</span> : null}
        </div>
        {configHint(metaMap, absolutePath) ? <p className={styles.treeHint}>{configHint(metaMap, absolutePath)}</p> : null}
        <div className={styles.treeFieldValue}>{formatConfigDisplayValue(fieldValue, meta?.kind, copy)}</div>
      </article>
    );
  }

  function renderFieldEditor(fieldValue: unknown, absolutePath: string) {
    const meta = metaMap[absolutePath];
    const kind = meta?.kind ?? "text";
    let control;

    if (kind === "boolean") {
      control = (
        <label className={styles.toggleField}>
          <input
            type="checkbox"
            checked={Boolean(fieldValue)}
            onChange={(event) => updateSectionDraft(absolutePath, event.target.checked)}
          />
          <span>{configLabel(metaMap, absolutePath)}</span>
        </label>
      );
    } else if (kind === "select") {
      control = (
        <label className={styles.field}>
          <span>{configLabel(metaMap, absolutePath)}</span>
          <select value={getString(fieldValue)} onChange={(event) => updateSectionDraft(absolutePath, event.target.value)}>
            {(meta?.options ?? []).map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      );
    } else if (kind === "number") {
      control = (
        <label className={styles.field}>
          <span>{configLabel(metaMap, absolutePath)}</span>
          <input
            type="number"
            step="any"
            value={getString(fieldValue)}
            onChange={(event) => {
              const raw = event.target.value;
              updateSectionDraft(absolutePath, raw === "" ? "" : Number(raw));
            }}
          />
        </label>
      );
    } else if (kind === "string_list") {
      control = (
        <label className={styles.field}>
          <span>{configLabel(metaMap, absolutePath)}</span>
          <textarea
            rows={Math.max(4, Array.isArray(fieldValue) ? fieldValue.length + 1 : 4)}
            value={Array.isArray(fieldValue) ? fieldValue.join("\n") : getString(fieldValue)}
            onChange={(event) =>
              updateSectionDraft(
                absolutePath,
                event.target.value
                  .split(/\r?\n/)
                  .map((line) => line.trim())
                  .filter(Boolean),
              )
            }
          />
        </label>
      );
    } else if (kind === "json") {
      control = (
        <label className={styles.field}>
          <span>{configLabel(metaMap, absolutePath)}</span>
          <textarea
            rows={6}
            value={typeof fieldValue === "string" ? fieldValue : formatJson(fieldValue)}
            onChange={(event) => {
              const raw = event.target.value;
              try {
                updateSectionDraft(absolutePath, JSON.parse(raw));
              } catch {
                updateSectionDraft(absolutePath, raw);
              }
            }}
          />
        </label>
      );
    } else {
      control = (
        <label className={styles.field}>
          <span>{configLabel(metaMap, absolutePath)}</span>
          <input
            type={kind === "secret" ? "password" : "text"}
            value={getString(fieldValue)}
            onChange={(event) => updateSectionDraft(absolutePath, event.target.value)}
          />
        </label>
      );
    }

    return (
      <article key={absolutePath} className={styles.treeFieldCard}>
        {configHint(metaMap, absolutePath) ? <p className={styles.treeHint}>{configHint(metaMap, absolutePath)}</p> : null}
        {control}
      </article>
    );
  }

  function renderNestedBlock(absolutePath: string, count: number, children: ReactNode, titleOverride?: string) {
    const expanded = Boolean(expandedPaths[absolutePath]);
    return (
      <div className={styles.treeObjectBlock}>
        <button
          type="button"
          className={styles.treeToggle}
          aria-expanded={expanded}
          onClick={() => toggleObjectPath(absolutePath)}
        >
          <div className={styles.treeToggleLabel}>
            <ChevronRight size={14} className={expanded ? styles.treeToggleIconExpanded : styles.treeToggleIcon} />
            <div>
              <p className={styles.cardTitle}>{titleOverride ?? configLabel(metaMap, absolutePath)}</p>
              {configHint(metaMap, absolutePath) ? <p className={styles.treeHint}>{configHint(metaMap, absolutePath)}</p> : null}
            </div>
          </div>
          <span className={styles.inlineBadge}>{count}</span>
        </button>
        {expanded ? <div className={styles.treeBody}>{children}</div> : null}
      </div>
    );
  }

  function renderObjectBody(nodeValue: Record<string, unknown>, absolutePath: string, mode: "view" | "edit") {
    const entries = Object.entries(nodeValue);
    if (!entries.length) {
      return <p className={styles.helperText}>{copy.emptyValue}</p>;
    }
    return (
      <div className={styles.treeGrid}>
        {entries.map(([key, childValue]) => {
          const childPath = `${absolutePath}.${key}`;
          const childMetaKind = metaMap[childPath]?.kind;
          const childIsObjectList =
            Array.isArray(childValue) &&
            (childMetaKind === "object_list" || childValue.every((item) => isPlainObject(item)));
          const childIsObject = isPlainObject(childValue);
          if (childIsObject || childIsObjectList) {
            return (
              <div key={childPath} className={styles.treeWide}>
                {renderNode(childValue, childPath, mode)}
              </div>
            );
          }
          return mode === "edit" ? renderFieldEditor(childValue, childPath) : renderFieldView(childValue, childPath);
        })}
      </div>
    );
  }

  function renderNode(nodeValue: unknown, absolutePath: string, mode: "view" | "edit", itemIndex?: number) {
    const isRoot = absolutePath === section.path;
    if (Array.isArray(nodeValue) && nodeValue.every((item) => isPlainObject(item))) {
      if (isRoot) {
        return nodeValue.length ? (
          <div className={styles.treeStack}>
            {nodeValue.map((item, index) => (
              <div key={`${absolutePath}.${index}`} className={styles.treeNestedBlock}>
                <div className={styles.treeNestedHeader}>
                  <strong>{`${copy.itemLabel} ${index + 1}`}</strong>
                </div>
                {renderObjectBody(item as Record<string, unknown>, `${absolutePath}.${index}`, mode)}
              </div>
            ))}
          </div>
        ) : (
          <p className={styles.helperText}>{copy.emptyValue}</p>
        );
      }

      return renderNestedBlock(
        absolutePath,
        nodeValue.length,
        nodeValue.length ? (
          <div className={styles.treeStack}>
            {nodeValue.map((item, index) => (
              <div key={`${absolutePath}.${index}`} className={styles.treeNestedBlock}>
                <div className={styles.treeNestedHeader}>
                  <strong>{`${copy.itemLabel} ${index + 1}`}</strong>
                </div>
                {renderObjectBody(item as Record<string, unknown>, `${absolutePath}.${index}`, mode)}
              </div>
            ))}
          </div>
        ) : (
          <p className={styles.helperText}>{copy.emptyValue}</p>
        ),
      );
    }

    if (isPlainObject(nodeValue)) {
      if (isRoot) {
        return renderObjectBody(nodeValue, absolutePath, mode);
      }
      const label = itemIndex == null ? configLabel(metaMap, absolutePath) : `${copy.itemLabel} ${itemIndex + 1}`;
      return (
        <>{renderNestedBlock(absolutePath, Object.keys(nodeValue).length, renderObjectBody(nodeValue, absolutePath, mode), label)}</>
      );
    }

    return mode === "edit" ? renderFieldEditor(nodeValue, absolutePath) : renderFieldView(nodeValue, absolutePath);
  }

  return (
    <section id={`config-${section.id}`} className={styles.sectionSurface}>
      <div className={styles.sectionHeader}>
        <div className={styles.sectionHeaderMain}>
          <p className={styles.eyebrow}>{section.path}</p>
          <h2 className={styles.sectionTitle}>{section.title}</h2>
          <p className={styles.sectionText}>{section.summary}</p>
        </div>
        <div className={styles.sectionHeaderActions}>
          <div className={styles.sectionHeaderMeta}>
            <span className={styles.sectionHeaderMetaLabel}>{copy.fieldCountLabel}</span>
            <span className={styles.inlineBadge}>{section.fieldCount}</span>
          </div>
          <div className={styles.sectionToolbarGroup}>
            <button
              type="button"
              className={`${styles.actionButton} ${styles.compactButton} ${styles.toolbarButton}`}
              aria-expanded={sectionExpanded}
              onClick={() => onUiStateChange(section.id, { ...uiState, expanded: !sectionExpanded })}
            >
              <ChevronRight size={14} className={sectionExpanded ? styles.treeToggleIconExpanded : styles.treeToggleIcon} />
              {sectionExpanded ? copy.collapseSection : copy.expandSection}
            </button>
          {editing ? (
            <>
              <button
                type="button"
                className={`${styles.primaryButton} ${styles.compactButton} ${styles.toolbarButton}`}
                disabled={disabled}
                onClick={handleSave}
              >
                <Save size={14} />
                {copy.saveSection}
              </button>
              <button
                type="button"
                className={`${styles.actionButton} ${styles.compactButton} ${styles.toolbarButton}`}
                disabled={disabled}
                onClick={() => {
                  onUiStateChange(section.id, {
                    ...uiState,
                    expanded: true,
                    editing: false,
                    draftValue: undefined,
                  });
                }}
              >
                <RotateCcw size={14} />
                {copy.cancelSection}
              </button>
            </>
          ) : (
            <button
              type="button"
              className={`${styles.actionButton} ${styles.compactButton} ${styles.toolbarButton}`}
              disabled={disabled}
              onClick={() => {
                onUiStateChange(section.id, {
                  ...uiState,
                  expanded: true,
                  editing: true,
                  draftValue: clonePublicConfig(value),
                });
              }}
            >
              <Pencil size={14} />
              {copy.editSection}
            </button>
          )}
          </div>
        </div>
      </div>
      {sectionExpanded ? renderNode(editing ? draftValue : value, section.path, editing ? "edit" : "view") : null}
    </section>
  );
}

async function requestJson<T>(url: string, body?: unknown, method = "POST"): Promise<T> {
  return fetchJson<T>(url, {
    method,
    headers: {
      "Content-Type": "application/json",
    },
    body: body == null ? undefined : JSON.stringify(body),
  });
}

export function ConfigRoute() {
  const queryClient = useQueryClient();
  const pageRef = useRef<HTMLDivElement | null>(null);
  const profileFormRef = useRef<HTMLDivElement | null>(null);
  const sidebarResizeCleanupRef = useRef<(() => void) | null>(null);
  const workspaceQuery = useQuery({
    queryKey: queryKeys.configWorkspace(),
    queryFn: () => fetchJson<ConfigWorkspace>("/api/config/workspace"),
  });

  const [draftConfig, setDraftConfig] = useState<PublicConfigShape | null>(null);
  const [draftMeta, setDraftMeta] = useState<ConfigDraftMeta>(emptyDraftMeta());
  const [baseHash, setBaseHash] = useState("");
  const [draftHash, setDraftHash] = useState("");
  const [jsonText, setJsonText] = useState("{}");
  const [notice, setNotice] = useState<{ tone: NoticeTone; text: string }>({ tone: "neutral", text: "" });
  const [busyAction, setBusyAction] = useState("");
  const [modelEditor, setModelEditor] = useState<ModelEditorState>(emptyModelEditorState());
  const [profileDraft, setProfileDraft] = useState<ProfileDraft>(emptyProfileDraft());
  const [profileEditors, setProfileEditors] = useState<Record<string, ProfileEditState>>({});
  const [expandedProfiles, setExpandedProfiles] = useState<Record<string, boolean>>({});
  const [expandedModels, setExpandedModels] = useState<Record<string, boolean>>({});
  const [profileFormExpanded, setProfileFormExpanded] = useState(false);
  const [modelEditorExpanded, setModelEditorExpanded] = useState(false);
  const [sidebarIndexCollapsed, setSidebarIndexCollapsed] = useState(() => readStoredFlag(SIDEBAR_INDEX_COLLAPSED_STORAGE_KEY) ?? false);
  const [activeSectionId, setActiveSectionId] = useState("");
  const [sectionUiState, setSectionUiState] = useState<Record<string, ConfigSectionUiState>>({});
  const [sidebarWidth, setSidebarWidth] = useState(() => {
    const viewportWidth = typeof window === "undefined" ? 1440 : window.innerWidth;
    return clampSidebarWidth(readStoredNumber(SIDEBAR_WIDTH_STORAGE_KEY) ?? SIDEBAR_WIDTH_DEFAULT, viewportWidth);
  });
  const [sidebarHeight, setSidebarHeight] = useState(() => {
    const viewportHeight = typeof window === "undefined" ? 960 : window.innerHeight;
    return clampSidebarHeight(
      readStoredNumber(SIDEBAR_HEIGHT_STORAGE_KEY) ?? viewportHeight - SIDEBAR_VIEWPORT_OFFSET,
      viewportHeight,
    );
  });

  function syncWorkspace(workspace: ConfigWorkspace, tone: NoticeTone = "neutral") {
    setDraftConfig(clonePublicConfig(workspace.publicConfig));
    setDraftMeta(clonePublicConfig(workspace.draftMeta));
    setBaseHash(workspace.baseHash);
    setDraftHash(workspace.hash);
    setJsonText(formatJson(workspace.publicConfig));
    setNotice({ tone, text: workspace.message || "" });
    setModelEditor(emptyModelEditorState());
    setProfileDraft(emptyProfileDraft(workspace.profileCards[0]?.profileId ?? "primary"));
    setProfileEditors({});
  }

  useEffect(() => {
    if (workspaceQuery.data) {
      syncWorkspace(workspaceQuery.data);
    }
  }, [workspaceQuery.data]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return undefined;
    }

    function handleWindowResize() {
      setSidebarWidth((current) => clampSidebarWidth(current, window.innerWidth));
      setSidebarHeight((current) => clampSidebarHeight(current, window.innerHeight));
    }

    window.addEventListener("resize", handleWindowResize);
    return () => {
      window.removeEventListener("resize", handleWindowResize);
    };
  }, []);

  useEffect(() => {
    if (typeof window !== "undefined") {
      window.localStorage.setItem(SIDEBAR_INDEX_COLLAPSED_STORAGE_KEY, sidebarIndexCollapsed ? "1" : "0");
    }
  }, [sidebarIndexCollapsed]);

  useEffect(() => {
    if (typeof window !== "undefined") {
      window.localStorage.setItem(SIDEBAR_WIDTH_STORAGE_KEY, String(sidebarWidth));
    }
  }, [sidebarWidth]);

  useEffect(() => {
    if (typeof window !== "undefined") {
      window.localStorage.setItem(SIDEBAR_HEIGHT_STORAGE_KEY, String(sidebarHeight));
    }
  }, [sidebarHeight]);

  useEffect(() => {
    return () => {
      sidebarResizeCleanupRef.current?.();
    };
  }, []);

  const workspace = workspaceQuery.data;
  const currentLanguage = getDraftLanguage(draftConfig, workspace?.language === "en" ? "en" : "zh");
  const copy = CONFIG_COPY[currentLanguage];
  const sectionIndexTitle = currentLanguage === "en" ? "Section index" : "分区索引";
  const sectionIndexHint = currentLanguage === "en" ? "Jump directly to a config area" : "直接跳到具体配置区";
  const sectionIndexCollapsedHint = currentLanguage === "en" ? "Index hidden for focused editing" : "目录已收起，专注右侧编辑区";
  const sectionIndexToggleLabel = currentLanguage === "en" ? (sidebarIndexCollapsed ? "Expand index" : "Collapse index") : (sidebarIndexCollapsed ? "展开索引" : "收起索引");
  const resizeWidthTitle = currentLanguage === "en" ? "Drag to resize sidebar width" : "左右拖动调整侧栏宽度";
  const resizeHeightTitle = currentLanguage === "en" ? "Drag to resize sidebar height" : "上下拖动调整侧栏高度";
  const resizeCornerTitle = currentLanguage === "en" ? "Drag to resize sidebar" : "拖动调整侧栏尺寸";
  const formattedDraft = useMemo(() => formatJson(draftConfig ?? {}), [draftConfig]);
  const hasEditorChanges = jsonText !== formattedDraft;
  const hasUnsavedDraft = Boolean(baseHash && draftHash && baseHash !== draftHash);
  const hasPendingApply = hasUnsavedDraft || hasEditorChanges;
  const structuredActionsDisabled = !draftConfig || hasEditorChanges || Boolean(busyAction);
  const sidebarSections = workspace?.sections ?? [];
  const editorSections = workspace?.editorSections ?? [];
  const editorMeta = workspace?.editorMeta ?? {};
  const sidebarGroups = useMemo(() => buildConfigSidebarGroups(copy), [copy]);
  const availableSectionIds = useMemo(() => new Set(sidebarSections.map((section) => section.id)), [sidebarSections]);
  const visibleSidebarGroups = useMemo(
    () =>
      sidebarGroups
        .map((group) => ({
          ...group,
          memberSectionIds: group.memberSectionIds.filter((sectionId) => availableSectionIds.has(sectionId)),
        }))
        .filter((group) => group.memberSectionIds.length),
    [availableSectionIds, sidebarGroups],
  );
  const activeSection = visibleSidebarGroups.find((section) => section.id === activeSectionId) ?? visibleSidebarGroups[0] ?? null;
  const activeEditorSections = editorSections.filter((section) => activeSection?.memberSectionIds.includes(section.id));
  const modelOptions = workspace?.modelOptions ?? [];
  const modelOptionsById = useMemo(() => new Map(modelOptions.map((option) => [option.model_id, option])), [modelOptions]);
  const modelDetailKeys = useMemo(() => collectModelDetailKeys(modelOptions), [modelOptions]);
  const modelPresetGroups = useMemo(
    () => {
      const labels: ModelPresetGroupLabels = {
        official: copy.presetGroupOfficial,
        relay: copy.presetGroupRelay,
        local: copy.presetGroupLocal,
      };
      return groupModelPresets(workspace?.modelPresetOptions ?? [], labels);
    },
    [copy, workspace?.modelPresetOptions],
  );

  useEffect(() => {
    if (!visibleSidebarGroups.length) {
      setActiveSectionId("");
      return;
    }
    if (!visibleSidebarGroups.some((section) => section.id === activeSectionId)) {
      setActiveSectionId(visibleSidebarGroups[0].id);
    }
  }, [activeSectionId, visibleSidebarGroups]);

  const sectionMap = useMemo(() => {
    return new Map((workspace?.sections ?? []).map((section) => [section.id, section]));
  }, [workspace?.sections]);
  const pageStyle = useMemo(
    () =>
      ({
        "--sidebar-width": `${sidebarWidth}px`,
      }) as CSSProperties,
    [sidebarWidth],
  );
  const sidebarStyle = useMemo(
    () =>
      ({
        height: `${sidebarHeight}px`,
      }) as CSSProperties,
    [sidebarHeight],
  );
  const applyButtonLabel = busyAction === copy.applying ? copy.applying : copy.applyConfig;

  function updateSectionUiState(sectionId: string, nextState: ConfigSectionUiState) {
    setSectionUiState((current) => ({ ...current, [sectionId]: nextState }));
  }

  function isActiveGroup(sectionId: string): boolean {
    return activeSection?.id === sectionId;
  }

  function isSectionVisible(sectionId: string): boolean {
    return Boolean(activeSection?.memberSectionIds.includes(sectionId));
  }

  function handleSelectSection(sectionId: string) {
    setActiveSectionId(sectionId);
    updateSectionUiState(sectionId, sectionUiState[sectionId] ?? defaultSectionUiState());
    pageRef.current?.scrollTo({ top: 0, behavior: "smooth" });
  }
  const sidebarApplyHint = hasEditorChanges ? copy.editorDirtyHint : hasPendingApply ? copy.saveSourceHint : copy.editorCleanHint;

  async function invalidateWorkbenchQueries() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.configPublic() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.configWorkspace() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.runtimeSummary() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.evolutionOverview() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.evolutionRuns() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.evolutionLibrary() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.evolutionSelfOverview() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.evolutionSelfActiveRun() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.evolutionSelfTransactions() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.evolutionSelfAudit() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.sessions() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.petSummary() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.resetSummary() }),
    ]);
  }

  function markError(error: unknown) {
    setNotice({
      tone: "error",
      text: error instanceof Error ? error.message : String(error),
    });
  }

  function requireDraft(): PublicConfigShape {
    if (!draftConfig) {
      throw new Error(copy.loadFailed);
    }
    return draftConfig;
  }

  function resolveDraftForSubmission(): PublicConfigShape {
    if (!draftConfig) {
      throw new Error(copy.loadFailed);
    }
    if (!hasEditorChanges) {
      return draftConfig;
    }
    return JSON.parse(jsonText) as PublicConfigShape;
  }

  async function previewDraft(nextConfig: PublicConfigShape, nextMeta: ConfigDraftMeta, pendingLabel: string) {
    setBusyAction(pendingLabel);
    try {
      const response = await requestJson<ConfigWorkspace>("/api/config/draft/preview", {
        publicConfig: nextConfig,
        draftMeta: nextMeta,
        baseHash,
      });
      syncWorkspace(response, "success");
      return true;
    } catch (error) {
      markError(error);
      return false;
    } finally {
      setBusyAction("");
    }
  }

  async function reloadWorkspace() {
    setBusyAction(copy.refreshPending);
    try {
      const fresh = await workspaceQuery.refetch();
      if (fresh.data) {
        syncWorkspace(fresh.data);
      }
    } catch (error) {
      markError(error);
    } finally {
      setBusyAction("");
    }
  }

  async function handleApply() {
    setBusyAction(copy.applying);
    try {
      const response = await requestJson<ConfigWorkspace>(
        "/api/config/apply",
        {
          publicConfig: resolveDraftForSubmission(),
          draftMeta,
          baseHash,
        },
        "PUT",
      );
      syncWorkspace(response, "success");
      await invalidateWorkbenchQueries();
    } catch (error) {
      markError(error);
    } finally {
      setBusyAction("");
    }
  }

  async function handleValidateEditorDraft() {
    try {
      const parsed = JSON.parse(jsonText) as PublicConfigShape;
      await previewDraft(parsed, draftMeta, copy.validationPending);
    } catch (error) {
      markError(error);
    }
  }

  async function updateSimpleDraft(mutator: (nextConfig: PublicConfigShape) => void) {
    try {
      const next = clonePublicConfig(requireDraft());
      mutator(next);
      await previewDraft(next, draftMeta, copy.validationPending);
    } catch (error) {
      markError(error);
    }
  }

  async function saveConfigSection(path: string, nextValue: unknown) {
    try {
      const next = clonePublicConfig(requireDraft());
      const updated = setConfigValueAtPath(next, path, nextValue);
      return await previewDraft(updated, draftMeta, copy.sectionSavePending);
    } catch (error) {
      markError(error);
      return false;
    }
  }

  function resolveSelectedProfileModelId(profileId: string, fallback = ""): string {
    return profileEditors[profileId]?.modelId ?? fallback;
  }

  function toggleExpandedProfile(profileId: string) {
    setExpandedProfiles((current) => ({ ...current, [profileId]: !current[profileId] }));
  }

  function beginProfileEdit(profileId: string, fallbackModelId = "") {
    setExpandedProfiles((current) => ({ ...current, [profileId]: true }));
    setProfileEditors((current) => ({
      ...current,
      [profileId]: emptyProfileEditState(fallbackModelId),
    }));
  }

  function cancelProfileEdit(profileId: string) {
    setProfileEditors((current) => {
      const next = { ...current };
      delete next[profileId];
      return next;
    });
  }

  function updateProfileModelDraft(profileId: string, modelId: string) {
    setProfileEditors((current) => ({
      ...current,
      [profileId]: emptyProfileEditState(modelId),
    }));
  }

  function toggleExpandedModel(modelId: string) {
    setExpandedModels((current) => ({ ...current, [modelId]: !current[modelId] }));
  }

  function resetSidebarWidth() {
    if (typeof window === "undefined") {
      setSidebarWidth(SIDEBAR_WIDTH_DEFAULT);
      return;
    }
    setSidebarWidth(clampSidebarWidth(SIDEBAR_WIDTH_DEFAULT, window.innerWidth));
  }

  function resetSidebarHeight() {
    if (typeof window === "undefined") {
      setSidebarHeight(SIDEBAR_HEIGHT_MIN);
      return;
    }
    setSidebarHeight(clampSidebarHeight(window.innerHeight - SIDEBAR_VIEWPORT_OFFSET, window.innerHeight));
  }

  function beginSidebarResize(axis: "width" | "height" | "both") {
    return (event: ReactPointerEvent<HTMLDivElement>) => {
      if (typeof window === "undefined") {
        return;
      }
      event.preventDefault();
      sidebarResizeCleanupRef.current?.();

      const startX = event.clientX;
      const startY = event.clientY;
      const initialWidth = sidebarWidth;
      const initialHeight = sidebarHeight;
      const cursor = axis === "width" ? "col-resize" : axis === "height" ? "row-resize" : "nwse-resize";

      const handlePointerMove = (moveEvent: PointerEvent) => {
        if (axis !== "height") {
          setSidebarWidth(clampSidebarWidth(initialWidth + (moveEvent.clientX - startX), window.innerWidth));
        }
        if (axis !== "width") {
          setSidebarHeight(clampSidebarHeight(initialHeight + (moveEvent.clientY - startY), window.innerHeight));
        }
      };

      const cleanup = () => {
        window.removeEventListener("pointermove", handlePointerMove);
        window.removeEventListener("pointerup", cleanup);
        window.removeEventListener("pointercancel", cleanup);
        document.body.style.userSelect = "";
        document.body.style.cursor = "";
        sidebarResizeCleanupRef.current = null;
      };

      sidebarResizeCleanupRef.current = cleanup;
      document.body.style.userSelect = "none";
      document.body.style.cursor = cursor;
      window.addEventListener("pointermove", handlePointerMove);
      window.addEventListener("pointerup", cleanup);
      window.addEventListener("pointercancel", cleanup);
    };
  }

  function buildDraftWithSelectedProfileModel(profileId: string, fallback = "") {
    const modelId = resolveSelectedProfileModelId(profileId, fallback);
    if (!modelId) {
      throw new Error(copy.requiredModelMissing);
    }
    const option = modelOptionsById.get(modelId);
    if (!option) {
      throw new Error(`Unknown model: ${modelId}`);
    }
    const next = clonePublicConfig(requireDraft());
    applyModelOptionToProfileDraft(next, profileId, option, modelDetailKeys);
    return { next, option };
  }

  function applyPreset(presetId: string) {
    setModelEditorExpanded(true);
    const preset = workspace?.modelPresetOptions.find((item) => item.preset_id === presetId);
    if (!preset) {
      setModelEditor((current) => ({ ...current, preset_id: presetId }));
      return;
    }
    const presetModel = asRecord(preset.model);
    setModelEditor({
      mode: "create",
      preset_id: presetId,
      model_id: getString(preset.model_id),
      label: getString(presetModel.label) || preset.label,
      model: getString(presetModel.model),
      api_key_env: getString(presetModel.api_key_env),
      api_key: "",
      clear_api_key: false,
      provider: buildProviderDraft(asRecord(preset.provider)),
      details: buildModelDetailsDraft(presetModel),
    });
  }

  async function handleSaveModel() {
    if (structuredActionsDisabled) {
      return;
    }
    setBusyAction(copy.modelSavePending);
    try {
      const endpoint = modelEditor.mode === "edit" ? "/api/config/draft/update-model" : "/api/config/draft/add-model";
      const response = await requestJson<ConfigWorkspace>(endpoint, {
        publicConfig: requireDraft(),
        draftMeta,
        baseHash,
        presetId: modelEditor.mode === "create" ? modelEditor.preset_id : "",
        modelId: modelEditor.model_id,
        provider: buildProviderPayload(modelEditor.provider),
        model: modelEditor.model,
        label: modelEditor.label,
        details: buildModelDetailsPayload(modelEditor.details),
        apiKeyEnv: modelEditor.api_key_env,
        apiKey: modelEditor.api_key,
        clearApiKey: modelEditor.clear_api_key,
      });
      syncWorkspace(response, "success");
      setModelEditorExpanded(false);
    } catch (error) {
      markError(error);
    } finally {
      setBusyAction("");
    }
  }

  async function handleDeleteModel(modelId: string) {
    if (structuredActionsDisabled) {
      return;
    }
    setBusyAction(copy.modelSavePending);
    try {
      const response = await requestJson<ConfigWorkspace>("/api/config/draft/delete-model", {
        publicConfig: requireDraft(),
        draftMeta,
        baseHash,
        modelId,
      });
      syncWorkspace(response, "success");
    } catch (error) {
      markError(error);
    } finally {
      setBusyAction("");
    }
  }

  async function handleAddProfile() {
    if (structuredActionsDisabled) {
      return;
    }
    setBusyAction(copy.profileSavePending);
    try {
      const response = await requestJson<ConfigWorkspace>("/api/config/draft/add-profile", {
        publicConfig: requireDraft(),
        draftMeta,
        baseHash,
        profileId: profileDraft.profile_id,
        sourceProfileId: profileDraft.source_profile_id,
        modelId: profileDraft.model_id,
      });
      syncWorkspace(response, "success");
      setProfileFormExpanded(false);
    } catch (error) {
      markError(error);
    } finally {
      setBusyAction("");
    }
  }

  async function handleApplySelectedProfileModel(profileId: string, fallbackModelId = "") {
    if (structuredActionsDisabled) {
      return;
    }
    try {
      const { next } = buildDraftWithSelectedProfileModel(profileId, fallbackModelId);
      await previewDraft(next, draftMeta, copy.profileApplyPending);
      cancelProfileEdit(profileId);
      setNotice({ tone: "success", text: copy.profileDraftSaved });
    } catch (error) {
      markError(error);
    }
  }

  async function handleTestProfile(profileId: string) {
    if (structuredActionsDisabled) {
      return;
    }
    setBusyAction(copy.testPending);
    try {
      const result = await requestJson<ConfigLlmTestResult>("/api/config/test-llm", {
        publicConfig: requireDraft(),
        draftMeta,
        baseHash,
        profileId,
      });
      setNotice({
        tone: result.ok ? "success" : "error",
        text: formatTestNotice(result),
      });
    } catch (error) {
      markError(error);
    } finally {
      setBusyAction("");
    }
  }

  async function handleTestSelectedProfile(profileId: string, fallbackModelId = "") {
    if (structuredActionsDisabled) {
      return;
    }
    setBusyAction(copy.testPending);
    try {
      const { next, option } = buildDraftWithSelectedProfileModel(profileId, fallbackModelId);
      const result = await requestJson<ConfigLlmTestResult>("/api/config/test-llm", {
        publicConfig: next,
        draftMeta,
        baseHash,
        profileId,
      });
      setNotice({
        tone: result.ok ? "success" : "error",
        text: formatTestNotice({
          ...result,
          provider_kind: result.provider_kind || option.provider_kind,
          base_url: result.base_url || getString(asRecord(option.provider).base_url),
        }),
      });
    } catch (error) {
      markError(error);
    } finally {
      setBusyAction("");
    }
  }

  function sectionTitle(sectionId: string, fallback: string) {
    return sectionMap.get(sectionId)?.title ?? fallback;
  }

  function keyStateLabel(state: string) {
    switch (state) {
      case "pending":
        return copy.keyPending;
      case "clear_pending":
        return copy.keyClearPending;
      case "configured":
        return copy.keyConfigured;
      default:
        return copy.keyMissing;
    }
  }

  function testScopeLabel(scope: ConfigLlmTestResult["config_scope"]) {
    return scope === "saved" ? copy.testScopeSaved : copy.testScopeDraft;
  }

  function formatTestKeyDetail(result: ConfigLlmTestResult) {
    if (!result.requires_api_key) {
      return `${copy.testKeyNotRequired}${result.api_key_source ? ` (${copy.testKeySourceLabel}: ${result.api_key_source})` : ""}`;
    }
    return result.api_key_source || "-";
  }

  function formatTestNotice(result: ConfigLlmTestResult) {
    const detailParts = [
      testScopeLabel(result.config_scope),
      `${copy.testRouteLabel}: ${[result.provider_kind, result.base_url].filter(Boolean).join(" · ") || "-"}`,
      `${copy.testKeyLabel}: ${formatTestKeyDetail(result)}`,
    ];
    return `${result.profile_id} / ${result.model}: ${result.message} [${detailParts.join(" | ")}]`;
  }

  function intakeLabel(mode: string) {
    if (mode === "auto") {
      return currentLanguage === "en" ? "auto" : "自动";
    }
    return currentLanguage === "en" ? "manual review" : "人工审核";
  }

  if (!draftConfig && workspaceQuery.isLoading) {
    return (
      <div className={styles.page}>
        <section className={styles.loadingSurface}>
          <p className={styles.eyebrow}>Config</p>
          <h1 className={styles.title}>{copy.loading}</h1>
        </section>
      </div>
    );
  }

  if (!draftConfig || !workspace) {
    return (
      <div className={styles.page}>
        <section className={styles.loadingSurface}>
          <p className={styles.eyebrow}>Config</p>
          <h1 className={styles.title}>{copy.loadFailed}</h1>
          <p className={styles.subtitle}>{workspaceQuery.error instanceof Error ? workspaceQuery.error.message : ""}</p>
        </section>
      </div>
    );
  }

  return (
    <div ref={pageRef} className={styles.page} style={pageStyle}>
      <aside className={styles.sidebar} style={sidebarStyle}>
        <div className={styles.sidebarIntro}>
          <p className={styles.eyebrow}>Config</p>
          <h1 className={styles.title}>{copy.pageTitle}</h1>
          <p className={styles.subtitle}>{copy.subtitle}</p>
        </div>

        <div className={styles.sidebarStatus}>
          <span
            className={
              hasPendingApply
                ? `${styles.statusBadge} ${styles.statusBadgePending}`
                : `${styles.statusBadge} ${styles.statusBadgeReady}`
            }
          >
            {hasPendingApply ? copy.unsavedDraft : copy.syncedDraft}
          </span>
          <button
            type="button"
            className={`${styles.primaryButton} ${styles.buttonBlock}`}
            disabled={Boolean(busyAction) || !hasPendingApply}
            onClick={handleApply}
          >
            <Save size={14} />
            {applyButtonLabel}
          </button>
          <span className={styles.helperText}>{sidebarApplyHint}</span>
        </div>

        <section className={sidebarIndexCollapsed ? `${styles.sidebarNavPanel} ${styles.sidebarNavPanelCollapsed}` : styles.sidebarNavPanel}>
          <div className={styles.sidebarPanelHeader}>
            <div className={styles.sidebarPanelIntro}>
              <p className={styles.matrixTitle}>{sectionIndexTitle}</p>
              <p className={styles.helperText}>{sidebarIndexCollapsed ? sectionIndexCollapsedHint : sectionIndexHint}</p>
            </div>
            <div className={styles.sidebarPanelActions}>
              <span className={styles.inlineBadge}>{visibleSidebarGroups.length}</span>
              <button
                type="button"
                className={`${styles.actionButton} ${styles.compactButton} ${styles.sidebarPanelToggle}`}
                aria-expanded={!sidebarIndexCollapsed}
                onClick={() => setSidebarIndexCollapsed((current) => !current)}
              >
                <ChevronRight size={14} className={sidebarIndexCollapsed ? styles.treeToggleIcon : styles.treeToggleIconExpanded} />
                {sectionIndexToggleLabel}
              </button>
            </div>
          </div>
          {sidebarIndexCollapsed ? null : (
            <nav className={styles.sectionNav} aria-label="config sections">
                {visibleSidebarGroups.map((section) => (
                  <button
                    key={section.id}
                    type="button"
                    className={
                      section.id === activeSection?.id
                      ? `${styles.sectionLink} ${styles.sectionLinkActive}`
                      : styles.sectionLink
                  }
                  aria-pressed={section.id === activeSection?.id}
                  onClick={() => handleSelectSection(section.id)}
                  >
                    <span>{section.title}</span>
                    <span className={styles.inlineBadge}>{section.memberSectionIds.length}</span>
                  </button>
                ))}
              </nav>
            )}
          </section>

        <div className={styles.sidebarMetrics}>
          <article className={styles.metricCard}>
            <span>{copy.runtimeProfile}</span>
            <strong>{workspace.runtimeProfile}</strong>
          </article>
          <article className={styles.metricCard}>
            <span>{copy.defaultMode}</span>
            <strong>{workspace.defaultMode}</strong>
          </article>
          <article className={styles.metricCard}>
            <span>{copy.defaultRoute}</span>
            <strong>{workspace.defaultRoute}</strong>
          </article>
          <article className={styles.metricCard}>
            <span>{copy.intakeMode}</span>
            <strong>{intakeLabel(asRecord(draftConfig.evolution).intake_mode as string)}</strong>
          </article>
        </div>
        <div
          className={styles.sidebarResizeX}
          title={resizeWidthTitle}
          onDoubleClick={resetSidebarWidth}
          onPointerDown={beginSidebarResize("width")}
        />
        <div
          className={styles.sidebarResizeY}
          title={resizeHeightTitle}
          onDoubleClick={resetSidebarHeight}
          onPointerDown={beginSidebarResize("height")}
        />
        <div
          className={styles.sidebarResizeCorner}
          title={resizeCornerTitle}
          onDoubleClick={() => {
            resetSidebarWidth();
            resetSidebarHeight();
          }}
          onPointerDown={beginSidebarResize("both")}
        />
      </aside>

      <section className={styles.content}>
        {notice.text ? (
          <div
            className={
              notice.tone === "error"
                ? `${styles.notice} ${styles.noticeError}`
                : notice.tone === "success"
                  ? `${styles.notice} ${styles.noticeSuccess}`
                  : styles.notice
            }
          >
            {notice.text}
          </div>
        ) : null}

        {isSectionVisible("overview") ? (
        <section id="config-overview" className={styles.sectionSurface}>
          <div className={styles.sectionHeader}>
            <div>
              <p className={styles.eyebrow}>{sectionTitle("overview", copy.sourceTitle)}</p>
              <h2 className={styles.sectionTitle}>{copy.sourceTitle}</h2>
            </div>
            <Database size={16} className={styles.sectionIcon} />
          </div>
          <p className={styles.sectionText}>{copy.sourceBody}</p>
          <div className={styles.hashGrid}>
            <article className={styles.detailCard}>
              <span>{copy.configPath}</span>
              <code className={styles.hashValue}>{workspace.configPath}</code>
            </article>
            <article className={styles.detailCard}>
              <span>{copy.persistedHash}</span>
              <code className={styles.hashValue}>{workspace.baseHash}</code>
            </article>
            <article className={styles.detailCard}>
              <span>{copy.baseHash}</span>
              <code className={styles.hashValue}>{baseHash}</code>
            </article>
            <article className={styles.detailCard}>
              <span>{copy.draftHash}</span>
              <code className={styles.hashValue}>{draftHash}</code>
            </article>
          </div>
          <div className={styles.actionsRow}>
            <button type="button" className={styles.actionButton} disabled={Boolean(busyAction)} onClick={reloadWorkspace}>
              <RefreshCw size={14} />
              {copy.refresh}
            </button>
            <button
              type="button"
              className={styles.actionButton}
              disabled={Boolean(busyAction)}
              onClick={() => {
                setJsonText(formattedDraft);
                setNotice({ tone: "neutral", text: "" });
              }}
            >
              <RotateCcw size={14} />
              {copy.resetDraft}
            </button>
          </div>
          <details className={styles.rawConfigPanel}>
            <summary>{copy.rawToml}</summary>
            <p className={styles.helperText}>{copy.rawTomlHint}</p>
            <pre className={styles.rawToml}>{workspace.rawToml}</pre>
          </details>
        </section>
        ) : null}

        {isSectionVisible("shell") ? (
        <section id="config-shell" className={styles.sectionSurface}>
          <div className={styles.sectionHeader}>
            <div>
              <p className={styles.eyebrow}>{sectionTitle("shell", copy.runtimeTitle)}</p>
              <h2 className={styles.sectionTitle}>{copy.runtimeTitle}</h2>
            </div>
            <SlidersHorizontal size={16} className={styles.sectionIcon} />
          </div>
          <p className={styles.sectionText}>{copy.runtimeBody}</p>
          <div className={styles.matrixGrid}>
            <article className={styles.matrixCard}>
              <p className={styles.matrixTitle}>{copy.interfaceLanguage}</p>
              <div className={styles.segmented}>
                {([
                  { value: "zh" as const, label: copy.languageChinese },
                  { value: "en" as const, label: copy.languageEnglish },
                ]).map((item) => (
                  <button
                    key={item.value}
                    type="button"
                    className={
                      getDraftLanguage(draftConfig, workspace.language) === item.value
                        ? `${styles.segmentButton} ${styles.segmentButtonActive}`
                        : styles.segmentButton
                    }
                    disabled={structuredActionsDisabled}
                    onClick={() =>
                      updateSimpleDraft((next) => {
                        const ui = asRecord(next.ui);
                        ui.language = item.value;
                        next.ui = ui;
                      })
                    }
                  >
                    <Languages size={14} />
                    {item.label}
                  </button>
                ))}
              </div>
            </article>

            <article className={styles.matrixCard}>
              <p className={styles.matrixTitle}>{copy.intakeMode}</p>
              <div className={styles.segmented}>
                {(["manual_review", "auto"] as const).map((mode) => (
                  <button
                    key={mode}
                    type="button"
                    className={
                      getString(asRecord(draftConfig.evolution).intake_mode) === mode
                        ? `${styles.segmentButton} ${styles.segmentButtonActive}`
                        : styles.segmentButton
                    }
                    disabled={structuredActionsDisabled}
                    onClick={() =>
                      updateSimpleDraft((next) => {
                        const evolution = asRecord(next.evolution);
                        evolution.intake_mode = mode;
                        next.evolution = evolution;
                      })
                    }
                  >
                    {intakeLabel(mode)}
                  </button>
                ))}
              </div>
            </article>
          </div>
        </section>
        ) : null}

        {isSectionVisible("profiles") ? (
        <section id="config-profiles" className={styles.sectionSurface}>
          <div className={styles.sectionHeader}>
            <div>
              <p className={styles.eyebrow}>{sectionTitle("profiles", copy.profilesTitle)}</p>
              <h2 className={styles.sectionTitle}>{copy.profilesTitle}</h2>
            </div>
            <Play size={16} className={styles.sectionIcon} />
          </div>
          <p className={styles.sectionText}>{copy.profilesBody}</p>
          <div className={styles.profileGrid}>
            {workspace.profileCards.map((profile) => (
              <article key={profile.profileId} className={styles.profileCard}>
                {(() => {
                  const profileEditor = profileEditors[profile.profileId];
                  const isEditingProfile = Boolean(profileEditor);
                  const selectedModelId = resolveSelectedProfileModelId(profile.profileId, profile.selectedModelId);
                  const selectedModel = modelOptionsById.get(selectedModelId) ?? null;
                  const profileExpanded = Boolean(expandedProfiles[profile.profileId]);
                  const selectionDirty = isEditingProfile && Boolean(selectedModelId) && selectedModelId !== profile.selectedModelId;
                  const previewProviderKind = selectionDirty ? selectedModel?.provider_kind ?? profile.providerKind : profile.providerKind;
                  const previewModel = selectionDirty ? selectedModel?.model ?? profile.model : profile.model;
                  const previewBaseUrl = selectionDirty
                    ? getString(asRecord(selectedModel?.provider).base_url) || profile.baseUrl
                    : profile.baseUrl;
                  const previewApiKeyEnv = selectionDirty ? selectedModel?.api_key_env ?? profile.apiKeyEnv : profile.apiKeyEnv;
                  const previewKeyState = selectionDirty ? selectedModel?.api_key_state ?? profile.apiKeyState : profile.apiKeyState;
                  const previewApiKeySource = selectionDirty ? previewApiKeyEnv || "-" : profile.apiKeySource || "-";

                  return (
                    <>
                      <div className={styles.cardHeader}>
                        <div>
                          <p className={styles.cardTitle}>{profile.label}</p>
                          <p className={styles.cardSubtle}>{profile.profileId}</p>
                        </div>
                        <div className={styles.cardHeaderActions}>
                          <div className={styles.cardBadges}>
                            <span
                              className={
                                profile.requiredModelMissing
                                  ? `${styles.inlineBadge} ${styles.inlineBadgeWarning}`
                                  : styles.inlineBadge
                              }
                            >
                              {profile.requiredModelMissing ? copy.requiredModelMissing : profile.selectedModelLabel}
                            </span>
                            {selectionDirty && selectedModel ? <span className={styles.inlineBadge}>{copy.stagedRoute}</span> : null}
                            {isEditingProfile ? <span className={styles.inlineBadge}>{copy.editProfile}</span> : null}
                          </div>
                          <button
                            type="button"
                            className={`${styles.actionButton} ${styles.compactButton}`}
                            aria-expanded={profileExpanded}
                            onClick={() => toggleExpandedProfile(profile.profileId)}
                          >
                            <ChevronRight size={14} className={profileExpanded ? styles.treeToggleIconExpanded : styles.treeToggleIcon} />
                            {profileExpanded ? copy.collapseSection : copy.expandSection}
                          </button>
                        </div>
                      </div>

                      <div className={styles.cardSummaryLine}>
                        <span>{previewProviderKind}</span>
                        <span>{previewModel}</span>
                        <span>{keyStateLabel(previewKeyState)}</span>
                      </div>

                      {profileExpanded ? (
                        <>
                          {isEditingProfile ? (
                            <label className={styles.field}>
                              <span>{copy.selectedModel}</span>
                              <select
                                value={selectedModelId}
                                disabled={structuredActionsDisabled}
                                onChange={(event) => updateProfileModelDraft(profile.profileId, event.target.value)}
                              >
                                <option value="" />
                                {modelOptions.map((option) => (
                                  <option key={option.model_id} value={option.model_id}>
                                    {option.label}
                                  </option>
                                ))}
                              </select>
                            </label>
                          ) : null}

                          <div className={styles.cardMeta}>
                            <strong>{selectionDirty ? copy.stagedRoute : copy.currentRoute}</strong>
                            <span>{previewProviderKind}</span>
                            <span>{previewModel}</span>
                            <span>{previewBaseUrl}</span>
                            <span>{previewApiKeyEnv || "-"}</span>
                            <span>{keyStateLabel(previewKeyState)}</span>
                            <span>{`${copy.apiKeySource}: ${previewApiKeySource}`}</span>
                          </div>

                          <div className={styles.cardActionsGrid}>
                            {isEditingProfile ? (
                              <>
                                <button
                                  type="button"
                                  className={`${styles.primaryButton} ${styles.buttonBlock}`}
                                  disabled={structuredActionsDisabled || !selectedModelId}
                                  onClick={() => handleApplySelectedProfileModel(profile.profileId, profile.selectedModelId)}
                                >
                                  <Save size={14} />
                                  {copy.applySelectedModel}
                                </button>
                                <button
                                  type="button"
                                  className={`${styles.actionButton} ${styles.buttonBlock}`}
                                  disabled={structuredActionsDisabled}
                                  onClick={() => cancelProfileEdit(profile.profileId)}
                                >
                                  <RotateCcw size={14} />
                                  {copy.cancelProfileEdit}
                                </button>
                              </>
                            ) : (
                              <button
                                type="button"
                                className={`${styles.actionButton} ${styles.buttonBlock}`}
                                disabled={structuredActionsDisabled}
                                onClick={() => beginProfileEdit(profile.profileId, profile.selectedModelId)}
                              >
                                <Pencil size={14} />
                                {copy.editProfile}
                              </button>
                            )}
                            <button
                              type="button"
                              className={`${styles.actionButton} ${styles.buttonBlock}`}
                              disabled={structuredActionsDisabled || !selectedModelId}
                              onClick={() =>
                                isEditingProfile
                                  ? handleTestSelectedProfile(profile.profileId, profile.selectedModelId)
                                  : handleTestProfile(profile.profileId)
                              }
                            >
                              <Play size={14} />
                              {isEditingProfile ? copy.testSelectedModel : copy.testConnection}
                            </button>
                          </div>
                        </>
                      ) : null}
                    </>
                  );
                })()}
              </article>
            ))}
          </div>
          <div ref={profileFormRef} className={styles.formSurface}>
            <div className={styles.formHeader}>
              <div className={styles.formHeaderIntro}>
                <Plus size={16} />
                <div>
                  <span>{copy.profileAdd}</span>
                  <p className={styles.helperText}>{copy.profilePreparedHint}</p>
                </div>
              </div>
              <button
                type="button"
                className={`${styles.actionButton} ${styles.compactButton}`}
                aria-expanded={profileFormExpanded}
                onClick={() => setProfileFormExpanded((current) => !current)}
              >
                <ChevronRight size={14} className={profileFormExpanded ? styles.treeToggleIconExpanded : styles.treeToggleIcon} />
                {profileFormExpanded ? copy.collapseSection : copy.expandSection}
              </button>
            </div>
            {profileFormExpanded ? (
              <>
                <div className={styles.formGrid}>
                  <label className={styles.field}>
                    <span>{copy.profileId}</span>
                    <input
                      value={profileDraft.profile_id}
                      onChange={(event) => setProfileDraft((current) => ({ ...current, profile_id: event.target.value }))}
                    />
                  </label>
                  <label className={styles.field}>
                    <span>{copy.sourceProfile}</span>
                    <select
                      value={profileDraft.source_profile_id}
                      onChange={(event) =>
                        setProfileDraft((current) => ({ ...current, source_profile_id: event.target.value }))
                      }
                    >
                      {workspace.profileCards.map((profile) => (
                        <option key={profile.profileId} value={profile.profileId}>
                          {profile.label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className={styles.field}>
                    <span>{copy.assignModel}</span>
                    <select
                      value={profileDraft.model_id}
                      onChange={(event) => setProfileDraft((current) => ({ ...current, model_id: event.target.value }))}
                    >
                      <option value="" />
                      {modelOptions.map((option) => (
                        <option key={option.model_id} value={option.model_id}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
                <button
                  type="button"
                  className={styles.primaryButton}
                  disabled={structuredActionsDisabled}
                  onClick={handleAddProfile}
                >
                  <Plus size={14} />
                  {copy.createProfile}
                </button>
              </>
            ) : null}
          </div>
        </section>
        ) : null}

        {isSectionVisible("models") ? (
        <section id="config-models" className={styles.sectionSurface}>
          <div className={styles.sectionHeader}>
            <div>
              <p className={styles.eyebrow}>{sectionTitle("models", copy.modelsTitle)}</p>
              <h2 className={styles.sectionTitle}>{copy.modelsTitle}</h2>
            </div>
            <Blocks size={16} className={styles.sectionIcon} />
          </div>
          <p className={styles.sectionText}>{copy.modelsBody}</p>
          <div className={styles.formSurface}>
            <div className={styles.formHeader}>
              <div className={styles.formHeaderIntro}>
                <Pencil size={16} />
                <span>{modelEditor.mode === "edit" ? copy.modelEditorEdit : copy.modelEditorCreate}</span>
              </div>
              <button
                type="button"
                className={`${styles.actionButton} ${styles.compactButton}`}
                aria-expanded={modelEditorExpanded}
                onClick={() => setModelEditorExpanded((current) => !current)}
              >
                <ChevronRight size={14} className={modelEditorExpanded ? styles.treeToggleIconExpanded : styles.treeToggleIcon} />
                {modelEditorExpanded ? copy.collapseSection : copy.expandSection}
              </button>
            </div>
            {modelEditorExpanded ? (
              <>
                <div className={styles.formGridWide}>
                  <label className={styles.field}>
                    <span>{copy.preset}</span>
                    <select value={modelEditor.preset_id} onChange={(event) => applyPreset(event.target.value)}>
                      <option value="">{copy.customEntry}</option>
                      {modelPresetGroups.map((group) => (
                        <optgroup key={group.id} label={group.label}>
                          {group.presets.map((preset: ConfigModelPresetOption) => (
                            <option key={preset.preset_id} value={preset.preset_id}>
                              {preset.label}
                            </option>
                          ))}
                        </optgroup>
                      ))}
                    </select>
                  </label>
                  <label className={styles.field}>
                    <span>{copy.modelId}</span>
                    <input
                      value={modelEditor.model_id}
                      onChange={(event) => setModelEditor((current) => ({ ...current, model_id: event.target.value }))}
                      disabled={modelEditor.mode === "edit"}
                    />
                  </label>
                  <label className={styles.field}>
                    <span>{copy.label}</span>
                    <input value={modelEditor.label} onChange={(event) => setModelEditor((current) => ({ ...current, label: event.target.value }))} />
                  </label>
                  <label className={styles.field}>
                    <span>{copy.modelName}</span>
                    <input value={modelEditor.model} onChange={(event) => setModelEditor((current) => ({ ...current, model: event.target.value }))} />
                  </label>
                  <label className={styles.field}>
                    <span>{copy.providerKind}</span>
                    <input
                      value={modelEditor.provider.kind}
                      onChange={(event) =>
                        setModelEditor((current) => ({
                          ...current,
                          provider: { ...current.provider, kind: event.target.value },
                        }))
                      }
                    />
                  </label>
                  <label className={styles.field}>
                    <span>{copy.baseUrl}</span>
                    <input
                      value={modelEditor.provider.base_url}
                      onChange={(event) =>
                        setModelEditor((current) => ({
                          ...current,
                          provider: { ...current.provider, base_url: event.target.value },
                        }))
                      }
                    />
                  </label>
                  <label className={styles.field}>
                    <span>{copy.providerKeyEnv}</span>
                    <input
                      value={modelEditor.provider.api_key_env}
                      onChange={(event) =>
                        setModelEditor((current) => ({
                          ...current,
                          provider: { ...current.provider, api_key_env: event.target.value },
                        }))
                      }
                    />
                  </label>
                  <label className={styles.field}>
                    <span>{copy.modelKeyEnv}</span>
                    <input
                      value={modelEditor.api_key_env}
                      onChange={(event) => setModelEditor((current) => ({ ...current, api_key_env: event.target.value }))}
                    />
                  </label>
                  <label className={styles.field}>
                    <span>{copy.compatMode}</span>
                    <input
                      value={modelEditor.provider.compat_mode}
                      onChange={(event) =>
                        setModelEditor((current) => ({
                          ...current,
                          provider: { ...current.provider, compat_mode: event.target.value },
                        }))
                      }
                    />
                  </label>
                  <label className={styles.field}>
                    <span>{copy.contextWindow}</span>
                    <input
                      value={modelEditor.provider.context_window}
                      onChange={(event) =>
                        setModelEditor((current) => ({
                          ...current,
                          provider: { ...current.provider, context_window: event.target.value },
                        }))
                      }
                    />
                  </label>
                  <label className={styles.field}>
                    <span>{copy.transport}</span>
                    <select
                      value={modelEditor.details.transport}
                      onChange={(event) =>
                        setModelEditor((current) => ({
                          ...current,
                          details: { ...current.details, transport: event.target.value },
                        }))
                      }
                    >
                      <option value="chat_completions">chat_completions</option>
                    </select>
                  </label>
                  <label className={styles.field}>
                    <span>{copy.contract}</span>
                    <select
                      value={modelEditor.details.contract}
                      onChange={(event) =>
                        setModelEditor((current) => ({
                          ...current,
                          details: { ...current.details, contract: event.target.value },
                        }))
                      }
                    >
                      <option value="tool_chat">tool_chat</option>
                      <option value="reasoning_chat">reasoning_chat</option>
                    </select>
                  </label>
                  <label className={styles.field}>
                    <span>{copy.reasoningStateField}</span>
                    <input
                      value={modelEditor.details.reasoning_state_field}
                      onChange={(event) =>
                        setModelEditor((current) => ({
                          ...current,
                          details: { ...current.details, reasoning_state_field: event.target.value },
                        }))
                      }
                    />
                  </label>
                  <label className={styles.field}>
                    <span>{copy.toolCallingMode}</span>
                    <select
                      value={modelEditor.details.tool_calling_mode}
                      onChange={(event) =>
                        setModelEditor((current) => ({
                          ...current,
                          details: { ...current.details, tool_calling_mode: event.target.value },
                        }))
                      }
                    >
                      <option value="auto">auto</option>
                      <option value="disabled">disabled</option>
                    </select>
                  </label>
                  <label className={styles.field}>
                    <span>{copy.temperature}</span>
                    <input
                      value={modelEditor.details.temperature}
                      onChange={(event) =>
                        setModelEditor((current) => ({
                          ...current,
                          details: { ...current.details, temperature: event.target.value },
                        }))
                      }
                    />
                  </label>
                  <label className={styles.field}>
                    <span>{copy.maxOutputTokens}</span>
                    <input
                      value={modelEditor.details.max_output_tokens}
                      onChange={(event) =>
                        setModelEditor((current) => ({
                          ...current,
                          details: { ...current.details, max_output_tokens: event.target.value },
                        }))
                      }
                    />
                  </label>
                  <label className={styles.field}>
                    <span>{copy.timeout}</span>
                    <input
                      value={modelEditor.details.timeout}
                      onChange={(event) =>
                        setModelEditor((current) => ({
                          ...current,
                          details: { ...current.details, timeout: event.target.value },
                        }))
                      }
                    />
                  </label>
                  <label className={styles.field}>
                    <span>{copy.connectTimeout}</span>
                    <input
                      value={modelEditor.details.connect_timeout}
                      onChange={(event) =>
                        setModelEditor((current) => ({
                          ...current,
                          details: { ...current.details, connect_timeout: event.target.value },
                        }))
                      }
                    />
                  </label>
                </div>

                <div className={styles.toggleGrid}>
                  <label className={styles.toggleField}>
                    <input
                      type="checkbox"
                      checked={modelEditor.provider.requires_api_key}
                      onChange={(event) =>
                        setModelEditor((current) => ({
                          ...current,
                          provider: { ...current.provider, requires_api_key: event.target.checked },
                        }))
                      }
                    />
                    <span>{copy.requiresApiKey}</span>
                  </label>
                  <label className={styles.toggleField}>
                    <input
                      type="checkbox"
                      checked={modelEditor.details.strict_compatibility}
                      onChange={(event) =>
                        setModelEditor((current) => ({
                          ...current,
                          details: { ...current.details, strict_compatibility: event.target.checked },
                        }))
                      }
                    />
                    <span>{copy.strictCompatibility}</span>
                  </label>
                  <label className={styles.toggleField}>
                    <input
                      type="checkbox"
                      checked={modelEditor.details.streaming}
                      onChange={(event) =>
                        setModelEditor((current) => ({
                          ...current,
                          details: { ...current.details, streaming: event.target.checked },
                        }))
                      }
                    />
                    <span>{copy.streaming}</span>
                  </label>
                  <label className={styles.toggleField}>
                    <input
                      type="checkbox"
                      checked={modelEditor.details.discovery_enabled}
                      onChange={(event) =>
                        setModelEditor((current) => ({
                          ...current,
                          details: { ...current.details, discovery_enabled: event.target.checked },
                        }))
                      }
                    />
                    <span>{copy.discoveryEnabled}</span>
                  </label>
                  <label className={styles.toggleField}>
                    <input
                      type="checkbox"
                      checked={modelEditor.clear_api_key}
                      onChange={(event) => setModelEditor((current) => ({ ...current, clear_api_key: event.target.checked }))}
                    />
                    <span>{copy.clearSecret}</span>
                  </label>
                </div>

                <label className={styles.field}>
                  <span>{copy.pendingSecret}</span>
                  <input
                    type="password"
                    value={modelEditor.api_key}
                    onChange={(event) => setModelEditor((current) => ({ ...current, api_key: event.target.value }))}
                  />
                </label>

                <div className={styles.actionsRow}>
                  <button type="button" className={styles.primaryButton} disabled={structuredActionsDisabled} onClick={handleSaveModel}>
                    <Save size={14} />
                    {copy.saveModel}
                  </button>
                  <button
                    type="button"
                    className={styles.actionButton}
                    onClick={() => {
                      setModelEditor(emptyModelEditorState());
                      setModelEditorExpanded(false);
                    }}
                  >
                    <RotateCcw size={14} />
                    {copy.cancelEditing}
                  </button>
                  {modelEditor.mode === "edit" ? (
                    <button
                      type="button"
                      className={styles.dangerButton}
                      disabled={structuredActionsDisabled}
                      onClick={() => handleDeleteModel(modelEditor.model_id)}
                    >
                      <Trash2 size={14} />
                      {copy.deleteModel}
                    </button>
                  ) : null}
                </div>
              </>
            ) : null}
          </div>

          <div className={styles.modelGrid}>
            {workspace.modelOptions.map((option) => (
              <article key={option.model_id} className={styles.modelCard}>
                {(() => {
                  const modelExpanded = Boolean(expandedModels[option.model_id]);
                  return (
                    <>
                      <div className={styles.cardHeader}>
                        <div>
                          <p className={styles.cardTitle}>{option.label}</p>
                          <p className={styles.cardSubtle}>{option.model_id}</p>
                        </div>
                        <div className={styles.cardHeaderActions}>
                          <span className={styles.inlineBadge}>
                            {option.source === "profile" ? copy.sourceProfileGenerated : copy.sourceLibrary}
                          </span>
                          <button
                            type="button"
                            className={`${styles.actionButton} ${styles.compactButton}`}
                            aria-expanded={modelExpanded}
                            onClick={() => toggleExpandedModel(option.model_id)}
                          >
                            <ChevronRight size={14} className={modelExpanded ? styles.treeToggleIconExpanded : styles.treeToggleIcon} />
                            {modelExpanded ? copy.collapseSection : copy.expandSection}
                          </button>
                        </div>
                      </div>
                      <div className={styles.cardSummaryLine}>
                        <span>{option.provider_kind}</span>
                        <span>{option.model}</span>
                        <span>{keyStateLabel(option.api_key_state)}</span>
                      </div>
                      {modelExpanded ? (
                        <>
                          <div className={styles.cardMeta}>
                            <span>{option.provider_kind}</span>
                            <span>{option.model}</span>
                            <span>{option.api_key_env}</span>
                            <span>{keyStateLabel(option.api_key_state)}</span>
                          </div>
                          <div className={styles.cardActionsGrid}>
                            <button
                              type="button"
                              className={`${styles.actionButton} ${styles.buttonBlock}`}
                              onClick={() => {
                                setModelEditor(hydrateModelEditorFromOption(option));
                                setModelEditorExpanded(true);
                              }}
                            >
                              <Pencil size={14} />
                              {copy.modelEditorEdit}
                            </button>
                            <button
                              type="button"
                              className={`${styles.dangerButton} ${styles.buttonBlock}`}
                              disabled={structuredActionsDisabled}
                              onClick={() => handleDeleteModel(option.model_id)}
                            >
                              <Trash2 size={14} />
                              {copy.deleteModel}
                            </button>
                          </div>
                        </>
                      ) : null}
                    </>
                  );
                })()}
              </article>
            ))}
          </div>
        </section>
        ) : null}

        {activeEditorSections.map((section) => (
          <ConfigSectionEditor
            key={section.id}
            section={section}
            value={getConfigValueAtPath(draftConfig, section.path)}
            metaMap={editorMeta}
            copy={copy}
            disabled={structuredActionsDisabled}
            active={isActiveGroup(activeSection?.id ?? "")}
            uiState={sectionUiState[section.id] ?? defaultSectionUiState()}
            onUiStateChange={updateSectionUiState}
            onSaveSection={saveConfigSection}
          />
        ))}

        {isSectionVisible("draft") ? (
        <section id="config-draft" className={styles.sectionSurface}>
          <div className={styles.sectionHeader}>
            <div>
              <p className={styles.eyebrow}>{sectionTitle("draft", copy.draftTitle)}</p>
              <h2 className={styles.sectionTitle}>{copy.draftTitle}</h2>
            </div>
            <Database size={16} className={styles.sectionIcon} />
          </div>
          <p className={styles.sectionText}>{copy.draftBody}</p>
          <div className={styles.actionsRow}>
            <button type="button" className={styles.actionButton} disabled={Boolean(busyAction)} onClick={handleValidateEditorDraft}>
              <RefreshCw size={14} />
              {copy.validateDraft}
            </button>
            <span className={styles.helperText}>{hasEditorChanges ? copy.editorDirtyHint : copy.editorCleanHint}</span>
          </div>
          <div className={styles.editorWrap}>
            <CodeMirror
              value={jsonText}
              theme={oneDark}
              height="100%"
              extensions={[json(), EditorView.lineWrapping]}
              onChange={(value) => setJsonText(value)}
              basicSetup={{
                foldGutter: false,
                allowMultipleSelections: false,
              }}
            />
          </div>
        </section>
        ) : null}

        {isSectionVisible("diagnostics") ? (
        <section id="config-diagnostics" className={styles.sectionSurface}>
          <div className={styles.sectionHeader}>
            <div>
              <p className={styles.eyebrow}>{sectionTitle("diagnostics", copy.diagnosticsTitle)}</p>
              <h2 className={styles.sectionTitle}>{copy.diagnosticsTitle}</h2>
            </div>
            <ShieldAlert size={16} className={styles.sectionIcon} />
          </div>
          <p className={styles.sectionText}>{copy.diagnosticsBody}</p>
          <div className={styles.diagnosticsGrid}>
            <article className={styles.matrixCard}>
              <p className={styles.matrixTitle}>{copy.blockingIssues}</p>
              {workspace.diagnosis.blocking_issues.length ? (
                <ul className={styles.issueList}>
                  {workspace.diagnosis.blocking_issues.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              ) : (
                <p className={styles.helperText}>{copy.noBlocking}</p>
              )}
            </article>
            <article className={styles.matrixCard}>
              <p className={styles.matrixTitle}>{copy.warningSignals}</p>
              {workspace.diagnosis.warnings.length ? (
                <ul className={styles.issueList}>
                  {workspace.diagnosis.warnings.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              ) : (
                <p className={styles.helperText}>{copy.noWarnings}</p>
              )}
            </article>
            <article className={styles.matrixCard}>
              <p className={styles.matrixTitle}>{copy.suggestedActions}</p>
              {workspace.diagnosis.suggested_actions.length ? (
                <ul className={styles.issueList}>
                  {workspace.diagnosis.suggested_actions.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              ) : (
                <p className={styles.helperText}>{copy.noSuggestions}</p>
              )}
            </article>
          </div>
        </section>
        ) : null}
      </section>
    </div>
  );
}
