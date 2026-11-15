# Changelog

## 0.5.0 (2026-11-15)

Owner rule (2026-11-15): a podcast with only headlines or short show notes is not a useful knowledge source. A source, and each of its items, may be in the catalog only if the assistant has a full path to the whole text.

- **Only discussable items are listed.** An item is in `items.json` only when the pipeline read its transcript in full or in part (`transcript.read` is `full` or `partial`) and the item carries `transcript_source`. Items with no transcript published, a failed fetch, an unreadable transcript, or no address to fetch the whole text from are not listed, have no digest file, and are not in `item_count` or `available`. No new member: absence means not discussable, the format stays 1.2 and the schemas still validate. An output from an older generator is cleaned on the next run.
- **One source rule.** Of its newest `transcript_check_items` (5) a source needs at least `min_discussable_items` (new, 2) and at least `min_full_transcript_share` (0.6) discussable items. This replaces the old 60-percent transcript count, which is now the same count. A failing source is paused (reason `empty` when it never had any, `format_changed` when it used to) and withdrawn after the existing 30 days. `0` and `0` switch it off.
- **A phone-style probe** (`src/pea_knowledge/probe.py`): for the newest discussable item of each source, one request with the headers, User-Agent and limits of the app's `PublicFetcher`, no robots.txt, checked for 200, the expected content type, at most 1.5 MB and conversion with this repository's own converters. A source whose newest item fails is paused with reason `fetch_failed` and "the publisher refuses requests like the app's"; an older item that fails is dropped. One request per source per run, an ok result reused for 24 hours (`phone_probe`, `phone_probe_reuse_hours`).
- `health.json` gains, per source, `dropped` (what was left out of `items.json`, by typed reason: `none_published`, `fetch_failed`, `unreadable`, `no_source`, `phone_probe`) and `phone_probe` (`item`, `result`, `reason`, `checked_at`, `reused`). `state.json` remembers dropped items and the last ok probe so nothing is asked twice; an item younger than a week is asked for again each run, because transcripts often appear after the episode.
- The generator is 0.5.0, so every source is read again and every old listing is judged by the new rule. Tests: made-up fixtures for each rule (an item without a path, a source below the minimum, a 403, a wrong content type, an oversize file and a timeout in the probe), golden samples regenerated.

## 0.4.0 (2026-11-15)

- **Format 1.2: topics.** `store.json` carries a controlled vocabulary of thirty topics (`topics`: id, label, the words a person might say, a description). Every source lists its beat (`topics`, up to six ids) and every item what it is about (`topics`: up to four `{"id", "score"}`, best first, and `topics_by`: `keywords` or `model`). All optional and additive.
- **Why 1.2 and not 1.1**: a reader whose known minor is 1 refuses an unknown member in a file that says 1.1. A file that says 1.2 it reads, ignoring what it does not know. An app that wants topics raises its known minor to 2 and takes the new `store` and `items` schemas. Digests did not change beyond saying 1.2.
- **A keyword tagger**, always on, deterministic, standard library only (`src/pea_knowledge/topics.py`, `config/topic_lexicon.json`). A wrong tag is worse than a missing one: an item with no confident topic gets an empty list. Measured on 94 hand-labelled real items: about 96 percent of tags right, about 94 percent of main topics found (README, "Topics").
- **A model may propose topics**, off by default (`model.topics`), from the vocabulary only and only where the checked digest bears them out; otherwise the keywords decide. Tested against the local stand-in only.
- The validator refuses a topic id that is not in the vocabulary of the same `store.json`, an id twice, unsorted scores, more than two decimals, and `topics` without `topics_by`. Thirteen new hostile samples (`tests/golden/hostile/topics-*`).
- Every item is made anew once after this change, and again whenever the vocabulary or the lexicon changes.

## 0.3.0 (2026-11-15)

- **HTML transcript pages are read** (`src/pea_knowledge/htmlpage.py`), for publishers that post the full transcript openly on their own site. A source names how the page of an episode is found (`transcript_page`: the item's page, a link in its notes, a link on its page, or a template), the one host it may be on, and the elements to read as simple selectors. Nothing is executed; hidden text, menus, scripts and advertising are dropped; reading is bounded in time; a page with too little text, no transcript, or a sign-in, paywall, cookie or robot-check wall is `none_published` or `unreadable` with a detail, never a partial read. A `podcast:transcript` tag that points to an HTML page is read the same way.
- **`transcript_source` on an item**, optional, within format 1.1: `link` (the publisher's own address of the transcript), `format`, `route`, `bytes`, and `extract` for an HTML page. An app can fetch the transcript from the publisher itself; nothing more is published here. The address is in a member named `link` so that readers of 1.0 and 1.1 accept it. `withheld_terms` now reads: read by the pipeline, not republished.
- **Lex Fridman Podcast is added**, read from its transcript pages. 99% Invisible, Syntax, Freakonomics Radio and NPR were checked and are not carried: their terms forbid robots or scraping. Hidden Brain is not carried: its feed gives no page per episode.
- A transcript that the pipeline cut at its own size cap counts as offered in full for the rule of the catalog. A transcript that failed to fetch is asked for again on the next run instead of being kept as failed.
- Every item is made anew once after this change, so that all of them carry `transcript_source`.

## 0.2.0 (2026-11-15)

- **Format 1.1**, additive: `link_kind` and `transcript.read` on an item; `guests`, `mentioned_resources` (names only), `chapters`, `snippable_moments` and `recap_cards` in a digest. A reader of 1.0 keeps working: it ignores what it does not know. No limit grew; the brief form is still at most 900 characters.
- **Per-episode links.** One source (Buzzcast) gave every episode the show's home page, because its feed has no `<link>`. The page is now found in the entry's link, a permanent-link guid, an Atom alternate link, the enclosure (a rule per known host) or an HTML transcript page; an item with none links to the show and says so. Ids did not change.
- **Only sources with full transcripts are carried**, enforced by the pipeline: paused, then withdrawn, when the transcripts stop. EFF Deeplinks (news, no transcript) is removed. Eight sources are added; twelve in all.
- The publisher's own marks are read: `podcast:person`, `psc:chapter`, `podcast:chapters`, `podcast:soundbite`, chapter lines and linked names in show notes. A feed larger than 8 MB is read up to its newest whole entries.
- A `keep-alive` job keeps the schedule from lapsing after 60 quiet days.
- After a change of the digest code (`DIGEST_REVISION`) kept digests are rebuilt on the next run.

## 0.1.0 (2026-11-14, not yet published)

First version.

- Format 1.0: `store.json` (the store listing with each source's lifecycle state), `sources/<id>/items.json`, a conversation digest per item, PEA transcript v1 for transcripts, `health.json`. JSON Schemas in `schema/`.
- The pipeline: polite fetching with checked public addresses; adapters for an agent index, RSS and Atom with `podcast:transcript`, and JSON Feed; transcripts converted from WebVTT, SubRip, Podcasting 2.0 JSON, markdown and plain text; an extractive digest that needs no key; an optional model digest through OpenRouter with caps on cost; a build that keeps the last good copy, pauses a source after repeated failures, leaves a notice for withdrawn sources and never publishes output that does not validate.
- A validator for an output folder: the reference for the app's checks.
- Five curated sources, all `digest_only`, with the terms verified for each on 2026-11-14.
- Tests with made-up fixtures, golden samples for the app's tests, and CI: a run every six hours in three jobs, and tests on pull requests.

Known limits: the extractive digest picks sentences and cannot say why a point matters; names and their kinds are found by pattern. The model digest is tested against a local stand-in only. Python 3.11 is supported by intent and tested in CI, not on the machine this was written on.
