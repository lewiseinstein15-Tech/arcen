// Tools view: the agent's reachable surface, rendered from the API that
// builds the planner's catalog — tools by trust domain, skills with bodies
// on demand, MCP servers with connect.

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import App from '../src/App';
import { useUiStore } from '../src/state/uiStore';

const TOOLS = [
  {
    name: 'bash',
    description: 'Run one shell command.',
    danger: 'sandboxed',
    required: ['cmd:str'],
    optional: ['cwd:str'],
    runs_in: 'sandbox',
  },
  {
    name: 'skill.load',
    description: 'Load a skill body.',
    danger: 'safe',
    required: ['name:str'],
    optional: [],
    runs_in: 'host',
  },
];

const SKILLS = [
  {
    name: 'debug-traceback',
    version: '1.0.0',
    description: 'Read a traceback before editing anything.',
    tools: ['file.read'],
    path: 'skills/debug-traceback/SKILL.md',
  },
];

const SERVERS = [
  { name: 'gh', state: 'declarative', error: null, transport: 'stdio', tools: [] },
];

function json(body: unknown) {
  return Promise.resolve(new Response(JSON.stringify(body), { status: 200 }));
}

function stubApi(overrides: Record<string, () => Promise<Response>> = {}) {
  const fetchMock = vi.fn().mockImplementation((url: string) => {
    const u = String(url);
    if (overrides[u]) return overrides[u]();
    if (u.includes('/api/tools')) return json({ tools: TOOLS, count: TOOLS.length });
    if (u.includes('/api/skills/debug-traceback')) return json({ body: '# Debug a traceback' });
    if (u.includes('/api/skills')) return json({ skills: SKILLS, count: SKILLS.length });
    if (u.includes('/api/mcp/gh/connect')) return json({ ok: true, state: 'connected' });
    if (u.includes('/api/mcp')) return json({ servers: SERVERS, count: SERVERS.length });
    return json({});
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

beforeEach(() => {
  useUiStore.getState().setView('chat');
});

describe('Tools view', () => {
  it('opens from the sidebar and groups tools by where they run', async () => {
    stubApi();
    render(<App />);
    fireEvent.click(screen.getByTestId('nav-tools'));
    expect(await screen.findByTestId('tools-view')).toBeInTheDocument();

    expect(await screen.findByTestId('tool-bash')).toBeInTheDocument();
    expect(screen.getByTestId('tool-skill.load')).toBeInTheDocument();
    // the trust domain is visible, not implied
    expect(screen.getByText(/Sandbox · 1/)).toBeInTheDocument();
    expect(screen.getByText(/Host · 1/)).toBeInTheDocument();
    // arguments come from the schema, so the user sees what the model sees
    expect(screen.getByText('cmd:str')).toBeInTheDocument();
  });

  it('lists skills and loads a body only when asked', async () => {
    const fetchMock = stubApi();
    render(<App />);
    fireEvent.click(screen.getByTestId('nav-tools'));
    fireEvent.click(await screen.findByTestId('tools-tab-skills'));

    expect(await screen.findByTestId('skill-debug-traceback')).toBeInTheDocument();
    expect(screen.queryByTestId('skill-body')).not.toBeInTheDocument();

    fireEvent.click(screen.getByText('debug-traceback'));
    expect(await screen.findByTestId('skill-body')).toHaveTextContent('Debug a traceback');
    // the index is cheap; the body is a second, deliberate request
    expect(fetchMock.mock.calls.some(([u]) => String(u).includes('/api/skills/debug-traceback'))).toBe(
      true,
    );
  });

  it('shows MCP server state and connects on demand', async () => {
    const fetchMock = stubApi();
    render(<App />);
    fireEvent.click(screen.getByTestId('nav-tools'));
    fireEvent.click(await screen.findByTestId('tools-tab-mcp'));

    expect(await screen.findByTestId('mcp-gh')).toHaveTextContent('declarative');
    fireEvent.click(screen.getByText('Connect'));
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([u]) => String(u).includes('/api/mcp/gh/connect'))).toBe(
        true,
      ),
    );
  });
});
