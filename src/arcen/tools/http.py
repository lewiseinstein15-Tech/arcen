"""ARCEN — http tools (Part 3 wrapped). Network is opt-in inside the sandbox."""

from __future__ import annotations

import httpx

from pydantic import BaseModel, Field

from .registry import BaseTool

_TIMEOUT = httpx.Timeout(30.0)
MAX_RESPONSE_BYTES = 1_000_000


class HttpGet(BaseTool):
    name = "http.get"
    description = "GET a URL; returns status, headers, and body (text or parsed JSON)."
    version = "1.0.0"
    danger = "sandboxed"

    class Args(BaseModel):
        url: str = Field(description="absolute http(s) URL")
        headers: dict[str, str] = Field(default_factory=dict, description="request headers")

    def _run(self, a: "HttpGet.Args") -> dict:
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
            resp = client.get(a.url, headers=a.headers)
        body = resp.text[:MAX_RESPONSE_BYTES]
        return {
            "status": resp.status_code,
            "content_type": resp.headers.get("content-type", ""),
            "body": _maybe_json(resp),
            "bytes": len(resp.content),
        }


class HttpPost(BaseTool):
    name = "http.post"
    description = "POST a JSON payload to a URL; returns status and parsed body."
    version = "1.0.0"
    danger = "sandboxed"

    class Args(BaseModel):
        url: str = Field(description="absolute http(s) URL")
        json_body: dict | None = Field(default=None, description="JSON payload")
        headers: dict[str, str] = Field(default_factory=dict, description="request headers")

    def _run(self, a: "HttpPost.Args") -> dict:
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
            resp = client.post(a.url, json=a.json_body, headers=a.headers)
        return {
            "status": resp.status_code,
            "content_type": resp.headers.get("content-type", ""),
            "body": _maybe_json(resp),
            "bytes": len(resp.content),
        }


class HttpHead(BaseTool):
    name = "http.head"
    description = "HEAD a URL; returns status and headers only."
    version = "1.0.0"
    danger = "sandboxed"

    class Args(BaseModel):
        url: str = Field(description="absolute http(s) URL")
        headers: dict[str, str] = Field(default_factory=dict, description="request headers")

    def _run(self, a: "HttpHead.Args") -> dict:
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
            resp = client.head(a.url, headers=a.headers)
        return {"status": resp.status_code, "headers": dict(resp.headers)}


def _maybe_json(resp: httpx.Response):
    if "application/json" in resp.headers.get("content-type", ""):
        try:
            return resp.json()
        except ValueError:
            pass
    return resp.text[:MAX_RESPONSE_BYTES]
