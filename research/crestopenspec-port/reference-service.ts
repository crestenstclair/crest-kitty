import type { CueArchitecture } from '../cue-architecture.js';
import { loadCueArchitecture } from '../cue-architecture.js';
import type { ResolvedOpenSpecRoot, RootOutput } from '../root-selection.js';
import { toRootOutput } from '../root-selection.js';
import {
  createDefaultAssertionRegistry,
  evaluateAssertions,
  assertionDiagnostics,
  type AssertionEvaluatorRegistry,
} from './assertions.js';
import { resolveValidationInventory } from './validation-inventory.js';
import {
  runStrictOpenSpecValidation,
  type StrictOpenSpecValidationResult,
} from './openspec-validation.js';
import { NodeCommandRunner } from './process-runner.js';
import {
  createDefaultRuntimeSessionRegistry,
} from './runtime-session.js';
import type { RuntimeSessionProviderRegistry } from './runtime-providers.js';
import {
  createDefaultTestEvidenceRegistry,
  extractTestEvidence,
  type TestEvidenceProviderRegistry,
} from './test-evidence.js';
import {
  ACCEPTANCE_REPORT_VERSION,
  SEMANTIC_REVIEW_BOUNDARY,
  type AcceptanceCheckResult,
  type AcceptanceDiagnostic,
  type AcceptanceReport,
  type AcceptanceRunOptions,
  type AcceptanceScope,
  type CommandRunner,
  type ProcessExecutionRequest,
  type ProcessResult,
  type RuntimeSessionEvidenceResult,
  type ValidationInventory,
} from './types.js';

export interface AcceptanceServiceDependencies {
  cueLoader?: (projectRoot: string) => CueArchitecture | undefined;
  commandRunner?: CommandRunner;
  assertionRegistry?: AssertionEvaluatorRegistry;
  testEvidenceRegistry?: TestEvidenceProviderRegistry;
  runtimeSessionRegistry?: RuntimeSessionProviderRegistry;
  strictValidation?: (
    root: ResolvedOpenSpecRoot,
    scope: AcceptanceScope
  ) => Promise<StrictOpenSpecValidationResult>;
}

function reportSkeleton(
  scope: AcceptanceScope,
  root: RootOutput | null
): Omit<AcceptanceReport, 'applicable' | 'passed'> {
  return {
    version: ACCEPTANCE_REPORT_VERSION,
    scope,
    root,
    gates: {
      architecture: { status: 'not_applicable', files: [], diagnostics: [] },
      openspec: { status: 'not_applicable', items: [], diagnostics: [] },
      validations: {
        status: 'not_applicable',
        declaredProjectChecks: 0,
        applicableAttachedTests: 0,
        applicableAttachedRuntimeSessions: 0,
        resolved: 0,
        executed: 0,
        diagnostics: [],
      },
    },
    checks: [],
    diagnostics: [],
    semanticReview: SEMANTIC_REVIEW_BOUNDARY,
  };
}

export function createAcceptanceFailureReport(
  scope: AcceptanceScope,
  diagnostic: AcceptanceDiagnostic,
  root: RootOutput | null = null
): AcceptanceReport {
  const report = reportSkeleton(scope, root);
  report.gates.architecture = {
    status: 'failed',
    files: [],
    diagnostics: [diagnostic],
  };
  report.diagnostics = [diagnostic];
  return { ...report, applicable: true, passed: false };
}

function processFailureDiagnostic(result: ProcessResult): AcceptanceDiagnostic | undefined {
  if (result.termination === 'spawn_error') {
    return {
      severity: 'error',
      code: 'validation_spawn_failed',
      message: result.spawnError?.code
        ? `Could not start validation (${result.spawnError.code}): ${result.spawnError.message}`
        : `Could not start validation: ${result.spawnError?.message ?? 'unknown spawn error'}`,
    };
  }
  if (result.termination === 'timed_out') {
    return {
      severity: 'error',
      code: 'validation_timed_out',
      message: `Validation exceeded its ${result.limits.timeoutMs} ms timeout.`,
    };
  }
  if (result.termination === 'output_limit') {
    return {
      severity: 'error',
      code: 'validation_output_limit',
      message: `Validation exceeded its declared ${result.outputLimitExceeded.join(' and ')} capture limit.`,
    };
  }
  if (result.termination === 'signaled') {
    return {
      severity: 'error',
      code: 'validation_signaled',
      message: `Validation terminated by signal ${result.signal ?? 'unknown'}.`,
    };
  }
  if (result.exitCode !== 0) {
    return {
      severity: 'error',
      code: 'validation_nonzero_exit',
      message: `Validation exited with code ${result.exitCode === null ? 'none' : result.exitCode}.`,
    };
  }
  return undefined;
}

