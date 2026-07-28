import type { JsonObject, JsonValue } from '../cue-architecture.js';
import type {
  AcceptanceDiagnostic,
  ProcessResult,
  TestEvidence,
  TestEvidenceProvider,
  TestEvidenceResult,
  TestSuiteProof,
} from './types.js';

export const STRUCTURED_JSON_TEST_EVIDENCE_PROVIDER = 'structured-json-v1';

export class TestEvidenceProviderRegistry {
  private readonly providers = new Map<string, TestEvidenceProvider>();

  register(provider: TestEvidenceProvider): this {
    if (!provider.id.trim()) {
      throw new Error('Test-evidence provider ID must not be empty.');
    }
    if (this.providers.has(provider.id)) {
      throw new Error(`Test-evidence provider '${provider.id}' is already registered.`);
    }
    this.providers.set(provider.id, provider);
    return this;
  }

  get(id: string): TestEvidenceProvider | undefined {
    return this.providers.get(id);
  }

  list(): string[] {
    return [...this.providers.keys()].sort(compareStrings);
  }
}

function compareStrings(left: string, right: string): number {
  return left < right ? -1 : left > right ? 1 : 0;
}

function isJsonObject(value: unknown): value is JsonObject {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isJsonSafeValue(value: unknown, ancestors = new Set<object>()): value is JsonValue {
  if (
    value === null ||
    typeof value === 'string' ||
    typeof value === 'boolean'
  ) {
    return true;
  }
  if (typeof value === 'number') return Number.isFinite(value);
  if (typeof value !== 'object') return false;
  if (ancestors.has(value)) return false;
  if (
    !Array.isArray(value) &&
    Object.getPrototypeOf(value) !== Object.prototype &&
    Object.getPrototypeOf(value) !== null
  ) {
    return false;
  }

  ancestors.add(value);
  const valid = Array.isArray(value)
    ? value.every((entry) => isJsonSafeValue(entry, ancestors))
    : Object.entries(value).every(([, entry]) => isJsonSafeValue(entry, ancestors));
  ancestors.delete(value);
  return valid;
}

function isJsonSafeEvidence(value: unknown): value is TestEvidence {
  return isJsonObject(value) && isJsonSafeValue(value);
}

function stableJsonValue(value: JsonValue): JsonValue {
  if (Array.isArray(value)) return value.map(stableJsonValue);
  if (!isJsonObject(value)) return value;
  return Object.fromEntries(
    Object.entries(value)
      .sort(([left], [right]) => compareStrings(left, right))
      .map(([key, child]) => [key, stableJsonValue(child)])
  );
}

function selectorsEqual(left: JsonValue, right: JsonValue): boolean {
  return JSON.stringify(stableJsonValue(left)) === JSON.stringify(stableJsonValue(right));
}

function countDiagnostic(field: string): AcceptanceDiagnostic {
  return {
    severity: 'error',
    code: 'test_evidence_malformed',
    message: `Test evidence '${field}' must be a nonnegative integer${field === 'executed' ? '' : ' when present'}.`,
    path: `testEvidence.${field}`,
  };
}

function isNonnegativeInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
}

export function validateTestEvidence(
  evidence: TestEvidence,
  proof: TestSuiteProof
): AcceptanceDiagnostic[] {
  const diagnostics: AcceptanceDiagnostic[] = [];
  const fields = ['discovered', 'executed', 'passed', 'failed', 'skipped'] as const;

  for (const field of fields) {
    const value = evidence[field];
    if ((field === 'executed' || value !== undefined) && !isNonnegativeInteger(value)) {
      diagnostics.push(countDiagnostic(field));
    }
  }

  if (evidence.provider !== proof.provider) {
    diagnostics.push({
      severity: 'error',
      code: 'test_evidence_provider_mismatch',
      message: `Provider '${proof.provider}' returned evidence labeled '${evidence.provider}'.`,
      path: 'testEvidence.provider',
    });
  }
  if (evidence.selector === undefined || !selectorsEqual(evidence.selector, proof.selector)) {
    diagnostics.push({
      severity: 'error',
      code: 'test_evidence_selector_mismatch',
      message: 'Test evidence selector does not match the exact validation declaration.',
      path: 'testEvidence.selector',
    });
  }
  if (!isJsonObject(evidence.source)) {
    diagnostics.push({
      severity: 'error',
      code: 'test_evidence_malformed',
      message: 'Test evidence must include a structured source explanation.',
      path: 'testEvidence.source',
    });
  }

  if (!isNonnegativeInteger(evidence.executed)) {
    return diagnostics;
  }

  if (isNonnegativeInteger(evidence.passed) && evidence.passed > evidence.executed) {
    diagnostics.push({
      severity: 'error',
      code: 'test_evidence_inconsistent',
      message: `Passed count ${evidence.passed} exceeds executed count ${evidence.executed}.`,
      path: 'testEvidence.passed',
    });
  }
  if (isNonnegativeInteger(evidence.failed) && evidence.failed > evidence.executed) {
    diagnostics.push({
      severity: 'error',
      code: 'test_evidence_inconsistent',
      message: `Failed count ${evidence.failed} exceeds executed count ${evidence.executed}.`,
      path: 'testEvidence.failed',
    });
  }
  if (
    isNonnegativeInteger(evidence.passed) &&
    isNonnegativeInteger(evidence.failed) &&
    evidence.passed + evidence.failed !== evidence.executed
  ) {
    diagnostics.push({
      severity: 'error',
      code: 'test_evidence_inconsistent',
      message: `Passed (${evidence.passed}) plus failed (${evidence.failed}) must equal executed (${evidence.executed}).`,
      path: 'testEvidence',
    });
  }
  if (isNonnegativeInteger(evidence.failed) && evidence.failed > 0) {
    diagnostics.push({
      severity: 'error',
      code: 'test_evidence_failed_tests',
      message: `Test evidence reports ${evidence.failed} failed test(s).`,
      path: 'testEvidence.failed',
    });
  }
  if (
    isNonnegativeInteger(evidence.discovered) &&
    evidence.discovered < evidence.executed
  ) {
    diagnostics.push({
      severity: 'error',
      code: 'test_evidence_inconsistent',
      message: `Discovered count ${evidence.discovered} is less than executed count ${evidence.executed}.`,
      path: 'testEvidence.discovered',
    });
  }
  if (
    isNonnegativeInteger(evidence.discovered) &&
    isNonnegativeInteger(evidence.skipped) &&
    evidence.discovered < evidence.executed + evidence.skipped
  ) {
    diagnostics.push({
      severity: 'error',
      code: 'test_evidence_inconsistent',
      message: `Discovered count ${evidence.discovered} is less than executed plus skipped (${evidence.executed + evidence.skipped}).`,
      path: 'testEvidence.discovered',
    });
  }
  if (evidence.executed < proof.minimumExecuted) {
    diagnostics.push({
      severity: 'error',
      code: 'test_evidence_minimum_not_met',
      message: `Executed ${evidence.executed} test(s); at least ${proof.minimumExecuted} must execute.`,
      path: 'testEvidence.executed',
    });
  }

  return diagnostics;
}

