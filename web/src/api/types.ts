export type ModeAvailability = {
  chat: boolean;
  self_evolution: boolean;
  supervised_evolution: boolean;
};

export type EvolutionTrack = "supervised" | "self";

export type DomainAvailability = {
  chat: boolean;
  evolution: boolean;
  config: boolean;
};

export type LogRoot = {
  id: string;
  path: string;
  exists: boolean;
  summary: {
    health: string;
    fileCount: number;
    directoryCount: number;
    sizeBytes: number;
    lastModifiedAt: string;
    latestPath: string;
    userGuide: string;
    agentGuide: string;
  };
};

export type LogDiagnostics = {
  severity: "error" | "warning" | "info" | string;
  lineCount: number;
  nonEmptyLineCount: number;
  errorCount: number;
  warningCount: number;
  ignoredSignalCount?: number;
  firstSignalLine: number | null;
  firstSignalPreview: string;
  lastSignalLine: number | null;
  lastSignalPreview: string;
  structuredEventCount: number;
  topEventTypes: Array<{
    type: string;
    count: number;
  }>;
  userSummary: string;
  agentHint: string;
  suggestedNextStep: string;
};

export type RuntimeSceneListItem = {
  runtimeSceneId: string;
  directoryName: string;
  title: string;
  displayName: string;
  packageIndex: RuntimeScenePackageIndex;
  startedAt: string;
  endedAt: string;
  status: string;
  result: string;
  stopReason: string;
  trigger: string;
  sessionMode: string;
  backendStatus: string;
  frontendStatus: string;
  browserStatus: string;
  eventCount: number;
  rawLogCount: number;
  conversationCount: number;
  agentLogCount: number;
  artifactCount: number;
};

export type RuntimeSceneEvent = {
  runtimeSceneId: string;
  component: string;
  phase: string;
  eventCode: string;
  level: string;
  message: string;
  timestamp: string;
  seq: number;
  outcome: string;
  fields: Record<string, unknown>;
  rawRefs: Array<{
    path: string;
    tail_lines?: number;
  }>;
};

export type RuntimeSceneRawFile = {
  path: string;
  label: string;
  size: number;
  language: string;
  updatedAt?: string;
};

export type RuntimeScenePackageSummary = {
  schemaVersion: number;
  eventCount: number;
  lifecycleEventCount: number;
  rawLogCount: number;
  conversationLogCount: number;
  agentLogCount: number;
  artifactCount: number;
  errorCount: number;
  warningCount: number;
};

export type RuntimeScenePackageIndex = {
  schemaVersion: number;
  packageId: string;
  displayName: string;
  indexKey: string;
  sortableTimestamp: string;
  startedAt: string;
  startedAtLocal: string;
  startedDate: string;
  startedTime: string;
  endedAt: string;
  durationSeconds: number | null;
  searchText: string;
  tags: string[];
};

export type RuntimeSceneDetail = {
  runtimeSceneId: string;
  directoryName: string;
  displayName: string;
  packageIndex: RuntimeScenePackageIndex;
  manifestPath: string;
  manifest: Record<string, unknown>;
  startedAt: string;
  endedAt: string;
  status: string;
  result: string;
  stopReason: string;
  trigger: string;
  sessionMode: string;
  host: string;
  port: number;
  url: string;
  frontend: Record<string, unknown>;
  backend: Record<string, unknown>;
  browser: Record<string, unknown>;
  supervisor: Record<string, unknown>;
  timeline: RuntimeSceneEvent[];
  lifecycle: RuntimeSceneEvent[];
  rawFiles: RuntimeSceneRawFile[];
  conversationLogs: RuntimeSceneRawFile[];
  agentLogs: RuntimeSceneRawFile[];
  artifacts: RuntimeSceneRawFile[];
  packageSummary: RuntimeScenePackageSummary;
};

export type RuntimeSceneDeleteResponse = {
  requestedCount: number;
  deletedCount: number;
  missingCount: number;
  deletedSceneIds: string[];
  missingSceneIds: string[];
  summary: string;
};

