import { spawn } from 'node:child_process';
import type {
  JsonObject,
  JsonValue,
} from '../cue-architecture.js';
import type {
  RuntimeInteractionProvider,
  RuntimeInteractionProviderEvidence,
  RuntimeInteractionProviderRequest,
  RuntimeSessionProvider,
  RuntimeTerminationAction,
} from './types.js';
import { OwnedProcessTree } from './process-tree.js';

export const PROCESS_JSON_INTERACTION_PROVIDER = 'process-json-v1';

function isObject(value: unknown): value is JsonObject {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isJsonValue(value: unknown): value is JsonValue {
  if (
    value === null ||
    typeof value === 'string' ||
    typeof value === 'number' ||
    typeof value === 'boolean'
  ) {
    return typeof value !== 'number' || Number.isFinite(value);
  }
  if (Array.isArray(value)) return value.every(isJsonValue);
  return isObject(value) && Object.values(value).every(isJsonValue);
}

export class RuntimeSessionProviderRegistry {
  private readonly providers = new Map<string, RuntimeSessionProvider>();

  register(provider: RuntimeSessionProvider): this {
    if (!provider.id.trim()) throw new Error('Runtime-session provider id cannot be empty.');
    if (this.providers.has(provider.id)) {
      throw new Error(`Runtime-session provider '${provider.id}' is already registered.`);
    }
    this.providers.set(provider.id, provider);
    return this;
  }

  get(id: string): RuntimeSessionProvider | undefined {
    return this.providers.get(id);
  }
}

export class RuntimeInteractionProviderRegistry {
  private readonly providers = new Map<string, RuntimeInteractionProvider>();

  register(provider: RuntimeInteractionProvider): this {
    if (!provider.id.trim()) throw new Error('Runtime interaction provider id cannot be empty.');
    if (this.providers.has(provider.id)) {
      throw new Error(`Runtime interaction provider '${provider.id}' is already registered.`);
    }
    this.providers.set(provider.id, provider);
    return this;
  }

  get(id: string): RuntimeInteractionProvider | undefined {
    return this.providers.get(id);
  }
}

export class RuntimeHostCapabilityRegistry {
  private readonly available = new Set<string>();

  constructor(capabilities: Iterable<string> = []) {
    for (const capability of capabilities) this.add(capability);
  }

  add(capability: string): this {
    if (!capability.trim()) throw new Error('Runtime host capability cannot be empty.');
    this.available.add(capability);
    return this;
  }

  has(capability: string): boolean {
    return this.available.has(capability);
  }

  missing(required: readonly string[]): string[] {
    return required.filter((capability) => !this.has(capability));
  }
}

interface DriverCapture {
  stdout: Buffer[];
  stderr: Buffer[];
  stdoutBytes: number;
  stderrBytes: number;
  exceeded: boolean;
}

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function appendBounded(
  chunks: Buffer[],
  currentBytes: number,
  value: Buffer | string,
  maximum: number
): { bytes: number; exceeded: boolean } {
  const chunk = Buffer.isBuffer(value) ? value : Buffer.from(value);
  const remaining = Math.max(0, maximum - currentBytes);
  if (remaining > 0) chunks.push(chunk.subarray(0, remaining));
  return {
    bytes: currentBytes + Math.min(remaining, chunk.length),
    exceeded: chunk.length > remaining,
  };
}

function parseDriverEvidence(value: unknown): RuntimeInteractionProviderEvidence {
  if (
    !isObject(value) ||
    typeof value.sessionId !== 'string' ||
    typeof value.actionId !== 'string' ||
    typeof value.attempted !== 'boolean' ||
    typeof value.reachedSeam !== 'boolean' ||
    typeof value.deliveredAtMs !== 'number' ||
    !Number.isFinite(value.deliveredAtMs) ||
    value.deliveredAtMs < 0 ||
    !Array.isArray(value.assertions) ||
    !isObject(value.details)
  ) {
    throw new Error(
      'Interaction driver evidence requires sessionId, actionId, attempted, reachedSeam, nonnegative deliveredAtMs, assertions, and object details.'
    );
  }
  const assertions = value.assertions.map((entry, index) => {
    if (
      !isObject(entry) ||
      typeof entry.id !== 'string' ||
      !entry.id.trim() ||
      typeof entry.passed !== 'boolean' ||
      ('expected' in entry && !isJsonValue(entry.expected)) ||
      ('observed' in entry && !isJsonValue(entry.observed))
    ) {
      throw new Error(`Interaction assertion ${index} is malformed.`);
    }
    return {
      id: entry.id,
      passed: entry.passed,
      ...('expected' in entry ? { expected: entry.expected } : {}),
      ...('observed' in entry ? { observed: entry.observed } : {}),
    };
  });
  if (!isJsonValue(value.details)) {
    throw new Error('Interaction driver details are not JSON-safe.');
  }
  return {
    sessionId: value.sessionId,
    actionId: value.actionId,
    attempted: value.attempted,
    reachedSeam: value.reachedSeam,
    deliveredAtMs: value.deliveredAtMs,
    assertions,
    details: value.details,
  };
}

class ProcessJsonInteractionProvider implements RuntimeInteractionProvider {
  readonly id = PROCESS_JSON_INTERACTION_PROVIDER;

  async invoke(
    request: RuntimeInteractionProviderRequest
  ): Promise<RuntimeInteractionProviderEvidence> {
    const command = request.action.request.command;
    if (
      !Array.isArray(command) ||
      command.length === 0 ||
      !command.every((argument) => typeof argument === 'string') ||
      typeof command[0] !== 'string' ||
      !command[0].trim()
    ) {
      throw new Error(
        "process-json-v1 interaction request requires a non-empty string 'command' argument vector."
      );
    }
    const requestedTimeout = request.action.request.timeoutMs;
    const timeoutMs = requestedTimeout === undefined ? request.limits.timeoutMs : requestedTimeout;
    if (
      typeof timeoutMs !== 'number' ||
      !Number.isSafeInteger(timeoutMs) ||
      timeoutMs < 1 ||
      timeoutMs > request.limits.timeoutMs
    ) {
      throw new Error(
        'process-json-v1 interaction timeoutMs must be a positive integer within the validation timeout.'
      );
    }

    const capture: DriverCapture = {
      stdout: [],
      stderr: [],
      stdoutBytes: 0,
      stderrBytes: 0,
      exceeded: false,
    };
    const child = spawn(command[0], command.slice(1), {
      cwd: request.cwd,
      detached: true,
      shell: false,
      windowsHide: true,
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    const driverStartedAt = Date.now();
    const tree = child.pid
      ? new OwnedProcessTree(child.pid, driverStartedAt)
      : undefined;
    const cleanupActions: RuntimeTerminationAction[] = [];
    let resolveAbort: (reason: 'spawn' | 'output') => void = () => undefined;
    const aborted = new Promise<'spawn' | 'output'>((resolve) => {
      resolveAbort = resolve;
    });
    let driverError: Error | undefined;
    child.on('error', (error) => {
      driverError = error;
      resolveAbort('spawn');
    });
    child.stdin.on('error', (error) => {
      driverError = error;
      resolveAbort('spawn');
    });
    child.stdout.on('data', (value: Buffer | string) => {
      const result = appendBounded(
        capture.stdout,
        capture.stdoutBytes,
        value,
        request.limits.stdoutBytes
      );
      capture.stdoutBytes = result.bytes;
      capture.exceeded ||= result.exceeded;
      if (result.exceeded) resolveAbort('output');
    });
    child.stderr.on('data', (value: Buffer | string) => {
      const result = appendBounded(
        capture.stderr,
        capture.stderrBytes,
        value,
        request.limits.stderrBytes
      );
      capture.stderrBytes = result.bytes;
      capture.exceeded ||= result.exceeded;
      if (result.exceeded) resolveAbort('output');
    });

    const input = {
      version: '1.0',
      sessionId: request.sessionId,
      actionId: request.action.id,
      sessionStartedAtEpochMs: request.sessionStartedAtEpochMs,
      invokedAtEpochMs: Date.now(),
      request: request.action.request.payload ?? {},
      milestones: request.milestones,
    };
    child.stdin.end(`${JSON.stringify(input)}\n`);

    const closed = new Promise<{ code: number | null; signal: string | null }>(
      (resolve) => {
        child.once('close', (code, signal) => resolve({ code, signal }));
      }
    );
    const treePoll = tree
      ? setInterval(() => {
          void tree.snapshot();
        }, 25)
      : undefined;
    treePoll?.unref();
    let timedOut = false;
    let timeoutHandle: NodeJS.Timeout;
    const timeout = new Promise<'timeout'>((resolve) => {
      timeoutHandle = setTimeout(() => {
        timedOut = true;
        resolve('timeout');
      }, timeoutMs);
    });
    const outcome = await Promise.race([
      closed.then((result) => ({ type: 'closed' as const, result })),
      aborted.then((reason) => ({ type: reason })),
      timeout.then(() => ({ type: 'timeout' as const })),
    ]);
    clearTimeout(timeoutHandle!);
    if (treePoll) clearInterval(treePoll);
    if (outcome.type !== 'closed') {
      if (tree) {
        await tree.terminate(Math.min(timeoutMs, 1_000), cleanupActions);
      } else {
        child.kill('SIGKILL');
      }
      await Promise.race([closed, delay(250)]);
    }
    const result = outcome.type === 'closed'
      ? outcome.result
      : { code: child.exitCode, signal: child.signalCode };
    if (driverError) throw new Error(`Interaction driver failed: ${driverError.message}`);
    if (timedOut) throw new Error(`Interaction driver exceeded its ${timeoutMs} ms timeout.`);
    if (capture.exceeded) throw new Error('Interaction driver exceeded its bounded output limit.');
    if (tree) {
      const remaining = await tree.snapshot();
      if (remaining.length > 0) {
        await tree.terminate(Math.min(timeoutMs, 1_000), cleanupActions);
        throw new Error(
          `Interaction driver left owned process IDs resident: ${remaining.join(', ')}.`
        );
      }
      if (tree.errors.length > 0) {
        throw new Error(
          `Interaction driver process tree could not be verified: ${tree.errors.join('; ')}`
        );
      }
    }
    if (result.code !== 0) {
      const stderr = Buffer.concat(capture.stderr, capture.stderrBytes).toString('utf8');
      throw new Error(
        `Interaction driver exited with code ${result.code ?? 'none'}${result.signal ? ` (${result.signal})` : ''}${stderr ? `: ${stderr}` : ''}`
      );
    }
    const stdout = Buffer.concat(capture.stdout, capture.stdoutBytes).toString('utf8').trim();
    let parsed: unknown;
    try {
      parsed = JSON.parse(stdout);
    } catch (cause) {
      throw new Error(
        `Interaction driver stdout is not one JSON document: ${cause instanceof Error ? cause.message : String(cause)}`
      );
    }
    return parseDriverEvidence(parsed);
  }
}

export function createDefaultRuntimeInteractionRegistry(): RuntimeInteractionProviderRegistry {
  return new RuntimeInteractionProviderRegistry().register(
    new ProcessJsonInteractionProvider()
  );
}

export function createDefaultRuntimeHostCapabilities(): RuntimeHostCapabilityRegistry {
  return new RuntimeHostCapabilityRegistry([
    'process',
    'stdio:pipe',
    `platform:${process.platform}`,
  ]);
}
