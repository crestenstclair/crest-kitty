import * as fs from 'node:fs';
import * as path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import fg from 'fast-glob';
import { FileSystemUtils } from '../utils/file-system.js';

const DEFAULT_CUE_ROOT = 'spec';
const BRIDGE_MAX_BUFFER = 32 * 1024 * 1024;

export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonObject | JsonValue[];
export interface JsonObject {
  [key: string]: JsonValue;
}

export interface CueRelationship {
  from: string;
  relation: string;
  to: string;
  detail?: string;
}

/**
 * A transient, evaluated view of the CUE architecture. CUE remains the source
 * of truth; this object exists only while OpenSpec assembles agent context.
 */
export interface CueArchitecture {
  root: string;
  files: string[];
  project: JsonObject;
  relationships: CueRelationship[];
}

export const CUE_INTERPRETATION_CONTRACT = `How to interpret and use the CUE architecture

Evaluation and authority
- All listed files are one CUE package. Declarations across files unify; they are not overrides processed in file order.
- The rendered project below is the concrete result of CUE evaluation at the top-level \`project\` field. It is the primary architecture input to planning.
- CUE is authoritative for architectural intent, boundaries, dependency direction, contracts, invariants, traceability, and verification. OpenSpec keeps its native proposal/spec/design/task/summary workflow and uses CUE to constrain the contents of those artifacts.
- CUE is also the dense, user-facing overview of that architecture. Keep declarations concise and relational; encode the authoritative model and proof instead of copying explanatory Markdown prose.
- Never silently plan around a conflict with CUE. If the requested change changes architecture, update the listed CUE sources during planning and evaluate them again. Do not defer CUE reconciliation to tasks or apply. Planning is incomplete while CUE and the Markdown artifacts disagree.

Intent model
- \`mission\` is the whole-project why and must inform every local decision. \`nonGoals\` are explicit exclusions.
- \`actors\` are stable participants. \`goals\` are outcomes, not implementation work; their status is derived rather than authored in CUE.
- \`capabilities\` are observable functionality that can serve multiple goals. Their \`acceptance\` scenarios describe journeys and required evidence.
- \`requirements\` are functional or nonfunctional constraints linked to goals and/or capabilities.
- \`evidence\` declares the proof required. \`completion.requiredGoals\` and \`completion.projectChecks\` define what completion means.
- Goal/capability links are bidirectional by design. Preserve their traceability rather than inventing unlinked OpenSpec capabilities.

Architecture model
- \`contexts\` are bounded contexts. Their \`purpose\`, \`ubiquitousLanguage\`, and invariants define ownership and vocabulary.
- \`valueObjects\` are immutable domain values: \`from\` is a newtype/enum representation; \`state\` is a structured value.
- \`aggregates\` are consistency boundaries. \`state\`, \`commands\`, \`events\`, and \`invariants\` define their behavioral model. Nested entities/value objects belong to that aggregate.
- \`domainServices\` hold domain behavior that does not naturally belong to one aggregate. \`applicationServices\` orchestrate use cases through operations and dependencies.
- \`repositories\` are persistence abstractions; \`of\` identifies the aggregate they store and \`contract\` defines the boundary.
- \`ports\` own boundary behavior. \`direction\` is inbound/outbound, \`contract\` defines operations, and \`consumes\` declares dependencies.
- \`adapters\` are delivery/infrastructure implementations of ports. \`implements\` points to the port; the port remains owner of the behavioral contract. Adapter profiles describe delivery mechanics, not domain behavior.
- \`contextMap\`, \`layers\`, and \`layerRules\` constrain context relationships and allowed dependency direction.

Resources and relations
- Canonical resource IDs are: \`context.<Context>\`, \`aggregate.<Context>.<Name>\`, \`entity.<Context>.<Aggregate>.<Name>\`, \`valueObject.<Context>[.<Aggregate>].<Name>\`, \`port.<Context>.<Name>\`, \`repository.<Context>.<Name>\`, \`domainService.<Context>.<Name>\`, \`applicationService.<Context>.<Name>\`, \`adapter.<Name>\`, \`assetKind.<Name>\`, and \`asset.[<Context>.[<Aggregate>.]]<Name>\`.
- \`uses\`, \`consumes\`, \`publishes\`, \`implements\`, \`of\`, and asset \`targets\` are directed architecture/dependency relations. Respect their direction when designing and sequencing work.
- \`contributesTo\` links an implementation resource to an observable capability. It is traceability, not a dependency edge. Use it to determine which resources realize a capability and which capabilities a resource can affect.
- Parent/containment relations express ownership, not dependency. Do not move behavior across bounded contexts or aggregate boundaries merely for implementation convenience.

Implementation and proof
- \`assets\` describe concrete implementation artifacts. Their kind, targets, prompts, profiles, and validations are implementation intent—not another planning database.
- \`meta\` is inherited guidance: language/style/rules/prompts/references/examples/avoid plus notes, rationale, framework, review level, mode, and amendments.
- Invariants are behavioral constraints. Treat them as non-negotiable acceptance/design constraints, not suggestions.
- \`validations\` are executable checks. Project validations are whole-system gates; attached validations prove local contracts or declared runtime sessions. Keep reachability, static, in-process behavior, external lifecycle, production composition, environment fidelity, and controlled interaction proof roles explicit.
- \`witnesses\` are behavioral proof with a positive command, a controlled negative command, structured observations, and predicates. Evidence links to validations/witnesses. Do not replace measured proof with self-reported success text.
- A runtime success marker is intermediate evidence, not completion. For applicable external-runtime claims, require a same-boundary runtime-session proof through declared success, teardown, parent exit, owned-resource cleanup, and any milestone-bound critical interaction.

How CUE drives OpenSpec artifacts
- Proposal: ground Why and scope in mission, goals, non-goals, capabilities, and requirements. Name the affected canonical IDs.
- Specs: derive observable behavior from capabilities, acceptance scenarios, requirements, invariants, and evidence while keeping OpenSpec requirement/scenario syntax.
- Design: map the change onto bounded contexts and canonical resources. Show existing and changed relations; obey ports, context maps, layers, and dependency direction.
- Tasks: sequence implementation assets/resources and validations/witnesses. CUE edits belong to planning itself, not a future bookkeeping task.
- Summary: provide a short, bullet-only outline of the other artifacts and the reconciled CUE model. It is an index, not another prose design document.
- Apply: implement against the rendered model and relevant CUE sources. Preserve OpenSpec task tracking, but treat CUE constraints and relationships as the architectural source of truth.`;

