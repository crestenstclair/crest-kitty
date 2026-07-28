import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import type {
  RuntimeProcessTreeEvidence,
  RuntimeTerminationAction,
} from './types.js';

const execFileAsync = promisify(execFile);

interface ProcessIdentity {
  pid: number;
  ppid: number;
  pgid?: number;
}

export interface ProcessTreeOperations {
  enumerate(platform: NodeJS.Platform): Promise<ProcessIdentity[]>;
  isAlive(pid: number): boolean;
  signalPid(pid: number, signal: NodeJS.Signals): void;
  signalGroup(processGroupId: number, signal: NodeJS.Signals): void;
  terminateWindowsTree(pid: number, force: boolean): Promise<void>;
}

function parsePosixProcesses(stdout: string): ProcessIdentity[] {
  const processes: ProcessIdentity[] = [];
  for (const line of stdout.split(/\r?\n/)) {
    const values = line.trim().split(/\s+/).map(Number);
    if (
      values.length >= 3 &&
      values.every((value) => Number.isSafeInteger(value) && value >= 0)
    ) {
      processes.push({ pid: values[0], ppid: values[1], pgid: values[2] });
    }
  }
  return processes;
}

function parseWindowsProcesses(stdout: string): ProcessIdentity[] {
  if (!stdout.trim()) return [];
  const parsed: unknown = JSON.parse(stdout);
  const rows = Array.isArray(parsed) ? parsed : [parsed];
  return rows.flatMap((row) => {
    if (
      typeof row !== 'object' ||
      row === null ||
      Array.isArray(row) ||
      !Number.isSafeInteger(Number((row as Record<string, unknown>).ProcessId)) ||
      !Number.isSafeInteger(Number((row as Record<string, unknown>).ParentProcessId))
    ) {
      return [];
    }
    return [
      {
        pid: Number((row as Record<string, unknown>).ProcessId),
        ppid: Number((row as Record<string, unknown>).ParentProcessId),
      },
    ];
  });
}

function defaultOperations(): ProcessTreeOperations {
  return {
    async enumerate(platform) {
      if (platform === 'win32') {
        const script =
          'Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId | ConvertTo-Json -Compress';
        const { stdout } = await execFileAsync(
          'powershell.exe',
          ['-NoLogo', '-NoProfile', '-NonInteractive', '-Command', script],
          { encoding: 'utf8', maxBuffer: 4 * 1024 * 1024, windowsHide: true }
        );
        return parseWindowsProcesses(stdout);
      }
      const { stdout } = await execFileAsync('ps', ['-axo', 'pid=,ppid=,pgid='], {
        encoding: 'utf8',
        maxBuffer: 4 * 1024 * 1024,
        windowsHide: true,
      });
      return parsePosixProcesses(stdout);
    },
    isAlive(pid) {
      try {
        process.kill(pid, 0);
        return true;
      } catch (cause) {
        const code = (cause as NodeJS.ErrnoException).code;
        return code === 'EPERM';
      }
    },
    signalPid(pid, signal) {
      process.kill(pid, signal);
    },
    signalGroup(processGroupId, signal) {
      process.kill(-processGroupId, signal);
    },
    async terminateWindowsTree(pid, force) {
      const arguments_ = ['/PID', String(pid), '/T'];
      if (force) arguments_.push('/F');
      await execFileAsync('taskkill.exe', arguments_, {
        encoding: 'utf8',
        maxBuffer: 1024 * 1024,
        windowsHide: true,
      });
    },
  };
}

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

export class OwnedProcessTree {
  readonly processGroupId: number | null;
  private readonly observed = new Set<number>();
  private readonly descendants = new Set<number>();
  private readonly errors_: string[] = [];
  private parentExitedAtMs: number | undefined;

  constructor(
    readonly parentPid: number,
    private readonly startedAtEpochMs: number,
    private readonly platform: NodeJS.Platform = process.platform,
    private readonly operations: ProcessTreeOperations = defaultOperations()
  ) {
    this.processGroupId = platform === 'win32' ? null : parentPid;
    this.observed.add(parentPid);
  }

  get errors(): readonly string[] {
    return this.errors_;
  }

  recordParentExit(): void {
    this.parentExitedAtMs ??= Date.now() - this.startedAtEpochMs;
  }

  private recordError(cause: unknown): void {
    const message = cause instanceof Error ? cause.message : String(cause);
    if (!this.errors_.includes(message)) this.errors_.push(message);
  }

  async snapshot(): Promise<number[]> {
    let processes: ProcessIdentity[];
    try {
      processes = await this.operations.enumerate(this.platform);
    } catch (cause) {
      this.recordError(cause);
      return [...this.observed].filter((pid) => this.operations.isAlive(pid)).sort((a, b) => a - b);
    }

    const byParent = new Map<number, number[]>();
    for (const process_ of processes) {
      const children = byParent.get(process_.ppid) ?? [];
      children.push(process_.pid);
      byParent.set(process_.ppid, children);
    }
    const owned = new Set<number>();
    const queue = [...this.observed];
    while (queue.length > 0) {
      const pid = queue.shift() as number;
      if (owned.has(pid)) continue;
      owned.add(pid);
      for (const child of byParent.get(pid) ?? []) queue.push(child);
    }
    if (this.processGroupId !== null) {
      for (const process_ of processes) {
        if (process_.pgid === this.processGroupId) owned.add(process_.pid);
      }
    }
    for (const pid of owned) {
      this.observed.add(pid);
      if (pid !== this.parentPid) this.descendants.add(pid);
    }
    const livePids = new Set(processes.map((process_) => process_.pid));
    return [...this.observed]
      .filter((pid) => livePids.has(pid) || this.operations.isAlive(pid))
      .sort((a, b) => a - b);
  }

