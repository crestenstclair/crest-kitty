import type { JsonObject, JsonValue } from '../cue-architecture.js';
import type { RootOutput } from '../root-selection.js';
import type { ValidationIssue } from '../validation/types.js';

export const ACCEPTANCE_REPORT_VERSION = '2.0' as const;

export type AcceptanceGateStatus = 'passed' | 'failed' | 'not_applicable';
export type AcceptanceScopeMode = 'change' | 'project';

export interface AcceptanceDiagnostic {
  severity: 'error' | 'warning' | 'info';
  code: string;
  message: string;
  path?: string;
  fix?: string;
}

export interface AcceptanceGateResult {
  status: AcceptanceGateStatus;
  diagnostics: AcceptanceDiagnostic[];
}

export interface ArchitectureGateResult extends AcceptanceGateResult {
  root?: string;
  files: string[];
}

export type OpenSpecValidationItemType =
  | 'change'
  | 'proposal'
  | 'spec'
  | 'future_spec';

export interface OpenSpecValidationItem {
  id: string;
  type: OpenSpecValidationItemType;
  path: string;
  valid: boolean;
  issues: ValidationIssue[];
}

export interface OpenSpecValidationGateResult extends AcceptanceGateResult {
  items: OpenSpecValidationItem[];
}

export interface ProcessLimits {
  timeoutMs: number;
  stdoutBytes: number;
  stderrBytes: number;
}

export interface ProcessExecutionRequest {
  argv: string[];
  cwd: string;
  limits: ProcessLimits;
}

export type ProcessTermination =
  | 'exited'
  | 'signaled'
  | 'timed_out'
  | 'output_limit'
  | 'spawn_error';

export interface ProcessSpawnError {
  code?: string;
  message: string;
}

export interface ProcessResult {
  argv: string[];
  cwd: string;
  limits: ProcessLimits;
  durationMs: number;
  termination: ProcessTermination;
  exitCode: number | null;
  signal: string | null;
  timedOut: boolean;
  outputLimitExceeded: Array<'stdout' | 'stderr'>;
  spawnError?: ProcessSpawnError;
  stdout: string;
  stderr: string;
  stdoutTruncated: boolean;
  stderrTruncated: boolean;
}

export interface CommandRunner {
  run(request: ProcessExecutionRequest): Promise<ProcessResult>;
}

export interface AssertionDeclaration extends JsonObject {
  type: string;
}

export interface AssertionResult {
  index: number;
  type: string;
  passed: boolean;
  expected?: JsonValue;
  observed?: JsonValue;
  diagnostic?: AcceptanceDiagnostic;
}

export interface TestSuiteProof {
  type: 'test-suite';
  provider: string;
  role?: AcceptanceProofRole;
  minimumExecuted: number;
  selector: JsonValue;
  options: JsonObject;
}

export type AcceptanceProofRole =
  | 'target-reachability'
  | 'static-validation'
  | 'in-process-behavior'
  | 'external-process-lifecycle'
  | 'production-composition-runtime';

export type RuntimeBoundary =
  | 'external-process'
  | 'production-composition'
  | 'native-ui'
  | 'physical-device'
  | 'network-service'
  | 'background-worker'
  | 'callback-runtime';

export type RuntimeEnvironment = 'synthetic' | 'physical' | 'native' | 'production';

export type RuntimeLifecycle =
  | 'bounded'
  | 'interactive-persistent'
  | 'service-persistent'
  | 'background-owned';

export type RuntimeStdioMode = 'pipe' | 'pty';
export type RuntimeStream = 'stdout' | 'stderr';

export interface RuntimeTimeouts {
  startupTimeoutMs: number;
  progressSilenceMs: number;
  completionTimeoutMs: number;
  completionToExitGraceMs: number;
  teardownGraceMs: number;
  hardTimeoutMs: number;
}

export interface RuntimeProgressMarker {
  id: string;
  stream: RuntimeStream;
  contains: string;
  minimumCount: number;
}

export interface RuntimeCompletionMarker {
  id: string;
  stream: RuntimeStream;
  contains: string;
  exactCount: number;
}

export interface RuntimeResourceDeclaration {
  id: string;
  type: string;
  disposition: 'release' | 'retain-during-readiness';
  owner: string;
}

export interface RuntimeInteractionDeclaration {
  id: string;
  provider: string;
  opensAfter: string;
  closesBefore: string;
  request: JsonObject;
  requiredAssertions: string[];
}

