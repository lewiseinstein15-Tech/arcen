# Partial recovery after missing base bundle

This is a **new salvage branch** from known commit `796659e`, not a restored
copy of the missing `cbd7fe4` branch. The original incremental bundle
`/home/user/000-000-003-A03a-resume.bundle` is preserved, but requires commit
`881c24c`, which is missing. The temporary backup returned HTTP 404.

A-03 source files were recovered from intact Git blobs in that bundle; the
validator and additive event field were reconstructed using the surviving
specification and tests. Surviving tests were copied from the workspace. The
missing intervening A-01, A-04, A-05, A-07 and other code changes have not been
fully restored. Do not mistake this branch for the original branch or deploy
it as a finished build. Tests may fail because of those missing changes.
No existing branch was rewritten, and no push or merge was performed.