function unexpectedProcessResult(
  request: ProcessExecutionRequest,
  error: unknown
): ProcessResult {
  return {
    argv: [...request.argv],
    cwd: request.cwd,
    limits: { ...request.limits },
    durationMs: 0,
    termination: 'spawn_error',
    exitCode: null,
    signal: null,
    timedOut: false,
    outputLimitExceeded: [],
    spawnError: {
      message: `Command runner failed: ${error instanceof Error ? error.message : String(error)}`,
    },
    stdout: '',
    stderr: '',
    stdoutTruncated: false,
    stderrTruncated: false,
  };
}

function downstreamFailure(
  code: string,
  message: string
): AcceptanceDiagnostic {
  return { severity: 'error', code, message };
}

export class AcceptanceService {
  private readonly cueLoader: (projectRoot: string) => CueArchitecture | undefined;
  private readonly commandRunner: CommandRunner;
  private readonly assertionRegistry: AssertionEvaluatorRegistry;
  private readonly testEvidenceRegistry: TestEvidenceProviderRegistry;
  private readonly runtimeSessionRegistry: RuntimeSessionProviderRegistry;
  private readonly strictValidation: NonNullable<
    AcceptanceServiceDependencies['strictValidation']
  >;

  constructor(dependencies: AcceptanceServiceDependencies = {}) {
    this.cueLoader = dependencies.cueLoader ?? loadCueArchitecture;
    this.commandRunner = dependencies.commandRunner ?? new NodeCommandRunner();
    this.assertionRegistry =
      dependencies.assertionRegistry ?? createDefaultAssertionRegistry();
    this.testEvidenceRegistry =
      dependencies.testEvidenceRegistry ?? createDefaultTestEvidenceRegistry();
    this.runtimeSessionRegistry =
      dependencies.runtimeSessionRegistry ?? createDefaultRuntimeSessionRegistry();
    this.strictValidation = dependencies.strictValidation ?? runStrictOpenSpecValidation;
  }

