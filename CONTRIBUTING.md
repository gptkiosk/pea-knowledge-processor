# Contributing

Thank you for helping. A few rules keep this project small and safe.

- **Standard library only.** No third-party dependencies, in the pipeline or the tests.
- **Run the tests** before you open a pull request: `python3 -I -m unittest` and `python3 -I spec/transcript-v1/test_conformance.py`.
- **Fixtures are invented.** Do not add text taken from a real feed, transcript or article. Change `tests/make_fixtures.py` and run it.
- **Golden samples change on purpose only.** If your change alters the output, run `python3 tests/make_golden.py`, read the diff, and say in the pull request why it changed. The app's tests copy these files.
- **The format changes by addition only** within a major version (docs/FORMAT.md, section 8). A new member needs its schema entry, its limit, its line in FORMAT.md saying what it is for, and a test.
- **A new source needs its terms checked** (docs/SOURCES-TERMS.md, the checklist). `publish` stays `digest_only` unless the publisher clearly permits redistributing transcripts.
- **Everything from a publisher or a model is untrusted.** New code that turns such text into output must go through `textrules.clean` or `digest.enforce`, and needs a test with hostile input.
- **No secrets and no personal data** in the repository, the fixtures or the logs.
- `spec/transcript-v1/` is a copy of the transcript specification; change it at its source. `src/pea_knowledge/transcript/` must stay identical to it apart from one import line (a test checks).
- Write plainly: short sentences, no jargon where a plain word will do.

Commits: one subject per commit, a short imperative first line.
