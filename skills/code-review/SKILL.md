---
name: code-review
version: 0.1.0
description: Adversarial review of a diff - find what breaks in production
tools: [bash, file.read, git.diff, git.log, search.text]
---

# Review a diff

Read the diff, then read the code around it. The bug is usually in the
interaction, not the line.

1. `git.diff {"staged": true}` (or against the base ref). Read it once without
   commenting — you are building a mental model, not a list of nits.
2. For every changed function, read the whole function and its callers.
3. Check the four things that actually break production:
   - error paths: what happens when this call fails, times out, or returns None
   - boundaries: empty input, huge input, unicode, concurrent access
   - resource limits: unbounded loops, unbounded reads, leaked handles
   - security: user input reaching a shell, a path, SQL, or a log
4. Check the tests: do they cover the new branch, or only the happy path?
5. Rank findings by consequence, not by line number: correctness first,
   security second, maintainability third, style last (and usually skip it).
6. For each finding give file:line, the failure scenario, and the smallest fix.
7. Say what is good. A review that only lists problems is a review that gets
   ignored.