  async run(
    root: ResolvedOpenSpecRoot,
    options: AcceptanceRunOptions
  ): Promise<AcceptanceReport> {
    const base = reportSkeleton(options.scope, toRootOutput(root));
    let architecture: CueArchitecture | undefined;

    try {
      architecture = this.cueLoader(root.path);
    } catch (cause) {
      const diagnostic: AcceptanceDiagnostic = {
        severity: 'error',
        code: 'cue_architecture_evaluation_failed',
        message: cause instanceof Error ? cause.message : String(cause),
        path: root.path,
      };
      base.gates.architecture = {
        status: 'failed',
        files: [],
        diagnostics: [diagnostic],
      };
      base.diagnostics = [diagnostic];
      return { ...base, applicable: true, passed: false };
    }

    if (!architecture) {
      const diagnostic: AcceptanceDiagnostic = {
        severity: 'info',
        code: 'acceptance_not_applicable_no_cue',
        message: 'No top-level CUE package is present; deterministic acceptance gates are not applicable.',
      };
      base.gates.architecture = {
        status: 'not_applicable',
        files: [],
        diagnostics: [diagnostic],
      };
      base.diagnostics = [diagnostic];
      return { ...base, applicable: false, passed: true };
    }

    base.gates.architecture = {
      status: 'passed',
      root: architecture.root,
      files: [...architecture.files],
      diagnostics: [],
    };

    const resolution = resolveValidationInventory(
      architecture.project,
      root.path,
      options.scope
    );
    if (!resolution.declared) {
      const diagnostic: AcceptanceDiagnostic = {
        severity: 'info',
        code: 'acceptance_not_applicable_no_executable_validations',
        message: 'Evaluated CUE declares neither project completion checks nor attached test/runtime validations; executable acceptance gates are not applicable.',
        path: 'project',
      };
      base.gates.validations = {
        status: 'not_applicable',
        declaredProjectChecks: 0,
        applicableAttachedTests: 0,
        applicableAttachedRuntimeSessions: 0,
        resolved: 0,
        executed: 0,
        diagnostics: [diagnostic],
      };
      base.diagnostics = [diagnostic];
      return { ...base, applicable: false, passed: true };
    }

    if (resolution.diagnostics.some((diagnostic) => diagnostic.severity === 'error')) {
      return this.resolutionFailure(base, resolution);
    }

    let validation: StrictOpenSpecValidationResult;
    try {
      validation = await this.strictValidation(root, options.scope);
    } catch (cause) {
      const diagnostic = downstreamFailure(
        'openspec_validation_internal_error',
        `Strict OpenSpec validation failed unexpectedly: ${cause instanceof Error ? cause.message : String(cause)}`
      );
      base.gates.openspec = {
        status: 'failed',
        items: [],
        diagnostics: [diagnostic],
      };
      base.gates.validations = {
        status: 'failed',
        declaredProjectChecks: resolution.projectCheckReferenceCount,
        applicableAttachedTests: resolution.applicableAttachedTestCount,
        applicableAttachedRuntimeSessions:
          resolution.applicableAttachedRuntimeSessionCount,
        resolved: resolution.checks.length,
        executed: 0,
        diagnostics: [
          downstreamFailure(
            'validations_not_executed_openspec_error',
            'Executable validations were not run because strict OpenSpec validation did not complete.'
          ),
        ],
      };
      base.diagnostics = [diagnostic, ...base.gates.validations.diagnostics];
      return { ...base, applicable: true, passed: false };
    }
    const validationFailed =
      validation.items.some((item) => !item.valid) ||
      validation.diagnostics.some((diagnostic) => diagnostic.severity === 'error');
    base.gates.openspec = {
      status: validationFailed ? 'failed' : 'passed',
      items: validation.items,
      diagnostics: validation.diagnostics,
    };
    if (validationFailed) {
      const blocked = downstreamFailure(
        'validations_not_executed_openspec_failed',
        'Executable validations were not run because strict OpenSpec validation failed.'
      );
      base.gates.validations = {
        status: 'failed',
        declaredProjectChecks: resolution.projectCheckReferenceCount,
        applicableAttachedTests: resolution.applicableAttachedTestCount,
        applicableAttachedRuntimeSessions:
          resolution.applicableAttachedRuntimeSessionCount,
        resolved: resolution.checks.length,
        executed: 0,
        diagnostics: [blocked],
      };
      base.diagnostics = [...validation.diagnostics, blocked];
      return { ...base, applicable: true, passed: false };
    }

    const checks: AcceptanceCheckResult[] = [];
    for (const check of resolution.checks) {
      checks.push(await this.executeCheck(check));
    }
    base.checks = checks;
    const checkDiagnostics = checks.flatMap((check) =>
      check.passed
        ? []
        : [
            {
              severity: 'error' as const,
              code: 'validation_failed',
              message: `Validation '${check.id}' failed.`,
              path: `checks.${check.id}`,
            },
          ]
    );
    const checksPassed = checks.every((check) => check.passed);
    base.gates.validations = {
      status: checksPassed ? 'passed' : 'failed',
      declaredProjectChecks: resolution.projectCheckReferenceCount,
      applicableAttachedTests: resolution.applicableAttachedTestCount,
      applicableAttachedRuntimeSessions:
        resolution.applicableAttachedRuntimeSessionCount,
      resolved: resolution.checks.length,
      executed: checks.length,
      diagnostics: checkDiagnostics,
    };
    base.diagnostics = checkDiagnostics;
    return { ...base, applicable: true, passed: checksPassed };
  }

