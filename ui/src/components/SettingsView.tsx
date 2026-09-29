// ARCEN — Settings view (T-036). Four sections per the ticket:
// PROVIDER (dropdown · base URL · masked key · model · Test Connection ·
// Save), AGENTS (per-role models + caps), SANDBOX (backend · image ·
// memory · cpu), GENERAL (theme · stream verbosity · auto-scroll).
//
// Save flow: PUT /api/config carries the FULL config fetched on mount.
// An untouched key field round-trips the '<redacted>' placeholder and the
// server substitutes the stored credential — a redacted view can never
// wipe a key. Saving persists to ~/.arcen/config.yaml and reloads the
// provider bridge in-memory.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Toast } from './Toast';

const PROVIDERS = ['custom', 'groq', 'deepseek', 'openai', 'anthropic', 'ollama'] as const;
type Provider = (typeof PROVIDERS)[number];

const MODEL_SUGGESTIONS: Record<Provider, string[]> = {
  anthropic: ['claude-sonnet-4-5', 'claude-haiku-4-5', 'claude-opus-4-1'],
  openai: ['gpt-4o', 'gpt-4o-mini', 'o1', 'o1-mini'],
  groq: ['llama-3.3-70b-versatile', 'llama-3.1-8b-instant', 'mixtral-8x7b-32768'],
  deepseek: ['deepseek-chat', 'deepseek-reasoner'],
  ollama: ['llama3.2', 'qwen2.5-coder:7b', 'mistral'],
  custom: ['gpt-4o-mini', 'llama-3.3-70b-versatile', 'deepseek-chat'],
};

const VERBOSITY_KEY = 'arcen.verbosity';
const AUTOSCROLL_KEY = 'arcen.autoscroll';

const SANDBOX_BACKENDS = ['auto', 'docker', 'process'] as const;

interface SandboxStatus {
  docker_available: boolean;
  image_present: boolean;
  image: string;
  // T-043: the boot-detected backend decision, surfaced for the user
  backend?: string;
  effective?: string;
  reason?: string;
  degraded?: boolean;
}

/** The General section's auto-scroll preference (T-036), read by ChatView. */
export function autoScrollPreference(): boolean {
  return localStorage.getItem(AUTOSCROLL_KEY) !== 'off'; // on by default
}

interface TestState {
  status: 'idle' | 'testing' | 'ok' | 'err';
  message?: string;
}

// T-051: every Save state is visible — no silent no-ops.
type SaveState = { kind: 'clean' | 'saved' | 'error'; message?: string };