export type GitStatusFile = {
  path: string;
  status: string;
  statusLabel: string;
  staged: boolean;
  unstaged: boolean;
  untracked: boolean;
  deleted: boolean;
  oldPath: string;
};

export type GitStatusSummary = {
  available: boolean;
  error: string;
  branch: string;
  headRev: string;
  headRevShort: string;
  upstream: {
    name: string;
    remote: string;
    ahead: number;
    behind: number;
    hasUpstream: boolean;
  };
  snapshotId: string;
  createdAt: string;
  dirty: boolean;
  summary: string;
  counts: {
    total: number;
    staged: number;
    unstaged: number;
    untracked: number;
    deleted: number;
  };
  files: GitStatusFile[];
  totalFiles: number;
  truncated: boolean;
};

export type GitCommitSummary = {
  sha: string;
  shortSha: string;
  author: string;
  authoredAt: string;
  subject: string;
};

export type GitCommitsResponse = {
  available: boolean;
  error: string;
  commits: GitCommitSummary[];
};

export type GitFileDiff = {
  available: boolean;
  error: string;
  path: string;
  status: string;
  statusLabel: string;
  summary: string;
  diff: string;
  content: string;
  language: string;
  truncated: boolean;
  binary: boolean;
};

export type LogTreeResponse = {
  root: LogRoot;
  nodes: FileTreeNode[];
};

export type LogFileContent = FileContent & {
  rootId: string;
  rootPath: string;
  relativePath: string;
  diagnostics: LogDiagnostics;
};

export type LogDeleteResponse = {
  rootId: string;
  rootPath: string;
  deletedPaths: string[];
  missingPaths: string[];
  deletedCount: number;
};

export type WorkRunSnapshot = {
  runId: string;
  runKind: "chat_turn" | "self_evolution_run" | "supervised_evolution_run" | string;
  status: string;
  leases: string[];
  sessionId?: string;
  track?: string;
  currentPhase?: string;
  summary?: string;
  startedAt?: string;
  updatedAt?: string;
  finishedAt?: string;
  [key: string]: unknown;
};

export type WorkRunSummary = {
  active: {
    chat_turn: WorkRunSnapshot | null;
    self_evolution_run: WorkRunSnapshot | null;
    supervised_evolution_run: WorkRunSnapshot | null;
  };
  latest: {
    chat_turn: WorkRunSnapshot | null;
    self_evolution_run: WorkRunSnapshot | null;
    supervised_evolution_run: WorkRunSnapshot | null;
  };
};

export type RuntimeSummary = {
  status: string;
  mode: string;
  model: string;
  profile: string;
  defaultRoute: string;
  intakeMode: string;
  modeAvailability: ModeAvailability;
  domainAvailability: DomainAvailability;
  agentName: string;
  agentStatusLine: string;
  sessionTitle: string;
  taskSummary: string;
  currentPhase: string;
  sessionState: string;
  sessionStateLine: string;
  sessionNeedsResponse: boolean;
  sessionToolName: string;
  sessionUpdatedAt: string;
  mentalState: {
    mood: string;
    feeling: string;
    whisper: string;
    summary: string;
    cognitiveState: string;
    confidence: number;
    sampleSize: number;
    interventionCount: number;
    updatedAt: string;
    source: string;
  };
  contextUsage: { used: number; limit: number };
  activeTools: string[];
  changedFilesCount: number;
  recentAction: string;
  runtimeManager: {
    running: boolean;
    runtimeState: string;
    managerPid: number;
    stateVersion: number;
  };
  workbench: {
    desiredState: string;
    observedState: string;
    phase: string;
    backendPid: number;
    browserWindowPid: number;
    browserManaged: boolean;
    url: string;
    lastReason: string;
    statusLine: string;
    failureMessage: string;
  };
  workRuns: WorkRunSummary;
};

export type BackendHealth = {
  status: string;
};

export type ShutdownResponse = {
  accepted: boolean;
  mode: string;
  message: string;
  chatTurns: Array<{
    sessionId: string;
    runId: string;
    status: string;
    error?: string;
  }>;
};

