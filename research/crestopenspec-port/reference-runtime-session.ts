import { randomUUID } from 'node:crypto';
import type { ChildProcess } from 'node:child_process';
import { StringDecoder } from 'node:string_decoder';
import { OwnedProcessTree } from './process-tree.js';
import {
  createDefaultRuntimeHostCapabilities,
  createDefaultRuntimeInteractionRegistry,
  RuntimeHostCapabilityRegistry,
  RuntimeInteractionProviderRegistry,
  RuntimeSessionProviderRegistry,
} from './runtime-providers.js';
import {
  NodeRuntimeProcessLauncher,
  type RuntimeProcessLauncher,
} from './runtime-process-launcher.js';
import type {
  AcceptanceDiagnostic,
  ProcessExecutionRequest,
  ProcessResult,
  ProcessSpawnError,
  RuntimeCompletionMarker,
  RuntimeInteractionDeclaration,
  RuntimeInteractionEvidence,
  RuntimeMarkerObservation,
  RuntimeMarkerOccurrence,
  RuntimeProgressMarker,
  RuntimeSessionEvidence,
  RuntimeSessionProvider,
  RuntimeSessionProviderRequest,
  RuntimeSessionProviderResult,
  RuntimeStream,
  RuntimeTerminationAction,
  RuntimeTimeoutStage,
} from './types.js';

export const PROCESS_LIFECYCLE_RUNTIME_PROVIDER = 'process-lifecycle-v1';
export const OWNED_PROCESS_SIGNAL_TEARDOWN_PROVIDER = 'owned-process-signal-v1';

const POLL_INTERVAL_MS = 10;
const PROCESS_TREE_POLL_INTERVAL_MS = 40;

interface CaptureState {
  chunks: Buffer[];
  bytes: number;
  truncated: boolean;
  text: string;
  decoder: StringDecoder;
}

interface MarkerState {
  declaration: RuntimeProgressMarker | RuntimeCompletionMarker;
  phase: 'progress' | 'completion';
  declarationIndex: number;
  occurrences: RuntimeMarkerOccurrence[];
}

interface InteractionState {
  declaration: RuntimeInteractionDeclaration;
  result: RuntimeInteractionEvidence;
  promise?: Promise<void>;
  settled: boolean;
}

interface SessionFailure {
  diagnostic: AcceptanceDiagnostic;
  timeoutStage?: RuntimeTimeoutStage;
  outputLimit?: RuntimeStream;
}

function elapsed(startedAtEpochMs: number): number {
  return Date.now() - startedAtEpochMs;
}

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function toSpawnError(cause: unknown): ProcessSpawnError {
  const candidate = cause as NodeJS.ErrnoException;
  return {
    ...(candidate.code ? { code: candidate.code } : {}),
    message: cause instanceof Error ? cause.message : String(cause),
  };
}

function diagnostic(code: string, message: string, path?: string): AcceptanceDiagnostic {
  return {
    severity: 'error',
    code,
    message,
    ...(path ? { path } : {}),
  };
}

function syntheticProcess(
  request: ProcessExecutionRequest,
  cause: string,
  code?: string
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
    spawnError: { ...(code ? { code } : {}), message: cause },
    stdout: '',
    stderr: '',
    stdoutTruncated: false,
    stderrTruncated: false,
  };
}

function occurrencePositions(haystack: string, needle: string): number[] {
  const positions: number[] = [];
  let offset = 0;
  while (offset <= haystack.length - needle.length) {
    const found = haystack.indexOf(needle, offset);
    if (found < 0) break;
    positions.push(found);
    offset = found + Math.max(1, needle.length);
  }
  return positions;
}

function markerObservation(state: MarkerState): RuntimeMarkerObservation {
  const declaration = state.declaration;
  const passed =
    state.phase === 'progress'
      ? state.occurrences.length >= (declaration as RuntimeProgressMarker).minimumCount
      : state.occurrences.length === (declaration as RuntimeCompletionMarker).exactCount;
  return {
    id: declaration.id,
    phase: state.phase,
    stream: declaration.stream,
    contains: declaration.contains,
    expected:
      state.phase === 'progress'
        ? { minimumCount: (declaration as RuntimeProgressMarker).minimumCount }
        : { exactCount: (declaration as RuntimeCompletionMarker).exactCount },
    observedCount: state.occurrences.length,
    passed,
    occurrences: state.occurrences.map((occurrence) => ({ ...occurrence })),
  };
}

