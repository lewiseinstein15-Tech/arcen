# Manual task bank (experimental)

The task bank stores locally curated task text as content-addressed objects and
keeps immutable local names in `tasks.sqlite3` under the harness store. It is a
convenience for manual editor and campaign commands, **not** task-level
recursion, an evaluator, authenticated provenance or an adoption gate.

**Tasks are stored in plaintext.** Hashes are not encryption and predictable
text may be guessed from its digest. Store directories, database and backups
must be protected. Import only data that may be stored locally and shared with
the configured model provider. Common secret patterns are rejected on import,
but detection is incomplete; unknown, encoded or split secrets can pass.
There is no automatic deletion or retention policy.

With an initialized trusted store:

```sh
arcen harness --store "$STORE" task import review-project ./task.txt
# Copy the printed SHA-256 into TASK_ID.
arcen harness --store "$STORE" task ls
arcen harness --store "$STORE" task show "$TASK_ID"
```

`task new NAME` accepts one line interactively, shows a sanitized preview and
requires exact `STORE TASK_ID` confirmation. It does not authenticate the
operator. Import supports multiple lines from a bounded UTF-8 regular file;
the final path component cannot be a symlink. Names are lowercase letters,
digits and hyphens, at most 64 characters. Content is at most 4,000 characters
and 16,000 UTF-8 bytes. An existing name cannot be replaced; re-importing the
same name and bytes is idempotent. Different names may reference the same
content hash. There are at most 1,000 names. A crash or I/O failure during an
import can leave an unreferenced plaintext object in the store.

The editor and manual campaign commands accept **either** `--task-id TASK_ID`
**or** `--task-file PATH`. The same task ID can be used at both plan and run:

```sh
arcen harness --store "$STORE" editor propose --baseline "$BASELINE" \
  --task-id "$TASK_ID" --config ./arcen.yaml --budget "$BUDGET"
arcen harness --store "$STORE" campaign plan --baseline "$BASELINE" \
  --candidate "$CANDIDATE" --task-id "$TASK_ID" \
  --commit "$(git rev-parse HEAD)" --budget "$BUDGET"
arcen harness --store "$STORE" campaign run "$CAMPAIGN" --task-id "$TASK_ID" \
  --config ./arcen.yaml --repo . --budget "$BUDGET"
```

The plan stores the SHA-256 of the exact task bytes; at run the stored object is
re-read and hash-checked, then compared with the plan before confirmation or a
provider call. Task contents are untrusted instructions; terminal output is
sanitized, not a byte-for-byte display or a prompt-injection defense. The
regular confirmation, Docker-only isolation and budget warnings still apply.

`task ls`, `task show`, and `harness doctor` check stored task metadata and
content hashes. Hashes detect ordinary corruption but do not authenticate who
created or edited a task. The database, store and parent directories are trusted
against hostile local filesystem mutation. No provider, Git operation, Docker
container, campaign, ref change or adoption occurs merely by adding or showing
a task.
