#!/usr/bin/env python3
"""ARCEN dev utility — a local OpenAI-compatible mock provider.

Serves POST /v1/chat/completions so the full provider bridge (T-031/T-036)
can be exercised end-to-end WITHOUT any real API key: point the config's
custom provider at this server and every DRAFT call lands here.

It answers by prompt shape:
- classification call ("Return ONLY the word") → a deterministic intent:
  greetings/self/math → DIRECT, search/weather → RESEARCH, else CODE;
- plan call ("Return ONLY a JSON array") → JSON steps (bash for CODE,
  search.text/http.get for RESEARCH);
- direct-answer call ("You are ARCEN") → canned conversational answers
  (2+2 → 4, name → "I'm ARCEN…", closures → prose, hello → greeting).

Usage: python scripts/mock_provider.py [port]   (default 9377)
"""

from __future__ import annotations

import json
import re
import sys
import time

from http.server import BaseHTTPRequestHandler, HTTPServer

RESEARCH_WORDS = {"search", "weather", "news", "latest", "google", "browse"}
GREETINGS = {"hello", "hi", "hey", "yo", "thanks", "bye"}
DIRECT_SHAPES = (
    "what is your name",
    "whats your name",
    "who built you",
    "who made you",
    "who are you",
)


def classify(text: str) -> str:
    lowered = text.strip().lower().rstrip("!.?,;: ")
    words = lowered.split()
    if lowered in GREETINGS or lowered in DIRECT_SHAPES:
        return "DIRECT"
    if words and words[0] in GREETINGS and len(words) <= 3:
        return "DIRECT"
    if re.fullmatch(r"(what\s+is\s+)?[\d\s+\-*/^().%]+", lowered) and any(c.isdigit() for c in lowered):
        return "DIRECT"
    # short direct questions a model answers with no tools
    if len(words) <= 6 and re.match(r"^(what|who|why|how|when|where|which|explain|define|tell me)\b", lowered):
        return "DIRECT"
    if any(w in RESEARCH_WORDS for w in words):
        return "RESEARCH"
    return "CODE"


def direct_answer(text: str) -> str:
    lowered = text.strip().lower().rstrip("!.?,;: ")
    if re.fullmatch(r"(what\s+is\s+)?2\s*\+\s*2", lowered):
        return "4"
    if "name" in lowered:
        return "I'm ARCEN — your agentic engineer. DRAFT plans, FORGE executes, TEMPER verifies."
    if "closure" in lowered:
        return (
            "A closure is a function that remembers the variables from the scope "
            "where it was created, even after that scope has finished running. "
            "In Python: `def outer(): x = 1; return lambda: x` — the returned "
            "function keeps `x` alive. Closures power decorators, callbacks, and "
            "factories."
        )
    if lowered in GREETINGS:
        return "Hello! I'm ARCEN — give me a coding task and I'll plan, build, and verify it."
    return "Here is a direct answer to: " + text


def plan_for(text: str, research: bool) -> str:
    # T-037: plans carry real tool args — a planner that returns steps
    # without args gets them rejected, so the mock models a real one.
    if research:
        return json.dumps(
            [
                {
                    "title": f"search the web for: {text}",
                    "tool": "search.text",
                    "args": {"query": text},
                },
                {
                    "title": "fetch the most relevant result",
                    "tool": "http.get",
                    "args": {"url": "https://example.com/"},
                },
                {"title": "summarize the findings", "tool": None},
            ]
        )
    return json.dumps(
        [
            {
                "title": "survey the working directory",
                "tool": "file.list",
                "args": {"path": "."},
            },
            {
                "title": f"do the work: {text}",
                "tool": "bash",
                "args": {"cmd": f"echo mock-work: {text}"},
            },
            {
                "title": "verify the result",
                "tool": "bash",
                "args": {"cmd": "true"},
            },
        ]
    )


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # quiet by default
        pass

    def _reply(self, content: str, model: str) -> None:
        body = json.dumps(
            {
                "id": f"chatcmpl-mock-{int(time.time() * 1000)}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": model,
                "choices": [
                    {"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):  # noqa: N802 — http.server API
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
        model = payload.get("model", "mock-1")

        if "Return ONLY the word" in user:
            intent = classify(user.split("\n\n")[0])
            self._reply(intent, model)
        elif "Return ONLY a JSON array" in user:
            goal = user[len("Goal: ") :].split("\n")[0] if user.startswith("Goal: ") else user
            research = "search.text|http.get" in user
            self._reply(plan_for(goal, research), model)
        elif system.startswith("You are ARCEN"):
            self._reply(direct_answer(user), model)
        else:
            self._reply("mock reply", model)


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9377
    server = HTTPServer(("127.0.0.1", port), Handler)
    print(f"[mock-provider] listening on http://127.0.0.1:{port}/v1", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
