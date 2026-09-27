# ARCEN — Frontend Specification

> Status: **frozen for v0.1** · Version: 0.1.0 · Owner: [@lewiseinstein15-Tech](https://github.com/lewiseinstein15-Tech)
> Companion docs: [ARCHITECTURE.md](ARCHITECTURE.md) · [BACKEND-SPEC.md](BACKEND-SPEC.md) · [TICKETS.md](TICKETS.md)
> The UI is a viewer for the NDJSON stream. It renders events; it does not hide them.

---

## Part 0 — Tech Choices

| Concern | Choice | Version | Why |
|---|---|---|---|
| Framework | [React](https://github.com/facebook/react) | 19 | concurrent rendering for streaming text |
| Language | TypeScript | 5.x | strict mode, no `any` in event paths |
| Build | [Vite](https://github.com/vitejs/vite) | 6 | instant HMR; the stream UI is iterated on constantly |
| State | [Zustand](https://github.com/pmndrs/zustand) | 5 | per-slice stores; no provider trees |
| Markdown | [react-markdown](https://github.com/remarkjs/react-markdown) | 9 | pipeline of remark/rehype plugins |
| Math | [KaTeX](https://github.com/KaTeX/KaTeX) | 0.16 | via `remark-math` + `rehype-katex` |
| Code highlight | [Shiki](https://github.com/shikijs/shiki) | 1.x | via `rehype-shiki`; TextMate grammars, JetBrains theme |
| Diagrams | [Mermaid](https://github.com/mermaid-js/mermaid) | 11 | lazy-loaded chunk; dark theme init |
| Drawer | [Vaul](https://github.com/emilkowalski/vaul) | 1.x | touch-first drawer for mobile sessions |
| Virtualization | [TanStack Virtual](https://github.com/TanStack/virtual) | 3 | 500+ event rows without jank |

Node 20+. Package manager: npm. No CSS framework — tokens.css plus plain CSS modules.

---

## Part 1 — Component Tree

```
<App>
├── <Drawer>                          mobile session list (Vaul, 375px)
├── <Header>                          wordmark · status dot · theme toggle*
│                                     (*present, inert in v0.1 — dark only)
└── <ChatView>
    ├── <Stream>                      role="log" aria-live="polite" · virtualized
    │   └── events[] ──▶ one block per event, keyed by seq:
    │       ├── <RunStartBlock>       ◆ goal line
    │       ├── <ThinkBlock>          ✱ DRAFT narration, collapsible
    │       ├── <PlanBlock>           ▸ steps checklist (plan / plan.update)
    │       ├── <SpawnBlock>          ⎇ sub-agent line + children (spawn / spawn.done)
    │       ├── <CommandBlock>        ❯ tool call (command / command.done)
    │       ├── <FileDiffBlock>       Δ unified diff, collapsed
    │       ├── <VerifyBlock>         ⊙ TEMPER pass/fail (verify.start / step.pass / step.fail)
    │       ├── <AnswerBlock>         ✦ Inter prose, markdown + math + code + mermaid
    │       ├── <MemoryBlock>         ⬡ recall/write notice
    │       ├── <UsageBlock>          ¤ tokens · cost
    │       ├── <RunErrorBlock>       ✗ fatal error banner
    │       └── <Footer>              session footer: usage rollup + status
    ├── <ScrollPill>                  floats above composer when scrolled up
    └── <Composer>                    auto-grow textarea · slash menu · send/stop
```

*plan.update mutates `<PlanBlock>` in place (matched by plan id). command.done mutates its `<CommandBlock>` in place. spawn.done mutates its `<SpawnBlock>` footer. Everything else appends.*

---

## Part 2 — Event → Component Map

All 17 event types, frozen — identical names and shapes to [BACKEND-SPEC.md](BACKEND-SPEC.md) Part 9.

| # | Event | Component | Default state |
|---|---|---|---|
| 1 | `run.start` | `RunStartBlock` | collapsed (goal line, always visible) |
| 2 | `think` | `ThinkBlock` | collapsed; auto-expands while it is the newest streaming block |
| 3 | `plan` | `PlanBlock` | expanded |
| 4 | `plan.update` | `PlanBlock` (in place) | stays expanded |
| 5 | `spawn` | `SpawnBlock` | expanded; children indented +2 spaces per depth |
| 6 | `spawn.done` | `SpawnBlock` footer (in place) | inline: `✓ TEST-READER · 3 calls · 12.4s` |
| 7 | `command` | `CommandBlock` | expanded while running |
| 8 | `command.done` | `CommandBlock` (in place) | collapsed to one line; click to open result |
| 9 | `file.diff` | `FileDiffBlock` | collapsed; click to open diff |
| 10 | `verify.start` | `VerifyBlock` | expanded |
| 11 | `step.pass` | `VerifyBlock` (in place) | inline pass line, mint |
| 12 | `step.fail` | `VerifyBlock` (in place) | expanded, danger; cannot collapse while retry pending |
| 13 | `answer` | `AnswerBlock` | always open; never collapsed |
| 14 | `memory` | `MemoryBlock` | collapsed (violet line) |
| 15 | `usage` | `UsageBlock` | inline in footer area |
| 16 | `run.done` | `Footer` | pinned; status + duration |
| 17 | `run.error` | `RunErrorBlock` | expanded; red banner, no collapse |

User overrides (Part 4) win over defaults for the session; defaults win on replay until the user interacts.

---

## Part 3 — Render Rules (frozen)

### 3.1 Colors — CSS custom properties, exact values, no derivatives

```css
:root {
  --bg:             #0A0B0D;
  --surface:        #111316;
  --elevated:       #181B20;
  --sunken:         #060709;
  --border-subtle:  #1E2126;
  --border:         #2A2E35;
  --border-strong:  #3A3F48;
  --text:           #E6E8EB;
  --text-2:         #9BA1A9;
  --text-3:         #6A7079;
  --accent:         #FF6B5C;   /* coral */
  --accent-hi:      #FF8878;
  --accent-lo:      #D9534A;
  --success:        #4ADE80;   /* mint */
  --warn:           #FBBF24;   /* amber */
  --danger:         #F87171;   /* soft red */
  --info:           #60A5FA;   /* sky */
  --memory:         #A78BFA;   /* violet */
  --browse:         #2DD4BF;   /* teal */
  --font-mono:      'JetBrains Mono', 'Geist Mono', 'SF Mono', Menlo, monospace;
  --font-sans:      'Inter', system-ui, sans-serif;
}
```

21 tokens. v0.1 is dark-only; the token names are the API — components never hard-code hex values.

### 3.2 Type

| Token | Font | Size | Weight | Line-height | Use |
|---|---|---|---|---|---|
| `meta` | mono | 11px | 500 | 1.4 | footer meter, timestamps |
| `label` | mono | 12px | 500 | 1.4 | block headers, glyphs, badges |
| `body` | mono | 13px | 400 | 1.5 | everything in the stream |
| `prose` | sans (Inter) | 15px | 400 | 1.65 | prose paragraphs in `AnswerBlock` only |
| `code` | mono | 12.5px | 400 | 1.55 | code blocks, diffs, command lines |

`letter-spacing: 0` on mono; `-0.01em` on prose. Weights 400/500/600 only. Everything in the stream is JetBrains Mono; Inter appears nowhere except `AnswerBlock` prose paragraphs.

### 3.3 Glyph map — 16 glyphs with colors

| Glyph | Meaning (event) | Color |
|---|---|---|
| `◆` | run.start | `--accent` |
| `◇` | run.done | `--success` |
| `✗` | run.error / step.fail | `--danger` |
| `✱` | think | `--text-3` |
| `▸` | plan / plan.update | `--accent` |
| `↻` | plan.update (re-plan) | `--warn` |
| `⎇` | spawn | `--info` |
| `✓` | spawn.done / step.pass | `--success` |
| `❯` | command | `--accent` |
| `●` | command.done | `--success` |
| `Δ` | file.diff | `--info` |
| `⊙` | verify.start | `--memory` |
| `⚑` | step.pass (check flag) | `--success` |
| `✦` | answer | `--accent-hi` |
| `⬡` | memory | `--memory` |
| `¤` | usage | `--text-2` |

Glyphs render in `label` style, one space before content, never colored content-wide — color belongs to the glyph and status, not to body text.

### 3.4 Indentation

- 2 spaces per depth level, **cap at 3** (max 6 spaces).
- Depth 0 = top-level agent events; depth 1 = sub-agent events; depth 2 = grandchild; depth ≥3 renders at cap with a `↳` continuation mark.
- Applies to mono stream lines; never applies inside `AnswerBlock` prose or code blocks.

### 3.5 Block code examples

**ThinkBlock** — collapsed narration:

```tsx
export const ThinkBlock = memo(function ThinkBlock({ event }: { event: ThinkEvent }) {
  const [open, setOpen] = useState(event.streaming); // newest block streams open
  return (
    <div className="block think" data-seq={event.seq}>
      <button className="block-head" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span className="glyph">✱</span>
        <span className="who">{event.agent}</span>
        {!open && <span className="preview">{truncate(event.text, 72)}</span>}
      </button>
      {open && <p className="body">{event.text}</p>}
    </div>
  );
});
```

**CommandBlock** — running then collapsed to result:

```tsx
export const CommandBlock = memo(function CommandBlock({ event }: { event: CommandEvent }) {
  const done = event.status === 'done';
  return (
    <div className={`block command ${done ? 'is-done' : 'is-running'}`} data-seq={event.seq}>
      <span className="glyph">❯</span>
      <span className="tool">{event.tool}</span>
      <code className="args">{summarizeArgs(event.args)}</code>
      {done && <span className="meta">{event.ok ? '●' : '✗'} {event.duration_s}s</span>}
      {done && <details><summary>result</summary><pre>{event.result.stdout}</pre></details>}
    </div>
  );
});
```

**SpawnBlock** — sub-agent with nested children:

```tsx
export const SpawnBlock = memo(function SpawnBlock({ event, children }: SpawnProps) {
  return (
    <div className="block spawn" style={{ paddingLeft: indent(event.depth) }} data-seq={event.seq}>
      <span className="glyph">⎇</span>
      <span className="who">{event.name}</span>
      <span className="task">{event.task}</span>
      {event.done && (
        <span className="meta">✓ {event.calls} calls · {event.duration_s}s</span>
      )}
      <div className="spawn-children">{children /* depth + 1, capped at 3 */}</div>
    </div>
  );
});
```

**AnswerBlock** — the only Inter prose on the page:

```tsx
export const AnswerBlock = memo(function AnswerBlock({ event }: { event: AnswerEvent }) {
  return (
    <div className="block answer" data-seq={event.seq}>
      <span className="glyph">✦</span>
      <Markdown prose>{event.text}</Markdown>  {/* gfm · math · shiki · mermaid */}
    </div>
  );
});
```

**Footer** — usage rollup, always at the end:

```tsx
export const Footer = memo(function Footer({ session }: { session: SessionMeta }) {
  return (
    <footer className="stream-footer">
      <span className="meta">¤ {session.tokens.input + session.tokens.output} tok</span>
      <span className="meta">${session.cost_usd.toFixed(3)}</span>
      <span className="meta">{session.duration_s}s</span>
      <span className={`status ${session.status}`}>{session.status}</span>
    </footer>
  );
});
```

---

## Part 4 — Panel State Machine

Every block type is a panel with three states: `open`, `closed`, `auto`.

- `auto` — the event's default state from Part 2 decides (plan opens, think collapses…)
- `open` — user pinned open; stays open regardless of new events
- `closed` — user pinned closed; new events increment the badge count instead of expanding

**Transition table:**

| From | Trigger | To | Notes |
|---|---|---|---|
| `auto` | user clicks chevron ▸ | `open` | pinned for the session |
| `auto` | user clicks chevron ▾ | `closed` | pinned for the session |
| `open` | user clicks chevron ▾ | `closed` | unpins |
| `closed` | high-signal event arrives | `open` | high-signal: `plan`, `step.fail`, `answer`, `run.error` |
| `closed` | low-signal event arrives | `closed` | badge count +1 |
| `open` / `closed` | `answer` arrives | `answer` block ignores panel state | always renders open |
| any | session replay starts | back to `auto` | user overrides reset per session |

**Zustand store:**

```ts
type PanelState = 'open' | 'closed' | 'auto';
type BlockKind = 'think' | 'plan' | 'spawn' | 'command' | 'diff' | 'verify' | 'memory' | 'error';

const HIGH_SIGNAL: BlockKind[] = ['plan', 'verify', 'error'];

interface PanelStore {
  panels: Record<BlockKind, PanelState>;
  badges: Record<BlockKind, number>;
  set: (kind: BlockKind, state: PanelState) => void;
  toggle: (kind: BlockKind) => void;
  onEvent: (kind: BlockKind) => void;
}

export const usePanelStore = create<PanelStore>((set) => ({
  panels: Object.fromEntries(BLOCK_KINDS.map((k) => [k, 'auto'])) as Record<BlockKind, PanelState>,
  badges: Object.fromEntries(BLOCK_KINDS.map((k) => [k, 0])) as Record<BlockKind, number>,
  set: (kind, state) => set((s) => ({ panels: { ...s.panels, [kind]: state } })),
  toggle: (kind) =>
    set((s) => ({
      panels: { ...s.panels, [kind]: s.panels[kind] === 'open' ? 'closed' : 'open' },
    })),
  onEvent: (kind) =>
    set((s) => {
      const state = s.panels[kind];
      if (state !== 'closed') return {};                       // auto/open: default wins
      if (HIGH_SIGNAL.includes(kind)) return { panels: { ...s.panels, [kind]: 'open' } };
      return { badges: { ...s.badges, [kind]: s.badges[kind] + 1 } };
    }),
}));
```

---

## Part 5 — Markdown / Math / Code / Diagrams

`AnswerBlock` renders through one pipeline:

| Plugin | Role |
|---|---|
| `remark-gfm` | tables, task lists, strikethrough, autolinks |
| `remark-math` | `$…$` inline, `$$…$$` display |
| `rehype-katex` | KaTeX render with `--text` color, throwOnError: false |
| `rehype-shiki` | Shiki, `jetbrains-dark` theme, line numbers off |

**Mermaid lazy-load** — the mermaid chunk downloads only when a ```` ```mermaid ```` fence appears:

```ts
let mermaidPromise: Promise<typeof import('mermaid').default> | null = null;

export function getMermaid() {
  mermaidPromise ??= import('mermaid').then((m) => {
    m.default.initialize({
      startOnLoad: false,
      theme: 'dark',
      fontFamily: 'JetBrains Mono, monospace',
      securityLevel: 'strict',
    });
    return m.default;
  });
  return mermaidPromise;
}

async function renderMermaid(code: string): Promise<string> {
  const mermaid = await getMermaid();
  const { svg } = await mermaid.render(`m-${hash(code)}`, code);
  return svg;
}
```

Render failure shows the raw fence with a warn-colored border — never a blank block.

**Image lightbox:** clicking any image in prose opens a fullscreen lightbox (scroll locked, Esc/backdrop click closes, zoom on wheel). Max display width = container; never upscale beyond natural size.

**Copy buttons:** every code block and diff gets a copy button on hover (top-right, `meta` size, label `copy` → `copied` for 1.5s). Copy uses `navigator.clipboard.writeText` with the raw source, not the highlighted HTML.

---

## Part 6 — Auto-Scroll

```ts
import { useEffect, useRef, useCallback } from 'react';

const BOTTOM_THRESHOLD = 100; // px from bottom that still counts as "pinned"

export function useAutoScroll(dep: unknown) {
  const ref = useRef<HTMLDivElement>(null);
  const pinned = useRef(true);

  const onScroll = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight <= BOTTOM_THRESHOLD;
  }, []);

  useEffect(() => {
    const el = ref.current;
    if (el && pinned.current) el.scrollTop = el.scrollHeight; // follow the stream
  }, [dep]);

  const scrollToBottom = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
    pinned.current = true;
  }, []);

  return { ref, onScroll, pinned: pinned.current, scrollToBottom };
}
```

Rules:

- `BOTTOM_THRESHOLD = 100` — frozen. Within 100px of bottom counts as pinned; further up is "browsing".
- While pinned, every appended event scrolls to bottom with no smooth animation (smooth fights a fast stream).
- While browsing, nothing moves — the stream never yanks the reader.

**Scroll pill:** when not pinned, a pill floats above the composer:

```
┌───────────────────────────┐
│  ▼  47 new events         │   ← click = scrollToBottom(), re-pin
└───────────────────────────┘
```

- Label shows the count of events appended since the user left the bottom.
- Hidden while pinned; appears with a 120ms fade; respects `prefers-reduced-motion` (no fade).
- Clicking it scrolls to bottom and re-enables pinning.

---

## Part 7 — Stream Consumption

```ts
export async function consumeStream(
  sessionId: string,
  onEvent: (e: ArcenEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`/api/stream?session=${sessionId}`, { signal });
  if (!res.ok || !res.body) throw new StreamError(res.status);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() ?? '';               // keep the partial line
    for (const line of lines) {
      if (!line.trim()) continue;
      onEvent(JSON.parse(line) as ArcenEvent);
    }
  }
  if (buffer.trim()) onEvent(JSON.parse(buffer) as ArcenEvent);
}
```

- One partial-line buffer — a `command.done` split across TCP chunks is never half-rendered.
- Malformed JSON emits a console error and a UI toast; the stream itself does not die.

**Resume on reconnect:** the reader tracks the last `seq` per session. On `fetch` failure or tab `visibilitychange → visible`, it reconnects with `Last-Event-ID: <seq>`; the server re-emits from that point (BACKEND-SPEC Part 9). Events arriving with `seq ≤ lastSeq` are dropped as duplicates; a gap (`seq > lastSeq + 1` after replay) triggers one full replay via `GET /api/sessions/<id>/events`.

**Event buffering:** while reconnecting, incoming user input queues in memory; `run.start` events are held and flushed in order on reconnect. The UI shows a `reconnecting…` pill (warn color) with the last known seq.

---

## Part 8 — Session Store & Persistence

Three storage layers, each with one job:

| Layer | Holds | Format | Lifetime |
|---|---|---|---|
| `localStorage` | active session id, panel states, composer draft, last seen `seq` | JSON keys `arcen.*` | until cleared |
| `~/.arcen/sessions/<id>.jsonl` | every event of every session (server-side) | NDJSON, append-only | permanent |
| `~/.arcen/memory.db` | cross-session entity graph | SQLite | permanent |

The UI never talks to SQLite or jsonl directly — only through the API (`GET /api/sessions`, `GET /api/sessions/<id>/events`), which replays the jsonl.

**Zustand store interfaces:**

```ts
interface StreamStore {
  events: ArcenEvent[];          // ordered by seq
  status: 'idle' | 'streaming' | 'done' | 'error';
  lastSeq: number;
  apply: (e: ArcenEvent) => void;
  hydrate: (events: ArcenEvent[]) => void;
}

interface SessionStore {
  sessions: SessionMeta[];
  activeId: string | null;
  list: () => Promise<void>;
  open: (id: string) => void;
  replay: (id: string) => Promise<void>;   // GET events → streamStore.hydrate
  rename: (id: string, title: string) => Promise<void>;
}
```

**Event flow:**

```
user sends ──▶ POST /api/run ──▶ run_id
                                    │
        GET /api/stream?session=…   ▼
 reader ──▶ parse line ──▶ streamStore.apply(e) ──▶ panelStore.onEvent(kind)
                                    │
                                    ├─▶ block renders (memo by seq)
                                    ├─▶ useAutoScroll dep++
                                    └─▶ sessionStore persists lastSeq to localStorage
```

Reload: `sessionStore.replay(activeId)` hydrates from the API, the stream re-renders in order, and the composer draft is restored from `localStorage`.

---

## Part 9 — State Management

Four Zustand stores, no cross-store imports — events flow one way:

| Store | Slice | Persisted |
|---|---|---|
| `streamStore` | `events[]`, `status`, `lastSeq` | `lastSeq` only |
| `sessionStore` | `sessions[]`, `activeId` | `activeId` |
| `panelStore` | `panels`, `badges` | `panels` |
| `drawerStore` | `open: boolean` | no |

Rules: no store reads another store; components compose them. Selectors are fine-grained (`usePanelStore((s) => s.panels.think)`) so a streaming block re-renders itself, not the page. `drawerStore` is deliberately ephemeral — a refresh closes the drawer.

---

## Part 10 — Composer

**Key bindings (frozen):**

| Key | Context | Action |
|---|---|---|
| `Enter` | menu closed, text present | send |
| `Shift+Enter` | always | newline |
| `↑` | composer empty | edit last sent message |
| `/` | composer empty | open slash commands menu |
| `↓` / `↑` | menu open | move selection |
| `Enter` | menu open | insert command |
| `Esc` | menu open | close menu |
| `Esc` | composer focused | blur composer |
| `Ctrl/Cmd+K` | anywhere | open session drawer |

**Send button states:**

| State | Icon | Enabled | Click |
|---|---|---|---|
| `idle` | `↗` | no (empty composer) | — |
| `armed` | `↗` (accent) | yes | `POST /api/run` |
| `streaming` | `■` stop | yes | interrupt run (`DELETE /api/run/<id>`) |
| `disabled` | `↗` (text-3) | no (offline) | — |

**Auto-grow rules:** `rows = min(8, max(1, lineCount))`; height animates via `field-sizing: growth` fallback JS; past 8 rows the textarea scrolls internally; composer never pushes the stream off-screen.

**Slash commands menu:** opens above the composer, filtered by the text after `/`:

```
┌─────────────────────────────────┐
│ /plan      show plan only       │
│ /dry-run   stream, change none  │
│ /model     switch provider      │
│ /mcp       list MCP servers     │
│ /clear     new session          │
└─────────────────────────────────┘
```

Filter-as-you-type; `↑↓` navigate; `Enter` inserts into the composer (does not send); `Esc` closes.

---

## Part 11 — Mobile

**Breakpoints:**

| Range | Layout |
|---|---|
| `< 768px` | mobile — single column, drawer nav, sticky composer, stream full-bleed |
| `768 – 1279px` | tablet — single column, inline session list, no drawer |
| `≥ 1280px` | desktop — centered stream (max 880px), session list docked left |

**Mobile header (fixed, 48px):**

```
┌──────────────────────────────────┐
│ [☰]   A R C E N          [◐]    │
│ drawer  wordmark        theme*   │  (*inert in v0.1 — dark only)
└──────────────────────────────────┘
```

- Drawer button left, 44×44 touch target, opens the Vaul drawer
- Wordmark centered in `label` style, letterspaced
- Theme toggle right, present but disabled in v0.1 (dark only) — wired, not hidden

**Drawer via Vaul:** slides from the left; lists sessions (active highlighted with the accent left-border), tap to `replay()`; drag-to-close and backdrop tap close; body scroll locked while open; focus trapped inside; returns focus to the drawer button on close.

**Touch targets:** all interactive elements ≥ 44×44px (buttons, chevrons, pill, drawer rows). Hover-only affordances (copy buttons) get a visible touch equivalent — long-press on a code block opens the copy action sheet.

---

## Part 12 — Performance

**Virtualization** — the stream renders through TanStack Virtual at 500+ events:

- Fixed-size estimate per block (variable measured after mount); `overscan: 12`
- Blocks are keyed by `seq` — never by index — so appends don't re-map existing rows
- Below 500 events the list renders plain (virtualization overhead not worth it), and the switch is transparent

**Streaming text mutation** — while a block streams (`think`, `command` args, `answer` prose), only that block's text node mutates:

- The growing event is stored separately (`streamStore.draft`) and merged into `events[]` when complete, so the array identity of finished events stays stable
- Text is appended via `ref` DOM mutation for `think`, virtual-DOM for `answer` (markdown reparses debounced at 50ms)

**Memoization strategy:**

| Level | Technique |
|---|---|
| Block | `React.memo` with props `{event, depth}` — identity changes only when that event updates |
| Store | fine-grained selectors (`s.panels.think`), not whole-store subscription |
| Derived | `useMemo` for glyph/color lookup tables (module-level constants, computed once) |
| List | TanStack Virtual row components memoized on `event.seq` + `done` flag |

Budget: a 1,000-event session scrolls at 60fps on a 2020 laptop; appending an event costs one row render, never a tree re-render.

---

## Part 13 — Accessibility

**aria-live on the stream:** the `<Stream>` container is `role="log" aria-live="polite"`. Screen readers get the whole narrated stream — that is the product.

- `aria-live="polite"` — never `"assertive"`; a fast stream must not interrupt the user's screen reader mid-sentence
- Every block is one `article` with `aria-label` from its glyph + summary (e.g. `✱ DRAFT: reading the failing test`)

**Focus visible:** a 2px `--accent` outline with 2px offset on every interactive element via `:focus-visible`; never `outline: none` without a replacement. Keyboard order follows DOM order (stream is `tabindex="0"`, blocks expand on Enter/Space as buttons).

**Reduced motion:** `@media (prefers-reduced-motion: reduce)` disables: scroll-pill fade, drawer slide (jumps instead), streaming shimmer, auto-scroll smoothing. Stream still appends instantly — content updates are never animated away.

**Screen reader announcement pattern:** high-frequency events (`command.done`, `memory`, `usage`) update an off-screen `aria-live="off"` region (they appear in the log on navigation). Announced immediately via the polite region: `run.start` ("ARCEN starting: <goal>"), `step.fail` ("Step <n> failed: <reason>"), `answer` (the prose itself), `run.done` ("Turn complete, <n> steps, <status>"). Everything else is discoverable in the log, not announced live — announcement is a summary, not a firehose.

---

## Part 14 — Test Plan

| ID | Test | Proves |
|---|---|---|
| F-01 | tokens.css loads; 21 custom properties resolve to exact spec hexes | Part 3.1 frozen palette |
| F-02 | App boots to ChatView; header, empty stream, composer present | Part 1 tree |
| F-03 | Composer send: type + click `↗` → `POST /api/run` fired once | Part 10 states |
| F-04 | Mock NDJSON stream of all 17 event types → all 17 components render with correct glyph/color | Part 2 map |
| F-05 | Panel machine: chevron toggles auto→open→closed; closed + low-signal → badge; closed + `step.fail` → opens | Part 4 |
| F-06 | Auto-scroll: append while pinned → stays at bottom | Part 6 |
| F-07 | Scroll up >100px → pill appears with new-event count | Part 6 |
| F-08 | Click pill → returns to bottom, re-pins, appends follow again | Part 6 |
| F-09 | Answer renders GFM table, `$…$` KaTeX, Shiki code block, mermaid SVG; copy button copies raw source | Part 5 |
| F-10 | Keyboard: Enter sends, Shift+Enter newlines, `/` opens menu, Esc closes, `↑` edits last | Part 10 |
| F-11 | 375px viewport: header shows drawer button; Vaul drawer opens; session list visible; targets ≥44px | Part 11 |
| F-12 | Reload mid-session: replay restores events in seq order; composer draft restored | Part 8 |

Same flakiness rule as the backend: **3× back-to-back, all green** (`npm run test && npm run test && npm run test`).

---

## Part 15 — Build Order

Twelve stages. Each stage ships something visible; no stage starts before the previous is green.

| Stage | Build | Ticket |
|---|---|---|
| 1 | `tokens.css` — 21 tokens, fonts, base reset | T-002 |
| 2 | App shell — `<App>`, `<Header>`, `<ChatView>`, empty `<Stream>` | T-021 |
| 3 | `reader.ts` — consumeStream + resume + buffering | T-022 |
| 4 | 17 event blocks with glyph/color from Part 3 | T-022 |
| 5 | Panel state machine + badges | T-023 |
| 6 | `useAutoScroll` + `<ScrollPill>` | T-024 |
| 7 | Markdown pipeline — gfm, math, Shiki, Mermaid, copy buttons | T-025 |
| 8 | Composer — auto-grow, key bindings, slash menu, send/stop | T-026 |
| 9 | Session store + localStorage persistence + replay | T-027 |
| 10 | Mobile — breakpoints, header, Vaul drawer | T-028 |
| 11 | Performance — virtualization, draft mutation, memo audit | — |
| 12 | Accessibility pass + F-01…F-12 green ×3 | T-029 |

---

## Part 16 — Pull Map

| Component | Source library | What to pull |
|---|---|---|
| Virtualized stream | [TanStack Virtual](https://github.com/TanStack/virtual) | `useVirtualizer` row pattern, dynamic measure |
| Markdown core | [react-markdown](https://github.com/remarkjs/react-markdown) | component + plugin pipeline wiring |
| GFM | [remark-gfm](https://github.com/remarkjs/remark-gfm) | as-is plugin |
| Math | [remark-math](https://github.com/remarkjs/remark-math) + [rehype-katex](https://github.com/remarkjs/remark-math) | as-is plugins, KaTeX CSS import |
| Code highlight | [Shiki](https://github.com/shikijs/shiki) | `rehype-shiki` with `jetbrains-dark`, lazy grammar load |
| Diagrams | [Mermaid](https://github.com/mermaid-js/mermaid) | dynamic `import('mermaid')`, dark init (Part 5) |
| Drawer | [Vaul](https://github.com/emilkowalski/vaul) | `<Drawer.Root>` primitives, drag-to-close |
| State | [Zustand](https://github.com/pmndrs/zustand) | `create` slices; no persist middleware — hand-rolled localStorage (Part 8) |
| Event typing | [AG-UI](https://github.com/ag-ui-protocol/ag-ui) | discriminated-union event type pattern, adapted to the frozen 17 |
| Slash menu | [cmdk](https://github.com/pacocoursey/cmdk) | list/filter/keyboard primitives for the composer menu |
| Auto-grow textarea | [react-textarea-autosize](https://github.com/Andarist/react-textarea-autosize) | auto-grow with maxRows=8 |
| Lightbox | [yet-another-react-lightbox](https://github.com/igordanchenko/yet-another-react-lightbox) | zoom + keyboard close, dark backdrop |

---

## Part 17 — Repository Structure

```
ui/
├── index.html
├── package.json
├── vite.config.ts
├── tsconfig.json
├── src/
│   ├── main.tsx
│   ├── App.tsx
│   ├── styles/
│   │   ├── tokens.css
│   │   └── global.css
│   ├── components/
│   │   ├── Header.tsx
│   │   ├── ChatView.tsx
│   │   ├── Composer.tsx
│   │   ├── Drawer.tsx
│   │   ├── ScrollPill.tsx
│   │   ├── CopyButton.tsx
│   │   └── Lightbox.tsx
│   ├── stream/
│   │   ├── reader.ts
│   │   ├── useAutoScroll.ts
│   │   └── useVirtualStream.ts
│   ├── events/
│   │   ├── index.ts              ← event kind → component map (17 rows)
│   │   ├── RunStartBlock.tsx
│   │   ├── ThinkBlock.tsx
│   │   ├── PlanBlock.tsx
│   │   ├── SpawnBlock.tsx
│   │   ├── CommandBlock.tsx
│   │   ├── FileDiffBlock.tsx
│   │   ├── VerifyBlock.tsx
│   │   ├── AnswerBlock.tsx
│   │   ├── MemoryBlock.tsx
│   │   ├── UsageBlock.tsx
│   │   ├── RunErrorBlock.tsx
│   │   └── Footer.tsx
│   ├── markdown/
│   │   ├── Markdown.tsx
│   │   ├── Mermaid.tsx
│   │   └── Code.tsx
│   ├── types/
│   │   └── events.ts             ← the frozen 17, as a discriminated union
│   └── state/
│       ├── streamStore.ts
│       ├── sessionStore.ts
│       ├── panelStore.ts
│       └── drawerStore.ts
└── tests/                        ← F-01…F-12 (vitest + testing-library)
```

`types/events.ts` mirrors `src/arcen/stream/events.py` name-for-name — a CI test diffs the two and fails on drift.

---

## Part 18 — Out of Scope (v0.1)

Deferred deliberately; each returns in a later version with its own spec part.

| Feature | Why deferred |
|---|---|
| Light theme / theme switching | one frozen palette keeps v0.1 honest; token names already theme-ready |
| Voice input | no backend contract yet |
| Multi-user / collaboration | sessions are single-owner in v0.1 |
| Plugin management UI | plugins are config-file managed; UI needs an API surface first |
| Stream editing / replay controls (scrub, branch) | replay is read-only; branching needs session forks |
| Sub-agent debug tree view | depth-capped indentation covers v0.1; full tree needs trace IDs |
| Cost budget alerts in UI | server-side `cost-guard` plugin exists; UI surfacing later |
| i18n | English-only copy; strings not yet centralized |
| Desktop app (Electron/Tauri) | browser UI is the product |
| Session search | needs server-side index over jsonl |

---

## Part 19 — Final Checklist

All 15 must be true before v0.1 ships:

1. `tokens.css` matches Part 3.1 hex-for-hex — zero hard-coded colors in components
2. All 17 event types render with the Part 2 map's glyph, color, and default state
3. Panel machine implements all 7 transitions; badges count while closed
4. Auto-scroll pins at `BOTTOM_THRESHOLD = 100` both ways; pill count accurate
5. Markdown pipeline renders GFM, KaTeX, Shiki, Mermaid; copy buttons copy raw source
6. Composer: every key binding in Part 10 works; auto-grow caps at 8 rows
7. Reload replays the session in `seq` order; composer draft survives
8. Drawer works at 375px with 44px touch targets; focus returns on close
9. Virtualization active at 500+ events; scroll stays at 60fps
10. Memo audit passed: appends re-render one row, not the tree
11. `aria-live="polite"` log + announcement pattern verified with a screen reader
12. Reduced-motion honored: no fade, no slide, no shimmer
13. F-01…F-12 pass 3× back-to-back
14. `npm run build` clean; bundle: mermaid/Shiki lazy chunks only
15. `types/events.ts` matches backend `events.py` — CI drift test green


