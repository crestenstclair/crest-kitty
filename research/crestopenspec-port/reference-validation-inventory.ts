import * as fs from 'node:fs';
import * as path from 'node:path';
import type { JsonObject, JsonValue } from '../cue-architecture.js';
import { FileSystemUtils } from '../../utils/file-system.js';
import type {
  AcceptanceProof,
  AcceptanceProofRole,
  AcceptanceDiagnostic,
  AcceptanceScope,
  AssertionDeclaration,
  ProcessLimits,
  ResolvedValidation,
  RuntimeBoundary,
  RuntimeCompletionMarker,
  RuntimeEnvironment,
  RuntimeInteractionDeclaration,
  RuntimeLifecycle,
  RuntimeProgressMarker,
  RuntimeResourceDeclaration,
  RuntimeSessionProof,
  RuntimeStdioMode,
  RuntimeTeardownDeclaration,
  RuntimeTimeouts,
  TestSuiteProof,
  ValidationApplicabilityEvidence,
  ValidationDeclarationKind,
  ValidationInventory,
} from './types.js';

export const MAX_ACCEPTANCE_TIMEOUT_MS = 30 * 60 * 1000;
export const MAX_ACCEPTANCE_STREAM_BYTES = 16 * 1024 * 1024;

interface ValidationCandidate {
  id?: string;
  value: JsonValue;
  location: string;
  owner: string;
  source: 'project' | 'attached';
}

interface ValidationReference {
  id: string;
  location: string;
}

interface CollectedArchitectureValidations {
  project: ValidationCandidate[];
  attached: ValidationCandidate[];
  references: ValidationReference[];
  malformedAttachments: AcceptanceDiagnostic[];
}