export type SessionSummary = {
  id: string;
  title: string;
  status: string;
  taskSummary: string;
  lastActive: string;
  updatedAt: string;
  currentPhase: string;
};

export type ToolCall = {
  name: string;
  status: string;
  summary?: string;
};

export type MentalStateSnapshot = {
  mood: string;
  feeling: string;
  whisper: string;
  summary: string;
  cognitiveState: string;
  confidence: number;
  sampleSize: number;
  interventionCount: number;
  updatedAt: string;
  source: string;
  intervention?: string;
  metrics?: Record<string, unknown>;
  historyTail?: Array<{
    cognitiveState: string;
    confidence: number;
    timestamp: string;
  }>;
};

export type ConversationMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: string;
  thought?: string;
  mentalSnapshot?: MentalStateSnapshot;
  streaming?: boolean;
  toolCalls?: ToolCall[];
};

export type SessionDetail = SessionSummary & {
  defaultFileContext: string;
  previewTabs: string[];
  activePreviewPath: string;
  changedFiles: string[];
  readFiles: string[];
  messages: ConversationMessage[];
  stopRequested: boolean;
  stopRequestedAt: string;
  stopReason: string;
};

export type SessionStreamEvent = {
  type: "session_detail";
  sessionId: string;
  detail: SessionDetail;
};

export type FileTreeNode = {
  name: string;
  path: string;
  type: "directory" | "file";
  children?: FileTreeNode[];
};

export type FileContent = {
  path: string;
  language: string;
  content: string;
  truncated: boolean;
};

export type EvolutionActionState = {
  enabled: boolean;
  reason: string;
};

export type EvolutionOutcomeSemantics = {
  decision: string;
  decisionLabel: string;
  proposalStatus: string;
  proposalStatusLabel: string;
  runtimeEffect: string;
  runtimeEffectLabel: string;
  runtimeExplanation: string;
  isRuntimeApplied: boolean;
};

export type SupervisedRunSemantics = {
  runStatus: string;
  runStatusLabel: string;
  stage: string;
  stageLabel: string;
  diagnosis: string;
  nextAction: string;
};

export type SelfEvolutionSceneSemantics = {
  sceneState: string;
  sceneTitle: string;
  sceneSummary: string;
  blockers: string[];
  nextAction: string;
};

export type SelfEvolutionRunSemantics = {
  runStatus: string;
  runStatusLabel: string;
  phase: string;
  phaseLabel: string;
  rollbackState: string;
  rollbackStateLabel: string;
  rollbackSummary: string;
};

export type EvolutionOverview = {
  intakeMode: string;
  currentStatus: {
    state: string;
    stage: string;
    lastResult: string;
    decision: string;
    proposalStatus: string;
    runtimeEffect: string;
    riskLevel: string;
    latestRunId: string;
    nextAction: string;
    activeAdvisoryCount: number;
    runSemantics: SupervisedRunSemantics;
    outcomeSemantics: EvolutionOutcomeSemantics;
    actionStates: Record<string, EvolutionActionState>;
  };
  recentRuns: Array<{
    id: string;
    score: number;
    status: string;
    summary: string;
    decision: string;
    proposalStatus: string;
    runtimeEffect: string;
  }>;
  recentLibrary: Array<{
    id: string;
    title: string;
    source: string;
    sourceRun: string;
  }>;
  workbench: {
    source: string;
    bundleName: string;
    datasetName: string;
    datasetLimit: number | null;
    keepWorktree: boolean | null;
    availableDatasets: number;
    runnableDatasets: number;
    blockedDatasets: number;
  };
};

export type EvolutionRun = {
  id: string;
  score: number;
  status: string;
  summary: string;
  diagnosis: string;
  decision: string;
  endedAt: string;
  bundleName: string;
  baselineScore: number;
  candidateScore: number;
  deltaScore: number;
  riskLevel: string;
  riskReasons: string[];
  proposalStatus: string;
  runtimeEffect: string;
  agentConsumption: string;
  availableActions: string[];
  nextAction: string;
  sourceDecisionPath: string;
  sourceProposalPath: string;
  activeAdvisoryCount: number;
  canDelete: boolean;
  deleteBlockReason: string;
  runSemantics: SupervisedRunSemantics;
  outcomeSemantics: EvolutionOutcomeSemantics;
  actionStates: Record<string, EvolutionActionState>;
};