function markerDiagnostics(states: MarkerState[]): AcceptanceDiagnostic[] {
  const diagnostics: AcceptanceDiagnostic[] = [];
  for (const state of states) {
    const observed = state.occurrences.length;
    if (state.phase === 'progress') {
      const expected = (state.declaration as RuntimeProgressMarker).minimumCount;
      if (observed < expected) {
        diagnostics.push(
          diagnostic(
            'runtime_progress_marker_missing',
            `Progress marker '${state.declaration.id}' occurred ${observed} time(s); at least ${expected} required.`,
            `proof.progress.${state.declaration.id}`
          )
        );
      }
    } else {
      const expected = (state.declaration as RuntimeCompletionMarker).exactCount;
      if (observed === 0) {
        diagnostics.push(
          diagnostic(
            'required_marker_missing',
            `Completion marker '${state.declaration.id}' did not occur; exactly ${expected} required.`,
            `proof.completion.${state.declaration.id}`
          )
        );
      } else if (observed !== expected) {
        diagnostics.push(
          diagnostic(
            'required_marker_count_mismatch',
            `Completion marker '${state.declaration.id}' occurred ${observed} time(s); exactly ${expected} required.`,
            `proof.completion.${state.declaration.id}`
          )
        );
      }
    }
  }

  const completion = states.filter((state) => state.phase === 'completion');
  for (let index = 1; index < completion.length; index++) {
    const previous = completion[index - 1].occurrences[0];
    const current = completion[index].occurrences[0];
    if (previous && current && current.sequence <= previous.sequence) {
      diagnostics.push(
        diagnostic(
          'required_marker_out_of_order',
          `Completion marker '${completion[index].declaration.id}' was observed before '${completion[index - 1].declaration.id}'.`,
          `proof.completion.${completion[index].declaration.id}`
        )
      );
    }
  }
  return diagnostics;
}

function completionSatisfied(states: MarkerState[]): boolean {
  return states
    .filter((state) => state.phase === 'completion')
    .every(
      (state) =>
        state.occurrences.length ===
        (state.declaration as RuntimeCompletionMarker).exactCount
    );
}

function firstObservationAt(state: MarkerState | undefined): number | undefined {
  return state?.occurrences[0]?.elapsedMs;
}