export function SettingsView() {
  const [cfg, setCfg] = useState<Record<string, unknown> | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [test, setTest] = useState<TestState>({ status: 'idle' });
  const [toast, setToast] = useState<{ message: string; kind: 'ok' | 'err' } | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveState, setSaveState] = useState<SaveState>({ kind: 'clean' });
  const savedCfgRef = useRef<Record<string, unknown> | null>(null); // last server view
  const savedTimer = useRef<number | null>(null);
  const [sandboxStatus, setSandboxStatus] = useState<SandboxStatus | null>(null);

  // local (UI-only) general preferences
  const [verbosity, setVerbosity] = useState<'full' | 'compact' | 'minimal'>('full');
  const [autoScroll, setAutoScroll] = useState(true);

  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const res = await fetch('/api/config');
        if (!res.ok) throw new Error(`config load failed (${res.status})`);
        const body = (await res.json()) as Record<string, unknown>;
        if (alive) {
          setCfg(body);
          savedCfgRef.current = body; // the server view Save is measured against
        }
      } catch (err) {
        if (alive) setLoadError(String(err));
      }
      // docker/image availability for the backend warning (T-038) —
      // advisory: a failure to fetch it never blocks Settings
      try {
        const st = await fetch('/api/sandbox/status');
        const body = (await st.json()) as Partial<SandboxStatus> | null;
        if (st.ok && alive && body && typeof body === 'object' && 'docker_available' in body) {
          setSandboxStatus(body as SandboxStatus);
        }
      } catch {
        /* status is advisory — absence just means no warning */
      }
    })();
    const v = localStorage.getItem(VERBOSITY_KEY);
    if (v === 'compact' || v === 'minimal' || v === 'full') setVerbosity(v);
    setAutoScroll(localStorage.getItem(AUTOSCROLL_KEY) !== 'off');
    return () => {
      alive = false;
    };
  }, []);

  // -- typed accessors over the raw config tree ---------------------------
  // T-049: the provider block is four scalars (name/base_url/api_key/model)
  // — no per-vendor dicts, no shipped vendor defaults.
  const provider = (cfg?.provider ?? {}) as Record<string, unknown>;
  const agents = (cfg?.agents ?? {}) as Record<string, Record<string, unknown>>;
  const sandbox = (cfg?.sandbox ?? {}) as Record<string, unknown>;

  const currentProvider = (provider.name as Provider) || 'custom';
  const [keyDraft, setKeyDraft] = useState<string | undefined>(undefined);

  const patchProvider = (patch: Record<string, unknown>) => {
    setCfg((c) => {
      const p = (c?.provider as Record<string, unknown> | undefined) ?? {};
      return { ...c, provider: { ...p, ...patch } };
    });
  };
  const patchAgent = (name: string, field: string, value: unknown) => {
    setCfg((c) => {
      const a = (c?.agents as Record<string, Record<string, unknown>> | undefined) ?? {};
      return { ...c, agents: { ...a, [name]: { ...a[name], [field]: value } } };
    });
  };
  const patchSandbox = (patch: Record<string, unknown>) => {
    setCfg((c) => {
      const s = (c?.sandbox as Record<string, unknown> | undefined) ?? {};
      return { ...c, sandbox: { ...s, ...patch } };
    });
  };

  // T-051: dirty when the form differs from the last saved server view,
  // or when a typed key has not been sent yet.
  const dirty = useMemo(() => {
    if (savedCfgRef.current == null) return false;
    if (keyDraft !== undefined && keyDraft !== '') return true;
    return JSON.stringify(cfg) !== JSON.stringify(savedCfgRef.current);
  }, [cfg, keyDraft]);

  const doTest = useCallback(async () => {
    setTest({ status: 'testing' });
    try {
      const res = await fetch('/api/config/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          provider: currentProvider,
          model: String(provider.model ?? ''),
          base_url: String(provider.base_url ?? ''),
          api_key:
            keyDraft !== undefined && keyDraft !== ''
              ? keyDraft
              : String(provider.api_key ?? ''),
        }),
      });
      const body = (await res.json()) as { ok: boolean; error?: string; sample?: string };
      if (body.ok) setTest({ status: 'ok', message: `connected · ${body.sample ?? ''}` });
      else setTest({ status: 'err', message: body.error ?? 'connection failed' });
    } catch (err) {
      setTest({ status: 'err', message: String(err) });
    }
  }, [currentProvider, provider.model, provider.base_url, provider.api_key, keyDraft]);

  const doSave = useCallback(async () => {
    if (!cfg) return; // a null config renders the loading/error view — no inert button
    setSaving(true);
    setSaveState({ kind: 'clean' });
    try {
      const payload = structuredClone(cfg);
      const p = (payload.provider ?? {}) as Record<string, unknown>;
      // the select DISPLAYS 'custom' while the stored name is still empty —
      // persist what the user sees, never a silent empty name (T-049)
      if (!String(p.name ?? '').trim()) p.name = currentProvider;
      if (keyDraft !== undefined && keyDraft !== '') p.api_key = keyDraft;
      payload.provider = p;
      const res = await fetch('/api/config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        signal: AbortSignal.timeout(20_000), // a hung PUT must not wedge the button
      });
      if (!res.ok) {
        const detail = await res.text();
        throw new Error(detail.slice(0, 160) || String(res.status));
      }
      // adopt the server's redacted view so the key field stays consistent
      const saved = (await res.json()) as Record<string, unknown>;
      setCfg(saved);
      savedCfgRef.current = saved;
      localStorage.setItem(VERBOSITY_KEY, verbosity);
      localStorage.setItem(AUTOSCROLL_KEY, autoScroll ? 'on' : 'off');
      setToast({ message: 'Saved', kind: 'ok' });
      setKeyDraft(undefined);
      setSaveState({ kind: 'saved' }); // "saved ✓" shows for 3s (T-051)
      if (savedTimer.current !== null) window.clearTimeout(savedTimer.current);
      savedTimer.current = window.setTimeout(() => setSaveState({ kind: 'clean' }), 3000);
    } catch (err) {
      const reason = err instanceof DOMException && err.name === 'TimeoutError'
        ? 'save timed out after 20s — is the server running?'
        : String(err);
      setToast({ message: `Error: ${reason}`, kind: 'err' });
      setSaveState({ kind: 'error', message: reason }); // red chip stays until retried
    } finally {
      setSaving(false);
    }
  }, [cfg, keyDraft, currentProvider, verbosity, autoScroll]);

  if (loadError) {
    return (
      <section className="settings" data-testid="settings-view">
        <div className="settings-error" role="alert">config could not be loaded — {loadError}</div>
      </section>
    );
  }
  if (!cfg) {
    return (
      <section className="settings" data-testid="settings-view">
        <div className="settings-loading meta">loading configuration…</div>
      </section>
    );
  }

  return (
    <section className="settings" data-testid="settings-view" aria-label="Settings">
      <h2 className="settings-title">Settings</h2>

      {/* -- 1. PROVIDER ------------------------------------------------- */}
      <fieldset className="settings-block" data-testid="settings-provider">
        <legend>PROVIDER</legend>

        <label className="field">
          <span className="field-label">Provider</span>
          <select
            data-testid="provider-select"
            value={currentProvider}
            onChange={(e) => patchProvider({ name: e.target.value })}
          >
            {PROVIDERS.map((p) => (
              <option key={p} value={p}>{p}</option>
            ))}
          </select>
        </label>

        {(currentProvider === 'custom' || currentProvider === 'ollama') && (
          <label className="field">
            <span className="field-label">Base URL</span>
            <input
              type="text"
              data-testid="base-url-input"
              placeholder="http://localhost:11434"
              value={String(provider.base_url ?? '')}
              onChange={(e) => patchProvider({ base_url: e.target.value })}
            />
          </label>
        )}

        <label className="field">
          <span className="field-label">API Key</span>
          <input
            type="password"
            data-testid="api-key-input"
            placeholder={String(provider.api_key ?? '') ? '•••• stored — leave blank to keep' : 'sk-…'}
            value={keyDraft ?? ''}
            onChange={(e) => setKeyDraft(e.target.value)}
            autoComplete="off"
          />
        </label>

        <label className="field">
          <span className="field-label">Model Name</span>
          <input
            type="text"
            data-testid="model-input"
            list="model-suggestions"
            placeholder="model for all agents"
            value={String(provider.model ?? '')}
            onChange={(e) => patchProvider({ model: e.target.value })}
          />
          <datalist id="model-suggestions">
            {MODEL_SUGGESTIONS[currentProvider].map((m) => (
              <option key={m} value={m} />
            ))}
          </datalist>
        </label>

        <div className="field-row">
          <button type="button" className="settings-btn" data-testid="test-connection-btn" onClick={() => void doTest()} disabled={test.status === 'testing'}>
            {test.status === 'testing' ? 'testing…' : 'Test Connection'}
          </button>
          {test.status === 'ok' && (
            <span className="test-ok" data-testid="test-ok" role="status">✓ {test.message}</span>
          )}
          {test.status === 'err' && (
            <span className="test-err" data-testid="test-err" role="alert">✗ {test.message}</span>
          )}
        </div>
      </fieldset>

      {/* -- 2. AGENTS --------------------------------------------------- */}
      <fieldset className="settings-block" data-testid="settings-agents">
        <legend>AGENTS</legend>
        <label className="field">
          <span className="field-label">DRAFT model</span>
          <input type="text" list="model-suggestions" data-testid="draft-model"
            placeholder="inherit from provider"
            value={String((agents.draft?.model as string | null) ?? '')}
            onChange={(e) => patchAgent('draft', 'model', e.target.value || null)} />
        </label>
        <label className="field">
          <span className="field-label">FORGE model</span>
          <input type="text" list="model-suggestions" data-testid="forge-model"
            placeholder="inherit from provider"
            value={String((agents.forge?.model as string | null) ?? '')}
            onChange={(e) => patchAgent('forge', 'model', e.target.value || null)} />
        </label>
        <label className="field">
          <span className="field-label">TEMPER model</span>
          <input type="text" list="model-suggestions" data-testid="temper-model"
            placeholder="inherit from provider"
            value={String((agents.temper?.model as string | null) ?? '')}
            onChange={(e) => patchAgent('temper', 'model', e.target.value || null)} />
        </label>
        <label className="field">
          <span className="field-label">DRAFT max steps</span>
          <input type="number" min={1} max={200} data-testid="draft-max-steps"
            value={String((agents.draft?.max_steps as number) ?? 40)}
            onChange={(e) => patchAgent('draft', 'max_steps', Number(e.target.value))} />
        </label>
        <label className="field">
          <span className="field-label">FORGE max retries</span>
          <input type="number" min={0} max={10} data-testid="forge-max-retries"
            value={String((agents.forge?.max_retries as number) ?? 2)}
            onChange={(e) => patchAgent('forge', 'max_retries', Number(e.target.value))} />
        </label>
        <label className="field">
          <span className="field-label">TEMPER reruns</span>
          <input type="number" min={0} max={5} data-testid="temper-reruns"
            value={String((agents.temper?.reruns as number) ?? 1)}
            onChange={(e) => patchAgent('temper', 'reruns', Number(e.target.value))} />
        </label>
      </fieldset>

      {/* -- 3. SANDBOX -------------------------------------------------- */}
      <fieldset className="settings-block" data-testid="settings-sandbox">
        <legend>SANDBOX</legend>
        <label className="field">
          <span className="field-label">Backend</span>
          <select
            data-testid="sandbox-backend"
            value={String(sandbox.backend ?? 'auto')}
            onChange={(e) => patchSandbox({ backend: e.target.value })}
          >
            {SANDBOX_BACKENDS.map((b) => (
              <option key={b} value={b}>
                {b === 'auto'
                  ? 'auto — docker when available'
                  : b === 'docker'
                    ? 'docker — require isolation'
                    : 'process — quarantined, no docker'}
              </option>
            ))}
          </select>
        </label>
        {/* T-043: the boot-detected sandbox state — the same four lines
            the server logs at boot, so what is actually happening is
            visible, not a silent fallback. */}
        {sandboxStatus && (
          <div className="sandbox-state" data-testid="sandbox-state">
            <div>docker daemon: {sandboxStatus.docker_available ? 'present' : 'absent'}</div>
            <div>
              image {sandboxStatus.image}: {sandboxStatus.image_present ? 'present' : 'absent'}
            </div>
            <div>
              backend selected: {sandboxStatus.effective ?? String(sandbox.backend ?? 'auto')}
              {sandboxStatus.reason ? ` — ${sandboxStatus.reason}` : ''}
            </div>
          </div>
        )}
        {(() => {
          if (!sandboxStatus) return null;
          const daemon = sandboxStatus.docker_available;
          const image = sandboxStatus.image_present;
          const backend = String(sandbox.backend ?? 'auto');
          let kind: 'green' | 'amber' | 'red';
          let text: string;
          if (backend === 'docker' && !daemon) {
            kind = 'red';
            text = 'docker daemon not detected — running tasks will fail';
          } else if (backend === 'process') {
            kind = 'amber';
            text = 'running in process mode — docker bypassed by config';
          } else if (!daemon) {
            kind = 'amber';
            text = 'running in process mode — docker not available';
          } else if (image) {
            kind = 'green';
            text = 'docker ready';
          } else {
            kind = 'amber';
            text = 'docker ready — sandbox image will be pulled on first use';
          }
          return (
            <div
              className={`settings-chip settings-chip-${kind}`}
              data-testid="sandbox-chip"
              data-chip={kind}
              role="status"
            >
              {text}
            </div>
          );
        })()}
        {(() => {
          if (String(sandbox.backend ?? 'auto') !== 'docker' || !sandboxStatus) return null;
          const warn = !sandboxStatus.docker_available
            ? 'no docker daemon detected — docker-pinned tasks will fail with a clear error until docker is running'
            : !sandboxStatus.image_present
              ? `sandbox image ${sandboxStatus.image} is not present locally — it will be pulled on first use, or the run degrades to process`
              : null;
          if (!warn) return null;
          return (
            <div className="settings-warn" data-testid="sandbox-warn" role="alert">
              {warn}
            </div>
          );
        })()}
        <label className="field">
          <span className="field-label">Image</span>
          <input type="text" data-testid="sandbox-image" value={String(sandbox.image ?? '')}
            onChange={(e) => patchSandbox({ image: e.target.value })} />
        </label>
        <label className="field">
          <span className="field-label">Memory limit</span>
          <input type="text" data-testid="sandbox-mem" value={String(sandbox.mem_limit ?? '')}
            onChange={(e) => patchSandbox({ mem_limit: e.target.value })} />
        </label>
        <label className="field">
          <span className="field-label">CPU limit</span>
          <input type="number" min={0.5} max={64} step={0.5} data-testid="sandbox-cpus"
            value={String(sandbox.cpus ?? 2)} onChange={(e) => patchSandbox({ cpus: Number(e.target.value) })} />
        </label>
      </fieldset>

      {/* -- 4. GENERAL ---------------------------------------------------
           Theme: dark-only in v0.1 (T-039) — the dead "light — v0.2" stub
           was removed; a half-audited light palette ships visual bugs. */}
      <fieldset className="settings-block" data-testid="settings-general">
        <legend>GENERAL</legend>
        <label className="field">
          <span className="field-label">Stream verbosity</span>
          <select data-testid="verbosity-select" value={verbosity}
            onChange={(e) => setVerbosity(e.target.value as 'full' | 'compact' | 'minimal')}>
            <option value="full">full</option>
            <option value="compact">compact</option>
            <option value="minimal">minimal</option>
          </select>
        </label>
        <label className="field">
          <span className="field-label">Auto-scroll</span>
          <select data-testid="autoscroll-select" value={autoScroll ? 'on' : 'off'}
            onChange={(e) => setAutoScroll(e.target.value === 'on')}>
            <option value="on">on</option>
            <option value="off">off</option>
          </select>
        </label>
      </fieldset>

      <div className="field-row settings-save-row">
        {/* T-051: the Save status chip — unsaved (amber) / saving / saved ✓
            (green, 3s) / error (red, with the reason). Persist on Save only. */}
        {saving && (
          <div className="settings-chip settings-chip-amber" data-testid="save-chip" data-chip="amber" role="status">
            saving…
          </div>
        )}
        {!saving && !dirty && saveState.kind === 'saved' && (
          <div className="settings-chip settings-chip-green" data-testid="save-chip" data-chip="green" role="status">
            saved ✓
          </div>
        )}
        {!saving && saveState.kind === 'error' && (
          <div className="settings-chip settings-chip-red" data-testid="save-chip" data-chip="red" role="alert">
            error: {saveState.message}
          </div>
        )}
        {!saving && dirty && saveState.kind !== 'error' && (
          <div className="settings-chip settings-chip-amber" data-testid="save-chip" data-chip="amber" role="status">
            unsaved changes
          </div>
        )}
        <button type="button" className="settings-btn settings-save" data-testid="settings-save" onClick={() => void doSave()} disabled={saving}>
          {saving ? 'saving…' : 'Save'}
        </button>
      </div>

      {toast && <Toast message={toast.message} kind={toast.kind} onDone={() => setToast(null)} />}
    </section>
  );
}
