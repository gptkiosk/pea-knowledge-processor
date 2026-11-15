# PEA knowledge processor

A scheduled pipeline that reads a short, curated list of podcast and news sources and turns them into **one fixed, validated format**, published as static files. The PEA iPhone app reads only that format, and checks every file before using it.

Why it exists: an assistant cannot talk well about a podcast episode if every publisher's feed and transcript arrives in a different shape and has to be untangled on the phone. Here the untangling happens once, in the open, with tests. The app always gets the data it expects in the form it expects, or a typed reason why not.

- No server, no accounts, no database: static files on GitHub Pages.
- Python 3.11 or later, standard library only. Nothing to install.
- Works with no API key. A model digest through OpenRouter is optional.

**Status: 0.1.0, not yet published.** See "Before the first publish".

## What comes out

```
store.json                                   every source as a store card, its state, the hash of its items file
sources/<source>/items.json                  one source's items, with the hash and size of every file
sources/<source>/<item>.digest.json          what the assistant needs to talk about one item
sources/<source>/<item>.transcript.pea.txt   the transcript (PEA transcript v1), only where the publisher's terms allow
health.json                                  what the last run did
```

- **The store listing** (`store.json`) is small and is all the app needs to show the catalog: name, description, topics, how often items come, how long and how large they are, the three newest titles, the terms.
- **A digest** is built for conversation: a framing, five to eight talking points in story order (each with why it matters, a pointer into the transcript and a question worth asking), exact quotes with speaker and time, a glossary of the names that come up, the figures, what is disputed, links to earlier items, conversation starters and follow-up questions, and a compact brief form of at most 900 characters.
- **Every source has a lifecycle state** (`active`, `paused`, `withdrawn`), so a source can be switched off for every app with one commit.

The full description is [docs/FORMAT.md](docs/FORMAT.md). What the app must do with it is [docs/APP-CONTRACT.md](docs/APP-CONTRACT.md). The sources and what their terms allow are in [docs/SOURCES-TERMS.md](docs/SOURCES-TERMS.md).

## Run it

From a checkout:

```
python3 -m pea_knowledge run --config config/sources.json --out dist      # the real sources (about a minute, about 30 polite requests)
python3 -m pea_knowledge validate dist                                    # check a folder the way the app does
python3 -m pea_knowledge run --config tests/fixtures/sources.json --out /tmp/dist --offline-fixtures tests/fixtures/web   # no network: made-up sources
```

`run` treats what is already in `--out` as the previous output: unchanged items are not fetched again, a source that fails keeps its last good items, and the folder is replaced only if the new one validates.

Tests:

```
python3 -I -m unittest                               # 90 tests, no network, about 20 seconds
python3 -I spec/transcript-v1/test_conformance.py    # the transcript format's own 40 tests
PEA_NETWORK_TESTS=1 python3 -I -m unittest           # also two tests that use the real network
```

## How it works

| Stage | What it does |
| --- | --- |
| 1. Fetch (`fetch.py`) | https only; the host name is resolved, every address must be public, and the connection goes to the address that was checked; redirects are checked again; robots.txt is obeyed and crawl delays honoured; conditional requests; size and time caps; no cookies; a User-Agent that names this project and its repository. |
| 2. Normalize (`adapters.py`, `transcript/`) | Reads an agent index (`agent.json`), RSS or Atom with `podcast:transcript`, or JSON Feed. Converts WebVTT, SubRip, Podcasting 2.0 JSON, markdown and plain text into PEA transcript v1. A missing or unusable transcript gets a typed reason. |
| 3. Digest (`digest.py`, `model_digest.py`) | An extractive digest, always: sentences picked from the transcript, the same result for the same input. Optionally a model digest; anything invalid in it falls back to the extractive one. |
| 4. Build (`pipeline.py`, `validate.py`) | Writes the output with hashes, keeps the last good copy of what failed, sets each source's state, prunes old items, validates everything, and only then replaces the previous output. |

In CI these run as three jobs: fetching has no secrets; the digest job is the only one given the model key; publishing validates before it deploys.

## The model digest (optional)

Off by default (`"model": {"enabled": false}` in `config/sources.json`). To use it: add the repository secret `OPENROUTER_API_KEY` and set `enabled` to true.