export type EvolutionDatasetOption = {
  name: string;
  bundleName: string;
  available: boolean;
  runnable: boolean;
  adapterStatus: string;
  description: string;
  sourcePath: string;
  sourceExists: boolean;
  tags: string[];
  reviewRequired: boolean;
  sourceTrack: string;
  allowedDownstreamUses: string[];
  holdoutAllowed: boolean;
  rawChatDirectTrainingAllowed: boolean;
};

export type EvolutionActiveRunEvent = {
  timestamp: string;
  event: string;
  title: string;
  summary: string;
  status: string;
  caseId?: string;
  caseIndex?: number | null;
  caseTotal?: number | null;
  role?: string;
  scenario?: string;
  mode?: string;
  bundleName?: string;
  sessionId?: string;
  decision?: string;
  reason?: string;
  errorType?: string;
  elapsedSeconds?: number | null;
  resultStatus?: string;
  sourceKind?: string;
  datasetName?: string;
  datasetLimit?: number | null;
  keepWorktree?: boolean;
};

export type EvolutionActiveRunIoEntry = {
  timestamp: string;
  kind: string;
  label: string;
  content: string;
  status?: string;
};

export type EvolutionActiveRunCaseIo = {
  conversationPath: string;
  latestInput: string;
  latestOutput: string;
  latestOutputKind: string;
  latestOutputLabel: string;
  updatedAt: string;
  transcript: EvolutionActiveRunIoEntry[];
};

export type EvolutionActiveRun = {
  runId: string;
  status: string;
  currentPhase: string;
  runtimeStatus: string;
  sourceKind: string;
  sessionId: string;
  bundleName: string;
  datasetName: string;
  datasetLimit: number | null;
  keepWorktree: boolean;
  startedAt: string;
  updatedAt: string;
  finishedAt: string;
  caseTotal: number;
  currentCaseIndex: number;
  currentCaseId: string;
  currentRole: string;
  currentCaseScenario: string;
  currentCaseMode: string;
  currentCasePrompt: string;
  currentCaseIo: EvolutionActiveRunCaseIo | null;
  currentTask: string;
  decision: string;
  reason: string;
  decisionPath: string;
  policyAction: string;
  lineageIndexPath: string;
  lineageSummary: string;
  activeAdvisoryCount: number;
  pauseRequested: boolean;
  pauseRequestedAt: string;
  pausedAt: string;
  stopRequested: boolean;
  stopRequestedAt: string;
  latestMessage: string;
  eventTail: EvolutionActiveRunEvent[];
  actionStates: Record<string, EvolutionActionState>;
};

export type EvolutionActiveRunStreamEvent = {
  type: "supervised_run";
  runId: string;
  snapshot: EvolutionActiveRun;
  terminal?: boolean;
};

export type EvolutionRunDeleteResponse = {
  deleted: boolean;
  runId: string;
  clearedActive: boolean;
  clearedLatest: boolean;
  activeRunId: string;
  latestRunId: string;
  summary: string;
};

export type SelfEvolutionRunStreamEvent = {
  type: "self_evolution_run";
  runId: string;
  snapshot: SelfEvolutionActiveRun;
  terminal?: boolean;
};

export type EvolutionWorkbench = {
  defaultBundleName: string;
  savedState: EvolutionOverview["workbench"];
  datasets: EvolutionDatasetOption[];
  activeRun: EvolutionActiveRun | null;
};

