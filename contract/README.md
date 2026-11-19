# The brief contract

Owner direction (2026-11-19): the brief creation process is the thorough side; the app side is so standard that its
stability can be assumed, apart from the ordinary glitches of the owner's chosen model. This folder is that split in
writing and in tests.

- **The processor guarantees** every rule below for every brief it publishes. The writer's check, the extractive
  builder and the build all apply them, and the publish job refuses to publish if one brief fails.
- **The app assumes** exactly these rules and no more. It runs the same rules (its reader is a port of
  `src/pea_knowledge/validate.py`) over the same golden corpus and gets the same result for every file.
- **The golden corpus** (`golden/`, written by `make_golden.py`) is the shared evidence: 38 canonical brief files, each
  with the result every reader must give, and `manifest.json` with each file's SHA-256 and one hash over the corpus.
  The app copies the folder and pins the SHA-256 of `manifest.json`.

## What every published brief guarantees (contract version 1, format 1.3)

A brief file `sources/<source>/<item>.brief.json`, checked on its own (`validate.check_brief_alone`), in this order.
The typed reason is the reader's code (docs/FORMAT.md, "Validation"), the same in the app.

| # | Rule | Reason when broken |
| --- | --- | --- |
| 1 | At most 8,000 bytes | `too_large` (refused unread) |
| 2 | Strict JSON: UTF-8, no NaN, no key written twice, no trailing comma | `not_json` |
| 3 | `format_version` is `1.<minor>`; major 1 only | `schema` (unreadable), `unsupported_version` (major 2 or later) |
| 4 | The 1.3 schema (`schema/brief.schema.json`): every field present, nullable ones as `null`, every cap (headline 160, claim 220, new 300, quote 300, speaker 80, at most 8 claims, 2 quotes, 4 topics, 5 keywords, 12 entities), an https link. In a 1.3 file a member the schema does not name is refused; in a newer minor file it is ignored | `schema` |
| 5 | Every text passes the text rules T1 to T4: no control character or line break, no HTML tag, no address, single spaces | `text_rule` |
| 6 | `link` is a normalized public https address | `address` |
| 7 | `date` is a date that exists (the schema's pattern lets 2026-02-30 through) | `schema` |
| 8 | All visible text (headline, claims, new, quote texts and speakers, topics, keywords, entities) is at most 1,800 characters | `brief_too_long` |
| 9 | The **talk size** is at most 1,050 characters (below) | `brief_too_long` |
| 10 | At least one claim. `brief_kind: model` names its model, has at least four claims, each with a `ref`, and a `new`; `extractive` has no model. `covers: partial` has a `covers_note`, `whole` has none | `inconsistent` |
| 11 | No authored text (headline, claims, new, quotes and speakers, keywords, entities, covers note) holds markup (`**`, `__`, a code mark, a `[text](...)` link, a leading `#`, `>` or bullet), a label of the app's prompt block (`[B1]`, `BRIEFS:`, `BRIEF RULES:`, `LAYERS:`, `AGE:`, `MORE:`, `HAVE:`) or text addressed to the reading program ("ignore all previous instructions") | `text_rule` |

Rule 11 covers the fields the brief's writer controls. `title` and `source_name` come from the publisher through the
items file and are held to rules 4 and 5 only, so one odd title can never stop a whole publish.

In an output folder the reader also checks each brief against its entry in `items.json` (hash, size, identity, kind,
coverage, path), topics against the vocabulary, and refs and quotes against the transcript when it is in the output
(docs/APP-CONTRACT.md section 10). The source and licence record of every brief is its listing in `store.json`:
`publisher`, `terms_summary` and `attribution` are required there by the store schema, and a brief whose source or
identity differs from its index is refused (`identity_mismatch`).

### The talk size, and why 1,050

The app puts at most three briefs into one prompt block of 4,200 characters (`BriefBlock.budget`, inside the
per-request budgets of the app's README). Its block shows, per brief, a label (source name, day, age, the title up to
120 characters, the coverage note), the headline, the claims (it trims them down to two, never fewer), what is new and
the quotes with their speakers. The talk size counts exactly those fields, with the first two claims:

    talk size = source_name + title (to 120) + covers_note + headline + claims[0] + claims[1] + new + each quote's text and speaker

At most 1,050 per brief, three briefs with the app's fixed text around them (about 140 characters each: the label
words, "About:", "Said:", "New:", the quote marks, "speaker not named" for an unknown speaker), the block header (88)
and the longest line that can travel with them (the "more" line, about 345) come to about 3,700 of the 4,200, so
**any three published briefs fit the block without cutting text, by construction**. The app's contract check renders
three copies of the largest golden brief and confirms it. An extractive brief always fits once its quotes are gone
(80 + 120 + 200 + 160 + 2 x 220 = 1,000), so the builder drops quotes, last first, until it fits; a model brief that
still does not fit falls back to the extractive brief.

