# PEA knowledge processor

A scheduled pipeline that reads a short, curated list of podcasts whose publishers offer full transcripts and turns them into **one fixed, validated format**, published as static files. The PEA iPhone app reads only that format, and checks every file before using it.

Why it exists: an assistant cannot talk well about a podcast episode if every publisher's feed and transcript arrives in a different shape and has to be untangled on the phone. Here the untangling happens once, in the open, with tests. The app always gets the data it expects in the form it expects, or a typed reason why not.

- No server, no accounts, no database: static files on GitHub Pages.
- Python 3.11 or later, standard library only. Nothing to install.
- Works with no API key. A model digest through OpenRouter is optional.

**Status: 0.5.0, format 1.2.** Thirteen sources listed. **The rule: a podcast with only headlines or short show notes is not a useful knowledge source. A source, and each of its items, is in the catalog only if the assistant has a full path to the whole text (the full transcript or manuscript), so it can discuss an item in depth beyond the digest's cursory points. An item with no such path is not listed at all; a source with too few such items is paused and then withdrawn.**

## What comes out

```
store.json                                   every source as a store card, its state, the hash of its items file
sources/<source>/items.json                  one source's items, with the hash and size of every file
sources/<source>/<item>.digest.json          what the assistant needs to talk about one item
sources/<source>/<item>.transcript.pea.txt   the transcript (PEA transcript v1), only where the publisher's terms allow
briefs-index.json                            the shows with briefs, how many, and the newest briefs (format 1.3, additive)
health.json                                  what the last run did
```

