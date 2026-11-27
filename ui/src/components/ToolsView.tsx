// ARCEN — Tools view (v0.2 "Tools" nav item, previously a placeholder).
//
// The agent's reachable surface, from the same three endpoints the planner
// is built from: /api/tools (name, description, args, and where each tool
// executes), /api/skills (the index; bodies load on demand) and /api/mcp
// (server state, plus connect for a server that is still declarative).
//
// The point is honesty: the model can only name what is listed here, so a
// tool missing from this page is a tool missing from the plan.

import { useCallback, useEffect, useState } from 'react';

interface ToolEntry {
  name: string;
  description: string;
  danger: string;
  required: string[];
  optional: string[];
  runs_in: 'sandbox' | 'host' | 'unknown';
}

interface SkillEntry {
  name: string;
  version: string;
  description: string;
  tools: string[];
  path: string;
}

interface McpServerEntry {
  name: string;
  state: string;
  error: string | null;
  transport: string;
  tools: { name: string; description: string }[];
}

interface PromptPayload {
  templates: Record<string, string>;
  catalog: string;
  skills: string;
  tools: string[];
  chars: number;
}

type Tab = 'tools' | 'skills' | 'mcp' | 'prompt';

const TABS: { id: Tab; label: string }[] = [
  { id: 'tools', label: 'Tools' },
  { id: 'skills', label: 'Skills' },
  { id: 'mcp', label: 'MCP' },
  { id: 'prompt', label: 'Prompt' },
];

export function ToolsView() {
  const [tab, setTab] = useState<Tab>('tools');
  const [tools, setTools] = useState<ToolEntry[] | null>(null);
  const [skills, setSkills] = useState<SkillEntry[] | null>(null);
  const [servers, setServers] = useState<McpServerEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [t, s, m] = await Promise.all([
        fetch('/api/tools').then((r) => r.json()),
        fetch('/api/skills').then((r) => r.json()),
        fetch('/api/mcp').then((r) => r.json()),
      ]);
      setTools(t.tools as ToolEntry[]);
      setSkills(s.skills as SkillEntry[]);
      setServers(m.servers as McpServerEntry[]);
      setError(null);
    } catch (err) {
      setError(String(err));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <section className="tools-view" data-testid="tools-view" aria-label="Tools">
      <header className="tools-head">
        <h2 className="settings-title">Tools</h2>
        <div className="tools-tabs" role="tablist">
          {TABS.map((t) => (
            <button
              key={t.id}
              role="tab"
              aria-selected={tab === t.id}
              className={`tools-tab ${tab === t.id ? 'is-active' : ''}`}
              data-testid={`tools-tab-${t.id}`}
              onClick={() => setTab(t.id)}
            >
              {t.label}
            </button>
          ))}
        </div>
      </header>

      {error && (
        <div className="settings-error" role="alert">
          could not load the tool surface — {error}
        </div>
      )}

      {tab === 'tools' && <ToolTable tools={tools} />}
      {tab === 'skills' && <SkillList skills={skills} />}
      {tab === 'mcp' && <McpServers servers={servers} onConnected={load} />}
      {tab === 'prompt' && <PromptInspector />}
    </section>
  );
}

function ToolTable({ tools }: { tools: ToolEntry[] | null }) {
  if (!tools) return <div className="settings-loading meta">loading tools…</div>;
  const sandbox = tools.filter((t) => t.runs_in === 'sandbox');
  const host = tools.filter((t) => t.runs_in !== 'sandbox');
  return (
    <>
      <p className="meta tools-note">
        {tools.length} tools are advertised to the planner. Sandbox tools run in the turn
        container; host tools run in the server process.
      </p>
      <ToolGroup title={`Sandbox · ${sandbox.length}`} tools={sandbox} />
      <ToolGroup title={`Host · ${host.length}`} tools={host} />
    </>
  );
}

function ToolGroup({ title, tools }: { title: string; tools: ToolEntry[] }) {
  if (tools.length === 0) return null;
  return (
    <fieldset className="settings-block">
      <legend>{title}</legend>
      <ul className="tool-list" data-testid="tool-list">
        {tools.map((t) => (
          <li key={t.name} className="tool-row" data-testid={`tool-${t.name}`}>
            <div className="tool-head">
              <code className="tool-name">{t.name}</code>
              <span className={`tool-danger danger-${t.danger}`}>{t.danger}</span>
            </div>
            <p className="tool-desc">{t.description}</p>
            {(t.required.length > 0 || t.optional.length > 0) && (
              <p className="tool-args meta">
                {t.required.map((a) => (
                  <span key={a} className="arg arg-required">
                    {a}
                  </span>
                ))}
                {t.optional.map((a) => (
                  <span key={a} className="arg">
                    {a}
                  </span>
                ))}
              </p>
            )}
          </li>
        ))}
      </ul>
    </fieldset>
  );
}

