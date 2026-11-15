# Changelog

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
