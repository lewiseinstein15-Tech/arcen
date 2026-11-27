---
name: git-workflow
version: 0.1.0
description: Branch, commit and prepare changes for review without touching the default branch
tools: [git.status, git.diff, git.log, git.add, git.commit, git.branch, git.checkout, bash]
---

# Git workflow

The default branch is sacred. Everything below assumes you never commit to it.

1. `git.status` first — know what is already dirty before you add to it.
2. Branch before editing: `git.branch {"name": "fix/short-slug", "create": true}`.
3. Work in small commits. One logical change per commit; a commit you cannot
   summarise in one line is two commits.
4. Stage deliberately: `git.add {"paths": ["src/x.py", "tests/test_x.py"]}` —
   never `git add -A` when the tree has unrelated edits.
5. Commit with a subject that states the change and a body that states why:
   `git.commit {"message": "Reject expired tokens\n\nA token past exp was accepted because ..."}`.
6. Before you stop: `git.status` clean, `git.log {"limit": 5}` shows your
   commits, and `git.diff {"ref": "main"}` is only what you meant.
7. Never force-push, never rewrite shared history, never commit secrets. If a
   secret was committed, say so loudly — rotating it is the fix, not deleting
   the line.