## Version rules

- **A newer minor** (1.4, ...) only adds members. An older app ignores what it does not know and checks everything it
  does know, so a 1.4 brief works in a 1.3 app (`newer-minor-1.4` in the corpus).
- **A newer major** (2.0) may change anything. The app refuses the brief (`unsupported_version`) and falls back to the
  item's digest: it talks from a brief it makes on the phone from the digest, as for an output older than 1.3
  (`newer-major-2.0`, `app: digest_fallback`). Nothing breaks; the owner sees "Update PEA to read the curated sources"
  only if the store itself moves to a new major.
- **The contract itself** has a version (`contract_version` in the manifest). A stricter rule is a new contract
  version, made in the same change as the corpus and the app's reader (the app's check fails until its copy and reader
  catch up).

## The golden corpus

`python3 contract/make_golden.py` writes `golden/`; `--check` fails when the files differ from what it writes.
`python3 -m pea_knowledge contract` checks every file against the manifest (hash and result). Both run in the test
workflow; the publish job runs `contract` and then `check-briefs dist` after `validate dist`, before anything is
packaged.

| Kind | Cases |
| --- | --- |
| Must pass (9) | typical model brief, minimal extractive, maximum size (talk size exactly 1,050, every list at its longest, partial with the longest label), unicode and emoji (CJK, Arabic, joiners, a variation selector), awkward punctuation (curly quotes, dashes, `C#`, `#1`, `<3`, `a > b`), every optional field null or empty, partial coverage, unknown speaker, newer minor 1.4 with unknown members |
| Must fail (29) | newer major 2.0; an unknown member at 1.3; a missing field; a missing nullable field; the wrong format name; no version; three quotes; an impossible date; an http link; a private address; over the visible cap; over the talk size; markdown bold, link and bullet; code marks; an app label; the rules label; an instruction; an HTML tag; an address in a quote; a line break; a model brief without a model, with three claims; partial without a note; no claims; a trailing comma; a key written twice; over 8,000 bytes |

To change the contract: edit the rule in `src/pea_knowledge/validate.py` (and `contract.py`), add or change cases in
`make_golden.py`, run it, then sync the app (`python3 tools/brief_contract/sync.py` in the app repo) and port the rule
to its reader in the same change.

## Checking real briefs

`python3 -m pea_knowledge check-briefs <folder or files> -v` runs the strict check over any brief output (a `dist/`
folder, a downloaded copy of the published catalog, or the briefs a dry run or a spike wrote) and prints the visible
and talk sizes. No network, no key.

## First real briefs: a one-time checklist

State on 2026-11-19: the owner has added the `OPENROUTER_API_KEY` repository secret and verified the writer model id
`anthropic/claude-haiku-5.5`. `briefs.enabled` is already true and `brief_budget` caps spend at 100 US cents per run
and 200 per month (config/sources.json). Real briefs start with the first scheduled run of a `main` that carries the
brief pipeline: `briefs-pipeline` and this `brief-contract` branch are not on `main` yet (pushing and merging is the
owner's step). Before that run, glance at `briefs.price_per_million_input_usd` and `..._output_usd` in
config/sources.json (0.10 and 0.50 today): the cost caps are computed from the provider's reported cost when it
gives one, but the dry run's estimates use these prices.

When the first scheduled run with the key has published:

1. In the run's summary, `briefs`: `key` true, `written` above 0, `fell_back` low, `month_cents` under the cap, `flags` noted.
2. The publish job's "The brief contract" step passed (it stops the publish otherwise).
3. Download the published catalog into a folder (`python3 -m pea_knowledge restore --url <pages url> --out real`) and
   run `python3 -m pea_knowledge check-briefs real -v`: every brief passes; note the largest talk size.
4. Read three model briefs against their episodes: claims supported, hedges kept, speakers right (the phase 1 rules).
5. Copy two or three real briefs (one long, one partial if any) into `make_golden.py` as new must-pass cases, run it,
   and sync the app. Bump nothing else.
6. In the app: `PEA_ONLY=briefcontract bash build.sh --check` and the `briefs` suite once on the simulator with the
   real catalog (tools/harness/real_catalog.py).