function finalizeInteraction(
  state: InteractionState,
  sessionId: string,
  markers: Map<string, MarkerState>
): void {
  const result = state.result;
  const opening = firstObservationAt(markers.get(state.declaration.opensAfter));
  const closing = firstObservationAt(markers.get(state.declaration.closesBefore));
  result.openingObservedAtMs = opening;
  result.closingObservedAtMs = closing;
  const evidence = result.evidence;

  if (opening === undefined) {
    result.diagnostics.push(
      diagnostic(
        'runtime_interaction_opening_milestone_missing',
        `Interaction '${state.declaration.id}' opening milestone '${state.declaration.opensAfter}' was not observed.`
      )
    );
  }
  if (closing === undefined) {
    result.diagnostics.push(
      diagnostic(
        'runtime_interaction_closing_milestone_missing',
        `Interaction '${state.declaration.id}' closing milestone '${state.declaration.closesBefore}' was not observed.`
      )
    );
  }
  if (!evidence) {
    if (result.diagnostics.length === 0) {
      result.diagnostics.push(
        diagnostic(
          'runtime_interaction_evidence_missing',
          `Interaction '${state.declaration.id}' returned no structured evidence.`
        )
      );
    }
    result.status = 'failed';
    return;
  }
  if (evidence.sessionId !== sessionId) {
    result.diagnostics.push(
      diagnostic(
        'runtime_interaction_session_mismatch',
        `Interaction '${state.declaration.id}' reported session '${evidence.sessionId}' instead of '${sessionId}'.`
      )
    );
  }
  if (evidence.actionId !== state.declaration.id) {
    result.diagnostics.push(
      diagnostic(
        'runtime_interaction_action_mismatch',
        `Interaction evidence action '${evidence.actionId}' does not match '${state.declaration.id}'.`
      )
    );
  }
  if (!evidence.attempted) {
    result.diagnostics.push(
      diagnostic(
        'runtime_interaction_not_attempted',
        `Interaction '${state.declaration.id}' was not attempted.`
      )
    );
  }
  if (!evidence.reachedSeam) {
    result.diagnostics.push(
      diagnostic(
        'runtime_interaction_seam_not_reached',
        `Interaction '${state.declaration.id}' did not reach the declared production seam.`
      )
    );
  }
  const deliveryOutsideWindow =
    opening !== undefined &&
    closing !== undefined &&
    (evidence.deliveredAtMs < opening || evidence.deliveredAtMs >= closing);
  if (deliveryOutsideWindow) {
    result.diagnostics.push(
      diagnostic(
        'runtime_interaction_timing_mismatch',
        `Interaction '${state.declaration.id}' was delivered at ${evidence.deliveredAtMs} ms outside the required [${opening}, ${closing}) ms window.`
      )
    );
  }
  if (
    !deliveryOutsideWindow &&
    result.invokedAtMs !== undefined &&
    evidence.deliveredAtMs < result.invokedAtMs
  ) {
    result.diagnostics.push(
      diagnostic(
        'runtime_interaction_timing_mismatch',
        `Interaction '${state.declaration.id}' reported delivery at ${evidence.deliveredAtMs} ms before its provider was invoked at ${result.invokedAtMs} ms.`
      )
    );
  }

  const assertionCounts = new Map<string, number>();
  for (const assertion of evidence.assertions) {
    assertionCounts.set(assertion.id, (assertionCounts.get(assertion.id) ?? 0) + 1);
    if (!assertion.passed) {
      result.diagnostics.push(
        diagnostic(
          'runtime_interaction_assertion_failed',
          `Interaction assertion '${assertion.id}' failed for '${state.declaration.id}'.`
        )
      );
    }
  }
  for (const required of state.declaration.requiredAssertions) {
    const count = assertionCounts.get(required) ?? 0;
    if (count !== 1) {
      result.diagnostics.push(
        diagnostic(
          'runtime_interaction_assertion_missing',
          `Interaction '${state.declaration.id}' requires exactly one '${required}' assertion; observed ${count}.`
        )
      );
    }
  }
  result.status = result.diagnostics.length === 0 ? 'passed' : 'failed';
}

function interactionDiagnostics(states: InteractionState[]): AcceptanceDiagnostic[] {
  return states.flatMap((state) => state.result.diagnostics);
}

function runtimeProcessResult(
  request: ProcessExecutionRequest,
  startedAtEpochMs: number,
  stdout: CaptureState,
  stderr: CaptureState,
  options: {
    spawnError?: ProcessSpawnError;
    timeoutStage?: RuntimeTimeoutStage;
    outputLimit?: RuntimeStream;
    exitCode: number | null;
    signal: string | null;
  }
): ProcessResult {
  const outputLimitExceeded = options.outputLimit ? [options.outputLimit] : [];
  return {
    argv: [...request.argv],
    cwd: request.cwd,
    limits: { ...request.limits },
    durationMs: elapsed(startedAtEpochMs),
    termination: options.spawnError
      ? 'spawn_error'
      : options.timeoutStage
        ? 'timed_out'
        : outputLimitExceeded.length > 0
          ? 'output_limit'
          : options.signal
            ? 'signaled'
            : 'exited',
    exitCode: options.spawnError ? null : options.exitCode,
    signal: options.signal,
    timedOut: options.timeoutStage !== undefined,
    outputLimitExceeded,
    ...(options.spawnError ? { spawnError: options.spawnError } : {}),
    stdout: Buffer.concat(stdout.chunks, stdout.bytes).toString('utf8'),
    stderr: Buffer.concat(stderr.chunks, stderr.bytes).toString('utf8'),
    stdoutTruncated: stdout.truncated,
    stderrTruncated: stderr.truncated,
  };
}

