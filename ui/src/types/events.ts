// ARCEN — the frozen 17 event types as a discriminated union.
// Mirrors src/arcen/stream/events.py name-for-name (FRONTEND-SPEC Part 17);
// a CI test diffs the two and fails on drift.

export const EVENT_TYPES = [
  'run.start',
  'think',
  'plan',
  'plan.update',
  'spawn',
  'spawn.done',
  'command',
  'command.done',
  'file.diff',
  'verify.start',
  'step.pass',
  'step.fail',
  'answer',
  'memory',
  'usage',
  'run.done',
  'run.error',
] as const;

export type EventType = (typeof EVENT_TYPES)[number];

export interface RunStartEvent {
  type: 'run.start';
  seq: number;
  ts: number;
  run_id: string;
  goal: string;
  depth: number;
}

export interface ThinkEvent {
  type: 'think';
  seq: number;
  ts: number;
  agent: string;
  text: string;
}

export interface PlanStep {
  id: number;
  title: string;
  tool: string | null;
}

export interface PlanEvent {
  type: 'plan';
  seq: number;
  ts: number;
  agent: string;
  steps: PlanStep[];
}

export interface PlanUpdateEvent {
  type: 'plan.update';
  seq: number;
  ts: number;
  agent: string;
  reason: string;
  steps: PlanStep[];
}

export interface SpawnEvent {
  type: 'spawn';
  seq: number;
  ts: number;
  parent: string;
  name: string;
  task: string;
  depth: number;
}

export interface SpawnDoneEvent {
  type: 'spawn.done';
  seq: number;
  ts: number;
  name: string;
  ok: boolean;
  calls: number;
  duration_s: number;
}

export interface CommandEvent {
  type: 'command';
  seq: number;
  ts: number;
  agent: string;
  step: number;
  tool: string;
  args: Record<string, unknown>;
}

export interface CommandDoneEvent {
  type: 'command.done';
  seq: number;
  ts: number;
  step: number;
  ok: boolean;
  result: Record<string, unknown> | null;
  duration_s: number;
}

export interface FileDiffEvent {
  type: 'file.diff';
  seq: number;
  ts: number;
  path: string;
  patch: string;
}

export interface VerifyStartEvent {
  type: 'verify.start';
  seq: number;
  ts: number;
  agent: string;
  target: string;
}

export interface StepPassEvent {
  type: 'step.pass';
  seq: number;
  ts: number;
  step: number;
  checks: string[];
}

export interface StepFailEvent {
  type: 'step.fail';
  seq: number;
  ts: number;
  step: number;
  reason: string;
  retry: number;
}

export interface AnswerEvent {
  type: 'answer';
  seq: number;
  ts: number;
  text: string;
}

export interface MemoryEvent {
  type: 'memory';
  seq: number;
  ts: number;
  op: string;
  entity: string;
  fact: string;
}

export interface UsageEvent {
  type: 'usage';
  seq: number;
  ts: number;
  tokens: { input: number; output: number };
  cost_usd: number;
}

export interface RunDoneEvent {
  type: 'run.done';
  seq: number;
  ts: number;
  status: 'ok' | 'failed' | 'interrupted';
  steps: number;
  duration_s: number;
}

export interface RunErrorEvent {
  type: 'run.error';
  seq: number;
  ts: number;
  code: string;
  message: string;
}

export type ArcenEvent =
  | RunStartEvent
  | ThinkEvent
  | PlanEvent
  | PlanUpdateEvent
  | SpawnEvent
  | SpawnDoneEvent
  | CommandEvent
  | CommandDoneEvent
  | FileDiffEvent
  | VerifyStartEvent
  | StepPassEvent
  | StepFailEvent
  | AnswerEvent
  | MemoryEvent
  | UsageEvent
  | RunDoneEvent
  | RunErrorEvent;
