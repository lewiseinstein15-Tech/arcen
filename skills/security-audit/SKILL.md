---
name: security-audit
version: 0.1.0
description: Audit a change or codebase for the vulnerabilities that actually get exploited
tools: [bash, file.read, search.text, file.glob, repo.map]
---

# Security audit

Look for the boring vulnerabilities first; they are the ones that get
exploited.

1. Map the trust boundary: where does untrusted input enter? HTTP handlers,
   CLI args, file uploads, webhooks, environment, model output.
2. Trace each input to a sink. The sinks that matter:
   - shell: `subprocess(..., shell=True)`, `os.system`, backticks
   - filesystem: `open(user_path)`, `../` in a joined path
   - SQL: string-built queries
   - templates: `render_template_string`, `dangerouslySetInnerHTML`
   - deserialisation: `pickle`, `yaml.load` (unsafe), `eval`
3. Grep for secrets and credentials in the tree, including history-adjacent
   files: `search.text {"pattern": "(api[_-]?key|secret|token|password)\\s*[:=]\\s*['\\\"][^'\\\"]+"}`.
4. Check authentication and authorisation separately. A logged-in user is not
   an authorised user; look for object-level checks (IDOR).
5. Check what is logged. A token, a password, or a full request body in a log
   is a finding.
6. Report by exploitability: reachable + unauthenticated first. For each,
   give the path, the payload, and the fix.
7. Do not fix and report in the same breath — a silent security fix hides the
   fact that the code was vulnerable.
