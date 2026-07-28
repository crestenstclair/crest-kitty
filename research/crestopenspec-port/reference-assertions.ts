import type {
  AcceptanceDiagnostic,
  AssertionDeclaration,
  AssertionEvaluator,
  AssertionResult,
  ProcessResult,
} from './types.js';

export class AssertionEvaluatorRegistry {
  private readonly evaluators = new Map<string, AssertionEvaluator>();

  register(evaluator: AssertionEvaluator): this {
    if (!evaluator.type.trim()) {
      throw new Error('Assertion evaluator type must not be empty.');
    }
    if (this.evaluators.has(evaluator.type)) {
      throw new Error(`Assertion evaluator '${evaluator.type}' is already registered.`);
    }
    this.evaluators.set(evaluator.type, evaluator);
    return this;
  }

  get(type: string): AssertionEvaluator | undefined {
    return this.evaluators.get(type);
  }

  list(): string[] {
    return [...this.evaluators.keys()].sort(compareStrings);
  }
}

function compareStrings(left: string, right: string): number {
  return left < right ? -1 : left > right ? 1 : 0;
}

function failed(
  index: number,
  type: string,
  code: string,
  message: string,
  expected?: string | number | boolean | null,
  observed?: string | number | boolean | null
): AssertionResult {
  return {
    index,
    type,
    passed: false,
    ...(expected !== undefined ? { expected } : {}),
    ...(observed !== undefined ? { observed } : {}),
    diagnostic: { severity: 'error', code, message },
  };
}

const exitCodeEvaluator: AssertionEvaluator = {
  type: 'exit-code',
  evaluate(declaration, process, index) {
    const expected = declaration.equals;
    if (typeof expected !== 'number' || !Number.isSafeInteger(expected)) {
      return failed(
        index,
        this.type,
        'assertion_malformed',
        `Assertion ${index} (${this.type}) requires an integer 'equals' value.`,
        undefined,
        process.exitCode
      );
    }
    const passed = process.exitCode === expected;
    return passed
      ? { index, type: this.type, passed, expected, observed: process.exitCode }
      : failed(
          index,
          this.type,
          'assertion_failed',
          `Expected exit code ${expected}, observed ${process.exitCode === null ? 'none' : process.exitCode}.`,
          expected,
          process.exitCode
        );
  },
};

function containsEvaluator(
  type: string,
  stream: 'stdout' | 'stderr',
  negated: boolean
): AssertionEvaluator {
  return {
    type,
    evaluate(declaration, process, index) {
      const expected = declaration.value;
      if (typeof expected !== 'string') {
        return failed(
          index,
          type,
          'assertion_malformed',
          `Assertion ${index} (${type}) requires a string 'value'.`
        );
      }
      const contains = process[stream].includes(expected);
      const passed = negated ? !contains : contains;
      const condition = negated ? 'not contain' : 'contain';
      return passed
        ? { index, type, passed, expected, observed: contains }
        : failed(
            index,
            type,
            'assertion_failed',
            `Expected ${stream} to ${condition} the declared value.`,
            expected,
            contains
          );
    },
  };
}

export function createDefaultAssertionRegistry(): AssertionEvaluatorRegistry {
  return new AssertionEvaluatorRegistry()
    .register(exitCodeEvaluator)
    .register(containsEvaluator('stdout-contains', 'stdout', false))
    .register(containsEvaluator('stdout-not-contains', 'stdout', true))
    .register(containsEvaluator('stderr-contains', 'stderr', false))
    .register(containsEvaluator('stderr-not-contains', 'stderr', true));
}

export async function evaluateAssertions(
  declarations: AssertionDeclaration[],
  process: ProcessResult,
  registry: AssertionEvaluatorRegistry
): Promise<AssertionResult[]> {
  const results: AssertionResult[] = [];

  for (let offset = 0; offset < declarations.length; offset++) {
    const declaration = declarations[offset];
    const index = offset + 1;
    const evaluator = registry.get(declaration.type);
    if (!evaluator) {
      results.push(
        failed(
          index,
          declaration.type,
          'assertion_unsupported',
          `No assertion evaluator is registered for '${declaration.type}'.`
        )
      );
      continue;
    }

    try {
      results.push(await evaluator.evaluate(declaration, process, index));
    } catch (error) {
      results.push(
        failed(
          index,
          declaration.type,
          'assertion_evaluator_error',
          `Assertion evaluator '${declaration.type}' failed: ${error instanceof Error ? error.message : String(error)}`
        )
      );
    }
  }

  return results;
}

export function assertionDiagnostics(results: AssertionResult[]): AcceptanceDiagnostic[] {
  return results.flatMap((result) => (result.diagnostic ? [result.diagnostic] : []));
}