function isObject(value: unknown): value is JsonObject {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function hasOwn(object: JsonObject, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(object, key);
}

function compareStrings(left: string, right: string): number {
  return left < right ? -1 : left > right ? 1 : 0;
}

function error(code: string, message: string, location: string): AcceptanceDiagnostic {
  return { severity: 'error', code, message, path: location };
}

function candidate(
  value: JsonValue,
  location: string,
  owner: string,
  source: ValidationCandidate['source']
): ValidationCandidate {
  return {
    id:
      isObject(value) && typeof value.id === 'string' && value.id.trim()
        ? value.id
        : undefined,
    value,
    location,
    owner,
    source,
  };
}

function collectContainer(
  value: JsonValue,
  location: string,
  owner: string,
  source: ValidationCandidate['source'],
  output: CollectedArchitectureValidations
): void {
  const target = source === 'project' ? output.project : output.attached;
  if (Array.isArray(value)) {
    value.forEach((entry, index) => {
      const entryLocation = `${location}[${index}]`;
      if (typeof entry === 'string') {
        output.references.push({ id: entry, location: entryLocation });
      } else if (isObject(entry)) {
        target.push(candidate(entry, entryLocation, owner, source));
      } else {
        output.malformedAttachments.push(
          error(
            'validation_attachment_malformed',
            'Validation attachments must contain declaration objects or string identity references.',
            entryLocation
          )
        );
      }
    });
    return;
  }
  if (isObject(value)) {
    for (const [name, entry] of Object.entries(value).sort(([left], [right]) =>
      compareStrings(left, right)
    )) {
      const entryLocation = `${location}.${name}`;
      if (typeof entry === 'string') {
        output.references.push({ id: entry, location: entryLocation });
      } else if (isObject(entry)) {
        target.push(candidate(entry, entryLocation, owner, source));
      } else {
        output.malformedAttachments.push(
          error(
            'validation_attachment_malformed',
            'Validation attachments must contain declaration objects or string identity references.',
            entryLocation
          )
        );
      }
    }
    return;
  }
  output.malformedAttachments.push(
    error(
      'validation_attachment_malformed',
      "A 'validations' field must be an array or object.",
      location
    )
  );
}

function collectArchitectureValidations(project: JsonObject): CollectedArchitectureValidations {
  const output: CollectedArchitectureValidations = {
    project: [],
    attached: [],
    references: [],
    malformedAttachments: [],
  };
  const projectOwner =
    typeof project.name === 'string' && project.name.trim()
      ? `project.${project.name}`
      : 'project';

  if (project.validations !== undefined) {
    collectContainer(
      project.validations,
      'project.validations',
      projectOwner,
      'project',
      output
    );
  }

  const walk = (value: JsonValue, location: string): void => {
    if (Array.isArray(value)) {
      value.forEach((entry, index) => walk(entry, `${location}[${index}]`));
      return;
    }
    if (!isObject(value)) return;
    for (const [key, entry] of Object.entries(value).sort(([left], [right]) =>
      compareStrings(left, right)
    )) {
      if (location === 'project' && key === 'validations') continue;
      const childLocation = `${location}.${key}`;
      if (key === 'validations') {
        collectContainer(entry, childLocation, location, 'attached', output);
      } else {
        walk(entry, childLocation);
      }
    }
  };
  walk(project, 'project');
  return output;
}

function parseProjectCheckReferences(
  project: JsonObject,
  diagnostics: AcceptanceDiagnostic[]
): { fieldPresent: boolean; references: ValidationReference[] } {
  const completion = project.completion;
  if (completion === undefined) return { fieldPresent: false, references: [] };
  if (!isObject(completion)) {
    diagnostics.push(
      error(
        'project_completion_malformed',
        "Evaluated project 'completion' must be an object.",
        'project.completion'
      )
    );
    return { fieldPresent: true, references: [] };
  }
  if (!hasOwn(completion, 'projectChecks')) {
    return { fieldPresent: false, references: [] };
  }
  const raw = completion.projectChecks;
  if (!Array.isArray(raw)) {
    diagnostics.push(
      error(
        'project_checks_malformed',
        "Evaluated 'completion.projectChecks' must be an array of non-empty validation IDs.",
        'project.completion.projectChecks'
      )
    );
    return { fieldPresent: true, references: [] };
  }

  const references: ValidationReference[] = [];
  const seen = new Set<string>();
  raw.forEach((value, index) => {
    const location = `project.completion.projectChecks[${index}]`;
    if (typeof value !== 'string' || !value.trim()) {
      diagnostics.push(
        error(
          'project_check_reference_malformed',
          'Every project-check reference must be a non-empty string.',
          location
        )
      );
      return;
    }
    if (seen.has(value)) {
      diagnostics.push(
        error(
          'project_check_reference_duplicate',
          `Project-check reference '${value}' is declared more than once.`,
          location
        )
      );
      return;
    }
    seen.add(value);
    references.push({ id: value, location });
  });
  return { fieldPresent: true, references };
}

function hasProof(candidate: ValidationCandidate): boolean {
  return isObject(candidate.value) && hasOwn(candidate.value, 'proof');
}

function validateGlobalIdentity(
  candidates: ValidationCandidate[],
  references: ValidationReference[],
  diagnostics: AcceptanceDiagnostic[]
): void {
  const byId = new Map<string, ValidationCandidate[]>();
  for (const entry of candidates) {
    if (!entry.id) {
      diagnostics.push(
        error(
          'validation_identity_missing',
          'Every validation declaration in an acceptance-governed project must have a non-empty string id.',
          `${entry.location}.id`
        )
      );
      continue;
    }
    const matches = byId.get(entry.id) ?? [];
    matches.push(entry);
    byId.set(entry.id, matches);
  }

  for (const [id, matches] of [...byId.entries()].sort(([left], [right]) =>
    compareStrings(left, right)
  )) {
    if (matches.length > 1) {
      diagnostics.push(
        error(
          'validation_identity_ambiguous_owner',
          `Validation identity '${id}' is declared by multiple owners: ${matches.map((match) => `${match.owner} at ${match.location}`).join('; ')}.`,
          matches[0].location
        )
      );
    }
  }

  for (const reference of references) {
    const matches = byId.get(reference.id) ?? [];
    if (matches.length === 0) {
      diagnostics.push(
        error(
          'validation_evidence_reference_orphaned',
          `Validation reference '${reference.id}' does not resolve to a declaration.`,
          reference.location
        )
      );
    } else if (matches.length > 1) {
      diagnostics.push(
        error(
          'validation_evidence_reference_ambiguous',
          `Validation reference '${reference.id}' resolves to multiple declaration owners.`,
          reference.location
        )
      );
    }
  }
}

function parseAttachedApplicability(
  candidate: ValidationCandidate,
  scope: AcceptanceScope,
  diagnostics: AcceptanceDiagnostic[]
): boolean | undefined {
  if (!isObject(candidate.value)) return undefined;
  const value = candidate.value.applicability;
  const location = `${candidate.location}.applicability`;
  if (!isObject(value)) {
    diagnostics.push(
      error(
        'validation_applicability_missing',
        'Attached proof-bearing validation requires explicit applicability metadata.',
        location
      )
    );
    return undefined;
  }
  if (value.mode === 'always') return true;
  if (value.mode !== 'changes') {
    diagnostics.push(
      error(
        'validation_applicability_malformed',
        "Attached proof applicability mode must be 'always' or 'changes'.",
        `${location}.mode`
      )
    );
    return undefined;
  }
  if (
    !Array.isArray(value.changes) ||
    value.changes.length === 0 ||
    !value.changes.every((change) => typeof change === 'string' && change.trim()) ||
    new Set(value.changes).size !== value.changes.length
  ) {
    diagnostics.push(
      error(
        'validation_applicability_malformed',
        "Change applicability requires a non-empty, unique array of change IDs.",
        `${location}.changes`
      )
    );
    return undefined;
  }
  return scope.mode === 'project' || Boolean(scope.change && value.changes.includes(scope.change));
}

function parseLimits(
  value: JsonValue | undefined,
  location: string,
  diagnostics: AcceptanceDiagnostic[]
): ProcessLimits | undefined {
  if (!isObject(value)) {
    diagnostics.push(
      error(
        'validation_limits_malformed',
        'Validation limits must be an object with timeoutMs, stdoutBytes, and stderrBytes.',
        location
      )
    );
    return undefined;
  }
  const fields = [
    ['timeoutMs', MAX_ACCEPTANCE_TIMEOUT_MS],
    ['stdoutBytes', MAX_ACCEPTANCE_STREAM_BYTES],
    ['stderrBytes', MAX_ACCEPTANCE_STREAM_BYTES],
  ] as const;
  let valid = true;
  for (const [field, maximum] of fields) {
    const fieldValue = value[field];
    if (
      typeof fieldValue !== 'number' ||
      !Number.isSafeInteger(fieldValue) ||
      fieldValue < 1 ||
      fieldValue > maximum
    ) {
      valid = false;
      diagnostics.push(
        error(
          'validation_limits_malformed',
          `'${field}' must be an integer from 1 through ${maximum}.`,
          `${location}.${field}`
        )
      );
    }
  }
  return valid
    ? {
        timeoutMs: value.timeoutMs as number,
        stdoutBytes: value.stdoutBytes as number,
        stderrBytes: value.stderrBytes as number,
      }
    : undefined;
}

function canonicalWorkingDirectory(
  projectRoot: string,
  value: JsonValue | undefined,
  location: string,
  diagnostics: AcceptanceDiagnostic[]
): string | undefined {
  if (typeof value !== 'string' || !value.trim()) {
    diagnostics.push(
      error(
        'validation_working_directory_malformed',
        "Validation 'workingDirectory' must be a non-empty path string.",
        location
      )
    );
    return undefined;
  }
  const canonicalRoot = FileSystemUtils.canonicalizeExistingPath(projectRoot);
  const candidatePath = path.resolve(canonicalRoot, value);
  try {
    if (!fs.statSync(candidatePath).isDirectory()) throw new Error('not a directory');
  } catch {
    diagnostics.push(
      error(
        'validation_working_directory_unavailable',
        `Validation working directory is unavailable: ${candidatePath}`,
        location
      )
    );
    return undefined;
  }
  const canonical = FileSystemUtils.canonicalizeExistingPath(candidatePath);
  const relative = path.relative(canonicalRoot, canonical);
  if (relative === '..' || relative.startsWith(`..${path.sep}`) || path.isAbsolute(relative)) {
    diagnostics.push(
      error(
        'validation_working_directory_outside_root',
        `Validation working directory resolves outside the canonical project root: ${canonical}`,
        location
      )
    );
    return undefined;
  }
  return canonical;
}

function parseAssertions(
  value: JsonValue | undefined,
  location: string,
  diagnostics: AcceptanceDiagnostic[]
): AssertionDeclaration[] | undefined {
  if (value === undefined) return [];
  if (!Array.isArray(value)) {
    diagnostics.push(
      error(
        'validation_assertions_malformed',
        "Validation 'assertions' must be an array when present.",
        location
      )
    );
    return undefined;
  }
  const assertions: AssertionDeclaration[] = [];
  value.forEach((entry, index) => {
    if (!isObject(entry) || typeof entry.type !== 'string' || !entry.type.trim()) {
      diagnostics.push(
        error(
          'validation_assertions_malformed',
          'Every assertion must be an object with a non-empty string type.',
          `${location}[${index}]`
        )
      );
    } else {
      assertions.push(entry as AssertionDeclaration);
    }
  });
  return assertions;
}

const ACCEPTANCE_PROOF_ROLES = new Set<AcceptanceProofRole>([
  'target-reachability',
  'static-validation',
  'in-process-behavior',
  'external-process-lifecycle',
  'production-composition-runtime',
]);

const RUNTIME_BOUNDARIES = new Set<RuntimeBoundary>([
  'external-process',
  'production-composition',
  'native-ui',
  'physical-device',
  'network-service',
  'background-worker',
  'callback-runtime',
]);

const RUNTIME_ENVIRONMENTS = new Set<RuntimeEnvironment>([
  'synthetic',
  'physical',
  'native',
  'production',
]);

const RUNTIME_LIFECYCLES = new Set<RuntimeLifecycle>([
  'bounded',
  'interactive-persistent',
  'service-persistent',
  'background-owned',
]);

function parseTestSuiteProof(
  value: JsonObject,
  location: string,
  diagnostics: AcceptanceDiagnostic[]
): TestSuiteProof | null {
  if (typeof value.provider !== 'string' || !value.provider.trim()) {
    diagnostics.push(
      error(
        'validation_proof_malformed',
        "Test-suite proof requires a non-empty 'provider'.",
        `${location}.provider`
      )
    );
    return null;
  }
  let role: AcceptanceProofRole | undefined;
  if (value.role !== undefined) {
    if (
      typeof value.role !== 'string' ||
      !ACCEPTANCE_PROOF_ROLES.has(value.role as AcceptanceProofRole)
    ) {
      diagnostics.push(
        error(
          'validation_proof_malformed',
          "Test-suite proof 'role' is not a supported proof role.",
          `${location}.role`
        )
      );
      return null;
    }
    role = value.role as AcceptanceProofRole;
    if (role !== 'in-process-behavior') {
      diagnostics.push(
        error(
          'validation_proof_role_mismatch',
          `A test-suite proof cannot satisfy the '${role}' role; declare an in-process behavior role or use a runtime-session proof for an external runtime claim.`,
          `${location}.role`
        )
      );
      return null;
    }
  }
  if (!hasOwn(value, 'selector') || value.selector === undefined) {
    diagnostics.push(
      error(
        'validation_selector_missing',
        'Test-suite proof requires an explicit opaque selector.',
        `${location}.selector`
      )
    );
    return null;
  }
  const minimumExecuted = value.minimumExecuted === undefined ? 1 : value.minimumExecuted;
  if (
    typeof minimumExecuted !== 'number' ||
    !Number.isSafeInteger(minimumExecuted) ||
    minimumExecuted < 1
  ) {
    diagnostics.push(
      error(
        'validation_proof_malformed',
        "Test-suite 'minimumExecuted' must be an integer of at least one.",
        `${location}.minimumExecuted`
      )
    );
    return null;
  }
  const options = value.options === undefined ? {} : value.options;
  if (!isObject(options)) {
    diagnostics.push(
      error(
        'validation_proof_malformed',
        "Test-suite proof 'options' must be an object when present.",
        `${location}.options`
      )
    );
    return null;
  }
  return {
    type: 'test-suite',
    provider: value.provider,
    ...(role ? { role } : {}),
    minimumExecuted,
    selector: value.selector,
    options,
  };
}

function parseRuntimeTimeouts(
  value: JsonValue | undefined,
  location: string,
  diagnostics: AcceptanceDiagnostic[]
): RuntimeTimeouts | undefined {
  if (!isObject(value)) {
    diagnostics.push(
      error(
        'runtime_timeouts_malformed',
        'Runtime proof timeouts must declare every lifecycle budget.',
        location
      )
    );
    return undefined;
  }
  const fields = [
    'startupTimeoutMs',
    'progressSilenceMs',
    'completionTimeoutMs',
    'completionToExitGraceMs',
    'teardownGraceMs',
    'hardTimeoutMs',
  ] as const;
  let valid = true;
  for (const field of fields) {
    const fieldValue = value[field];
    if (
      typeof fieldValue !== 'number' ||
      !Number.isSafeInteger(fieldValue) ||
      fieldValue < 1 ||
      fieldValue > MAX_ACCEPTANCE_TIMEOUT_MS
    ) {
      diagnostics.push(
        error(
          'runtime_timeouts_malformed',
          `'${field}' must be an integer from 1 through ${MAX_ACCEPTANCE_TIMEOUT_MS}.`,
          `${location}.${field}`
        )
      );
      valid = false;
    }
  }
  if (!valid) return undefined;
  const timeouts = Object.fromEntries(
    fields.map((field) => [field, value[field] as number])
  ) as unknown as RuntimeTimeouts;
  if (
    timeouts.startupTimeoutMs > timeouts.completionTimeoutMs ||
    timeouts.completionTimeoutMs > timeouts.hardTimeoutMs ||
    timeouts.progressSilenceMs > timeouts.hardTimeoutMs ||
    timeouts.completionToExitGraceMs > timeouts.hardTimeoutMs ||
    timeouts.teardownGraceMs > timeouts.hardTimeoutMs
  ) {
    diagnostics.push(
      error(
        'runtime_timeouts_incoherent',
        'Runtime timeout stages must fit within the completion and hard limits.',
        location
      )
    );
    return undefined;
  }
  return timeouts;
}

function parseRuntimeMarkers(
  value: JsonValue | undefined,
  phase: 'progress' | 'completion',
  location: string,
  diagnostics: AcceptanceDiagnostic[]
): RuntimeProgressMarker[] | RuntimeCompletionMarker[] | undefined {
  if (!Array.isArray(value) || value.length === 0) {
    diagnostics.push(
      error(
        'runtime_markers_malformed',
        `Runtime '${phase}' must be a non-empty marker array.`,
        location
      )
    );
    return undefined;
  }
  const output: Array<RuntimeProgressMarker | RuntimeCompletionMarker> = [];
  value.forEach((entry, index) => {
    const markerLocation = `${location}[${index}]`;
    const countField = phase === 'progress' ? 'minimumCount' : 'exactCount';
    if (
      !isObject(entry) ||
      typeof entry.id !== 'string' ||
      !entry.id.trim() ||
      (entry.stream !== 'stdout' && entry.stream !== 'stderr') ||
      typeof entry.contains !== 'string' ||
      !entry.contains ||
      typeof entry[countField] !== 'number' ||
      !Number.isSafeInteger(entry[countField]) ||
      (entry[countField] as number) < 1
    ) {
      diagnostics.push(
        error(
          'runtime_markers_malformed',
          `Each ${phase} marker requires a non-empty id and substring, a stdout/stderr stream, and a positive ${countField}.`,
          markerLocation
        )
      );
      return;
    }
    if (phase === 'progress') {
      output.push({
        id: entry.id,
        stream: entry.stream,
        contains: entry.contains,
        minimumCount: entry.minimumCount as number,
      });
    } else {
      output.push({
        id: entry.id,
        stream: entry.stream,
        contains: entry.contains,
        exactCount: entry.exactCount as number,
      });
    }
  });
  return output.length === value.length
    ? (output as RuntimeProgressMarker[] | RuntimeCompletionMarker[])
    : undefined;
}

function parseRuntimeResources(
  value: JsonValue | undefined,
  location: string,
  lifecycle: RuntimeLifecycle,
  diagnostics: AcceptanceDiagnostic[]
): RuntimeResourceDeclaration[] | undefined {
  if (!Array.isArray(value) || value.length === 0) {
    diagnostics.push(
      error(
        'runtime_resources_malformed',
        'Runtime proof resources must be a non-empty array.',
        location
      )
    );
    return undefined;
  }
  const resources: RuntimeResourceDeclaration[] = [];
  const seen = new Set<string>();
  value.forEach((entry, index) => {
    const resourceLocation = `${location}[${index}]`;
    if (
      !isObject(entry) ||
      typeof entry.id !== 'string' ||
      !entry.id.trim() ||
      typeof entry.type !== 'string' ||
      !entry.type.trim() ||
      (entry.disposition !== 'release' && entry.disposition !== 'retain-during-readiness') ||
      typeof entry.owner !== 'string' ||
      !entry.owner.trim() ||
      seen.has(entry.id)
    ) {
      diagnostics.push(
        error(
          'runtime_resources_malformed',
          'Each runtime resource requires a unique id, type, owner, and supported disposition.',
          resourceLocation
        )
      );
      return;
    }
    if (lifecycle === 'bounded' && entry.disposition !== 'release') {
      diagnostics.push(
        error(
          'runtime_resource_lifecycle_mismatch',
          'A bounded runtime cannot declare a resource retained after terminal success.',
          `${resourceLocation}.disposition`
        )
      );
      return;
    }
    seen.add(entry.id);
    resources.push(entry as unknown as RuntimeResourceDeclaration);
  });
  return resources.length === value.length ? resources : undefined;
}

function parseRuntimeInteractions(
  value: JsonValue | undefined,
  location: string,
  markerOrder: Map<string, number>,
  diagnostics: AcceptanceDiagnostic[]
): RuntimeInteractionDeclaration[] | undefined {
  if (value === undefined) return [];
  if (!Array.isArray(value)) {
    diagnostics.push(
      error('runtime_interactions_malformed', "Runtime 'interactions' must be an array.", location)
    );
    return undefined;
  }
  const interactions: RuntimeInteractionDeclaration[] = [];
  const ids = new Set<string>();
  value.forEach((entry, index) => {
    const interactionLocation = `${location}[${index}]`;
    if (
      !isObject(entry) ||
      typeof entry.id !== 'string' ||
      !entry.id.trim() ||
      ids.has(entry.id) ||
      typeof entry.provider !== 'string' ||
      !entry.provider.trim() ||
      typeof entry.opensAfter !== 'string' ||
      !markerOrder.has(entry.opensAfter) ||
      typeof entry.closesBefore !== 'string' ||
      !markerOrder.has(entry.closesBefore) ||
      entry.opensAfter === entry.closesBefore ||
      (markerOrder.get(entry.opensAfter) as number) >=
        (markerOrder.get(entry.closesBefore) as number) ||
      !isObject(entry.request) ||
      !Array.isArray(entry.requiredAssertions) ||
      entry.requiredAssertions.length === 0 ||
      !entry.requiredAssertions.every(
        (assertion) => typeof assertion === 'string' && assertion.trim()
      ) ||
      new Set(entry.requiredAssertions).size !== entry.requiredAssertions.length
    ) {
      diagnostics.push(
        error(
          'runtime_interactions_malformed',
          'Each interaction requires a unique id, provider, ordered opening/closing marker references, an object request, and unique required assertion IDs.',
          interactionLocation
        )
      );
      return;
    }
    ids.add(entry.id);
    interactions.push({
      id: entry.id,
      provider: entry.provider,
      opensAfter: entry.opensAfter,
      closesBefore: entry.closesBefore,
      request: entry.request,
      requiredAssertions: [...entry.requiredAssertions] as string[],
    });
  });
  return interactions.length === value.length ? interactions : undefined;
}

function parseRuntimeTeardown(
  value: JsonValue | undefined,
  location: string,
  lifecycle: RuntimeLifecycle,
  diagnostics: AcceptanceDiagnostic[]
): RuntimeTeardownDeclaration | undefined | null {
  if (lifecycle === 'bounded') {
    if (value !== undefined) {
      diagnostics.push(
        error(
          'runtime_lifecycle_teardown_mismatch',
          'A bounded runtime must terminate itself and cannot declare controller teardown.',
          location
        )
      );
      return null;
    }
    return undefined;
  }
  if (
    !isObject(value) ||
    typeof value.provider !== 'string' ||
    !value.provider.trim() ||
    !isObject(value.request)
  ) {
    diagnostics.push(
      error(
        'runtime_teardown_missing',
        'A persistent or background runtime requires a provider-backed controller teardown.',
        location
      )
    );
    return null;
  }
  return { provider: value.provider, request: value.request };
}

function parseRuntimeSessionProof(
  value: JsonObject,
  location: string,
  diagnostics: AcceptanceDiagnostic[]
): RuntimeSessionProof | null {
  const before = diagnostics.length;
  if (typeof value.provider !== 'string' || !value.provider.trim()) {
    diagnostics.push(
      error(
        'validation_proof_malformed',
        "Runtime-session proof requires a non-empty 'provider'.",
        `${location}.provider`
      )
    );
  }
  if (
    value.role !== 'external-process-lifecycle' &&
    value.role !== 'production-composition-runtime'
  ) {
    diagnostics.push(
      error(
        'validation_proof_role_mismatch',
        "A runtime-session proof must use role 'external-process-lifecycle' or 'production-composition-runtime'; reachability, static, and in-process roles cannot satisfy a runtime claim.",
        `${location}.role`
      )
    );
  }
  if (typeof value.entryPoint !== 'string' || !value.entryPoint.trim()) {
    diagnostics.push(
      error(
        'runtime_entry_point_malformed',
        'Runtime proof entryPoint must name the exact production entry point.',
        `${location}.entryPoint`
      )
    );
  }
  if (
    typeof value.boundary !== 'string' ||
    !RUNTIME_BOUNDARIES.has(value.boundary as RuntimeBoundary)
  ) {
    diagnostics.push(
      error('runtime_boundary_malformed', 'Runtime proof boundary is unsupported.', `${location}.boundary`)
    );
  }
  if (
    typeof value.environment !== 'string' ||
    !RUNTIME_ENVIRONMENTS.has(value.environment as RuntimeEnvironment)
  ) {
    diagnostics.push(
      error(
        'runtime_environment_malformed',
        'Runtime proof environment is unsupported.',
        `${location}.environment`
      )
    );
  }
  if (
    typeof value.lifecycle !== 'string' ||
    !RUNTIME_LIFECYCLES.has(value.lifecycle as RuntimeLifecycle)
  ) {
    diagnostics.push(
      error(
        'runtime_lifecycle_malformed',
        'Runtime proof lifecycle is unsupported.',
        `${location}.lifecycle`
      )
    );
  }
  if (typeof value.successCondition !== 'string' || !value.successCondition.trim()) {
    diagnostics.push(
      error(
        'runtime_success_condition_malformed',
        'Runtime proof successCondition must identify the authoritative condition.',
        `${location}.successCondition`
      )
    );
  }
  if (typeof value.terminationOwner !== 'string' || !value.terminationOwner.trim()) {
    diagnostics.push(
      error(
        'runtime_termination_owner_malformed',
        'Runtime proof terminationOwner must identify who owns termination.',
        `${location}.terminationOwner`
      )
    );
  }
  if (value.stdioMode !== 'pipe' && value.stdioMode !== 'pty') {
    diagnostics.push(
      error(
        'runtime_stdio_mode_malformed',
        "Runtime stdioMode must be 'pipe' or 'pty'.",
        `${location}.stdioMode`
      )
    );
  }
  if (
    typeof value.requireExitCode !== 'number' ||
    !Number.isSafeInteger(value.requireExitCode)
  ) {
    diagnostics.push(
      error(
        'runtime_exit_requirement_malformed',
        'Runtime requireExitCode must be an integer.',
        `${location}.requireExitCode`
      )
    );
  }
  if (value.requireNoDescendants !== true) {
    diagnostics.push(
      error(
        'runtime_descendant_requirement_malformed',
        'Runtime requireNoDescendants must be true so acceptance cannot leave an owned fixture process behind.',
        `${location}.requireNoDescendants`
      )
    );
  }

  const lifecycle = RUNTIME_LIFECYCLES.has(value.lifecycle as RuntimeLifecycle)
    ? (value.lifecycle as RuntimeLifecycle)
    : 'bounded';
  const timeouts = parseRuntimeTimeouts(value.timeouts, `${location}.timeouts`, diagnostics);
  const progress = parseRuntimeMarkers(
    value.progress,
    'progress',
    `${location}.progress`,
    diagnostics
  ) as RuntimeProgressMarker[] | undefined;
  const completion = parseRuntimeMarkers(
    value.completion,
    'completion',
    `${location}.completion`,
    diagnostics
  ) as RuntimeCompletionMarker[] | undefined;
  const resources = parseRuntimeResources(
    value.resources,
    `${location}.resources`,
    lifecycle,
    diagnostics
  );

  const allMarkers = [...(progress ?? []), ...(completion ?? [])];
  if (
    value.stdioMode === 'pty' &&
    allMarkers.some((marker) => marker.stream === 'stderr')
  ) {
    diagnostics.push(
      error(
        'runtime_pty_stream_mismatch',
        'PTY transport combines terminal output; PTY milestone declarations must observe stdout.',
        `${location}.stdioMode`
      )
    );
  }
  const markerIds = new Set<string>();
  const markerPredicates = new Set<string>();
  for (const [index, marker] of allMarkers.entries()) {
    const predicate = JSON.stringify([marker.stream, marker.contains]);
    if (markerIds.has(marker.id) || markerPredicates.has(predicate)) {
      diagnostics.push(
        error(
          'runtime_marker_identity_ambiguous',
          'Runtime marker IDs and stream/substring predicates must be unique within a session.',
          `${location}.${index < (progress?.length ?? 0) ? 'progress' : 'completion'}`
        )
      );
    }
    markerIds.add(marker.id);
    markerPredicates.add(predicate);
  }
  const markerOrder = new Map(allMarkers.map((marker, index) => [marker.id, index]));
  const interactions = parseRuntimeInteractions(
    value.interactions,
    `${location}.interactions`,
    markerOrder,
    diagnostics
  );
  const teardown = parseRuntimeTeardown(
    value.teardown,
    `${location}.teardown`,
    lifecycle,
    diagnostics
  );

  let requiredCapabilities: string[] | undefined;
  if (
    value.requiredCapabilities === undefined ||
    !Array.isArray(value.requiredCapabilities) ||
    !value.requiredCapabilities.every(
      (capability) => typeof capability === 'string' && capability.trim()
    ) ||
    new Set(value.requiredCapabilities).size !== value.requiredCapabilities.length
  ) {
    diagnostics.push(
      error(
        'runtime_capabilities_malformed',
        'Runtime requiredCapabilities must be a unique string array, including an empty array when no extra capability is required.',
        `${location}.requiredCapabilities`
      )
    );
  } else {
    requiredCapabilities = [...value.requiredCapabilities] as string[];
  }

  if (
    diagnostics.length !== before ||
    !timeouts ||
    !progress ||
    !completion ||
    !resources ||
    !interactions ||
    teardown === null ||
    !requiredCapabilities
  ) {
    return null;
  }
  return {
    type: 'runtime-session',
    provider: value.provider as string,
    role: value.role as RuntimeSessionProof['role'],
    entryPoint: value.entryPoint as string,
    boundary: value.boundary as RuntimeBoundary,
    environment: value.environment as RuntimeEnvironment,
    lifecycle,
    successCondition: value.successCondition as string,
    terminationOwner: value.terminationOwner as string,
    resources,
    stdioMode: value.stdioMode as RuntimeStdioMode,
    timeouts,
    progress,
    completion,
    requireExitCode: value.requireExitCode as number,
    requireNoDescendants: value.requireNoDescendants as boolean,
    requiredCapabilities,
    interactions,
    ...(teardown ? { teardown } : {}),
  };
}

function parseProof(
  value: JsonValue | undefined,
  location: string,
  diagnostics: AcceptanceDiagnostic[]
): AcceptanceProof | undefined | null {
  if (value === undefined) return undefined;
  if (!isObject(value)) {
    diagnostics.push(
      error(
        'validation_proof_malformed',
        "Validation proof must be an object with type 'test-suite' or 'runtime-session'.",
        location
      )
    );
    return null;
  }
  if (value.type === 'test-suite') {
    return parseTestSuiteProof(value, location, diagnostics);
  }
  if (value.type === 'runtime-session') {
    return parseRuntimeSessionProof(value, location, diagnostics);
  }
  diagnostics.push(
    error(
      'validation_proof_malformed',
      "Validation proof type must be 'test-suite' or 'runtime-session'.",
      `${location}.type`
    )
  );
  return null;
}

function parseExecutableValidation(
  entry: ValidationCandidate,
  expectedScope: 'project' | 'attached',
  kind: ValidationDeclarationKind,
  projectRoot: string,
  diagnostics: AcceptanceDiagnostic[],
  applicability: ValidationApplicabilityEvidence
): ResolvedValidation | undefined {
  if (!isObject(entry.value) || !entry.id) {
    diagnostics.push(
      error(
        'validation_declaration_malformed',
        'Executable validation must be an object with a unique non-empty id.',
        entry.location
      )
    );
    return undefined;
  }
  const value = entry.value;
  const before = diagnostics.length;
  if (value.scope !== expectedScope) {
    diagnostics.push(
      error(
        'validation_scope_invalid',
        `Validation '${entry.id}' must declare scope '${expectedScope}'.`,
        `${entry.location}.scope`
      )
    );
  }

  let argv: string[] | undefined;
  if (
    Array.isArray(value.command) &&
    value.command.length > 0 &&
    value.command.every((argument) => typeof argument === 'string') &&
    typeof value.command[0] === 'string' &&
    value.command[0].trim()
  ) {
    argv = [...value.command] as string[];
  } else {
    diagnostics.push(
      error(
        'validation_command_malformed',
        "Validation 'command' must be a non-empty string argument vector with a non-empty executable.",
        `${entry.location}.command`
      )
    );
  }
  const cwd = canonicalWorkingDirectory(
    projectRoot,
    value.workingDirectory,
    `${entry.location}.workingDirectory`,
    diagnostics
  );
  const limits = parseLimits(value.limits, `${entry.location}.limits`, diagnostics);
  const assertions = parseAssertions(
    value.assertions,
    `${entry.location}.assertions`,
    diagnostics
  );
  const proof = parseProof(value.proof, `${entry.location}.proof`, diagnostics);
  let declaredProofRole: AcceptanceProofRole | undefined;
  if (value.proofRole !== undefined) {
    if (
      typeof value.proofRole !== 'string' ||
      !ACCEPTANCE_PROOF_ROLES.has(value.proofRole as AcceptanceProofRole)
    ) {
      diagnostics.push(
        error(
          'validation_proof_role_malformed',
          "Validation 'proofRole' is not a supported proof role.",
          `${entry.location}.proofRole`
        )
      );
    } else {
      declaredProofRole = value.proofRole as AcceptanceProofRole;
    }
  }
  if (
    proof?.role &&
    declaredProofRole &&
    proof.role !== declaredProofRole
  ) {
    diagnostics.push(
      error(
        'validation_proof_role_mismatch',
        `Validation proofRole '${declaredProofRole}' conflicts with proof role '${proof.role}'.`,
        `${entry.location}.proofRole`
      )
    );
  }
  const proofRole =
    proof?.role ??
    declaredProofRole ??
    (proof?.type === 'test-suite' ? 'in-process-behavior' : undefined);
  if (
    proof?.type === 'test-suite' &&
    proofRole !== 'in-process-behavior'
  ) {
    diagnostics.push(
      error(
        'validation_proof_role_mismatch',
        `A test-suite proof cannot satisfy the '${proofRole}' role; external lifecycle and production composition require runtime-session proof.`,
        `${entry.location}.proofRole`
      )
    );
  }
  if (
    proof === undefined &&
    (proofRole === 'external-process-lifecycle' ||
      proofRole === 'production-composition-runtime')
  ) {
    diagnostics.push(
      error(
        'validation_proof_role_mismatch',
        `Validation proofRole '${proofRole}' requires a runtime-session proof.`,
        `${entry.location}.proofRole`
      )
    );
  }
  if (
    limits &&
    proof?.type === 'runtime-session' &&
    proof.timeouts.hardTimeoutMs > limits.timeoutMs
  ) {
    diagnostics.push(
      error(
        'runtime_timeouts_incoherent',
        `Runtime hardTimeoutMs (${proof.timeouts.hardTimeoutMs}) must not exceed the validation timeout (${limits.timeoutMs}).`,
        `${entry.location}.proof.timeouts.hardTimeoutMs`
      )
    );
  }

  if (
    diagnostics.length !== before ||
    !argv ||
    !cwd ||
    !limits ||
    !assertions ||
    proof === null
  ) {
    return undefined;
  }
  return {
    id: entry.id,
    declaration: { kind, location: entry.location, owner: entry.owner },
    argv,
    cwd,
    limits,
    assertions,
    applicability,
    ...(proofRole ? { proofRole } : {}),
    ...(proof ? { proof } : {}),
  };
}

export function resolveValidationInventory(
  project: JsonObject,
  projectRoot: string,
  scope: AcceptanceScope
): ValidationInventory {
  const diagnostics: AcceptanceDiagnostic[] = [];
  const collected = collectArchitectureValidations(project);
  const projectChecks = parseProjectCheckReferences(project, diagnostics);
  const attachedWithProof = collected.attached.filter(hasProof);
  const declared = projectChecks.fieldPresent || attachedWithProof.length > 0;
  if (!declared) {
    return {
      declared: false,
      projectCheckReferenceCount: 0,
      applicableAttachedTestCount: 0,
      applicableAttachedRuntimeSessionCount: 0,
      checks: [],
      diagnostics: [],
    };
  }

  diagnostics.push(...collected.malformedAttachments);
  const allCandidates = [...collected.project, ...collected.attached];
  validateGlobalIdentity(allCandidates, collected.references, diagnostics);

  const checks: ResolvedValidation[] = [];
  for (const reference of projectChecks.references) {
    const matches = collected.project.filter((entry) => entry.id === reference.id);
    if (matches.length === 0) {
      diagnostics.push(
        error(
          'project_check_reference_missing',
          `Project-check reference '${reference.id}' does not resolve to a top-level project validation.`,
          reference.location
        )
      );
    } else if (matches.length > 1) {
      diagnostics.push(
        error(
          'project_check_reference_ambiguous',
          `Project-check reference '${reference.id}' resolves to multiple top-level validations.`,
          reference.location
        )
      );
    } else {
      const check = parseExecutableValidation(
        matches[0],
        'project',
        'project_check',
        projectRoot,
        diagnostics,
        { mode: 'project-check' }
      );
      if (check) checks.push(check);
    }
  }

  let applicableAttachedTestCount = 0;
  let applicableAttachedRuntimeSessionCount = 0;
  for (const entry of attachedWithProof) {
    const applicable = parseAttachedApplicability(entry, scope, diagnostics);
    if (applicable !== true) continue;
    const proofType = isObject(entry.value) && isObject(entry.value.proof)
      ? entry.value.proof.type
      : undefined;
    if (proofType === 'runtime-session') {
      applicableAttachedRuntimeSessionCount++;
    } else {
      applicableAttachedTestCount++;
    }
    const check = parseExecutableValidation(
      entry,
      'attached',
      proofType === 'runtime-session' ? 'attached_runtime' : 'attached_test',
      projectRoot,
      diagnostics,
      isObject(entry.value) && isObject(entry.value.applicability) &&
        entry.value.applicability.mode === 'changes'
        ? {
            mode: 'changes',
            changes: [...(entry.value.applicability.changes as string[])],
          }
        : { mode: 'always' }
    );
    if (check) checks.push(check);
  }

  return {
    declared: true,
    projectCheckReferenceCount: projectChecks.references.length,
    applicableAttachedTestCount,
    applicableAttachedRuntimeSessionCount,
    checks,
    diagnostics,
  };
}
