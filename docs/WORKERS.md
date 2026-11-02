# Workers and Phase 0 command log

Phase 0 installs or invokes no external coding worker. Any future worker is an untrusted subprocess, never speaks directly to the user, receives neither ARCEN system prompt nor secrets, and its output requires independent validation. Ask before a worker needs a paid key or account. No worker integration is authorized yet.

Before using a tool, consult its official documentation. Before copying any outside code or ideas, inspect the source LICENSE; only MIT, Apache-2.0, or BSD code may be copied, and record source repository, exact commit and license in NOTICE. Ask the user if license terms are unclear. Never copy proprietary Claude Code; rely only on public documented behavior. No external source code was copied during this audit.

## Official documentation consulted

* Python AST, `ast.parse`, `ExceptHandler`, `Raise`: https://docs.python.org/3/library/ast.html
* Git tracked inventory: https://git-scm.com/docs/git-ls-files
* Git bundles: https://git-scm.com/docs/git-bundle
* pytest invocation: https://docs.pytest.org/en/stable/how-to/usage.html
* npm clean install, lockfile and lifecycle scripts: https://docs.npmjs.com/cli/v10/commands/npm-ci and https://docs.npmjs.com/cli/v11/commands/npm-ci
* Vitest CLI: https://vitest.dev/guide/cli
* Ruff formatter: https://docs.astral.sh/ruff/formatter/
* Playwright screenshots: https://playwright.dev/python/docs/screenshots

## Commands used (run at repository root unless noted)

```sh
git ls-remote https://github.com/lewiseinstein15-Tech/arcen.git refs/heads/main
python docs/audit/inspect_repo.py --write
python docs/audit/inspect_repo.py
PYTHONPATH=src python docs/audit/reproduce.py
ruff format docs/audit/inspect_repo.py docs/audit/reproduce.py
ruff check docs/audit/inspect_repo.py docs/audit/reproduce.py
TMPDIR=/home/user/.cache/tmp PYTHONPATH=src /home/user/.cache/env13/bin/python -m pytest -o asyncio_default_fixture_loop_scope=function -o addopts='' -q
cd ui
npm ci --ignore-scripts --no-audit --no-fund
npm test -- --run
npm run build
NODE_OPTIONS=--max-old-space-size=1024 npm run build
```

For reproducibility, Python dependencies must be installed in an isolated venv (not system Python on PEP 668 systems). Paths to the local venv and temp directory above are specific to the audit workspace. `npm ci --ignore-scripts` is not equivalent to a normal lifecycle-enabled install. Exact results and limitations are in `AUDIT.md`.

Fresh audit evidence (a real PTY, xterm.js and headless Chromium, not a TUI feature demonstration):

```sh
PYTHONPATH=src /home/user/.cache/env13/bin/python scripts/terminal_shot.py --cols 150 --rows 28 --wait 4 --out docs/verify/P0-AUDIT-inventory.png -- /bin/bash -c 'PYTHONPATH=src /home/user/.cache/env13/bin/python docs/audit/reproduce.py; /home/user/.cache/env13/bin/python docs/audit/inspect_repo.py; sleep 10'
```

A-15 test guidance: https://testing-library.com/docs/queries/about/ (`findBy` waits for an asynchronously appearing element). Exact focused command: `cd ui && npm test -- --run tests/settings.test.tsx`.

A-08 metering documentation consulted before implementation: https://docs.litellm.ai/docs/completion/token_usage (`cost_per_token`, `model_cost`).

A-15 fresh focused test terminal capture (real PTY/xterm.js/headless Chromium; displays test output, not a live UI demonstration):

```sh
PYTHONPATH=src /home/user/.cache/env13/bin/python scripts/terminal_shot.py --cols 145 --rows 30 --wait 11 --out docs/verify/A-15-real-async-tests.png -- /bin/bash -c 'cd ui; npm test -- --run tests/settings.test.tsx tests/markdown.test.tsx; status=$?; echo "A-15 focused tests exit: $status"; sleep 15; exit "$status"'
```

A-08 commands (the Python environment contains project dependencies):

```sh
TMPDIR=/home/user/.cache/tmp PYTHONPATH=src /home/user/.cache/env13/bin/python -m pytest -o asyncio_default_fixture_loop_scope=function -o addopts='' -q
cd ui
npm test -- --run
npx tsc -b
```

TUI evidence uses the installed `arcen-tui` entry point with the current workspace source. It replays a pre-recorded mock-provider fixture, not a live provider, benchmark or real verification run:

```sh
PYTHONPATH=src /home/user/.cache/env13/bin/python scripts/terminal_shot.py --cols 150 --rows 44 --wait 13 --env PYTHONPATH=/home/user/arcen-continue/src --out docs/verify/A-08-real-tui-recorded-replay.png -- /home/user/.cache/env13/bin/arcen-tui --demo --replay
```
