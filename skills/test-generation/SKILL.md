---
name: test-generation
version: 0.1.0
description: Write tests that would actually catch the bug - real code paths, no mocks by default
tools: [bash, file.read, file.write, file.edit, search.text]
---

# Write tests worth keeping

A test that cannot fail is worse than no test: it costs runtime and buys
false confidence.

1. Read the code under test first. You are looking for the inputs that are
   hard, not the ones that are easy: empty, one, many, malformed, unicode,
   concurrent, huge.
2. Match the repository's existing test style — same framework, same fixture
   conventions, same file layout. Read a neighbouring test file before
   writing one.
3. Prefer the real code path. Mock only a genuine external boundary (network,
   clock, subprocess) and say in a comment why the mock is unavoidable.
4. One behaviour per test, named after the behaviour: `test_rejects_expired_token`,
   not `test_validate_2`.
5. Assert on observable output, not on internal calls.
6. Run the new test alone, then the file, then the suite. A new test that
   passes only in isolation is a leak — fix the leak.
7. Prove the test can fail: break the implementation on purpose, watch the
   test go red, then revert. A test you never saw fail is a guess.
