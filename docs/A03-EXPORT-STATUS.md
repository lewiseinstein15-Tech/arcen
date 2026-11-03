# A-03a export: partial salvage implementation

The explicit headless `--workspace` path now captures the Git-root working
files and HEAD on the host, stores a private baseline, imports the identical
archive into the existing isolated container, collects bounded untrusted tar
output before teardown, and generates/validates the patch on the host. A
`file.diff` artifact event is emitted after storage. Reusing a session ID with
an existing baseline is refused. The HTTP `/api/run` surface does not yet pass
through a workspace; do not assume it exports artifacts.

The workspace snapshot includes ignored and untracked files. Common credential
paths are rejected before starting the sandbox, but no filename denylist scans
file contents or guarantees confidentiality. Use only a reviewed workspace
containing no private data inappropriate to give the sandboxed agent.

This is a reconstructed branch, not the missing original history. Fake runtime
tests do not establish real Docker behavior. Docker-machine smoke, broader
integration and the remaining A-03 acceptance checks are still required.