export type EvolutionChatReviewCandidate = {
  candidateId: string;
  status: string;
  sessionId: string;
  topicSummary: string;
  startTurn: number;
  endTurn: number;
  turnCount: number;
  qualitySignals: string[];
  sourceLogPath: string;
  rawExcerptPath: string;
  reviewerNote: string;
  reviewedAt: string;
  conversationTurns: Array<{
    turnNumber: number;
    userMessage: string;
    assistantMessage: string;
    toolCalls: string[];
  }>;
  reviewProfile: {
    suggestedDecision: string;
    suggestedReason: string;
    learningFocus: string;
    taskClarity: {
      level: string;
      note: string;
    };
    goalStability: {
      level: string;
      note: string;
    };
    assistantLearningValue: {
      level: string;
      note: string;
    };
    antiPatternRisk: {
      level: string;
      note: string;
    };
    positiveSignals: string[];
    negativeSignals: string[];
    evidenceTurnNumbers: number[];
  };
  reviewDecision: {
    reasonCode: string;
    errorType: string;
    correctPrinciple: string;
    idealBehavior: string;
  };
  structuredSample: {
    caseId: string;
    mode: string;
    scenario: string;
    trainingTier: string;
    promptSeed: string;
    promptPreview: string;
  };
};

export type EvolutionChatReviewQueue = {
  datasetName: string;
  bundleName: string;
  positiveDatasetName: string;
  positiveBundleName: string;
  positiveDatasetPath: string;
  positiveDatasetExists: boolean;
  negativeDatasetName: string;
  negativeBundleName: string;
  negativeDatasetPath: string;
  negativeDatasetExists: boolean;
  discardAuditPath: string;
  approvedDatasetPath: string;
  approvedDatasetExists: boolean;
  pendingCount: number;
  positiveCount: number;
  negativeCount: number;
  discardCount: number;
  countsByStatus: {
    pending: number;
    positive: number;
    negative: number;
    discard: number;
  };
  approvedCount: number;
  rejectedCount: number;
  lifecycle: {
    rawChatDirectTrainingAllowed: boolean;
    candidateStage: string;
    reviewedCaseStage: string;
    datasetTarget: string;
    negativeTarget: string;
    allowedDownstreamUses: string[];
  };
  items: EvolutionChatReviewCandidate[];
};

export type EvolutionChatReviewDecisionResponse = {
  candidateId: string;
  status: string;
  datasetName: string;
  bundleName: string;
  datasetPath: string;
  caseId: string;
  summary: string;
};

export type EvolutionLibraryEntry = {
  id: string;
  title: string;
  type: string;
  sourceRun: string;
  ingestMode?: string;
  proposalStatus: string;
  runtimeEffect: string;
  decision: string;
  targetKey: string;
  targetLabel: string;
  headline: string;
  changeSummary: string;
  summary: string;
  reason?: string;
  availableActions: string[];
  updatedAt: string;
  canDelete: boolean;
  deleteBlockReason: string;
  outcomeSemantics: EvolutionOutcomeSemantics;
  actionStates: Record<string, EvolutionActionState>;
};

export type EvolutionLibraryPayload = {
  items: EvolutionLibraryEntry[];
  pending: EvolutionLibraryEntry[];
};

export type EvolutionRunActionResponse = {
  action: string;
  summary: string;
  run: EvolutionRun | null;
  lifecycle: {
    status: string;
    proposalId: string | null;
    targetKey: string | null;
    runtimeEffect: string;
    agentConsumption: string;
    availableActions: string[];
    note: string;
    error: string;
  };
};

export type EvolutionProposalDetail = {
  sessionId: string;
  sourceRun: string;
  title: string;
  type: string;
  updatedAt: string;
  decision: string;
  proposalStatus: string;
  runtimeEffect: string;
  targetKey: string;
  targetLabel: string;
  availableActions: string[];
  canDelete: boolean;
  deleteBlockReason: string;
  runSemantics: SupervisedRunSemantics;
  outcomeSemantics: EvolutionOutcomeSemantics;
  actionStates: Record<string, EvolutionActionState>;
  review: {
    headline: string;
    changeSummary: string;
    whatChanged: string[];
    whyCreated: string[];
    currentState: string[];
    nextAction: string;
    deleteImpact: string;
    canDelete: boolean;
    deleteBlockReason: string;
    evidenceNotes: string[];
  };
  supervised: {
    baselineScore: number;
    candidateScore: number;
    deltaScore: number;
    riskLevel: string;
    riskReasons: string[];
    decisionReason: string;
    activeAdvisoryCount: number;
  };
  proposal: {
    proposalId: string | null;
    episodeId: string | null;
    candidateImprovementId: string | null;
    improvementType: string;
    expectedEffect: string;
    targetLabel: string;
    target: Record<string, unknown> | null;
    payload: Record<string, unknown> | null;
    targetKey: string;
  };
  paths: {
    supervisedDecisionPath: string;
    gymProposalPath: string;
    gymDecisionPath: string;
    traceIndexPath: string;
    lineageIndexPath: string;
  };
  rawProposal: Record<string, unknown> | null;
  rawGymDecision: Record<string, unknown> | null;
  rawSupervisedDecision: Record<string, unknown> | null;
};