function isDirectory(candidatePath: string): boolean {
  try {
    return fs.statSync(candidatePath).isDirectory();
  } catch {
    return false;
  }
}

function bridgePath(): string {
  const configured = process.env.CREST_CUE_BRIDGE_BIN;
  if (configured) {
    return FileSystemUtils.canonicalizeExistingPath(configured);
  }

  const moduleDir = path.dirname(fileURLToPath(import.meta.url));
  const executable = process.platform === 'win32' ? 'crest-cue-bridge.exe' : 'crest-cue-bridge';
  return path.resolve(moduleDir, '..', '..', 'bin', executable);
}

function evaluateProject(root: string): JsonObject {
  const executable = bridgePath();
  const result = spawnSync(executable, [root], {
    encoding: 'utf-8',
    maxBuffer: BRIDGE_MAX_BUFFER,
    windowsHide: true,
  });

  if (result.error) {
    const hint = (result.error as NodeJS.ErrnoException).code === 'ENOENT'
      ? ' Build OpenSpec to compile the bundled CUE bridge.'
      : '';
    throw new Error(`Could not run the CUE architecture bridge: ${result.error.message}.${hint}`);
  }
  if (result.status !== 0) {
    const detail = result.stderr.trim() || `bridge exited with status ${result.status}`;
    throw new Error(`Could not evaluate CUE architecture at ${root}: ${detail}`);
  }

  try {
    const parsed: unknown = JSON.parse(result.stdout);
    if (!isObject(parsed)) {
      throw new Error('the resolved project is not an object');
    }
    return parsed;
  } catch (error) {
    throw new Error(
      `CUE architecture bridge returned invalid JSON: ${error instanceof Error ? error.message : String(error)}`
    );
  }
}

/** Evaluate the conventional top-level `spec/*.cue` package for a project. */
export interface LoadCueArchitectureOptions {
  evaluate?: (root: string) => JsonObject;
}

