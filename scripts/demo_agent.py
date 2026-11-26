#!/usr/bin/env python3
"""ARCEN demo planner — OpenAI-compatible, deterministic, needs no API key.

This is a *scripted* planner standing in for a model, so the real pipeline can
be driven on a machine with no provider key. Only planning is scripted:
every step runs inside the Docker sandbox, pytest really fails and then really
passes, TEMPER discovers and runs the suite, and the exported patch is a
genuine host diff.

Scenario (any goal mentioning "calc"):
  attempt 1: write the buggy project, run pytest   -> red, step fails
  replan:    read calc.py, fix it, run pytest      -> green
  TEMPER:    discovers test_calc.py, verifies the turn

Usage: python scripts/demo_agent.py [port]   (default 9378)
"""

from __future__ import annotations

import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

CALC_PY = """def add(a, b):
    \"\"\"Return the sum of a and b.\"\"\"
    return a - b
"""

TEST_PY = """from calc import add


def test_add_positive():
    assert add(2, 3) == 5


def test_add_negative():
    assert add(-4, 1) == -3
"""

WRITE_CMD = (
    "cat > calc.py <<'PY'\n" + CALC_PY + "PY\ncat > test_calc.py <<'PY'\n" + TEST_PY + "PY\nls -1"
)

FIRST_PLAN = [
    {"title": "scaffold calc.py and test_calc.py", "tool": "bash", "args": {"cmd": WRITE_CMD}},
    {"title": "run the test suite", "tool": "bash", "args": {"cmd": "python -m pytest -q"}},
]

REPLAN = [
    {"title": "read the failing implementation", "tool": "file.read", "args": {"path": "calc.py"}},
    {
        "title": "fix add(): subtraction where addition is required",
        "tool": "file.edit",
        "args": {"path": "calc.py", "find": "return a - b", "replace": "return a + b"},
    },
    {"title": "re-run the test suite", "tool": "bash", "args": {"cmd": "python -m pytest -q"}},
]

GREETINGS = {"hello", "hi", "hey", "yo", "thanks", "bye"}
# Optional pacing so a human (or a screenshot run) can follow each phase.
DELAY_S = float(os.environ.get("DEMO_DELAY", "0"))


def classify(text: str) -> str:
    lowered = text.strip().lower().rstrip("!.?,;: ")
    if lowered in GREETINGS or lowered.startswith(("what is your name", "who are you")):
        return "DIRECT"
    return "CODE"


def plan_for(goal: str, is_replan: bool) -> str:
    if "calc" in goal.lower():
        return json.dumps(REPLAN if is_replan else FIRST_PLAN)
    steps = [
        {
            "title": f"do the work: {goal}",
            "tool": "bash",
            "args": {"cmd": f"echo demo-work: {goal}"},
        },
        {"title": "verify the result", "tool": "bash", "args": {"cmd": "true"}},
    ]
    return json.dumps(steps)


def direct_answer(text: str) -> str:
    lowered = text.strip().lower()
    if lowered in GREETINGS:
        return "Hello — I plan, build, and verify inside a locked-down sandbox."
    return "I'm ARCEN: DRAFT plans, FORGE builds, TEMPER verifies."


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _reply(self, content: str, model: str) -> None:
        body = json.dumps(
            {
                "id": f"chatcmpl-demo-{int(time.time() * 1000)}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if not self.path.endswith("/chat/completions"):
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length) or b"{}")
        messages = payload.get("messages", [])
        user = next(
            (m.get("content", "") for m in reversed(messages) if m.get("role") != "system"),
            "",
        )
        system = next((m.get("content", "") for m in messages if m.get("role") == "system"), "")
        model = payload.get("model", "demo-1")
        if DELAY_S:
            time.sleep(DELAY_S)

        if "Return ONLY the word" in user:
            self._reply(classify(user.split("\n\n")[0]), model)
        elif "Return ONLY a JSON array" in user:
            goal = user[len("Goal: ") :].split("\n")[0] if user.startswith("Goal: ") else user
            self._reply(plan_for(goal, "The step " in user), model)
        elif system.startswith("You are ARCEN"):
            self._reply(direct_answer(user), model)
        else:
            self._reply("demo reply", model)


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9378
    server = HTTPServer(("127.0.0.1", port), Handler)
    print(f"[demo-agent] listening on http://127.0.0.1:{port}/v1", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
