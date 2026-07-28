import { promises as fs } from 'node:fs';
import * as path from 'node:path';
import type { ResolvedOpenSpecRoot } from '../root-selection.js';
import { Validator } from '../validation/validator.js';
import type { ValidationIssue, ValidationReport } from '../validation/types.js';
import { buildUpdatedSpec, findSpecUpdates } from '../specs-apply.js';
import { discoverSpecFiles } from '../../utils/spec-discovery.js';
import type {
  AcceptanceDiagnostic,
  AcceptanceScope,
  OpenSpecValidationItem,
} from './types.js';

export interface StrictOpenSpecValidationResult {
  items: OpenSpecValidationItem[];
  diagnostics: AcceptanceDiagnostic[];
}

function item(
  id: string,
  type: OpenSpecValidationItem['type'],
  itemPath: string,
  report: ValidationReport
): OpenSpecValidationItem {
  return {
    id,
    type,
    path: itemPath,
    valid: report.valid,
    issues: report.issues,
  };
}

function errorReport(message: string, issuePath = 'file'): ValidationReport {
  const issue: ValidationIssue = { level: 'ERROR', path: issuePath, message };
  return {
    valid: false,
    issues: [issue],
    summary: { errors: 1, warnings: 0, info: 0 },
  };
}

async function listActiveChanges(changesDir: string): Promise<string[]> {
  const entries = await fs.readdir(changesDir, { withFileTypes: true });
  return entries
    .filter(
      (entry) =>
        entry.isDirectory() && entry.name !== 'archive' && !entry.name.startsWith('.')
    )
    .map((entry) => entry.name)
    .sort(compareStrings);
}

function compareStrings(left: string, right: string): number {
  return left < right ? -1 : left > right ? 1 : 0;
}

async function validateChange(
  validator: Validator,
  root: ResolvedOpenSpecRoot,
  changeName: string,
  includeAffectedSpecs: boolean
): Promise<OpenSpecValidationItem[]> {
  const items: OpenSpecValidationItem[] = [];
  const changeDir = path.join(root.changesDir, changeName);
  const proposalPath = path.join(changeDir, 'proposal.md');

  const deltaReport = await validator.validateChangeDeltaSpecs(changeDir);
  items.push(item(changeName, 'change', changeDir, deltaReport));

  const proposalReport = await validator.validateChange(proposalPath);
  items.push(item(changeName, 'proposal', proposalPath, proposalReport));

  if (!includeAffectedSpecs) return items;

  let updates;
  try {
    updates = await findSpecUpdates(changeDir, root.specsDir);
  } catch (cause) {
    items.push(
      item(
        changeName,
        'future_spec',
        path.join(changeDir, 'specs'),
        errorReport(
          `Could not discover affected specifications: ${cause instanceof Error ? cause.message : String(cause)}`
        )
      )
    );
    return items;
  }

  for (const update of updates) {
    if (update.exists) {
      items.push(item(update.id, 'spec', update.target, await validator.validateSpec(update.target)));
    }
    try {
      const { rebuilt } = await buildUpdatedSpec(update, changeName, { silent: true });
      items.push(
        item(
          update.id,
          'future_spec',
          update.target,
          await validator.validateSpecContent(update.id, rebuilt)
        )
      );
    } catch (cause) {
      items.push(
        item(
          update.id,
          'future_spec',
          update.target,
          errorReport(
            `Could not construct the post-delta specification: ${cause instanceof Error ? cause.message : String(cause)}`
          )
        )
      );
    }
  }

  return items;
}

export async function runStrictOpenSpecValidation(
  root: ResolvedOpenSpecRoot,
  scope: AcceptanceScope
): Promise<StrictOpenSpecValidationResult> {
  const validator = new Validator(true);
  const items: OpenSpecValidationItem[] = [];
  const diagnostics: AcceptanceDiagnostic[] = [];

  if (scope.mode === 'change') {
    if (!scope.change) {
      return {
        items,
        diagnostics: [
          {
            severity: 'error',
            code: 'acceptance_change_required',
            message: 'Change-scoped acceptance requires a change name.',
            path: 'scope.change',
          },
        ],
      };
    }
    try {
      const stats = await fs.stat(path.join(root.changesDir, scope.change));
      if (!stats.isDirectory()) throw new Error('target is not a directory');
    } catch {
      return {
        items,
        diagnostics: [
          {
            severity: 'error',
            code: 'acceptance_change_not_found',
            message: `Change '${scope.change}' was not found in the resolved OpenSpec root.`,
            path: path.join(root.changesDir, scope.change),
          },
        ],
      };
    }
    items.push(...(await validateChange(validator, root, scope.change, true)));
    return { items, diagnostics };
  }

  let changes: string[] = [];
  try {
    changes = await listActiveChanges(root.changesDir);
  } catch (cause) {
    diagnostics.push({
      severity: 'error',
      code: 'openspec_changes_unreadable',
      message: `Could not enumerate active changes: ${cause instanceof Error ? cause.message : String(cause)}`,
      path: root.changesDir,
    });
  }
  for (const changeName of changes) {
    items.push(...(await validateChange(validator, root, changeName, false)));
  }

  try {
    const specs = await discoverSpecFiles(root.specsDir);
    for (const spec of specs) {
      items.push(item(spec.id, 'spec', spec.specFile, await validator.validateSpec(spec.specFile)));
    }
  } catch (cause) {
    diagnostics.push({
      severity: 'error',
      code: 'openspec_specs_unreadable',
      message: `Could not enumerate canonical specifications: ${cause instanceof Error ? cause.message : String(cause)}`,
      path: root.specsDir,
    });
  }

  return { items, diagnostics };
}