export type EvolutionProposalDeleteResponse = {
  sessionId: string;
  title: string;
  deleted: boolean;
  deletedPaths: string[];
  summary: string;
};

export type EvolutionProposalBulkDeleteResponse = {
  requestedCount: number;
  deletedCount: number;
  skippedCount: number;
  errorCount: number;
  summary: string;
  results: Array<{
    sessionId: string;
    status: string;
    summary: string;
    deletedPaths?: string[];
  }>;
};

export type SelfEvolutionTransaction = {
  txnId: string;
  openedAt: string;
  closedAt: string;
  baseRev: string;
  baseRevShort: string;
  status: string;
  summary: string;
  isOpen: boolean;
};

export type SelfEvolutionHistoryDeleteResponse = {
  requestedCount: number;
  deletedGroupCount: number;
  deletedAuditCount: number;
  summary: string;
  deletedTxnIds: string[];
  blockedTxnIds: string[];
};

export type SelfEvolutionAuditEvent = {
  timestamp: string;
  event: string;
  txnId: string;
  status: string;
  kind: string;
  message: string;
  toolName: string;
  baseRev: string;
  passed: boolean | null;
  targetPaths: string[];
  summary: string;
};

export type SelfEvolutionRollbackTouchedFile = {
  path: string;
  changeType: string;
  trackedBefore: boolean;
  existedBefore: boolean;
  statusAfter: string;
  preHash: string;
  postHash: string;
  postExists: boolean;
  conflict: boolean;
  conflictReason: string;
};

export type SelfEvolutionRollbackConflictFile = {
  path: string;
  reason: string;
  currentHash: string;
  expectedHash: string;
};

export type SelfEvolutionRollbackState = {
  status: string;
  reason: string;
  baseRev: string;
  rolledBackAt: string;
  entryCount: number;
  touchedFiles: SelfEvolutionRollbackTouchedFile[];
  conflictFiles: SelfEvolutionRollbackConflictFile[];
  blockedHint: string;
};

export type SelfEvolutionRun = {
  runId: string;
  goal: string;
  status: string;
  phase: string;
  startedAt: string;
  updatedAt: string;
  finishedAt: string;
  latestMessage: string;
  currentGoal: string;
  currentTask: string;
  lastToolName: string;
  runtimeStatus: string;
  toolCallCount: number;
  summary: string;
  error: string;
  cancelRequested: boolean;
  cancelRequestedAt: string;
  stopReason: string;
  controlAction: string;
  controlRequestedAt: string;
  messages: ConversationMessage[];
  turnCount: number;
  resumeCount: number;
  readingTask: string;
  readingHint: string;
  readingSufficiency: string;
  convergenceState: string;
  nextToolIntent: string;
  rollback: SelfEvolutionRollbackState;
  runSemantics: SelfEvolutionRunSemantics;
  actionStates: Record<string, EvolutionActionState>;
};

export type SelfEvolutionActiveRun = SelfEvolutionRun;
export type SelfEvolutionLatestRun = SelfEvolutionRun;

export type SelfEvolutionHandoffResponse = {
  status: string;
  message: string;
  sessionId: string;
  content: string;
  run: SelfEvolutionRun | null;
};