const structuredJsonProvider: TestEvidenceProvider = {
  id: STRUCTURED_JSON_TEST_EVIDENCE_PROVIDER,
  extract({ proof, process }) {
    const stream = proof.options.stream;
    if (stream !== 'stdout' && stream !== 'stderr') {
      throw new Error("Option 'stream' must be exactly 'stdout' or 'stderr'.");
    }
    const document = process[stream].trim();
    if (!document) {
      throw new Error(`The selected ${stream} stream is empty.`);
    }

    let parsed: unknown;
    try {
      parsed = JSON.parse(document);
    } catch (error) {
      throw new Error(
        `The selected ${stream} stream is not one JSON document: ${error instanceof Error ? error.message : String(error)}`
      );
    }
    if (!isJsonObject(parsed)) {
      throw new Error('The structured test-evidence document must be a JSON object.');
    }
    if (!isJsonObject(parsed.source)) {
      throw new Error("The structured test-evidence document requires an object-valued 'source'.");
    }
    if (!('selector' in parsed) || parsed.selector === undefined) {
      throw new Error("The structured test-evidence document requires a 'selector'.");
    }

    const evidence = {
      provider: this.id,
      selector: parsed.selector,
      ...('discovered' in parsed ? { discovered: parsed.discovered } : {}),
      executed: parsed.executed,
      ...('passed' in parsed ? { passed: parsed.passed } : {}),
      ...('failed' in parsed ? { failed: parsed.failed } : {}),
      ...('skipped' in parsed ? { skipped: parsed.skipped } : {}),
      source: {
        kind: 'process-stream',
        stream,
        format: STRUCTURED_JSON_TEST_EVIDENCE_PROVIDER,
        report: parsed.source,
      },
    };
    return evidence as unknown as TestEvidence;
  },
};

export function createDefaultTestEvidenceRegistry(): TestEvidenceProviderRegistry {
  return new TestEvidenceProviderRegistry().register(structuredJsonProvider);
}

export async function extractTestEvidence(
  proof: TestSuiteProof,
  process: ProcessResult,
  registry: TestEvidenceProviderRegistry
): Promise<TestEvidenceResult> {
  const provider = registry.get(proof.provider);
  if (!provider) {
    return {
      provider: proof.provider,
      minimumExecuted: proof.minimumExecuted,
      selector: proof.selector,
      status: 'failed',
      diagnostics: [
        {
          severity: 'error',
          code: 'test_evidence_provider_unsupported',
          message: `No test-evidence provider is registered for '${proof.provider}'.`,
          path: 'proof.provider',
        },
      ],
    };
  }

  try {
    const extracted: unknown = await provider.extract({ proof, process });
    if (!isJsonSafeEvidence(extracted)) {
      return {
        provider: proof.provider,
        minimumExecuted: proof.minimumExecuted,
        selector: proof.selector,
        status: 'failed',
        diagnostics: [
          {
            severity: 'error',
            code: 'test_evidence_malformed',
            message: `Test-evidence provider '${proof.provider}' returned a value that is not a finite, acyclic JSON object.`,
            path: 'testEvidence',
          },
        ],
      };
    }
    const evidence = extracted;
    const diagnostics = validateTestEvidence(evidence, proof);
    return {
      provider: proof.provider,
      minimumExecuted: proof.minimumExecuted,
      selector: proof.selector,
      status: diagnostics.some((diagnostic) => diagnostic.severity === 'error')
        ? 'failed'
        : 'passed',
      evidence,
      diagnostics,
    };
  } catch (error) {
    return {
      provider: proof.provider,
      minimumExecuted: proof.minimumExecuted,
      selector: proof.selector,
      status: 'failed',
      diagnostics: [
        {
          severity: 'error',
          code: 'test_evidence_provider_error',
          message: `Test-evidence provider '${proof.provider}' failed: ${error instanceof Error ? error.message : String(error)}`,
          path: 'proof.provider',
        },
      ],
    };
  }
}
