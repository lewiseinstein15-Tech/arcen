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
No existing branch was rewritten during this recovery. Check Git history and
remote state for any later merge or push; this file is a historical account.

## Restore this salvage branch (not the original branch)

The file `/home/user/000-000-004-A03-salvage.bundle` is an incremental bundle
requiring commit `7af6cd0e440b6e677f5afe84394c8b9ea92fb5be`. Its second copy
is `~/rebuild-arcen/docs/A03-SALVAGE.bundle`. If that copy is missing but all
parts are present, reconstruct it without changing any existing data:

```sh
cat ~/rebuild-arcen/docs/A03-SALVAGE.part* > ~/A03-SALVAGE-rejoined.bundle
```

The required base can be reconstructed from the already existing small
bundles, in this order, after cloning the public repository to a new directory:

```sh
git clone https://github.com/lewiseinstein15-Tech/arcen.git arcen-salvage-restore
cd arcen-salvage-restore
for name in 000-000-h20b-live-progress 000-000-h19f-stream-hygiene \
  000-000-h11j-probe-attribution 000-000-h14c-parallel-binding \
  000-000-h17f-stop-reporting 000-000-h05a-git-package \
  000-000-h19g-live-stream-bounds 000-000-h19h-replay-bounds \
  000-000-h19i-stream-errors 000-000-h19j-offline-git-snapshot \
  000-000-h19k-git-filter-preflight 000-000-h15a-static-policy \
  000-000-h11k-terminal-consistency 000-000-h16b-canary-safeguards \
  000-000-h16c-canary-nofollow; do
  git fetch "$HOME/$name.bundle" "HEAD:refs/heads/restore-$name"
done
git bundle verify "$HOME/000-000-004-A03-salvage.bundle"
git fetch "$HOME/000-000-004-A03-salvage.bundle" refs/heads/salvage-a03:refs/heads/salvage-a03
git switch salvage-a03
```

These steps do not recover the lost intervening branch. Bundles and snapshots
can be omitted by workspace size limits, so this is a mitigation, not a promise.
