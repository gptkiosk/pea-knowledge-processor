# Changelog

## 0.1.0 (2026-11-14, not yet published)

First version.

- Format 1.0: `store.json` (the store listing with each source's lifecycle state), `sources/<id>/items.json`, a conversation digest per item, PEA transcript v1 for transcripts, `health.json`. JSON Schemas in `schema/`.
- The pipeline: polite fetching with checked public addresses; adapters for an agent index, RSS and Atom with `podcast:transcript`, and JSON Feed; transcripts converted from WebVTT, SubRip, Podcasting 2.0 JSON, markdown and plain text; an extractive digest that needs no key; an optional model digest through OpenRouter with caps on cost; a build that keeps the last good copy, pauses a source after repeated failures, leaves a notice for withdrawn sources and never publishes output that does not validate.
- A validator for an output folder: the reference for the app's checks.
- Five curated sources, all `digest_only`, with the terms verified for each on 2026-11-14.
- Tests with made-up fixtures, golden samples for the app's tests, and CI: a run every six hours in three jobs, and tests on pull requests.

Known limits: the extractive digest picks sentences and cannot say why a point matters; names and their kinds are found by pattern. The model digest is tested against a local stand-in only. Python 3.11 is supported by intent and tested in CI, not on the machine this was written on.
