// ARCEN — the event → component map (FRONTEND-SPEC Part 1/2).
// One block per event, keyed by seq. plan.update / command.done /
// spawn.done / step.pass / step.fail mutate their parent block in place;
// everything else appends.

import type { FoldedBlock } from '../stream/fold';
import type { CommandDoneEvent, SpawnDoneEvent } from '../types/events';
import { AnswerBlock } from './AnswerBlock';
import { CommandBlock } from './CommandBlock';
import { FileDiffBlock } from './FileDiffBlock';
import { Footer } from './Footer';
import { MemoryBlock } from './MemoryBlock';
import { PlanBlock } from './PlanBlock';
import { RunErrorBlock } from './RunErrorBlock';
import { RunStartBlock } from './RunStartBlock';
import { SpawnBlock } from './SpawnBlock';
import { ThinkBlock } from './ThinkBlock';
import { UsageBlock } from './UsageBlock';
import { VerifyBlock } from './VerifyBlock';

export function BlockFor({ block, depth }: { block: FoldedBlock; depth: number }) {
  const { primary, update, verdicts } = block;
  // the fold logic pairs each done with its parent type by construction
  const done = block.done as SpawnDoneEvent & CommandDoneEvent;
  switch (primary.type) {
    case 'run.start':
      return <RunStartBlock event={primary} />;
    case 'think':
      return <ThinkBlock event={primary} />;
    case 'plan':
    case 'plan.update':
      return <PlanBlock event={primary} update={update} />;
    case 'spawn':
      return <SpawnBlock event={primary} done={done} depth={depth} />;
    case 'spawn.done':
      return null; // folded into its spawn block
    case 'command':
      return <CommandBlock event={primary} done={done} />;
    case 'command.done':
      return null; // folded into its command block
    case 'file.diff':
      return <FileDiffBlock event={primary} />;
    case 'verify.start':
      return <VerifyBlock event={primary} verdicts={verdicts} />;
    case 'step.pass':
    case 'step.fail':
      return <VerifyBlock event={primary} verdicts={verdicts} />;
    case 'answer':
      return <AnswerBlock event={primary} />;
    case 'memory':
      return <MemoryBlock event={primary} />;
    case 'usage':
      return <UsageBlock event={primary} />;
    case 'run.error':
      return <RunErrorBlock event={primary} />;
    case 'run.done':
      return <Footer event={primary} />;
    default:
      return null;
  }
}