export interface ProcessLifecycleRuntimeProviderDependencies {
  launcher?: RuntimeProcessLauncher;
  interactions?: RuntimeInteractionProviderRegistry;
  capabilities?: RuntimeHostCapabilityRegistry;
  processTreeFactory?: (pid: number, startedAtEpochMs: number) => OwnedProcessTree;
}

export class ProcessLifecycleRuntimeProvider implements RuntimeSessionProvider {
  readonly id = PROCESS_LIFECYCLE_RUNTIME_PROVIDER;
  private readonly launcher: RuntimeProcessLauncher;
  private readonly interactions: RuntimeInteractionProviderRegistry;
  private readonly capabilities: RuntimeHostCapabilityRegistry;
  private readonly processTreeFactory: (
    pid: number,
    startedAtEpochMs: number
  ) => OwnedProcessTree;

  constructor(dependencies: ProcessLifecycleRuntimeProviderDependencies = {}) {
    this.launcher = dependencies.launcher ?? new NodeRuntimeProcessLauncher();
    this.interactions =
      dependencies.interactions ?? createDefaultRuntimeInteractionRegistry();
    this.capabilities =
      dependencies.capabilities ?? createDefaultRuntimeHostCapabilities();
    if (this.launcher.ptyAvailable) this.capabilities.add('stdio:pty');
    this.processTreeFactory =
      dependencies.processTreeFactory ??
      ((pid, startedAtEpochMs) => new OwnedProcessTree(pid, startedAtEpochMs));
  }

