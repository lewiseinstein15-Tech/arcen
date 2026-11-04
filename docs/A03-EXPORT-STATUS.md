# A-03a export: partial salvage implementation

The explicit headless `--workspace` path now captures the Git-root working
files and HEAD on the host, stores a private baseline, imports the identical
archive into the existing isolated container, collects bounded untrusted tar
output before teardown, and generates/validates the patch on the host. A
`file.diff` artifact event is emitted after storage. Reusing a session ID with
an existing baseline is refused. For safety, HTTP `/api/run` rejects any
workspace field rather than letting an unauthenticated remote client choose a
host path. Its default session is now a canonical UUID, and supplied IDs must
also be canonical UUIDs. HTTP turns do not export workspace artifacts.

The workspace snapshot includes ignored and untracked files. Common credential
paths are rejected before starting the sandbox, but no filename denylist scans
file contents or guarantees confidentiality. Use only a reviewed workspace
containing no private data inappropriate to give the sandboxed agent.

This is a reconstructed branch, not the missing original history. Fake runtime
tests do not establish real Docker behavior. Docker-machine smoke, broader
integration and the remaining A-03 acceptance checks are still required.