export type SelfEvolutionOverview = {
  enabled: boolean;
  goal: string;
  readiness: {
    state: string;
    title: string;
    summary: string;
    nextAction: string;
    reasons: string[];
  };
  sceneSemantics: SelfEvolutionSceneSemantics;
  runSemantics: SelfEvolutionRunSemantics;
  actionStates: Record<string, EvolutionActionState>;
  guardrails: string[];
  metrics: {
    activeAdvisories: number;
    dirtyFiles: number;
    recentTransactions: number;
    successRate: number | null;
    validationPassRate: number | null;
  };
  advisory: {
    activeCount: number;
    entries: Array<{
      targetKey: string;
      targetLabel: string;
      proposalId: string;
      episodeId: string;
      candidateImprovementId: string;
      activatedAt: string;
      runtimeEffect: string;
      agentConsumption: string;
      proposalPath: string;
      decisionPath: string;
      traceIndexPath: string;
    }>;
  };
  gitStatus: {
    summary: string;
    lines: string[];
  };
  recentChanges: Array<{
    path: string;
    changeType: string;
    summary: string;
  }>;
  fitness: {
    transactions: {
      opened: number;
      closed: number;
      successful: number;
      failed: number;
      successRate: number | null;
      recent: Array<{
        txnId: string;
        status: string;
        validationPassed: number;
        validationFailed: number;
        mutationsRecorded: number;
      }>;
    };
    validation: {
      passed: number;
      failed: number;
      passRate: number | null;
    };
    mutations: {
      recorded: number;
      successful: number;
      failed: number;
      blocked: number;
    };
  };
  worktree: {
    available: boolean;
    error: string;
    snapshotId: string;
    createdAt: string;
    baseRev: string;
    hasStaged: boolean;
    hasUnstaged: boolean;
    hasUntracked: boolean;
    isDirty: boolean;
    dirtyFileCount: number;
    files: Array<{
      path: string;
      status: string;
      staged: boolean;
      unstaged: boolean;
      untracked: boolean;
      deleted: boolean;
    }>;
  };
  recentTransactions: SelfEvolutionTransaction[];
  auditTail: SelfEvolutionAuditEvent[];
};

export type ConfigSummary = {
  hash: string;
  language: "zh" | "en";
  runtimeProfile: string;
  defaultMode: string;
  defaultRoute: string;
  intakeMode: string;
  modeAvailability: ModeAvailability;
  domainAvailability: DomainAvailability;
  modelLibraryCount: number;
  profileCount: number;
  blockingCount: number;
  warningCount: number;
  sections: Array<{
    id: string;
    title: string;
    summary: string;
  }>;
};

export type ConfigDraftMeta = {
  pending_api_keys: Record<string, string>;
  pending_cleared_api_keys: string[];
};

export type ConfigEditorOption = {
  value: string;
  label: string;
};

export type ConfigEditorMeta = {
  path: string;
  label: string;
  hint: string;
  kind: "object" | "object_list" | "boolean" | "select" | "number" | "string_list" | "json" | "secret" | "url" | "path" | "text";
  badge: string;
  options: ConfigEditorOption[];
};

export type ConfigEditorSection = {
  id: string;
  path: string;
  title: string;
  summary: string;
  fieldCount: number;
};

export type ConfigDiagnosis = {
  blocking_issues: string[];
  warnings: string[];
  suggested_actions: string[];
};

export type ConfigModelPresetOption = {
  preset_id: string;
  label: string;
  category?: string;
  provider_id: string;
  model_id: string;
  provider: Record<string, unknown>;
  model: Record<string, unknown>;
};

export type ConfigModelOption = {
  model_id: string;
  source: string;
  provider: Record<string, unknown>;
  provider_kind: string;
  model: string;
  label: string;
  details: Record<string, unknown>;
  api_key_env: string;
  api_key_configured: boolean;
  api_key_state: string;
};

export type ConfigProfileCard = {
  profileId: string;
  label: string;
  modelRef: string;
  selectedModelId: string;
  selectedModelLabel: string;
  model: string;
  providerKind: string;
  baseUrl: string;
  apiKeyEnv: string;
  apiKeyConfigured: boolean;
  apiKeyState: string;
  apiKeySource: string;
  requiredModelMissing: boolean;
};