  async run(request: RuntimeSessionProviderRequest): Promise<RuntimeSessionProviderResult> {
    const processRequest: ProcessExecutionRequest = {
      argv: [...request.argv],
      cwd: request.cwd,
      limits: { ...request.limits },
    };
    const requiredCapabilities = [
      ...request.proof.requiredCapabilities,
      ...(request.proof.stdioMode === 'pty' ? ['stdio:pty'] : ['stdio:pipe']),
    ];
    const missing = this.capabilities.missing(requiredCapabilities);
    if (missing.length > 0) {
      const gap = diagnostic(
        'BLOCKING_REQUIRED_PROOF_GAP',
        `Applicable runtime proof '${request.proof.entryPoint}' requires unavailable host capability: ${missing.join(', ')}.`,
        'proof.requiredCapabilities'
      );
      return {
        process: syntheticProcess(
          processRequest,
          `Runtime host capability unavailable: ${missing.join(', ')}`,
          'RUNTIME_CAPABILITY_UNAVAILABLE'
        ),
        runtimeSession: {
          provider: this.id,
          status: 'failed',
          proof: request.proof,
          diagnostics: [gap],
        },
      };
    }

    const sessionId = randomUUID();
    const startedAtEpochMs = Date.now();
    let child: ChildProcess;
    try {
      child = this.launcher.launch({
        argv: request.argv,
        cwd: request.cwd,
        stdioMode: request.proof.stdioMode,
      });
    } catch (cause) {
      const spawnError = toSpawnError(cause);
      const failure = diagnostic(
        'runtime_spawn_failed',
        `Could not start runtime session: ${spawnError.message}`
      );
      return {
        process: syntheticProcess(
          processRequest,
          spawnError.message,
          spawnError.code
        ),
        runtimeSession: {
          provider: this.id,
          status: 'failed',
          proof: request.proof,
          diagnostics: [failure],
        },
      };
    }

    const stdout: CaptureState = {
      chunks: [],
      bytes: 0,
      truncated: false,
      text: '',
      decoder: new StringDecoder('utf8'),
    };
    const stderr: CaptureState = {
      chunks: [],
      bytes: 0,
      truncated: false,
      text: '',
      decoder: new StringDecoder('utf8'),
    };
    const markerStates: MarkerState[] = [
      ...request.proof.progress.map((declaration, declarationIndex) => ({
        declaration,
        phase: 'progress' as const,
        declarationIndex,
        occurrences: [],
      })),
      ...request.proof.completion.map((declaration, index) => ({
        declaration,
        phase: 'completion' as const,
        declarationIndex: request.proof.progress.length + index,
        occurrences: [],
      })),
    ];
    const markersById = new Map(
      markerStates.map((state) => [state.declaration.id, state])
    );
    let markerSequence = 0;
    let lastOutputAtEpochMs = startedAtEpochMs;
    let outputFailure: SessionFailure | undefined;

    const scanMarkers = (stream: RuntimeStream, text: string) => {
      const candidates: Array<{
        state: MarkerState;
        offset: number;
      }> = [];
      for (const state of markerStates.filter(
        (candidate) => candidate.declaration.stream === stream
      )) {
        const positions = occurrencePositions(text, state.declaration.contains);
        for (const offset of positions.slice(state.occurrences.length)) {
          candidates.push({ state, offset });
        }
      }
      candidates.sort(
        (left, right) =>
          left.offset - right.offset ||
          left.state.declarationIndex - right.state.declarationIndex
      );
      const now = elapsed(startedAtEpochMs);
      for (const candidate of candidates) {
        candidate.state.occurrences.push({
          elapsedMs: now,
          offset: candidate.offset,
          sequence: markerSequence++,
        });
      }
    };

    const capture = (
      stream: RuntimeStream,
      state: CaptureState,
      maximum: number,
      value: Buffer | string
    ) => {
      const chunk = Buffer.isBuffer(value) ? value : Buffer.from(value);
      lastOutputAtEpochMs = Date.now();
      const remaining = Math.max(0, maximum - state.bytes);
      if (remaining > 0) {
        const retained = chunk.subarray(0, remaining);
        state.chunks.push(retained);
        state.bytes += retained.length;
        state.text += state.decoder.write(retained);
        scanMarkers(stream, state.text);
      }
      if (chunk.length > remaining && !outputFailure) {
        state.truncated = true;
        outputFailure = {
          diagnostic: diagnostic(
            'runtime_output_limit',
            `Runtime session exceeded its ${stream} capture limit.`
          ),
          outputLimit: stream,
        };
      }
    };

    child.stdout?.on('data', (value: Buffer | string) =>
      capture('stdout', stdout, request.limits.stdoutBytes, value)
    );
    child.stderr?.on('data', (value: Buffer | string) =>
      capture('stderr', stderr, request.limits.stderrBytes, value)
    );

    let spawnError: ProcessSpawnError | undefined;
    let spawned = child.pid !== undefined;
    let parentExited = false;
    let childClosed = false;
    let exitCode: number | null = null;
    let signal: string | null = null;
    child.once('spawn', () => {
      spawned = true;
    });
    child.once('error', (cause) => {
      spawnError = toSpawnError(cause);
    });

    let tree: OwnedProcessTree | undefined;
    if (child.pid !== undefined) {
      tree = this.processTreeFactory(child.pid, startedAtEpochMs);
    }
    child.once('exit', (code, exitSignal) => {
      parentExited = true;
      exitCode = code;
      signal = exitSignal ?? null;
      tree?.recordParentExit();
    });
    child.once('close', () => {
      childClosed = true;
    });

    const interactionStates: InteractionState[] = request.proof.interactions.map(
      (declaration) => ({
        declaration,
        result: {
          id: declaration.id,
          provider: declaration.provider,
          opensAfter: declaration.opensAfter,
          closesBefore: declaration.closesBefore,
          status: 'failed',
          diagnostics: [],
        },
        settled: false,
      })
    );

    const startEligibleInteractions = () => {
      for (const state of interactionStates) {
        if (state.promise) {
          continue;
        }
        const openingObservedAtMs = firstObservationAt(
          markersById.get(state.declaration.opensAfter)
        );
        if (openingObservedAtMs === undefined) continue;
        const closingObservedAtMs = firstObservationAt(
          markersById.get(state.declaration.closesBefore)
        );
        if (closingObservedAtMs !== undefined) {
          state.result.diagnostics.push(
            diagnostic(
              'runtime_interaction_timing_mismatch',
              `Interaction '${state.declaration.id}' could not be invoked because its window closed at ${closingObservedAtMs} ms before dispatch.`
            )
          );
          state.result.completedAtMs = elapsed(startedAtEpochMs);
          state.settled = true;
          state.promise = Promise.resolve();
          continue;
        }
        state.result.invokedAtMs = elapsed(startedAtEpochMs);
        const provider = this.interactions.get(state.declaration.provider);
        if (!provider) {
          state.result.diagnostics.push(
            diagnostic(
              'runtime_interaction_provider_unsupported',
              `No runtime interaction provider is registered for '${state.declaration.provider}'.`
            )
          );
          state.result.completedAtMs = elapsed(startedAtEpochMs);
          state.settled = true;
          state.promise = Promise.resolve();
          continue;
        }
        state.promise = provider
          .invoke({
            sessionId,
            sessionStartedAtEpochMs: startedAtEpochMs,
            action: state.declaration,
            cwd: request.cwd,
            limits: request.limits,
            milestones: markerStates.map(markerObservation),
          })
          .then((evidence) => {
            state.result.evidence = evidence;
          })
          .catch((cause) => {
            state.result.diagnostics.push(
              diagnostic(
                'runtime_interaction_provider_failed',
                `Interaction provider '${state.declaration.provider}' failed: ${cause instanceof Error ? cause.message : String(cause)}`
              )
            );
          })
          .finally(() => {
            state.result.completedAtMs = elapsed(startedAtEpochMs);
            state.settled = true;
          });
      }
    };

    let startupObservedAtMs: number | undefined;
    let completionObservedAtMs: number | undefined;
    let failure: SessionFailure | undefined;
    let lastTreePollAt = 0;
    let teardownStartedAtMs: number | undefined;
    let teardownCompletedAtMs: number | undefined;
    let teardownPassed = request.proof.lifecycle === 'bounded';
    let persistentTeardownAttempted = false;
    const terminationActions: RuntimeTerminationAction[] = [];

    while (!failure) {
      const now = Date.now();
      const duration = now - startedAtEpochMs;
      if (!tree && child.pid !== undefined) {
        tree = this.processTreeFactory(child.pid, startedAtEpochMs);
      }
      if (tree && now - lastTreePollAt >= PROCESS_TREE_POLL_INTERVAL_MS) {
        await tree.snapshot();
        lastTreePollAt = now;
      }

      startEligibleInteractions();
      startupObservedAtMs ??= request.proof.progress
        .map((marker) => firstObservationAt(markersById.get(marker.id)))
        .find((value): value is number => value !== undefined);
      if (completionObservedAtMs === undefined && completionSatisfied(markerStates)) {
        completionObservedAtMs = duration;
      }

      if (spawnError) {
        failure = {
          diagnostic: diagnostic(
            'runtime_spawn_failed',
            `Could not start runtime session: ${spawnError.message}`
          ),
        };
      } else if (outputFailure) {
        failure = outputFailure;
      } else if (!spawned && duration >= request.proof.timeouts.startupTimeoutMs) {
        failure = {
          diagnostic: diagnostic(
            'runtime_startup_timeout',
            `Runtime process did not start within ${request.proof.timeouts.startupTimeoutMs} ms.`
          ),
          timeoutStage: 'startup',
        };
      } else if (
        startupObservedAtMs === undefined &&
        duration >= request.proof.timeouts.startupTimeoutMs
      ) {
        failure = {
          diagnostic: diagnostic(
            'runtime_startup_timeout',
            `Runtime emitted no declared progress within ${request.proof.timeouts.startupTimeoutMs} ms.`
          ),
          timeoutStage: 'startup',
        };
      } else if (
        completionObservedAtMs === undefined &&
        now - lastOutputAtEpochMs >= request.proof.timeouts.progressSilenceMs
      ) {
        failure = {
          diagnostic: diagnostic(
            'runtime_progress_silence_timeout',
            `Runtime produced no output for ${request.proof.timeouts.progressSilenceMs} ms before completion.`
          ),
          timeoutStage: 'progress_silence',
        };
      } else if (
        completionObservedAtMs === undefined &&
        duration >= request.proof.timeouts.completionTimeoutMs
      ) {
        failure = {
          diagnostic: diagnostic(
            'runtime_completion_timeout',
            `Runtime did not reach its declared success condition within ${request.proof.timeouts.completionTimeoutMs} ms.`
          ),
          timeoutStage: 'completion',
        };
      } else if (duration >= request.proof.timeouts.hardTimeoutMs) {
        failure = {
          diagnostic: diagnostic(
            'runtime_hard_timeout',
            `Runtime exceeded its ${request.proof.timeouts.hardTimeoutMs} ms hard limit.`
          ),
          timeoutStage: 'hard_limit',
        };
      } else if (childClosed && completionObservedAtMs === undefined) {
        failure = {
          diagnostic: diagnostic(
            'exit_before_required_completion',
            'Runtime parent exited before every required completion marker was observed.'
          ),
        };
      } else if (
        request.proof.lifecycle === 'bounded' &&
        completionObservedAtMs !== undefined &&
        !parentExited &&
        duration - completionObservedAtMs >=
          request.proof.timeouts.completionToExitGraceMs
      ) {
        failure = {
          diagnostic: diagnostic(
            'success_reported_but_process_resident',
            `Runtime reported terminal success but remained resident beyond its ${request.proof.timeouts.completionToExitGraceMs} ms completion-to-exit grace.`
          ),
          timeoutStage: 'completion_to_exit',
        };
      }

      if (childClosed) {
        for (const state of interactionStates) {
          if (!state.promise) state.settled = true;
        }
      }
      const allInteractionsSettled = interactionStates.every(
        (state) => state.settled
      );
      if (
        !failure &&
        request.proof.lifecycle !== 'bounded' &&
        completionObservedAtMs !== undefined &&
        allInteractionsSettled &&
        !persistentTeardownAttempted
      ) {
        persistentTeardownAttempted = true;
        teardownStartedAtMs = elapsed(startedAtEpochMs);
        if (
          request.proof.teardown?.provider !==
          OWNED_PROCESS_SIGNAL_TEARDOWN_PROVIDER
        ) {
          failure = {
            diagnostic: diagnostic(
              'runtime_teardown_provider_unsupported',
              `Runtime teardown provider '${request.proof.teardown?.provider ?? 'missing'}' is not supported by '${this.id}'.`
              ),
            };
        } else if (request.proof.teardown.request.signal !== 'SIGTERM') {
          failure = {
            diagnostic: diagnostic(
              'runtime_teardown_request_malformed',
              "owned-process-signal-v1 teardown requires request.signal to be 'SIGTERM'."
            ),
          };
        } else if (!tree) {
          failure = {
            diagnostic: diagnostic(
              'runtime_teardown_unavailable',
              'Runtime controller could not establish an owned process tree for teardown.'
            ),
          };
        } else {
          const remaining = await tree.terminate(
            request.proof.timeouts.teardownGraceMs,
            terminationActions
          );
          teardownCompletedAtMs = elapsed(startedAtEpochMs);
          teardownPassed = remaining.length === 0;
          if (!teardownPassed) {
            failure = {
              diagnostic: diagnostic(
                'runtime_teardown_incomplete',
                `Controller teardown left owned process IDs resident: ${remaining.join(', ')}.`
              ),
              timeoutStage: 'teardown',
            };
          }
        }
      }

      if (!failure && parentExited && completionObservedAtMs !== undefined) {
        if (!allInteractionsSettled) {
          await delay(POLL_INTERVAL_MS);
          continue;
        }
        const remaining = tree ? await tree.snapshot() : [];
        if (request.proof.requireNoDescendants && remaining.length > 0) {
          const descendants = remaining.filter((pid) => pid !== child.pid);
          if (descendants.length > 0 || remaining.includes(child.pid as number)) {
            failure = {
              diagnostic: diagnostic(
                'owned_descendant_resident',
                `Runtime parent exited while owned process IDs remained resident: ${remaining.join(', ')}.`
              ),
            };
          }
        } else if (
          childClosed &&
          (request.proof.lifecycle === 'bounded' || persistentTeardownAttempted)
        ) {
          break;
        }
      }

      await delay(POLL_INTERVAL_MS);
    }

    for (const state of interactionStates) {
      if (state.promise) {
        await Promise.race([
          state.promise,
          delay(Math.max(1, request.proof.timeouts.teardownGraceMs)),
        ]);
      }
      finalizeInteraction(state, sessionId, markersById);
    }

    const diagnostics: AcceptanceDiagnostic[] = [];
    if (failure) diagnostics.push(failure.diagnostic);
    diagnostics.push(...markerDiagnostics(markerStates));
    diagnostics.push(...interactionDiagnostics(interactionStates));

    if (parentExited && exitCode !== request.proof.requireExitCode) {
      diagnostics.push(
        diagnostic(
          'runtime_exit_code_mismatch',
          `Runtime exit code was ${exitCode === null ? 'none' : exitCode}; expected ${request.proof.requireExitCode}.`
        )
      );
    }
    if (signal && !failure) {
      diagnostics.push(
        diagnostic(
          'runtime_unexpected_signal',
          `Runtime terminated by signal ${signal}.`
        )
      );
    }

    if (tree && (failure || diagnostics.length > 0)) {
      const remaining = await tree.terminate(
        request.proof.timeouts.teardownGraceMs,
        terminationActions
      );
      if (remaining.length > 0) {
        diagnostics.push(
          diagnostic(
            'runtime_cleanup_incomplete',
            `Runtime cleanup could not terminate owned process IDs: ${remaining.join(', ')}.`
          )
        );
      }
    }
    if (tree?.errors.length) {
      diagnostics.push(
        diagnostic(
          'runtime_process_tree_observation_failed',
          `Could not fully observe the owned process tree: ${tree.errors.join('; ')}`
        )
      );
    }

    const processTree = tree
      ? await tree.evidence()
      : {
          parentPid: child.pid ?? null,
          processGroupId: null,
          observedPids: child.pid === undefined ? [] : [child.pid],
          observedDescendantPids: [],
          remainingPids: [],
          noOwnedProcessesRemain: child.pid === undefined,
        };
    if (
      request.proof.requireNoDescendants &&
      !processTree.noOwnedProcessesRemain &&
      !diagnostics.some((entry) => entry.code === 'runtime_cleanup_incomplete')
    ) {
      diagnostics.push(
        diagnostic(
          'runtime_cleanup_incomplete',
          `Owned process IDs remain resident: ${processTree.remainingPids.join(', ')}.`
        )
      );
    }

    const evidence: RuntimeSessionEvidence = {
      sessionId,
      provider: this.id,
      proof: request.proof,
      argv: [...request.argv],
      cwd: request.cwd,
      durationMs: elapsed(startedAtEpochMs),
      ...(startupObservedAtMs === undefined ? {} : { startupObservedAtMs }),
      ...(completionObservedAtMs === undefined
        ? {}
        : { completionObservedAtMs }),
      ...(failure?.timeoutStage ? { timeoutStage: failure.timeoutStage } : {}),
      milestones: markerStates.map(markerObservation),
      interactions: interactionStates.map((state) => state.result),
      processTree,
      terminationActions,
      teardown: {
        required: request.proof.lifecycle !== 'bounded',
        ...(request.proof.teardown
          ? { provider: request.proof.teardown.provider }
          : {}),
        ...(teardownStartedAtMs === undefined ? {} : { startedAtMs: teardownStartedAtMs }),
        ...(teardownCompletedAtMs === undefined
          ? {}
          : { completedAtMs: teardownCompletedAtMs }),
        passed: teardownPassed,
      },
    };
    const process = runtimeProcessResult(
      processRequest,
      startedAtEpochMs,
      stdout,
      stderr,
      {
        ...(spawnError ? { spawnError } : {}),
        ...(failure?.timeoutStage ? { timeoutStage: failure.timeoutStage } : {}),
        ...(failure?.outputLimit ? { outputLimit: failure.outputLimit } : {}),
        exitCode,
        signal,
      }
    );
    return {
      process,
      runtimeSession: {
        provider: this.id,
        status: diagnostics.length === 0 ? 'passed' : 'failed',
        proof: request.proof,
        evidence,
        diagnostics,
      },
    };
  }
}

export function createDefaultRuntimeSessionRegistry(): RuntimeSessionProviderRegistry {
  return new RuntimeSessionProviderRegistry().register(
    new ProcessLifecycleRuntimeProvider()
  );
}