export interface RuntimeTeardownDeclaration {
  provider: string;
  request: JsonObject;
}

export interface RuntimeSessionProof {
  type: 'runtime-session';
  provider: string;
  role: 'external-process-lifecycle' | 'production-composition-runtime';
  entryPoint: string;
  boundary: RuntimeBoundary;
  environment: RuntimeEnvironment;
  lifecycle: RuntimeLifecycle;
  successCondition: string;
  terminationOwner: string;
  resources: RuntimeResourceDeclaration[];
  stdioMode: RuntimeStdioMode;
  timeouts: RuntimeTimeouts;
  progress: RuntimeProgressMarker[];
  completion: RuntimeCompletionMarker[];
  requireExitCode: number;
  requireNoDescendants: boolean;
  requiredCapabilities: string[];
  interactions: RuntimeInteractionDeclaration[];
  teardown?: RuntimeTeardownDeclaration;
}

export type AcceptanceProof = TestSuiteProof | RuntimeSessionProof;

export interface AcceptanceProofSummary {
  type: AcceptanceProof['type'];
  provider: string;
  role?: AcceptanceProofRole;
}

export interface ValidationApplicabilityEvidence {
  mode: 'project-check' | 'always' | 'changes';
  changes?: string[];
}

export interface TestEvidence {
  provider: string;
  selector: JsonValue;
  discovered?: number;
  executed: number;
  passed?: number;
  failed?: number;
  skipped?: number;
  source: JsonObject;
}

export interface TestEvidenceResult {
  provider: string;
  minimumExecuted: number;
  selector: JsonValue;
  status: 'passed' | 'failed';
  evidence?: TestEvidence;
  diagnostics: AcceptanceDiagnostic[];
}

export interface ResolvedValidation {
  id: string;
  declaration: ValidationDeclarationProvenance;
  argv: string[];
  cwd: string;
  limits: ProcessLimits;
  assertions: AssertionDeclaration[];
  applicability: ValidationApplicabilityEvidence;
  proofRole?: AcceptanceProofRole;
  proof?: AcceptanceProof;
}

export interface RuntimeMarkerOccurrence {
  elapsedMs: number;
  offset: number;
  sequence: number;
}

export interface RuntimeMarkerObservation {
  id: string;
  phase: 'progress' | 'completion';
  stream: RuntimeStream;
  contains: string;
  expected: { minimumCount: number } | { exactCount: number };
  observedCount: number;
  passed: boolean;
  occurrences: RuntimeMarkerOccurrence[];
}

export interface RuntimeInteractionAssertionEvidence {
  id: string;
  passed: boolean;
  expected?: JsonValue;
  observed?: JsonValue;
}

export interface RuntimeInteractionProviderEvidence {
  sessionId: string;
  actionId: string;
  attempted: boolean;
  reachedSeam: boolean;
  deliveredAtMs: number;
  assertions: RuntimeInteractionAssertionEvidence[];
  details: JsonObject;
}

export interface RuntimeInteractionEvidence {
  id: string;
  provider: string;
  opensAfter: string;
  closesBefore: string;
  invokedAtMs?: number;
  completedAtMs?: number;
  openingObservedAtMs?: number;
  closingObservedAtMs?: number;
  status: 'passed' | 'failed';
  evidence?: RuntimeInteractionProviderEvidence;
  diagnostics: AcceptanceDiagnostic[];
}

export interface RuntimeTerminationAction {
  elapsedMs: number;
  action: string;
  target: string;
  succeeded: boolean;
  detail?: string;
}

export interface RuntimeProcessTreeEvidence {
  parentPid: number | null;
  processGroupId: number | null;
  observedPids: number[];
  observedDescendantPids: number[];
  remainingPids: number[];
  parentExitedAtMs?: number;
  noOwnedProcessesRemain: boolean;
}

export type RuntimeTimeoutStage =
  | 'startup'
  | 'progress_silence'
  | 'completion'
  | 'completion_to_exit'
  | 'teardown'
  | 'hard_limit';

export interface RuntimeSessionEvidence {
  sessionId: string;
  provider: string;
  proof: RuntimeSessionProof;
  argv: string[];
  cwd: string;
  durationMs: number;
  startupObservedAtMs?: number;
  completionObservedAtMs?: number;
  timeoutStage?: RuntimeTimeoutStage;
  milestones: RuntimeMarkerObservation[];
  interactions: RuntimeInteractionEvidence[];
  processTree: RuntimeProcessTreeEvidence;
  terminationActions: RuntimeTerminationAction[];
  teardown: {
    required: boolean;
    provider?: string;
    startedAtMs?: number;
    completedAtMs?: number;
    passed: boolean;
  };
}

