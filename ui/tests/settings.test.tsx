// T-036 — Settings view with model providers.
// Proves: reachable from the sidebar; four sections render; the provider
// select swaps fields; Save PUTs the full config with the redacted key
// preserved; Test Connection surfaces ok/error inline; the toast reports
// the outcome.

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import App from '../src/App';
import { useDrawerStore } from '../src/state/drawerStore';
import { useSessionStore } from '../src/state/sessionStore';
import { useStreamStore } from '../src/state/streamStore';
import { useUiStore } from '../src/state/uiStore';

function configFixture() {
  return {
    provider: {
      default: 'custom',
      models: { planner: 'mock-1', executor: 'mock-1', verifier: 'mock-1' },
      api_keys: { custom: '<redacted>' },
      base_urls: { custom: 'http://127.0.0.1:9377/v1' },
    },
    agents: {
      draft: { max_steps: 40, replan_on_fail: true },
      forge: { step_timeout_s: 120, max_retries: 2 },
      temper: { adversarial: true, reruns: 1 },
    },
    sandbox: { image: 'ghcr.io/lewiseinstein15-tech/arcen-sandbox:0.1.0', mem_limit: '2g', cpus: 2, network: 'none' },
    stream: { port: 3002, content_type: 'application/x-ndjson' },
    session: { dir: '~/.arcen/sessions' },
    memory: { db: '~/.arcen/memory.db', decay_half_life_days: 14 },
    subagents: { max_depth: 2, max_concurrent: 8, default_model: 'claude-haiku-4-5' },
    skills: { paths: [] },
    mcps: [],
    plugins: { enabled: [], paths: [] },
  };
}

beforeEach(() => {
  useStreamStore.getState().reset();
  useSessionStore.setState({ sessions: [], activeId: null });
  useDrawerStore.getState().setOpen(false);
  useUiStore.getState().setView('chat');
  localStorage.clear();
});

describe('T-036: settings view', () => {
  it('opens from the sidebar and renders the four sections', async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (String(url).includes('/api/config')) {
        return Promise.resolve(new Response(JSON.stringify(configFixture()), { status: 200 }));
      }
      return Promise.resolve(new Response('[]', { status: 200 }));
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<App />);
    fireEvent.click(screen.getByTestId('nav-settings'));
    expect(await screen.findByTestId('settings-view')).toBeInTheDocument();
    expect(screen.getByTestId('settings-provider')).toBeInTheDocument();
    expect(screen.getByTestId('settings-agents')).toBeInTheDocument();
    expect(screen.getByTestId('settings-sandbox')).toBeInTheDocument();
    expect(screen.getByTestId('settings-general')).toBeInTheDocument();
    // the provider select offers the ticket's dropdown values
    const select = screen.getByTestId('provider-select') as HTMLSelectElement;
    expect([...select.options].map((o) => o.value)).toEqual(
      ['custom', 'groq', 'deepseek', 'openai', 'anthropic', 'ollama'],
    );
  });

  it('Save PUTs the full config; the redacted key round-trips; toast says Saved', async () => {
    const putBodies: string[] = [];
    const fetchMock = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      if (String(url).includes('/api/config') && init?.method === 'PUT') {
        putBodies.push(String(init.body));
        return Promise.resolve(new Response(JSON.stringify(configFixture()), { status: 200 }));
      }
      if (String(url).includes('/api/config')) {
        return Promise.resolve(new Response(JSON.stringify(configFixture()), { status: 200 }));
      }
      return Promise.resolve(new Response('[]', { status: 200 }));
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<App />);
    fireEvent.click(screen.getByTestId('nav-settings'));
    await screen.findByTestId('settings-view');
    await screen.findByTestId('provider-select');

    // switch provider custom → groq, then save
    fireEvent.change(screen.getByTestId('provider-select'), { target: { value: 'groq' } });
    fireEvent.click(screen.getByTestId('settings-save'));

    await waitFor(() => {
      expect(putBodies.length).toBe(1);
    });
    const body = JSON.parse(putBodies[0]);
    expect(body.provider.default).toBe('groq');
    expect(body.provider.api_keys.custom).toBe('<redacted>'); // untouched → placeholder
    expect(body.agents.draft.max_steps).toBe(40); // full config preserved
    expect(await screen.findByTestId('toast')).toHaveTextContent('Saved');
  });

  it('Test Connection shows ok inline (and the toast flow stays separate)', async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (String(url).includes('/api/config/test')) {
        return Promise.resolve(new Response(JSON.stringify({ ok: true, model: 'groq/mock-1', sample: 'pong' }), { status: 200 }));
      }
      if (String(url).includes('/api/config')) {
        return Promise.resolve(new Response(JSON.stringify(configFixture()), { status: 200 }));
      }
      return Promise.resolve(new Response('[]', { status: 200 }));
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<App />);
    fireEvent.click(screen.getByTestId('nav-settings'));
    await screen.findByTestId('settings-view');
    fireEvent.click(await screen.findByTestId('test-connection-btn'));
    expect(await screen.findByTestId('test-ok')).toHaveTextContent('pong');
  });

  it('Test Connection shows the error inline when the probe fails', async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (String(url).includes('/api/config/test')) {
        return Promise.resolve(new Response(JSON.stringify({ ok: false, error: '401 from provider' }), { status: 200 }));
      }
      if (String(url).includes('/api/config')) {
        return Promise.resolve(new Response(JSON.stringify(configFixture()), { status: 200 }));
      }
      return Promise.resolve(new Response('[]', { status: 200 }));
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<App />);
    fireEvent.click(screen.getByTestId('nav-settings'));
    await screen.findByTestId('settings-view');
    fireEvent.click(await screen.findByTestId('test-connection-btn'));
    expect(await screen.findByTestId('test-err')).toHaveTextContent('401 from provider');
  });

  it('returning to Chat via the sidebar keeps the session stream intact', async () => {
    const replay = [{ type: 'answer', seq: 1, text: 'kept', agent: 'DRAFT', ts: 1 }];
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (String(url).includes('/api/config')) {
        return Promise.resolve(new Response(JSON.stringify(configFixture()), { status: 200 }));
      }
      if (String(url).includes('/api/sessions') && String(url).endsWith('/events')) {
        return Promise.resolve(new Response(JSON.stringify(replay), { status: 200 }));
      }
      return Promise.resolve(new Response('[]', { status: 200 }));
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<App />);
    useStreamStore.getState().apply({ type: 'answer', seq: 1, text: 'kept', agent: 'DRAFT', ts: 1 } as never);
    fireEvent.click(screen.getByTestId('nav-settings'));
    await screen.findByTestId('settings-view');
    fireEvent.click(screen.getByTestId('nav-chat'));
    await waitFor(() => {
      expect(screen.getByTestId('chat-view')).toBeInTheDocument();
    });
    // boot re-replayed from the server — the turn is still there
    await waitFor(() => {
      expect(useStreamStore.getState().events).toHaveLength(1);
    });
  });
});

