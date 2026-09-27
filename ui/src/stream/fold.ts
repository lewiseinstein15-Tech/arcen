// ARCEN — event folding (Part 1): plan.update mutates PlanBlock in place;
// command.done mutates its CommandBlock; spawn.done mutates its SpawnBlock
// footer; step.pass/step.fail mutate their VerifyBlock. Everything else appends.

import type {
  ArcenEvent,
  CommandDoneEvent,
  PlanUpdateEvent,
  SpawnDoneEvent,
  StepFailEvent,
  StepPassEvent,
} from '../types/events';

export interface FoldedBlock {
  seq: number; // the parent block's seq
  primary: ArcenEvent;
  done?: SpawnDoneEvent | CommandDoneEvent;
  update?: PlanUpdateEvent;
  verdicts?: (StepPassEvent | StepFailEvent)[];
}

export function foldEvents(events: ArcenEvent[]): FoldedBlock[] {
  const out: FoldedBlock[] = [];

  const lastParent = (
    type: ArcenEvent['type'],
    pred: (e: ArcenEvent) => boolean,
  ): FoldedBlock | undefined => {
    for (let i = out.length - 1; i >= 0; i--) {
      const b = out[i];
      if (b.primary.type === type && pred(b.primary)) return b;
    }
    return undefined;
  };

  for (const e of events) {
    switch (e.type) {
      case 'plan.update': {
        const parent = lastParent('plan', (p) => {
          const plan = p as Extract<ArcenEvent, { type: 'plan' }>;
          return plan.agent === e.agent;
        });
        if (parent) parent.update = e;
        else out.push({ seq: e.seq, primary: e });
        break;
      }
      case 'command.done': {
        const parent = lastParent('command', (p) => {
          const cmd = p as Extract<ArcenEvent, { type: 'command' }>;
          return cmd.step === e.step;
        });
        if (parent) parent.done = e;
        else out.push({ seq: e.seq, primary: e });
        break;
      }
      case 'spawn.done': {
        const parent = lastParent('spawn', (p) => {
          const spawn = p as Extract<ArcenEvent, { type: 'spawn' }>;
          return spawn.name === e.name;
        });
        if (parent) parent.done = e;
        else out.push({ seq: e.seq, primary: e });
        break;
      }
      case 'step.pass':
      case 'step.fail': {
        const parent = lastParent('verify.start', () => true);
        if (parent) {
          parent.verdicts = [...(parent.verdicts ?? []), e]; // verdicts accumulate
        } else {
          out.push({ seq: e.seq, primary: e });
        }
        break;
      }
      default:
        out.push({ seq: e.seq, primary: e });
    }
  }
  return out;
}