export interface RuntimeSessionEvidenceResult {
  provider: string;
  status: 'passed' | 'failed';
  proof: RuntimeSessionProof;
  evidence?: RuntimeSessionEvidence;
  diagnostics: AcceptanceDiagnostic[];
}

export interface AcceptanceCheckResult {
  id: string;
  declaration: ValidationDeclarationProvenance;
  applicability: ValidationApplicabilityEvidence;
  proofRole?: AcceptanceProofRole;
  proof?: AcceptanceProofSummary;
  process: ProcessResult;
  processPassed: boolean;
  assertions: AssertionResult[];
  assertionsPassed: boolean;
  testEvidence?: TestEvidenceResult;
  runtimeSession?: RuntimeSessionEvidenceResult;
  passed: boolean;
  diagnostics: AcceptanceDiagnostic[];
}

export type ValidationDeclarationKind =
  | 'project_check'
  | 'attached_test'
  | 'attached_runtime';

export interface ValidationDeclarationProvenance {
  kind: ValidationDeclarationKind;
  location: string;
  owner: string;
}

export interface ValidationExecutionGateResult extends AcceptanceGateResult {
  declaredProjectChecks: number;
  applicableAttachedTests: number;
  applicableAttachedRuntimeSessions: number;
  resolved: number;
  executed: number;
}

export interface AcceptanceScope {
  mode: AcceptanceScopeMode;
  change?: string;
}

export interface SemanticReviewBoundary {
  status: 'not_evaluated';
  message: string;
}

export interface AcceptanceReport {
  version: typeof ACCEPTANCE_REPORT_VERSION;
  scope: AcceptanceScope;
  root: RootOutput | null;
  applicable: boolean;
  passed: boolean;
  gates: {
    architecture: ArchitectureGateResult;
    openspec: OpenSpecValidationGateResult;
    validations: ValidationExecutionGateResult;
  };
  checks: AcceptanceCheckResult[];
  diagnostics: AcceptanceDiagnostic[];
  semanticReview: SemanticReviewBoundary;
}

export interface AcceptanceRunOptions {
  scope: AcceptanceScope;
}

export interface ValidationInventory {
  declared: boolean;
  projectCheckReferenceCount: number;
  applicableAttachedTestCount: number;
  applicableAttachedRuntimeSessionCount: number;
  checks: ResolvedValidation[];
  diagnostics: AcceptanceDiagnostic[];
}

export interface TestEvidenceProviderRequest {
  proof: TestSuiteProof;
  process: ProcessResult;
}

export interface RuntimeSessionProviderRequest {
  proof: RuntimeSessionProof;
  argv: string[];
  cwd: string;
  limits: ProcessLimits;
  declaration: ValidationDeclarationProvenance;
}

export interface RuntimeSessionProviderResult {
  process: ProcessResult;
  runtimeSession: RuntimeSessionEvidenceResult;
}

export interface RuntimeSessionProvider {
  readonly id: string;
  run(request: RuntimeSessionProviderRequest): Promise<RuntimeSessionProviderResult>;
}

export interface RuntimeInteractionProviderRequest {
  sessionId: string;
  sessionStartedAtEpochMs: number;
  action: RuntimeInteractionDeclaration;
  cwd: string;
  limits: ProcessLimits;
  milestones: RuntimeMarkerObservation[];
}

export interface RuntimeInteractionProvider {
  readonly id: string;
  invoke(
    request: RuntimeInteractionProviderRequest
  ): Promise<RuntimeInteractionProviderEvidence>;
}

export interface TestEvidenceProvider {
  readonly id: string;
  extract(request: TestEvidenceProviderRequest): Promise<TestEvidence> | TestEvidence;
}

export interface AssertionEvaluator {
  readonly type: string;
  evaluate(
    declaration: AssertionDeclaration,
    process: ProcessResult,
    index: number
  ): Promise<AssertionResult> | AssertionResult;
}

export const SEMANTIC_REVIEW_BOUNDARY: SemanticReviewBoundary = {
  status: 'not_evaluated',
  message:
    'Deterministic acceptance does not establish semantic implementation conformance; use the adversarial agent review for that separate evidence layer.',
};