  private action(
    actions: RuntimeTerminationAction[],
    action: string,
    target: string,
    operation: () => void
  ): void {
    try {
      operation();
      actions.push({
        elapsedMs: Date.now() - this.startedAtEpochMs,
        action,
        target,
        succeeded: true,
      });
    } catch (cause) {
      const code = (cause as NodeJS.ErrnoException).code;
      const alreadyGone = code === 'ESRCH';
      actions.push({
        elapsedMs: Date.now() - this.startedAtEpochMs,
        action,
        target,
        succeeded: alreadyGone,
        detail: cause instanceof Error ? cause.message : String(cause),
      });
    }
  }

  private async waitForEmpty(milliseconds: number): Promise<boolean> {
    const deadline = Date.now() + Math.max(0, milliseconds);
    do {
      if ((await this.snapshot()).length === 0) return true;
      if (Date.now() >= deadline) break;
      await delay(Math.min(25, Math.max(1, deadline - Date.now())));
    } while (Date.now() <= deadline);
    return (await this.snapshot()).length === 0;
  }

  async terminate(
    graceMs: number,
    actions: RuntimeTerminationAction[]
  ): Promise<number[]> {
    const before = await this.snapshot();
    if (before.length === 0) return [];
    const softBudget = Math.max(1, Math.floor(graceMs / 2));
    const hardBudget = Math.max(1, graceMs - softBudget);

    if (this.platform === 'win32') {
      try {
        await this.operations.terminateWindowsTree(this.parentPid, false);
        actions.push({
          elapsedMs: Date.now() - this.startedAtEpochMs,
          action: 'terminate-tree',
          target: `pid:${this.parentPid}`,
          succeeded: true,
        });
      } catch (cause) {
        actions.push({
          elapsedMs: Date.now() - this.startedAtEpochMs,
          action: 'terminate-tree',
          target: `pid:${this.parentPid}`,
          succeeded: false,
          detail: cause instanceof Error ? cause.message : String(cause),
        });
      }
    } else if (this.processGroupId !== null) {
      this.action(actions, 'signal:SIGTERM', `process-group:${this.processGroupId}`, () =>
        this.operations.signalGroup(this.processGroupId as number, 'SIGTERM')
      );
    }
    for (const pid of before) {
      if (pid === this.parentPid && this.platform !== 'win32') continue;
      this.action(actions, 'signal:SIGTERM', `pid:${pid}`, () =>
        this.operations.signalPid(pid, 'SIGTERM')
      );
    }
    if (await this.waitForEmpty(softBudget)) return [];

    const remaining = await this.snapshot();
    if (this.platform === 'win32') {
      try {
        await this.operations.terminateWindowsTree(this.parentPid, true);
        actions.push({
          elapsedMs: Date.now() - this.startedAtEpochMs,
          action: 'force-terminate-tree',
          target: `pid:${this.parentPid}`,
          succeeded: true,
        });
      } catch (cause) {
        actions.push({
          elapsedMs: Date.now() - this.startedAtEpochMs,
          action: 'force-terminate-tree',
          target: `pid:${this.parentPid}`,
          succeeded: false,
          detail: cause instanceof Error ? cause.message : String(cause),
        });
      }
    } else if (this.processGroupId !== null) {
      this.action(actions, 'signal:SIGKILL', `process-group:${this.processGroupId}`, () =>
        this.operations.signalGroup(this.processGroupId as number, 'SIGKILL')
      );
    }
    for (const pid of remaining) {
      if (pid === this.parentPid && this.platform !== 'win32') continue;
      this.action(actions, 'signal:SIGKILL', `pid:${pid}`, () =>
        this.operations.signalPid(pid, 'SIGKILL')
      );
    }
    await this.waitForEmpty(hardBudget);
    return await this.snapshot();
  }

  async evidence(): Promise<RuntimeProcessTreeEvidence> {
    const remainingPids = await this.snapshot();
    return {
      parentPid: this.parentPid,
      processGroupId: this.processGroupId,
      observedPids: [...this.observed].sort((a, b) => a - b),
      observedDescendantPids: [...this.descendants].sort((a, b) => a - b),
      remainingPids,
      ...(this.parentExitedAtMs === undefined
        ? {}
        : { parentExitedAtMs: this.parentExitedAtMs }),
      noOwnedProcessesRemain: remainingPids.length === 0,
    };
  }
}

export const processTreeInternals = {
  parsePosixProcesses,
  parseWindowsProcesses,
};
