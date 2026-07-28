import { spawn, type ChildProcess } from 'node:child_process';
import type {
  CommandRunner,
  ProcessExecutionRequest,
  ProcessResult,
  ProcessSpawnError,
  ProcessTermination,
} from './types.js';

interface CaptureState {
  chunks: Buffer[];
  bytes: number;
  truncated: boolean;
}

const FORCE_KILL_DELAY_MS = 250;

function cloneRequest(request: ProcessExecutionRequest) {
  return {
    argv: [...request.argv],
    cwd: request.cwd,
    limits: { ...request.limits },
  };
}

function toSpawnError(error: unknown): ProcessSpawnError {
  const candidate = error as NodeJS.ErrnoException;
  return {
    ...(candidate?.code ? { code: candidate.code } : {}),
    message: error instanceof Error ? error.message : String(error),
  };
}

function requestTermination(child: ChildProcess): NodeJS.Timeout {
  try {
    child.kill('SIGTERM');
  } catch {
    // The close/error event remains authoritative; the forced attempt below
    // handles a still-live process without masking its original result.
  }

  const forceTimer = setTimeout(() => {
    if (child.exitCode === null && child.signalCode === null) {
      try {
        child.kill('SIGKILL');
      } catch {
        // The result will still record the timeout/output-limit condition.
      }
    }
  }, FORCE_KILL_DELAY_MS);
  forceTimer.unref();
  return forceTimer;
}

function terminationFor(
  timedOut: boolean,
  outputLimitExceeded: Set<'stdout' | 'stderr'>,
  spawnError: ProcessSpawnError | undefined,
  signal: NodeJS.Signals | string | null
): ProcessTermination {
  if (timedOut) return 'timed_out';
  if (outputLimitExceeded.size > 0) return 'output_limit';
  if (spawnError) return 'spawn_error';
  if (signal) return 'signaled';
  return 'exited';
}

export class NodeCommandRunner implements CommandRunner {
  async run(request: ProcessExecutionRequest): Promise<ProcessResult> {
    const stableRequest = cloneRequest(request);
    const started = Date.now();
    let child: ChildProcess;

    try {
      child = spawn(stableRequest.argv[0], stableRequest.argv.slice(1), {
        cwd: stableRequest.cwd,
        shell: false,
        windowsHide: true,
        stdio: ['ignore', 'pipe', 'pipe'],
      });
    } catch (error) {
      return {
        ...stableRequest,
        durationMs: Date.now() - started,
        termination: 'spawn_error',
        exitCode: null,
        signal: null,
        timedOut: false,
        outputLimitExceeded: [],
        spawnError: toSpawnError(error),
        stdout: '',
        stderr: '',
        stdoutTruncated: false,
        stderrTruncated: false,
      };
    }

    const stdout: CaptureState = { chunks: [], bytes: 0, truncated: false };
    const stderr: CaptureState = { chunks: [], bytes: 0, truncated: false };
    const outputLimitExceeded = new Set<'stdout' | 'stderr'>();
    let timedOut = false;
    let spawnError: ProcessSpawnError | undefined;
    let forceKillTimer: NodeJS.Timeout | undefined;

    const terminateOnce = () => {
      if (!forceKillTimer) {
        forceKillTimer = requestTermination(child);
      }
    };

    const capture = (
      stream: 'stdout' | 'stderr',
      state: CaptureState,
      limit: number,
      value: Buffer | string
    ) => {
      const chunk = Buffer.isBuffer(value) ? value : Buffer.from(value);
      const remaining = Math.max(0, limit - state.bytes);
      if (remaining > 0) {
        const retained = chunk.length > remaining ? chunk.subarray(0, remaining) : chunk;
        state.chunks.push(retained);
        state.bytes += retained.length;
      }
      if (chunk.length > remaining) {
        state.truncated = true;
        outputLimitExceeded.add(stream);
        terminateOnce();
      }
    };

    child.stdout!.on('data', (value: Buffer | string) =>
      capture('stdout', stdout, stableRequest.limits.stdoutBytes, value)
    );
    child.stderr!.on('data', (value: Buffer | string) =>
      capture('stderr', stderr, stableRequest.limits.stderrBytes, value)
    );
    child.on('error', (error) => {
      spawnError = toSpawnError(error);
    });

    const timeoutTimer = setTimeout(() => {
      timedOut = true;
      terminateOnce();
    }, stableRequest.limits.timeoutMs);

    return await new Promise<ProcessResult>((resolve) => {
      child.once('close', (exitCode, signal) => {
        clearTimeout(timeoutTimer);
        if (forceKillTimer) clearTimeout(forceKillTimer);
        const normalizedSignal = signal ?? child.signalCode ?? null;
        const exceeded = (['stdout', 'stderr'] as const).filter((stream) =>
          outputLimitExceeded.has(stream)
        );

        resolve({
          ...stableRequest,
          durationMs: Date.now() - started,
          termination: terminationFor(
            timedOut,
            outputLimitExceeded,
            spawnError,
            normalizedSignal
          ),
          exitCode: spawnError ? null : exitCode,
          signal: normalizedSignal,
          timedOut,
          outputLimitExceeded: exceeded,
          ...(spawnError ? { spawnError } : {}),
          stdout: Buffer.concat(stdout.chunks, stdout.bytes).toString('utf8'),
          stderr: Buffer.concat(stderr.chunks, stderr.bytes).toString('utf8'),
          stdoutTruncated: stdout.truncated,
          stderrTruncated: stderr.truncated,
        });
      });
    });
  }
}