function SkillList({ skills }: { skills: SkillEntry[] | null }) {
  const [open, setOpen] = useState<string | null>(null);
  const [body, setBody] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const toggle = async (name: string) => {
    if (open === name) {
      setOpen(null);
      setBody(null);
      return;
    }
    setOpen(name);
    setLoading(true);
    try {
      const res = await fetch(`/api/skills/${encodeURIComponent(name)}`);
      const payload = (await res.json()) as { body?: string; detail?: string };
      setBody(payload.body ?? payload.detail ?? 'no body');
    } catch (err) {
      setBody(String(err));
    } finally {
      setLoading(false);
    }
  };

  if (!skills) return <div className="settings-loading meta">loading skills…</div>;
  if (skills.length === 0) {
    return <p className="meta">no skills installed — drop SKILL.md files under ./skills</p>;
  }
  return (
    <>
      <p className="meta tools-note">
        {skills.length} skills. The planner sees names and descriptions; a body loads only when
        the agent calls skill.load.
      </p>
      <ul className="skill-list" data-testid="skill-list">
        {skills.map((s) => (
          <li key={s.name} className="skill-row" data-testid={`skill-${s.name}`}>
            <button className="skill-head" onClick={() => void toggle(s.name)} aria-expanded={open === s.name}>
              <code className="tool-name">{s.name}</code>
              <span className="meta">v{s.version}</span>
            </button>
            <p className="tool-desc">{s.description}</p>
            <p className="tool-args meta">
              {s.tools.map((t) => (
                <span key={t} className="arg">
                  {t}
                </span>
              ))}
            </p>
            {open === s.name && (
              <pre className="skill-body" data-testid="skill-body">
                {loading ? 'loading…' : body}
              </pre>
            )}
          </li>
        ))}
      </ul>
    </>
  );
}

function McpServers({
  servers,
  onConnected,
}: {
  servers: McpServerEntry[] | null;
  onConnected: () => Promise<void>;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const connect = async (name: string) => {
    setBusy(name);
    setNote(null);
    try {
      const res = await fetch(`/api/mcp/${encodeURIComponent(name)}/connect`, { method: 'POST' });
      const body = (await res.json()) as { ok?: boolean; error?: string | null; state?: string };
      setNote(
        body.ok
          ? `${name} connected — its tools join the next plan`
          : `${name}: ${body.error ?? body.state ?? 'connect failed'}`,
      );
      await onConnected();
    } catch (err) {
      setNote(String(err));
    } finally {
      setBusy(null);
    }
  };

  if (!servers) return <div className="settings-loading meta">loading servers…</div>;
  if (servers.length === 0) {
    return (
      <p className="meta">
        no MCP servers configured — add one under <code>mcps:</code> in ~/.arcen/config.yaml
      </p>
    );
  }
  return (
    <>
      {note && (
        <div className="settings-warn" role="status">
          {note}
        </div>
      )}
      <ul className="mcp-list" data-testid="mcp-list">
        {servers.map((s) => (
          <li key={s.name} className="mcp-row" data-testid={`mcp-${s.name}`}>
            <div className="tool-head">
              <code className="tool-name">{s.name}</code>
              <span className={`mcp-state state-${s.state}`}>{s.state}</span>
              <span className="meta">{s.transport}</span>
            </div>
            {s.error && <p className="mcp-error">{s.error}</p>}
            <p className="tool-args meta">
              {s.tools.length === 0 ? 'no tools published' : s.tools.map((t) => t.name).join(', ')}
            </p>
            {s.state !== 'connected' && s.state !== 'disabled' && (
              <button
                className="settings-btn"
                onClick={() => void connect(s.name)}
                disabled={busy === s.name}
              >
                {busy === s.name ? 'connecting…' : 'Connect'}
              </button>
            )}
          </li>
        ))}
      </ul>
    </>
  );
}

function PromptInspector() {
  const [data, setData] = useState<PromptPayload | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const res = await fetch('/api/prompt');
        if (!res.ok) throw new Error(`prompt load failed (${res.status})`);
        setData((await res.json()) as PromptPayload);
      } catch (err) {
        setError(String(err));
      }
    })();
  }, []);

  if (error) {
    return (
      <div className="settings-error" role="alert">
        {error}
      </div>
    );
  }
  if (!data) return <div className="settings-loading meta">loading prompt…</div>;

  return (
    <>
      <p className="meta tools-note">
        What the planner will be told on the next turn: {data.tools.length} tools and{' '}
        {data.chars} characters of catalog and skills. Read this before blaming the model.
      </p>
      <fieldset className="settings-block">
        <legend>Catalog</legend>
        <pre className="skill-body" data-testid="prompt-catalog">
          {data.catalog}
        </pre>
      </fieldset>
      {data.skills && (
        <fieldset className="settings-block">
          <legend>Skills index</legend>
          <pre className="skill-body">{data.skills}</pre>
        </fieldset>
      )}
      <fieldset className="settings-block">
        <legend>Templates</legend>
        {Object.entries(data.templates).map(([name, text]) => (
          <details key={name} className="prompt-template">
            <summary>
              <code className="tool-name">{name}</code>
            </summary>
            <pre className="skill-body">{text}</pre>
          </details>
        ))}
      </fieldset>
    </>
  );
}
