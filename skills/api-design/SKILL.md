---
name: api-design
version: 0.1.0
description: Design or extend an HTTP API that stays compatible
tools: [file.read, file.write, file.edit, search.text, bash, http.get]
---

# Design an HTTP API

Compatibility is the requirement. Everything else is taste.

1. Read the existing API surface before adding to it: routes, schemas, error
   shapes, auth. Match them; a second dialect is a bug.
2. Name resources as nouns, actions as methods: `POST /runs`, not
   `POST /createRun`.
3. Decide the error contract once: status code, stable machine-readable code,
   human message. Never leak a stack trace or a secret in an error body.
4. Make every list endpoint paginated from day one — adding pagination later
   is a breaking change.
5. Accept additive change only: new optional fields, new endpoints. Removing
   or renaming a field is a new version, not an edit.
6. Validate input at the boundary and return 422 with the offending field.
7. Write the test before the handler: request in, status and body out.
8. Document with one example request and one example response per endpoint —
   the examples are what people copy.
