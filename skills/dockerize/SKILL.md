---
name: dockerize
version: 0.1.0
description: Containerize an application with a small, reproducible image
tools: [bash, file.read, file.write, file.edit, file.glob]
---

# Containerize an application

A Dockerfile is a build recipe, not a wish list. Pin what matters, copy what
is needed.

1. Find the real entry point and runtime version: read the manifest
   (`pyproject.toml`, `package.json`, `go.mod`) before writing anything.
2. Start from a slim, pinned base: `python:3.12-slim`, not `python:latest`.
3. Copy dependency files first, install, then copy source. That ordering is
   the difference between a 3-second and a 3-minute rebuild.
4. Run as a non-root user. Create it, `chown` the app directory, `USER` it.
5. No secrets in layers — no `ENV API_KEY`, no copying `.env`. Secrets arrive
   at runtime.
6. Add a `HEALTHCHECK` that hits something real.
7. Build it: `bash {"cmd": "docker build -t app:test ."}`. Then run it and hit
   the health endpoint. An image that builds but does not start is not done.
8. Add a `.dockerignore` with at least `.git`, `node_modules`, `.venv`,
   `__pycache__`, `dist`.