- **The store listing** (`store.json`) is small and is all the app needs to show the catalog: name, description, topics, how often items come, how long and how large they are, the three newest titles, the terms.
- **A digest** is built for conversation: a framing, five to eight talking points in story order (each with why it matters, a pointer into the transcript and a question worth asking), exact quotes with speaker and time, a glossary of the names that come up, the figures, what is disputed, links to earlier items, conversation starters and follow-up questions, and a compact brief form of at most 900 characters. Since format 1.1 also: the guests, the books, tools and sites that are named (names only, never a link), chapters (the publisher's own where it marks them), up to five exact passages worth snipping with their times, and three recap cards.
- **Every item is tagged with topics** from one vocabulary of thirty (`topics` in `store.json`: technology, AI, health, wellness, supplements, politics, religion, leadership and so on), so an app can answer "I want to talk tech" with items from every source its owner follows. The tags need no model. See "Topics" below.
- **Every listed item says where the publisher offers its transcript** (`transcript_source`: the address, the format, how it was found), and is listed only because the pipeline read that transcript. Transcripts are not republished here; an app that wants the whole text fetches it from the publisher itself. `items.json` lists only such discussable items, so the app may offer every item it sees (absence means not discussable).
- **Every item links to its own page** at the publisher. Where a feed gives no page per episode, the item links to the show and says so (`link_kind: show`).
- **Every source has a lifecycle state** (`active`, `paused`, `withdrawn`), so a source can be switched off for every app with one commit.

The full description is [docs/FORMAT.md](docs/FORMAT.md). What the app must do with it is [docs/APP-CONTRACT.md](docs/APP-CONTRACT.md). The sources and what their terms allow are in [docs/SOURCES-TERMS.md](docs/SOURCES-TERMS.md).

## Run it

From a checkout:

```
python3 -m pea_knowledge run --config config/sources.json --out dist      # the real sources (two minutes and about 100 polite requests the first time, then seconds)
python3 -m pea_knowledge validate dist                                    # check a folder the way the app does
python3 -m pea_knowledge run --config tests/fixtures/sources.json --out /tmp/dist --offline-fixtures tests/fixtures/web   # no network: made-up sources
```

`run` treats what is already in `--out` as the previous output: unchanged items are not fetched again, a source that fails keeps its last good items, and the folder is replaced only if the new one validates.

Tests:

```
python3 -I -m unittest                               # 180 tests, no network, about 30 seconds
python3 -I spec/transcript-v1/test_conformance.py    # the transcript format's own 40 tests
PEA_NETWORK_TESTS=1 python3 -I -m unittest           # also two tests that use the real network
```

## How it works

| Stage | What it does |
| --- | --- |
| 1. Fetch (`fetch.py`) | https only; the host name is resolved, every address must be public, and the connection goes to the address that was checked; redirects are checked again; robots.txt is obeyed and crawl delays honoured; conditional requests; size and time caps; no cookies; a User-Agent that names this project and its repository. |
| 2. Normalize (`adapters.py`, `transcript/`) | Reads an agent index (`agent.json`), RSS or Atom with `podcast:transcript`, or JSON Feed; a feed larger than 8 MB is read up to its newest whole entries. Finds each item's own page, and what the publisher marks up itself: people, chapters (`psc:chapter`, `podcast:chapters`, timed lines in the notes), soundbites, the names the notes link to. Converts WebVTT, SubRip, Podcasting 2.0 JSON, markdown and plain text into PEA transcript v1. For a publisher whose transcript is a web page on its own site (`htmlpage.py`), finds the page of each episode and reads only the transcript from it: nothing is executed, hidden text and menus are dropped, and a page with too little text or a sign-in wall is a typed failure, never a partial read. A missing or unusable transcript gets a typed reason. |
| 3. Digest (`digest.py`, `model_digest.py`) | An extractive digest, always: sentences picked from the transcript, the same result for the same input. Optionally a model digest; anything invalid in it falls back to the extractive one. |
| 3b. Probe (`probe.py`) | For the newest discussable item of each source, one request made exactly as the app makes it (the app's headers and time limits, no robots.txt), checked for a 200, the expected content type, at most 1.5 MB and a transcript that converts. A source whose newest item fails is paused: the app must not offer what its own phone cannot fetch. |
| 4. Build (`pipeline.py`, `validate.py`) | Writes the output with hashes, lists only discussable items, keeps the last good copy of what failed, sets each source's state (also: too few discussable items, a refused probe), prunes old items, validates everything, and only then replaces the previous output. |

In CI these run as three jobs: fetching has no secrets; the digest job is the only one given the model key; publishing validates before it deploys.

## The model digest (optional)

Off by default (`"model": {"enabled": false}` in `config/sources.json`). To use it: add the repository secret `OPENROUTER_API_KEY` and set `enabled` to true.

- Default model `openai/gpt-4.1-nano` (listed on OpenRouter on 2026-11-14 at USD 0.10 per million input tokens and 0.40 per million output tokens). Any chat model there can be named instead.
- The call has no tools. The answer is checked field by field: quotes must be in the transcript word for word, times must exist, names and figures must occur in the transcript, everything is length-capped, links and markup are dropped.
- The model is shown the transcript (at most 60,000 characters) and the show notes (at most 3,000), and may also propose guests, named resources, chapters and moments. Each is checked like a quote or a name: against the transcript and the notes, never trusted. Recap cards are never taken from it.
- Cost: an episode is at most about 21,000 tokens in and 2,800 out, so **at most about USD 0.0035 per episode**, usually less. Only new episodes are sent. The twelve sources publish about four episodes a day between them: **about one to one and a half cents a day, under fifty cents a month.** The very first run has 55 transcripts; 24 calls per run are allowed, so it takes three runs and about 15 cents in all. Limits: USD 0.02 per item and USD 0.25 per run (`max_cost_usd_per_item`, `max_cost_usd_per_run`). What was spent is in `health.json` and in the run summary.
- No real key is used in the tests; they run against a small local server. The model path has not been run against the real service yet.

## Briefs (format 1.3)

Every listed item has a brief: a short summary of fixed shape (a headline, 4 to 8 claims with a pointer into the transcript, what is new, at most two exact quotes, topics, keywords and names; at most 1,800 characters of text) that the app searches on the phone and talks from. docs/FORMAT.md section 12 has the format and docs/APP-CONTRACT.md section 10 what the app may rely on.

- **Model briefs** are written in the digest job by `python3 -m pea_knowledge briefs` when the secret `OPENROUTER_API_KEY` is set and `briefs.enabled` is true (the default). Model `anthropic/claude-haiku-5.5` by default (`briefs.model`; the id has not been checked against OpenRouter's list yet), priced in the config at USD 0.10 and 0.50 per million tokens in and out. Every brief is checked against the transcript (quotes word for word, every claim pointing to a real line, speakers, caps, vocabulary); one retry sends the errors back; anything that still fails falls back. Long transcripts are written in up to four parts of 60,000 characters and merged.
- **Extractive briefs** are made by the build for every other item, with no model and no key.
- **Cost caps**: `brief_budget` in `config/sources.json`, in US cents: `per_run_cents` (100) and `monthly_cents` (200). The run stops calling the model at either cap and the rest are extractive. The month's spend is in `state.json` of the published output and carries over between scheduled runs; each run's spend and the month's are in `health.json` and in the run summary. A brief is reused without a call when the transcript and model are unchanged, so an unchanged item costs nothing.
- **Upgrades**: listed items whose brief is extractive get a model brief a few per run (`briefs.upgrade_per_run`, newest first). The fetch job has no key, so it fetches their transcripts again only when it knows the brief step will have one: dispatch with `gh workflow run process.yml -f expect_key=true`, or set the repository variable `PEA_BRIEFS_KEY_EXPECTED` to `true` for scheduled runs; once a published `state.json` records a brief step with a key, scheduled runs go on by that.
- **Before spending**: `python3 -m pea_knowledge briefs --dry-run --limit 10` prints which items would get a model brief and the estimated tokens and cost. It calls no model.
- **Terms**: `"brief_writer": "extractive"` on a source keeps it away from any model (for a source whose terms forbid quotes or derived summaries).
- **The briefs index** (`briefs-index.json`, about 11 KB): every show with briefs, its brief count and newest five briefs (title, date, model or extractive, whether it covers only part), and the twelve newest across shows. Made by every build from the items files; the validator makes it again and refuses one that differs. The app uses it to say truthfully which shows and how many briefs it holds; older apps ignore it. docs/FORMAT.md section 13.
- No real key is used in the tests; they run against a local stand-in server. The first real runs (2026-11-19, branch only) are in docs/FIRST-REAL-BRIEFS.md.

## Topics

- **The vocabulary** is `config/topics.json`: thirty topics, each with an id, a label, up to twelve words a person might say for it, and one line of description. It is published in `store.json`, and an app turns a spoken word into ids from it without a model ("tech" is `technology`, "faith" is `religion-spirituality`, "investing" is two topics on purpose). An id never changes once published; add a topic at the end.
- **The tagger** (`src/pea_knowledge/topics.py`) counts the words and phrases of `config/topic_lexicon.json` in an item's title, the publisher's notes, the digest and the first 30,000 characters of the transcript. Phrases have a weight of 1, 2 or 3; the longest phrase wins; phrases that use a word in another sense ("in good faith", "role model", "to supplement") are listed and count for nothing. A topic needs two different phrases or one strong one, must show in the title, notes or digest, and gets a score from 0.5 to 1. At most four topics; an item with no confident topic gets an empty list and an app falls back to the topics of the source (`topics` on each source in `config/sources.json`). The same input always gives the same tags.
- **How good it is.** 94 real items of the eleven live sources were labelled by hand on 2026-11-15 (`tests/data/topics_labelled.json`: ids and titles only). The lexicon was tuned on the 54 that were live that day; 40 older ones were labelled before the tagger saw them. On those 40, at the first try: 68 tags, 65 right (**95.6 percent**), 45 of 48 main topics found (93.8 percent). With the lexicon as shipped, on all 94: 181 tags, 173 right (**95.6 percent**), 107 of 114 main topics found (93.9 percent), two items without any tag. These sources are mostly technology, AI, software, podcasting, security and health: sports, religion, fitness, education and the environment hardly occur in them and are tested with made-up texts only (`tests/data/topics_cases.json`), so expect less there. Measure again with `python3 tests/eval_topics.py <output folder>` while the labelled items are still in the feeds.
- **To change it**: edit the lexicon or the vocabulary, run the tests (every topic has a text that must get it and one that must not), run the measurement, commit. The next run makes every item anew, about two minutes.
- **A model may tag instead**, off by default: `"model": {"enabled": true, "topics": true}`. It may only name ids of the vocabulary that the checked digest bears out; anything else falls back to the keywords. About 500 tokens more per call. Each item says which it was (`topics_by`).
- **Off switch**: `"topics": {"enabled": false}` at the top of `config/sources.json`.

## Time, and what one failure costs

Measured on 2026-11-15 against the eleven active sources, one process, no model (with topic tagging, measured again the same day: 1 minute 53 seconds and 18 seconds, tagging itself takes well under a second per run): a first run with nothing published yet took **1 minute 54 seconds** (89 requests, 53 transcripts fetched and converted, four of them web pages, 54 digests); the next run, with nothing new, took **17 seconds** (21 requests). In CI the three jobs add about a minute of setup each, so a scheduled run is two to five minutes on a standard runner, far under ten. What keeps it there: conditional requests (a feed that answers "not modified" costs one request), an item whose key did not change is not fetched or digested again, and the model is called for new items only. Requests go one host at a time with a pause, on purpose. A source that fails, times out, changes shape or loses its transcripts never stops the others: it keeps its last good items and the rest publish as usual (`tests/test_pipeline.py`).

## The schedule stays on

GitHub switches off a scheduled workflow after 60 days without activity in the repository. The last job of "Process sources" (`keep-alive`, scheduled runs only, also after a failed run) asks GitHub to enable that same workflow, which it already is. The call changes nothing and counts as activity. It needs `actions: write` for that one job and nothing else: no checkout, no commit, no branch, no third-party action, and a call made with the job's own token cannot start another run. It has not run on GitHub yet. If the call is ever refused, that job fails visibly and publishing is not affected; the fallback is to press "Enable workflow" in the Actions tab once every two months.

## Add a source

0. **Only sources with full transcripts are carried, and only their items that have one.** The publisher itself must offer the full transcript, openly, where the pipeline can fetch it, and where the app's own request (not just the pipeline's) can fetch it too. Not behind a login, paywall or membership, and not YouTube captions or a third-party transcript site.
1. Go through the terms checklist in [docs/SOURCES-TERMS.md](docs/SOURCES-TERMS.md): robots.txt, licence, terms of use.
2. Add an entry to `config/sources.json` (`schema/sources.schema.json` describes it): id, name, kind, adapter, feed address, site, description, overview, categories, icon hint, the hosts, where the transcript is (`transcript_route`; for a transcript that is a web page also `transcript_page`: how the page of an episode is found, its one host, and the elements to read), why it is there (`chosen_because`), the `terms` you verified, and `publish`. **`publish` is `digest_only` unless the publisher clearly permits redistributing transcripts.**
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
- Automatic, too few discussable items: of its newest five items a source needs at least two **and** at least 60 percent (`min_discussable_items`, `min_full_transcript_share`, `transcript_check_items`; one count, not two) whose whole text the assistant can reach. Otherwise it is treated as one that cannot be read (next line), with reason `empty` (none, never any) or `format_changed` (it used to have some) and a sentence that says why, and is withdrawn after 30 days in that pause. It comes back by itself when the items do.
- Automatic, a publisher that refuses the app: if the one phone-style request for the newest discussable item fails (403, wrong content type, over 1.5 MB, timeout, not a transcript), the source goes the same way with reason `fetch_failed` and "the publisher refuses requests like the app's"; an older item that fails is dropped. `health.json` records `phone_probe` and, per reason, what was `dropped`.
- Automatic: a source that cannot be read three runs in a row (`auto_pause_after_failed_runs`) is paused with its last good items kept, and resumes by itself when it reads again. `"state": "active"` on a source stops the automatic pause.
- Emergency stop for everything: disable the workflow in the Actions tab. The published files stay as they are.

## How the app consumes it, and privacy

The app downloads static files and sends nothing about its owner: no account, no cookie, no identifier. It fetches `store.json` with `If-None-Match`, then only the files whose SHA-256 changed. Browsing the store needs `store.json` alone, which is the same for everyone. Fetching one source's items does show the static host which sources an address follows; the app says so and can fetch all sources' items instead. Details in [docs/APP-CONTRACT.md](docs/APP-CONTRACT.md).

Transcripts are the one thing the app may fetch from a publisher: when the owner wants the whole text of an episode, the app downloads the address in `transcript_source` from the publisher itself, which then sees the phone's network address, as with any podcast app.

This repository holds no personal data. The fixtures and golden samples are invented.

## Before the first publish

The owner has to:

1. Fill in the copyright holder in `LICENSE` (the line that says so).
2. Create the public repository `gptkiosk/pea-knowledge-processor` and push `main`.
3. In the repository settings, Pages: set the source to **GitHub Actions**.
4. Optional: add the secret `OPENROUTER_API_KEY` (Settings, Secrets and variables, Actions). With it, model briefs are written within `brief_budget`; set `model.enabled` to true as well for model digests.
5. Run "Process sources" once by hand and read the run summary. The files appear at `https://gptkiosk.github.io/pea-knowledge-processor/store.json`.
6. Read [docs/SOURCES-TERMS.md](docs/SOURCES-TERMS.md), "What is uncertain overall", and decide.

Good to know: the first scheduled run finds nothing published yet, which is expected. The first run of 0.2.0 over an output written by 0.1.0 rebuilds every digest (format 1.1) and lists the removed news source as withdrawn for 90 days.

## Layout

```
config/sources.json      the curated list
config/topics.json       the vocabulary of topics; config/topic_lexicon.json: what the tagger looks for
schema/                  JSON Schemas (draft 2020-12)
spec/transcript-v1/      the PEA transcript v1 specification, tools and fixtures (a copy)
src/pea_knowledge/       the pipeline
tests/                   tests, made-up fixtures, golden samples for the app's tests
docs/                    the format, the app's contract, the sources' terms
.github/workflows/       the scheduled run and the tests
```

## Licence

Apache-2.0. See `LICENSE`.