  private resolutionFailure(
    base: Omit<AcceptanceReport, 'applicable' | 'passed'>,
    resolution: ValidationInventory
  ): AcceptanceReport {
    const validationBlocked = downstreamFailure(
      'openspec_validation_not_executed_declarations_failed',
      'Strict OpenSpec validation was not executed because the validation inventory is invalid.'
    );
    base.gates.openspec = {
      status: 'failed',
      items: [],
      diagnostics: [validationBlocked],
    };
    base.gates.validations = {
      status: 'failed',
      declaredProjectChecks: resolution.projectCheckReferenceCount,
      applicableAttachedTests: resolution.applicableAttachedTestCount,
      applicableAttachedRuntimeSessions:
        resolution.applicableAttachedRuntimeSessionCount,
      resolved: resolution.checks.length,
      executed: 0,
      diagnostics: resolution.diagnostics,
    };
    base.diagnostics = [...resolution.diagnostics, validationBlocked];
    return { ...base, applicable: true, passed: false };
  }

  private async executeCheck(
    check: ValidationInventory['checks'][number]
  ): Promise<AcceptanceCheckResult> {
    const request: ProcessExecutionRequest = {
      argv: check.argv,
      cwd: check.cwd,
      limits: check.limits,
    };
    let process: ProcessResult;
    let runtimeSession: RuntimeSessionEvidenceResult | undefined;
    if (check.proof?.type === 'runtime-session') {
      const provider = this.runtimeSessionRegistry.get(check.proof.provider);
      if (!provider) {
        process = unexpectedProcessResult(
          request,
          new Error(`No runtime-session provider is registered for '${check.proof.provider}'.`)
        );
        runtimeSession = {
          provider: check.proof.provider,
          status: 'failed',
          proof: check.proof,
          diagnostics: [
            {
              severity: 'error',
              code: 'runtime_session_provider_unsupported',
              message: `No runtime-session provider is registered for '${check.proof.provider}'.`,
              path: 'proof.provider',
            },
          ],
        };
      } else {
        try {
          const result = await provider.run({
            proof: check.proof,
            argv: check.argv,
            cwd: check.cwd,
            limits: check.limits,
            declaration: check.declaration,
          });
          process = result.process;
          runtimeSession = result.runtimeSession;
        } catch (cause) {
          process = unexpectedProcessResult(request, cause);
          runtimeSession = {
            provider: check.proof.provider,
            status: 'failed',
            proof: check.proof,
            diagnostics: [
              {
                severity: 'error',
                code: 'runtime_session_provider_failed',
                message: `Runtime-session provider '${check.proof.provider}' failed unexpectedly: ${cause instanceof Error ? cause.message : String(cause)}`,
                path: 'proof.provider',
              },
            ],
          };
        }
      }
    } else {
      try {
        process = await this.commandRunner.run(request);
      } catch (cause) {
        process = unexpectedProcessResult(request, cause);
      }
    }

    const runtimeProof = check.proof?.type === 'runtime-session' ? check.proof : undefined;
    const processDiagnostic = runtimeProof ? undefined : processFailureDiagnostic(process);
    const processPassed = runtimeProof
      ? process.termination === 'exited' && process.exitCode === runtimeProof.requireExitCode
      : processDiagnostic === undefined;
    const assertions = await evaluateAssertions(
      check.assertions,
      process,
      this.assertionRegistry
    );
    const assertionErrors = assertionDiagnostics(assertions);
    const assertionsPassed = assertions.every((assertion) => assertion.passed);
    const testEvidence = check.proof?.type === 'test-suite'
      ? await extractTestEvidence(check.proof, process, this.testEvidenceRegistry)
      : undefined;
    const diagnostics = [
      ...(processDiagnostic ? [processDiagnostic] : []),
      ...assertionErrors,
      ...(testEvidence?.diagnostics ?? []),
      ...(runtimeSession?.diagnostics ?? []),
    ];
    const passed =
      processPassed &&
      assertionsPassed &&
      (testEvidence === undefined || testEvidence.status === 'passed') &&
      (runtimeSession === undefined || runtimeSession.status === 'passed');

    return {
      id: check.id,
      declaration: check.declaration,
      applicability: check.applicability,
      ...(check.proofRole ? { proofRole: check.proofRole } : {}),
      ...(check.proof
        ? {
            proof: {
              type: check.proof.type,
              provider: check.proof.provider,
              ...(check.proofRole ? { role: check.proofRole } : {}),
            },
          }
        : {}),
      process,
      processPassed,
      assertions,
      assertionsPassed,
      ...(testEvidence ? { testEvidence } : {}),
      ...(runtimeSession ? { runtimeSession } : {}),
      passed,
      diagnostics,
    };
  }
}