export type ConfigWorkspace = ConfigSummary & {
  message: string;
  baseHash: string;
  configPath: string;
  publicConfig: Record<string, unknown>;
  rawToml: string;
  draftMeta: ConfigDraftMeta;
  diagnosis: ConfigDiagnosis;
  summary: Record<string, string | number | boolean | null>;
  editorSections: ConfigEditorSection[];
  editorMeta: Record<string, ConfigEditorMeta>;
  modelPresetOptions: ConfigModelPresetOption[];
  modelOptions: ConfigModelOption[];
  profileCards: ConfigProfileCard[];
};

export type ConfigLlmTestResult = {
  ok: boolean;
  message: string;
  profile_id: string;
  provider_id: string;
  provider_kind: string;
  base_url: string;
  model: string;
  api_key_source: string;
  config_scope: "saved" | "draft";
  requires_api_key: boolean;
};

export type PetSummary = {
  name: string;
  avatarPreset: string;
  level: number;
  exp: number;
  expToNext: number;
  mood: number;
  hunger: number;
  energy: number;
  health: number;
  love: number;
  totalTasks: number;
  achievements: string[];
  heartActive: boolean;
  inDream: boolean;
  friendCount: number;
  dailyTokens: number;
  totalTokens: number;
  statusLine: string;
};

export type ResetSummary = {
  warning: string;
  mode: "custom" | string;
  items: ResetInventoryItem[];
  protected: ResetProtectedGroup[];
  presets: Array<{
    id: string;
    label: string;
    keys: string[];
  }>;
  categories: ResetInventoryItem[];
};

export type ResetInventoryItem = {
  id: string;
  name: string;
  description: string;
  detail: string;
  risk: "low" | "medium" | "high" | string;
  defaultSelected: boolean;
  exists: boolean;
  sizeBytes: number;
  size: string;
  fileCount: number;
  candidateCount: number;
  protectedCount: number;
  missingCount: number;
  rebuildHint: string;
};

export type ResetProtectedGroup = {
  id: string;
  label: string;
  paths: string[];
  reason: string;
};

export type ResetPathEntry = {
  path: string;
  kind: string;
  action: string;
  sizeBytes?: number;
  fileCount?: number;
  status?: string;
  message?: string;
};

export type ResetItemTotals = {
  deleteCount?: number;
  deleteFileCount?: number;
  deleteSizeBytes?: number;
  deletedCount?: number;
  deletedFileCount?: number;
  deletedSizeBytes?: number;
  skippedCount: number;
  protectedCount: number;
  failedCount: number;
};

export type ResetPreviewItem = {
  id: string;
  name: string;
  risk: string;
  deleteCandidates: ResetPathEntry[];
  skipped: ResetPathEntry[];
  protected: ResetPathEntry[];
  failed: ResetPathEntry[];
  warnings: string[];
  truncated: boolean;
  summary: ResetItemTotals;
};

export type ResetExecuteItem = {
  id: string;
  name: string;
  risk: string;
  deleted: ResetPathEntry[];
  skipped: ResetPathEntry[];
  protected: ResetPathEntry[];
  failed: ResetPathEntry[];
  warnings: string[];
  truncated: boolean;
  summary: ResetItemTotals;
};

export type ResetTotals = {
  deleteCount: number;
  deleteFileCount: number;
  deleteSizeBytes: number;
  deletedCount: number;
  deletedFileCount: number;
  deletedSizeBytes: number;
  skippedCount: number;
  protectedCount: number;
  failedCount: number;
};

export type ResetPreviewResponse = {
  selectedItemIds: string[];
  items: ResetPreviewItem[];
  totals: ResetTotals;
  warnings: string[];
  rebuildHints: string[];
  summary: string;
};

export type ResetExecuteResponse = {
  selectedItemIds: string[];
  items: ResetExecuteItem[];
  totals: ResetTotals;
  warnings: string[];
  rebuildHints: string[];
  summary: string;
};