export function loadCueArchitecture(
  projectRoot: string,
  options: LoadCueArchitectureOptions = {}
): CueArchitecture | undefined {
  const candidateRoot = path.join(projectRoot, DEFAULT_CUE_ROOT);
  if (!isDirectory(candidateRoot)) {
    return undefined;
  }

  const root = FileSystemUtils.canonicalizeExistingPath(candidateRoot);
  const files = [
    ...new Set(
      fg
        .sync('*.cue', {
          cwd: root,
          absolute: true,
          dot: true,
          followSymbolicLinks: true,
          onlyFiles: true,
          unique: true,
        })
        .map((filePath) => FileSystemUtils.canonicalizeExistingPath(filePath))
    ),
  ].sort(compareStrings);

  if (files.length === 0) {
    return undefined;
  }

  const project = (options.evaluate ?? evaluateProject)(root);
  return {
    root,
    files,
    project,
    relationships: buildRelationships(project),
  };
}

function compareStrings(left: string, right: string): number {
  return left < right ? -1 : left > right ? 1 : 0;
}

function isObject(value: unknown): value is JsonObject {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function objectAt(object: JsonObject, key: string): JsonObject | undefined {
  const value = object[key];
  return isObject(value) ? value : undefined;
}

function stringsAt(object: JsonObject, key: string): string[] {
  const value = object[key];
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [];
}

function sortedEntries(object: JsonObject | undefined): Array<[string, JsonValue]> {
  return object
    ? Object.entries(object).sort(([left], [right]) => compareStrings(left, right))
    : [];
}

function buildRelationships(project: JsonObject): CueRelationship[] {
  const relations: CueRelationship[] = [];
  const seen = new Set<string>();
  const projectName = typeof project.name === 'string' ? project.name : 'project';
  const projectID = `project.${projectName}`;

  const add = (from: string, relation: string, to: string, detail?: string): void => {
    const key = JSON.stringify([from, relation, to, detail ?? '']);
    if (seen.has(key)) return;
    seen.add(key);
    relations.push({ from, relation, to, ...(detail ? { detail } : {}) });
  };

  const addList = (from: string, relation: string, values: string[]): void => {
    for (const to of values) add(from, relation, to);
  };

  const registerResource = (id: string, declaration: JsonObject, parent?: string): void => {
    if (parent) add(parent, 'contains', id);
    if (typeof declaration.layer === 'string') {
      add(id, 'belongs_to_layer', `layer.${declaration.layer}`);
    }
    if (typeof declaration.implements === 'string') add(id, 'implements', declaration.implements);
    if (typeof declaration.of === 'string') add(id, 'of', declaration.of);
    addList(id, 'uses', stringsAt(declaration, 'uses'));
    addList(id, 'consumes', stringsAt(declaration, 'consumes'));
    addList(id, 'publishes', stringsAt(declaration, 'publishes'));
    addList(id, 'targets', stringsAt(declaration, 'targets'));

    if (id.startsWith('asset.') && typeof declaration.kind === 'string') {
      add(id, 'uses', `assetKind.${declaration.kind}`);
    }
    const contributions = declaration.contributesTo;
    if (Array.isArray(contributions)) {
      for (const contribution of contributions) {
        if (!isObject(contribution) || typeof contribution.capability !== 'string') continue;
        add(
          id,
          'contributes_to',
          contribution.capability,
          typeof contribution.contribution === 'string' ? contribution.contribution : undefined
        );
      }
    }

    const localValidations = declaration.validations;
    if (Array.isArray(localValidations)) {
      localValidations.forEach((value, index) =>
        registerValidation(value, `validation.local.${id}.${index + 1}`, id, add, addList)
      );
    } else if (isObject(localValidations)) {
      for (const [name, value] of sortedEntries(localValidations)) {
        registerValidation(value, `validation.local.${id}.${name}`, id, add, addList);
      }
    }
  };

  for (const [name, actor] of sortedEntries(objectAt(project, 'actors'))) {
    if (isObject(actor)) add(projectID, 'defines', `actor.${name}`);
  }
  for (const [name, goalValue] of sortedEntries(objectAt(project, 'goals'))) {
    if (!isObject(goalValue)) continue;
    const id = `goal.${name}`;
    add(projectID, 'defines', id);
    addList(id, 'serves_actor', stringsAt(goalValue, 'actors'));
    addList(id, 'depends_on', stringsAt(goalValue, 'dependsOn'));
    addList(id, 'requires_capability', stringsAt(goalValue, 'capabilities'));
    addList(id, 'constrained_by', stringsAt(goalValue, 'requirements'));
  }
  for (const [name, capabilityValue] of sortedEntries(objectAt(project, 'capabilities'))) {
    if (!isObject(capabilityValue)) continue;
    const id = `capability.${name}`;
    add(projectID, 'defines', id);
    addList(id, 'supports_goal', stringsAt(capabilityValue, 'goals'));
    for (const [scenarioName, scenarioValue] of sortedEntries(objectAt(capabilityValue, 'acceptance'))) {
      if (!isObject(scenarioValue)) continue;
      const scenarioID = `acceptance.${name}.${scenarioName}`;
      add(id, 'accepted_by', scenarioID);
      if (typeof scenarioValue.actor === 'string') add(scenarioID, 'performed_by', scenarioValue.actor);
      addList(scenarioID, 'requires_evidence', stringsAt(scenarioValue, 'evidence'));
    }
  }
  for (const [name, requirementValue] of sortedEntries(objectAt(project, 'requirements'))) {
    if (!isObject(requirementValue)) continue;
    const id = `requirement.${name}`;
    add(projectID, 'defines', id);
    addList(id, 'constrains_goal', stringsAt(requirementValue, 'goals'));
    addList(id, 'constrains_capability', stringsAt(requirementValue, 'capabilities'));
  }
  for (const [name, evidenceValue] of sortedEntries(objectAt(project, 'evidence'))) {
    if (!isObject(evidenceValue)) continue;
    const id = `evidence.${name}`;
    add(projectID, 'defines', id);
    addList(id, 'proven_by', stringsAt(evidenceValue, 'validations'));
    addList(id, 'witnessed_by', stringsAt(evidenceValue, 'witnesses'));
  }

  const completion = objectAt(project, 'completion');
  if (completion) {
    addList(projectID, 'completion_requires', stringsAt(completion, 'requiredGoals'));
    addList(projectID, 'completion_checks', stringsAt(completion, 'projectChecks'));
  }

  for (const [layer, ruleValue] of sortedEntries(objectAt(project, 'layerRules'))) {
    if (!isObject(ruleValue)) continue;
    addList(`layer.${layer}`, 'may_depend_on', stringsAt(ruleValue, 'dependsOn').map((name) => `layer.${name}`));
  }

  for (const [name, kindValue] of sortedEntries(objectAt(project, 'assetKinds'))) {
    if (isObject(kindValue)) registerResource(`assetKind.${name}`, kindValue, projectID);
  }

  for (const [contextName, contextValue] of sortedEntries(objectAt(project, 'contexts'))) {
    if (!isObject(contextValue)) continue;
    const contextID = `context.${contextName}`;
    registerResource(contextID, contextValue, projectID);

    const registerContextChildren = (field: string, kind: string): void => {
      for (const [name, value] of sortedEntries(objectAt(contextValue, field))) {
        if (isObject(value)) registerResource(`${kind}.${contextName}.${name}`, value, contextID);
      }
    };
    registerContextChildren('valueObjects', 'valueObject');
    registerContextChildren('repositories', 'repository');
    registerContextChildren('ports', 'port');
    registerContextChildren('domainServices', 'domainService');
    registerContextChildren('applicationServices', 'applicationService');
    registerContextChildren('assets', 'asset');

    for (const [aggregateName, aggregateValue] of sortedEntries(objectAt(contextValue, 'aggregates'))) {
      if (!isObject(aggregateValue)) continue;
      const aggregateID = `aggregate.${contextName}.${aggregateName}`;
      registerResource(aggregateID, aggregateValue, contextID);
      for (const [name, value] of sortedEntries(objectAt(aggregateValue, 'entities'))) {
        if (isObject(value)) registerResource(`entity.${contextName}.${aggregateName}.${name}`, value, aggregateID);
      }
      for (const [name, value] of sortedEntries(objectAt(aggregateValue, 'valueObjects'))) {
        if (isObject(value)) registerResource(`valueObject.${contextName}.${aggregateName}.${name}`, value, aggregateID);
      }
      for (const [name, value] of sortedEntries(objectAt(aggregateValue, 'assets'))) {
        if (isObject(value)) registerResource(`asset.${contextName}.${aggregateName}.${name}`, value, aggregateID);
      }
    }
  }

  for (const [name, adapterValue] of sortedEntries(objectAt(project, 'adapters'))) {
    if (isObject(adapterValue)) registerResource(`adapter.${name}`, adapterValue, projectID);
  }
  for (const [name, assetValue] of sortedEntries(objectAt(project, 'assets'))) {
    if (isObject(assetValue)) registerResource(`asset.${name}`, assetValue, projectID);
  }

  const contextMap = project.contextMap;
  const contextRelationships = Array.isArray(contextMap)
    ? contextMap
    : isObject(contextMap)
      ? Object.values(contextMap)
      : [];
  for (const relationship of contextRelationships) {
    if (!isObject(relationship) || typeof relationship.from !== 'string' || typeof relationship.to !== 'string') continue;
    const kind = typeof relationship.kind === 'string' ? relationship.kind : 'related';
    const direction = typeof relationship.direction === 'string' ? relationship.direction : undefined;
    add(`context.${relationship.from}`, `context_map:${kind}`, `context.${relationship.to}`, direction);
  }

  const validations = project.validations;
  if (Array.isArray(validations)) {
    validations.forEach((value, index) =>
      registerValidation(value, `validation.${index + 1}`, projectID, add, addList)
    );
  } else if (isObject(validations)) {
    for (const [name, value] of sortedEntries(validations)) {
      registerValidation(value, `validation.${name}`, projectID, add, addList);
    }
  }

  for (const [name, witnessValue] of sortedEntries(objectAt(project, 'witnesses'))) {
    if (!isObject(witnessValue)) continue;
    const id = `witness.${name}`;
    add(projectID, 'defines', id);
    if (typeof witnessValue.goal === 'string') add(id, 'proves_goal', witnessValue.goal);
    if (typeof witnessValue.capability === 'string') add(id, 'proves_capability', witnessValue.capability);
    addList(id, 'observes', stringsAt(witnessValue, 'resources'));
    addList(id, 'may_repair', stringsAt(witnessValue, 'repairResources'));
    addList(id, 'counterexample_owned_by', stringsAt(witnessValue, 'counterexampleRepairResources'));
    addList(id, 'produces_evidence', stringsAt(witnessValue, 'evidence'));
    addList(id, 'produces_artifact', stringsAt(witnessValue, 'artifacts'));
  }

  return relations.sort((left, right) =>
    compareStrings(
      `${left.from}\u0000${left.relation}\u0000${left.to}\u0000${left.detail ?? ''}`,
      `${right.from}\u0000${right.relation}\u0000${right.to}\u0000${right.detail ?? ''}`
    )
  );
}

function registerValidation(
  value: JsonValue,
  fallbackID: string,
  ownerID: string,
  add: (from: string, relation: string, to: string, detail?: string) => void,
  addList: (from: string, relation: string, values: string[]) => void
): void {
  if (!isObject(value)) return;
  const id = typeof value.id === 'string' ? value.id : fallbackID;
  add(ownerID, 'validated_by', id);
  addList(id, 'checks_resource', stringsAt(value, 'resources'));
  addList(id, 'checks_capability', stringsAt(value, 'capabilities'));
  addList(id, 'checks_goal', stringsAt(value, 'goals'));
}

function stableValue(value: JsonValue): JsonValue {
  if (Array.isArray(value)) return value.map(stableValue);
  if (!isObject(value)) return value;
  return Object.fromEntries(
    sortedEntries(value).map(([key, child]) => [key, stableValue(child)])
  );
}

function renderRelationships(relationships: CueRelationship[]): string {
  if (relationships.length === 0) return '- No explicit relationships declared.';
  return relationships
    .map(({ from, relation, to, detail }) =>
      `- \`${from}\` --${relation}--> \`${to}\`${detail ? ` (${detail})` : ''}`
    )
    .join('\n');
}

/** Render evaluated CUE semantics into the native OpenSpec project-context channel. */
export function renderCueArchitectureContext(architecture: CueArchitecture): string {
  const fileList = architecture.files.map((filePath) => `- ${filePath}`).join('\n');
  const renderedProject = JSON.stringify(stableValue(architecture.project), null, 2);

  return `CUE architecture (authoritative)

${CUE_INTERPRETATION_CONTRACT}

Source package
Root: ${architecture.root}
Files:
${fileList}

Resolved relationship index
${renderRelationships(architecture.relationships)}

Resolved project value
\`\`\`json
${renderedProject}
\`\`\``;
}