- Default model `openai/gpt-4.1-nano` (listed on OpenRouter on 2026-11-14 at USD 0.10 per million input tokens and 0.40 per million output tokens). Any chat model there can be named instead.
- The call has no tools. The answer is checked field by field: quotes must be in the transcript word for word, times must exist, names and figures must occur in the transcript, everything is length-capped, links and markup are dropped.
- Cost: an episode of up to 60,000 characters is about 20,000 tokens in and at most 2,000 out, so **about USD 0.003 per episode**. Only new episodes are sent. With the five sources here that is one or two a day: **well under one cent a day**; the very first run, with about sixteen transcripts, about five cents. Limits: USD 0.02 per item and USD 0.25 per run (`max_cost_usd_per_item`, `max_cost_usd_per_run`), 24 calls per run. What was spent is in `health.json` and in the run summary.
- No real key is used in the tests; they run against a small local server. The model path has not been run against the real service yet.

## Add a source

1. Go through the terms checklist in [docs/SOURCES-TERMS.md](docs/SOURCES-TERMS.md): robots.txt, licence, terms of use.
2. Add an entry to `config/sources.json` (`schema/sources.schema.json` describes it): id, name, kind, adapter, feed address, site, description, overview, categories, icon hint, the `terms` you verified, and `publish`. **`publish` is `digest_only` unless the publisher clearly permits redistributing transcripts.** A news source is always `digest_only`: headline, a short description and the link, never the article text.
3. `python3 -m pea_knowledge run --config config/sources.json --out dist`, read the summary, open a digest.
4. Open a pull request. The tests run on it.

## Take a source offline in one commit

Edit the source in `config/sources.json`, commit to `main`, and run the workflow (Actions, "Process sources", "Run workflow") or wait for the next scheduled run. No app update is needed.

| You want | Set on the source | What apps do |
| --- | --- | --- |
| Pause it (outage, the publisher changed format) | `"state": "paused", "message": "A plain sentence for the owner."` | Show the message, keep reading what they have, stop fetching, leave it out of suggestions. |
| Remove it (quality, no longer wanted) | `"state": "withdrawn", "state_reason": "quality", "message": "..."` | Switch it off, show the message; the owner may keep or delete local items. |
| Remove it and have local copies deleted (a takedown request) | `"state": "withdrawn", "state_reason": "takedown", "purge": true, "message": "..."` | Switch it off and delete the local copy. |
| Bring it back | Remove `state`, `message`, `purge` | Back to normal on the next run. |

- The message is text only: no links, no markup, at most 240 characters. The run refuses a config that breaks this.
- A withdrawn source's files leave the published output at once; its listing stays for 90 days (`tombstone_days`) as a notice so every app learns of it, then disappears. After that the entry can be deleted from the config.
- Deleting the entry from the config outright also works: the next run lists it as withdrawn ("The curator removed this source.") for 90 days. An app that finds a source gone treats it as withdrawn anyway.
- Automatic: a source that cannot be read three runs in a row (`auto_pause_after_failed_runs`) is paused with its last good items kept, and resumes by itself when it reads again. `"state": "active"` on a source stops the automatic pause.
- Emergency stop for everything: disable the workflow in the Actions tab. The published files stay as they are.

## How the app consumes it, and privacy

The app downloads static files and sends nothing about its owner: no account, no cookie, no identifier. It fetches `store.json` with `If-None-Match`, then only the files whose SHA-256 changed. Browsing the store needs `store.json` alone, which is the same for everyone. Fetching one source's items does show the static host which sources an address follows; the app says so and can fetch all sources' items instead. Details in [docs/APP-CONTRACT.md](docs/APP-CONTRACT.md).

This repository holds no personal data. The fixtures and golden samples are invented.

## Before the first publish

The owner has to:

1. Fill in the copyright holder in `LICENSE` (the line that says so).
2. Create the public repository `gptkiosk/pea-knowledge-processor` and push `main`.
3. In the repository settings, Pages: set the source to **GitHub Actions**.
4. Optional: add the secret `OPENROUTER_API_KEY` (Settings, Secrets and variables, Actions) and set `model.enabled` to true.
5. Run "Process sources" once by hand and read the run summary. The files appear at `https://gptkiosk.github.io/pea-knowledge-processor/store.json`.
6. Read [docs/SOURCES-TERMS.md](docs/SOURCES-TERMS.md), "What is uncertain overall", and decide.

Good to know: GitHub disables scheduled workflows in a repository with no activity for 60 days; and the first scheduled run finds nothing published yet, which is expected.

## Layout

```
config/sources.json      the curated list
schema/                  JSON Schemas (draft 2020-12)
spec/transcript-v1/      the PEA transcript v1 specification, tools and fixtures (a copy)
src/pea_knowledge/       the pipeline
tests/                   tests, made-up fixtures, golden samples for the app's tests
docs/                    the format, the app's contract, the sources' terms
.github/workflows/       the scheduled run and the tests
```

## Licence

Apache-2.0. See `LICENSE`.
