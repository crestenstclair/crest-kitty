import { spawn, type ChildProcess } from 'node:child_process';
import * as fs from 'node:fs';
import type { RuntimeStdioMode } from './types.js';

const PTY_CHILD_WRAPPER = String.raw`
const { spawn } = require('node:child_process');
let argv;
try { argv = JSON.parse(Buffer.from(process.argv[1], 'base64url').toString('utf8')); }
catch (error) { process.stderr.write(String(error)); process.exit(125); }
if (!Array.isArray(argv) || argv.length === 0 || !argv.every((value) => typeof value === 'string') || !argv[0]) process.exit(125);
const child = spawn(argv[0], argv.slice(1), { shell: false, windowsHide: true, stdio: 'inherit' });
child.once('error', (error) => { process.stderr.write(error.message); process.exit(125); });
child.once('exit', (code, signal) => {
  if (signal) { try { process.kill(process.pid, signal); } catch { process.exit(128); } }
  else process.exit(code ?? 1);
});`;

export interface RuntimeLaunchRequest {
  argv: string[];
  cwd: string;
  stdioMode: RuntimeStdioMode;
}

export interface RuntimeProcessLauncher {
  readonly ptyAvailable: boolean;
  launch(request: RuntimeLaunchRequest): ChildProcess;
}

function findScriptExecutable(): string | undefined {
  if (process.platform !== 'darwin' && process.platform !== 'linux') return undefined;
  for (const candidate of ['/usr/bin/script', '/bin/script']) {
    try {
      if (fs.statSync(candidate).isFile()) return candidate;
    } catch {
      // Try the next explicit platform location.
    }
  }
  return undefined;
}

function quotePosix(value: string): string {
  return `'${value.replaceAll("'", `'"'"'`)}'`;
}

export class NodeRuntimeProcessLauncher implements RuntimeProcessLauncher {
  private readonly scriptExecutable = findScriptExecutable();
  readonly ptyAvailable = this.scriptExecutable !== undefined;

  launch(request: RuntimeLaunchRequest): ChildProcess {
    if (request.stdioMode === 'pipe') {
      return spawn(request.argv[0], request.argv.slice(1), {
        cwd: request.cwd,
        detached: true,
        shell: false,
        windowsHide: true,
        stdio: ['ignore', 'pipe', 'pipe'],
      });
    }
    if (!this.scriptExecutable) {
      throw new Error(`PTY transport is unavailable on platform '${process.platform}'.`);
    }

    const encodedArgv = Buffer.from(JSON.stringify(request.argv), 'utf8').toString('base64url');
    const wrapperArgv = [process.execPath, '-e', PTY_CHILD_WRAPPER, encodedArgv];
    const scriptArguments =
      process.platform === 'darwin'
        ? ['-q', '/dev/null', ...wrapperArgv]
        : [
            '-qefc',
            wrapperArgv.map(quotePosix).join(' '),
            '/dev/null',
          ];
    return spawn(this.scriptExecutable, scriptArguments, {
      cwd: request.cwd,
      detached: true,
      shell: false,
      windowsHide: true,
      stdio: ['ignore', 'pipe', 'pipe'],
    });
  }
}
