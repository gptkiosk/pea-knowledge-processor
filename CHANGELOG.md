# Changelog

## 0.8.0 (2026-11-19)

The brief contract (contract/README.md): the processor is the thorough side, the app a thin reader. Builds on 0.7.0 (briefs index).

- **Stricter brief rules**, in the reader's check (`validate.brief_rules`, also `check_brief_alone` for a brief on its own): a talk size of at most 1,050 characters (what the app's 4,200-character block shows of a brief, so any three fit by construction), a date that exists, at least one claim, and no markup, app label or instruction in any authored text. The writer's check and the extractive builder use the same text rule; quotes give way to the talk size; an extractive brief always has a plain headline and a claim; a model brief or an earlier published brief that fails is replaced by an extractive one, so the build never publishes what the reader refuses. The format stays 1.3.
- **Golden corpus** `contract/golden/` (38 files: 9 must pass, 29 must fail with one typed reason each) with `manifest.json` (SHA-256 per file and over the corpus), written by `contract/make_golden.py`.
- **Commands**: `python3 -m pea_knowledge contract` (the corpus holds) and `check-briefs <paths>` (the strict check over any brief output, no network).
- **Workflows**: the test workflow checks the corpus and the offline run's briefs; the publish job runs `contract` and `check-briefs dist` after `validate dist`, and publishes nothing if one fails.
- Generator 0.8.0, so every source's feed is read once more; items are not made again.
- Tests: `tests/test_contract.py`. Golden files regenerated.

## 0.7.0 (2026-11-19)

The app was asked for "three across three different podcasts" and said it had only two podcast briefs, then found two from a third show: it counted whatever few briefs happened to be in its prompt. This release publishes the list it should count from.

- **`briefs-index.json`** (format 1.3, additive; `src/pea_knowledge/briefs_index.py`, `schema/briefs-index.schema.json`, docs/FORMAT.md section 13, docs/APP-CONTRACT.md section 10): `generated_at` (that of `store.json`), `shows[]` (id, name, kind, `brief_count`, `latest`: the newest five briefs with `item_id`, `title` cut to 120, `date`, `method` model or extractive, `partial`), and `latest_overall` (the twelve newest across shows, with `show_id`). Sorted and deterministic, written compact (the one file without indent): about 11 KB for today's fourteen sources. Nothing in it that the items files do not say.
- **Build** writes it after the items files, from them. **Validate** checks it when present (optional, so an output of 0.6.0 still validates): schema and text rules, at most 32,000 bytes, `generated_at` that of `store.json`, every named brief listed (`missing`), and equal to the index made again from the items files (`inconsistent`). **Restore** fetches it when it is published.
- Generator 0.7.0, so every source's feed is read once more; items are not made again.
- Tests: `tests/test_briefs_index.py` (the offline fixture run writes an index the validator accepts; same bytes for the same output; tampered counts, titles, kinds, order, a brief that is not listed, another run's time, oversize; cut titles and order; fourteen sources under 15 KB; restore with and without one). Golden files regenerated, with nine `index-*` hostile samples checked against `golden/dist`.

## 0.6.0 (2026-11-17)

Phase 2 of the briefs plan (stateless talk on current information): a short brief per item that the app can search on the phone.

- **Format 1.3: briefs.** A new file per item, `sources/<source>/<item>.brief.json`: `headline`, `claims` (each with a `ref` into the transcript), `new`, at most two `quotes` with speaker and time, `topics` from the vocabulary, up to five `keywords`, up to twelve `entities`, the source, title, date and link, `brief_kind` (`model` or `extractive`), `covers` (`whole` or `partial`, with a note) and the model. At most 1,800 characters of visible text. Named on each item of `items.json` by a new optional `brief` member (path, hash, size, kind, covers); its size is not counted in the item's `bytes`, so a 1.2 reader's checks still hold. Every listed item has one. New schema `schema/brief.schema.json`; docs/FORMAT.md section 12, docs/APP-CONTRACT.md section 10.
- **The writer** (`src/pea_knowledge/brief.py`, stage 3b, `python3 -m pea_knowledge briefs`): the phase 1 writer prompt v3 with its ten rules, through the same OpenRouter client as the model digest (`model_digest.chat`) and the same key, `OPENROUTER_API_KEY`. Default model `anthropic/claude-haiku-5.5` (not yet checked against OpenRouter's list). Long transcripts are written in parts and merged in one more call. One automatic retry sends the checker's errors back; anything that still fails, or no key, gives an extractive brief built from the digest. A brief is reused without a call when the transcript and the model are unchanged.
- **The checker**: schema and caps, text rules, every quote word for word in the transcript, every claim's ref a line that exists (claims without one are dropped; fewer than four is a failure), a quote's speaker the speaker of its line and of any claim that uses the same line (rule 8), topics only from the vocabulary; names and numbers not in the transcript are flagged. The reader's validator checks every brief against its index entry, the 1,800-character cap and the vocabulary. The output folder is still replaced only when everything validates.
- **Cost caps**: `brief_budget` in config/sources.json, `per_run_cents` 100 and `monthly_cents` 200 by default; tokens and cost are taken from the provider's answer. When a cap is reached the run stops calling the model and the rest are extractive. The month's spend is kept in `state.json` (`briefs`), which every run restores from the published output. `health.json` gains `briefs` (calls, written, cached, retried, fell back, over the cap, by terms, tokens, run and month spend, briefs by kind, flags).
- **Upgrades**: once a run's brief step has had a key, the next runs fetch again a few listed items whose brief is still extractive (`briefs.upgrade_per_run`, 12), so the older items get model briefs too, within the caps. The fetch job still gets no secret: it reads the previous run's ledger. An item whose model brief failed its checks is not asked for again until it changes.
- **Terms**: a source may say `brief_writer: extractive`; it is then never sent to a model. No carried source needs it today (docs/SOURCES-TERMS.md).
- **Workflow**: the digest job's one keyed step now also runs `briefs`. Without the secret no model is called. The schedule is unchanged.
- **Dry run**: `python3 -m pea_knowledge briefs --dry-run --limit N` lists which items would get a model brief and the estimated tokens and cost, with no model call (it fetches into a temporary folder first when there is no work folder).
- Tests: `tests/test_briefs.py` against a local stand-in model server (good answer, malformed JSON, garbled retry, over the cap, invented quote, wrong speaker and rule 8, dropped refs, flags, hostile text, chunk and merge, caps, no key, terms, cache, monthly ledger across runs, upgrades, the reader's checks, the dry run, and a whole run on the fixtures). Golden files regenerated; seven `brief-*` hostile samples.

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
