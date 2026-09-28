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

import { useCallback, useEffect, useMemo, useState } from 'react';
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
}

/** The General section's auto-scroll preference (T-036), read by ChatView. */
export function autoScrollPreference(): boolean {
  return localStorage.getItem(AUTOSCROLL_KEY) !== 'off'; // on by default
}

interface TestState {
  status: 'idle' | 'testing' | 'ok' | 'err';
  message?: string;
}

export function SettingsView() {
  const [cfg, setCfg] = useState<Record<string, unknown> | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [test, setTest] = useState<TestState>({ status: 'idle' });
  const [toast, setToast] = useState<{ message: string; kind: 'ok' | 'err' } | null>(null);
  const [saving, setSaving] = useState(false);
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
        if (alive) setCfg(body);
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
  const provider = (cfg?.provider ?? {}) as Record<string, unknown>;
  const models = (provider.models ?? {}) as Record<string, string>;
  const apiKeys = (provider.api_keys ?? {}) as Record<string, string>;
  const baseUrls = (provider.base_urls ?? {}) as Record<string, string>;
  const agents = (cfg?.agents ?? {}) as Record<string, Record<string, unknown>>;
  const sandbox = (cfg?.sandbox ?? {}) as Record<string, unknown>;

  const currentProvider = (provider.default as Provider) ?? 'custom';
  const [keyDraft, setKeyDraft] = useState<string | undefined>(undefined);

  const commonModel = useMemo(() => {
    const vals = new Set(Object.values(models));
    return vals.size === 1 ? [...vals][0] ?? '' : '';
  }, [models]);

  const patchProvider = (patch: Record<string, unknown>) => {
    setCfg((c) => {
      const p = (c?.provider as Record<string, unknown> | undefined) ?? {};
      return { ...c, provider: { ...p, ...patch } };
    });
  };
  const patchModels = (patch: Record<string, string>) => {
    setCfg((c) => {
      const p = (c?.provider as Record<string, unknown> | undefined) ?? {};
      const m = (p.models as Record<string, string> | undefined) ?? {};
      return { ...c, provider: { ...p, models: { ...m, ...patch } } };
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

  const setModelEverywhere = (name: string) => {
    patchModels({ planner: name, executor: name, verifier: name });
  };

  const doTest = useCallback(async () => {
    setTest({ status: 'testing' });
    try {
      const res = await fetch('/api/config/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          provider: currentProvider,
          model: models.planner || '',
          base_url: baseUrls[currentProvider] || '',
          api_key: keyDraft !== undefined ? keyDraft : apiKeys[currentProvider] || '',
        }),
      });
      const body = (await res.json()) as { ok: boolean; error?: string; sample?: string };
      if (body.ok) setTest({ status: 'ok', message: `connected · ${body.sample ?? ''}` });
      else setTest({ status: 'err', message: body.error ?? 'connection failed' });
    } catch (err) {
      setTest({ status: 'err', message: String(err) });
    }
  }, [currentProvider, models.planner, baseUrls, apiKeys, keyDraft]);

  const doSave = useCallback(async () => {
    if (!cfg) return;
    setSaving(true);
    try {
      const payload = structuredClone(cfg);
      const p = (payload.provider ?? {}) as Record<string, unknown>;
      const keys = { ...(p.api_keys as Record<string, string> | undefined) };
      if (keyDraft !== undefined && keyDraft !== '') keys[currentProvider] = keyDraft;
      p.api_keys = keys;
      payload.provider = p;
      const res = await fetch('/api/config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const detail = await res.text();
        throw new Error(detail.slice(0, 160) || String(res.status));
      }
      localStorage.setItem(VERBOSITY_KEY, verbosity);
      localStorage.setItem(AUTOSCROLL_KEY, autoScroll ? 'on' : 'off');
      setToast({ message: 'Saved', kind: 'ok' });
      setKeyDraft(undefined);
    } catch (err) {
      setToast({ message: `Error: ${String(err)}`, kind: 'err' });
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
            onChange={(e) => patchProvider({ default: e.target.value })}
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
              value={baseUrls[currentProvider] ?? ''}
              onChange={(e) => patchProvider({ base_urls: { ...baseUrls, [currentProvider]: e.target.value } })}
            />
          </label>
        )}

        <label className="field">
          <span className="field-label">API Key</span>
          <input
            type="password"
            data-testid="api-key-input"
            placeholder={apiKeys[currentProvider] ? '•••• stored — leave blank to keep' : 'sk-…'}
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
            placeholder={commonModel || 'model for all agents'}
            value={commonModel}
            onChange={(e) => setModelEverywhere(e.target.value)}
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
            value={models.planner ?? ''} onChange={(e) => patchModels({ planner: e.target.value })} />
        </label>
        <label className="field">
          <span className="field-label">FORGE model</span>
          <input type="text" list="model-suggestions" data-testid="forge-model"
            value={models.executor ?? ''} onChange={(e) => patchModels({ executor: e.target.value })} />
        </label>
        <label className="field">
          <span className="field-label">TEMPER model</span>
          <input type="text" list="model-suggestions" data-testid="temper-model"
            value={models.verifier ?? ''} onChange={(e) => patchModels({ verifier: e.target.value })} />
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
        <button type="button" className="settings-btn settings-save" data-testid="settings-save" onClick={() => void doSave()} disabled={saving}>
          {saving ? 'saving…' : 'Save'}
        </button>
      </div>

      {toast && <Toast message={toast.message} kind={toast.kind} onDone={() => setToast(null)} />}
    </section>
  );
}