// T-038 — the sandbox backend dropdown is editable and warns honestly.
function sandboxStatus(over: Record<string, unknown> = {}) {
  return {
    docker_available: false,
    image_present: false,
    image: 'ghcr.io/lewiseinstein15-tech/arcen-sandbox:0.1.0',
    ...over,
  };
}

describe('T-038: sandbox backend', () => {
  it('backend select offers auto/docker/process and PUTs the chosen value', async () => {
    const putBodies: string[] = [];
    const fetchMock = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      if (String(url).includes('/api/config') && init?.method === 'PUT') {
        putBodies.push(String(init.body));
        return Promise.resolve(new Response(JSON.stringify(configFixture()), { status: 200 }));
      }
      if (String(url).includes('/api/sandbox/status')) {
        return Promise.resolve(new Response(JSON.stringify(sandboxStatus()), { status: 200 }));
      }
      if (String(url).includes('/api/config')) {
        return Promise.resolve(new Response(JSON.stringify(configFixture()), { status: 200 }));
      }
      return Promise.resolve(new Response('[]', { status: 200 }));
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<App />);
    fireEvent.click(screen.getByTestId('nav-settings'));
    await screen.findByTestId('settings-view');
    const select = (await screen.findByTestId('sandbox-backend')) as HTMLSelectElement;
    expect([...select.options].map((o) => o.value)).toEqual(['auto', 'docker', 'process']);
    expect(select.value).toBe('auto'); // the config default

    fireEvent.change(select, { target: { value: 'process' } });
    fireEvent.click(screen.getByTestId('settings-save'));
    await waitFor(() => expect(putBodies.length).toBe(1));
    expect(JSON.parse(putBodies[0]).sandbox.backend).toBe('process');
    // auto/process never warn
    expect(screen.queryByTestId('sandbox-warn')).not.toBeInTheDocument();
  });

  it('warns when docker is pinned but no docker daemon exists', async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (String(url).includes('/api/sandbox/status')) {
        return Promise.resolve(new Response(JSON.stringify(sandboxStatus({ docker_available: false })), { status: 200 }));
      }
      if (String(url).includes('/api/config')) {
        return Promise.resolve(new Response(JSON.stringify(configFixture()), { status: 200 }));
      }
      return Promise.resolve(new Response('[]', { status: 200 }));
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<App />);
    fireEvent.click(screen.getByTestId('nav-settings'));
    await screen.findByTestId('settings-view');
    fireEvent.change(await screen.findByTestId('sandbox-backend'), { target: { value: 'docker' } });
    expect(await screen.findByTestId('sandbox-warn')).toHaveTextContent('no docker daemon');
  });

  it('warns when docker is pinned but the sandbox image is missing', async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (String(url).includes('/api/sandbox/status')) {
        return Promise.resolve(
          new Response(JSON.stringify(sandboxStatus({ docker_available: true, image_present: false })), { status: 200 }),
        );
      }
      if (String(url).includes('/api/config')) {
        return Promise.resolve(new Response(JSON.stringify(configFixture()), { status: 200 }));
      }
      return Promise.resolve(new Response('[]', { status: 200 }));
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<App />);
    fireEvent.click(screen.getByTestId('nav-settings'));
    await screen.findByTestId('settings-view');
    fireEvent.change(await screen.findByTestId('sandbox-backend'), { target: { value: 'docker' } });
    const warn = await screen.findByTestId('sandbox-warn');
    expect(warn).toHaveTextContent('not present locally');
  });

  it('docker pinned and fully usable → no warning', async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (String(url).includes('/api/sandbox/status')) {
        return Promise.resolve(
          new Response(JSON.stringify(sandboxStatus({ docker_available: true, image_present: true })), { status: 200 }),
        );
      }
      if (String(url).includes('/api/config')) {
        return Promise.resolve(new Response(JSON.stringify(configFixture()), { status: 200 }));
      }
      return Promise.resolve(new Response('[]', { status: 200 }));
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<App />);
    fireEvent.click(screen.getByTestId('nav-settings'));
    await screen.findByTestId('settings-view');
    fireEvent.change(await screen.findByTestId('sandbox-backend'), { target: { value: 'docker' } });
    await waitFor(() => {
      expect(screen.queryByTestId('sandbox-warn')).not.toBeInTheDocument();
    });
  });
});
