# The PEA knowledge format, version 1.3

This is the one format the PEA knowledge processor writes and the PEA iPhone app reads. A curated list of sources goes in; a folder of static files comes out. The app never reads a publisher's feed: it reads this, and it checks every file before it uses it. The one thing it may fetch from a publisher is the transcript an item points to (`transcript_source`, section 6), when the owner wants the whole text.

The format exists for one purpose: so that the assistant can hold a natural conversation about any item and suggest things to talk about, and always gets the data it expects in the shape it expects. It is not an archive format.

Nothing in it is specific to one show. A source is a listing plus items; an item is a digest plus, where the publisher's terms allow, a transcript.

The key words MUST, MUST NOT, SHOULD and MAY are used as in RFC 2119.

## 1. The files

```
store.json                                   the store listing: every source as a card, its state, the hash of its items file
sources/<source>/items.json                  one source's items, newest first, with the hash and size of every file
sources/<source>/<item>.digest.json          one item's digest: everything needed to talk about it
sources/<source>/<item>.brief.json           one item's brief (1.3): a short fixed-shape summary for search and talk
sources/<source>/<item>.transcript.pea.txt   one item's transcript (PEA transcript v1), only where the terms allow
briefs-index.json                            the shows the output holds briefs for and their newest briefs (1.3, additive, section 13)
health.json                                  what the last run did (for the curator; an app does not need it)
state.json                                   the pipeline's memory between runs (an app MUST NOT fetch or use it)
```

Published at `https://gptkiosk.github.io/pea-knowledge-processor/`, so the entry point is `https://gptkiosk.github.io/pea-knowledge-processor/store.json`.

A reader starts at `store.json` and follows hashes: the listing names each source's items file with its SHA-256 and size; the items file names each digest and transcript with theirs. A file that does not match what named it is not used.

Why the split: the store screen needs only `store.json` (about 43 KB for thirteen listings, 12 KB of it the vocabulary of topics). A source's items are loaded only after the owner adds that source. `items.json` carries no time of its own, so its hash changes only when an item changes; a run that finds nothing new changes only `generated_at` in `store.json` and the counters in `health.json`.

JSON Schemas (draft 2020-12) are in `schema/`: `store`, `items`, `digest`, `brief`, `briefs-index`, `health`, `state`, and `sources` for the curated list. The schemas, plus the rules of sections 7 to 9 and 11 that a schema cannot state, are the format. `python3 -m pea_knowledge validate <folder>` checks all of it and is the reference for the app's checks.

All JSON is UTF-8 without a byte order mark, keys sorted, two spaces of indent, one line break at the end. The same data always gives the same bytes. The one exception is `briefs-index.json`, written without indent or spaces (keys still sorted) so that it stays small.

## 2. store.json: the store listing

| Member | What it is for |
| --- | --- |
| `format`, `format_version` | `"pea-knowledge-store"`, `"1.3"`. See section 8. |
| `generated_at` | When this output was built (UTC, `YYYY-MM-DDTHH:MM:SSZ`). |
| `generator` | The program and version that wrote it. |
| `min_app_version` | The oldest app version that should read this output, or null. An older app keeps what it has and asks for an update. |
| `sources` | One listing per source, in the curator's order. |
| `topics` (1.2) | The controlled vocabulary of topics, the same for every source: at most 40 entries, each `id`, `label` (40), `synonyms` (12) and `description` (120). The only ids a `topics` member anywhere in the output may hold. Section 11. |

Each listing:

| Member | What it is for |
| --- | --- |
| `id`, `name` | The source. The id never changes and is safe in a path. |
| `description` (200) | The store card: what the owner gets. |
| `overview` (600) | For the assistant: what the source is, its beat and voice, and how an item is usually built, so she can talk about the source itself. |
| `categories`, `language`, `kind` | Browsing and filtering. `kind` is `podcast` or `news`. `categories` are the curator's free words for one source; for anything across sources use `topics`. |
| `topics` (1.2) | The source's overall beat: up to six ids of the vocabulary, most typical first. What an item without topics of its own falls back to. Section 11. |
| `publisher`, `site` | Who makes it and where. `site` is one of the two kinds of address the format allows. |
| `icon` | A symbol name and a colour name from fixed lists. The format carries no images, so nothing third-party is ever hosted. |
| `cadence`, `typical_duration_seconds` | How often items come and how long they usually are, measured from the listed items. |
| `publish` | `full` (transcripts are in the output) or `digest_only`. |
| `terms_summary` (300), `attribution` (160) | What the publisher's terms were found to allow, and the credit line to show. |
| `state`, `state_reason`, `message` (240), `purge`, `state_since` | The lifecycle. Section 5. |
| `freshness` | `fresh`, or `stale` with `last_ok` and the number of failed runs in a row. |
| `item_count`, `latest_titles` (3), `latest_date`, `whats_new` (240) | So the card shows what is current without a second download. `whats_new` is one line on the newest item and the one before it. |
| `available` | How many items have a digest, how many have a transcript file, and that each links back. Every item listed is discussable, so `available.digest` equals `item_count`. |
| `avg_bytes`, `suggested_keep` | The typical size of one item and how many the curator suggests keeping on the device. Suggestions only: the owner decides (docs/APP-CONTRACT.md, "Keeping items on the device"). |
| `items_file` | Path, SHA-256 and size of the items file. Null when the source has no items or is withdrawn. |

## 3. items.json: one source's items

`format` is `"pea-knowledge-items"`. `source_id` must be the listing's id. `items` is newest first. Each item:

**Only discussable items are listed** (generator 0.5.0, 2026-11-15; the format stays 1.2 and no member was added). A podcast with only headlines or short show notes is not a useful source: an assistant can say little about it beyond the digest's cursory points. An item is listed only when the assistant has a full path to the whole text, that is when (1) the pipeline read the item's transcript in full or in part (`transcript.read` is `full` or `partial`) and (2) the item carries `transcript_source`, the publisher's own address of the whole text. An item whose transcript is not published, could not be fetched, could not be read, or was read but gives no address is left out: it has no digest file, it is not counted in `item_count` or `available`, and an app never sees it. For the newest discussable item of the source the address has also passed the phone-style probe (section 10). **Absence from `items.json` means not discussable.** A reader may therefore offer every item it sees; an older output (generator before 0.5.0) may still list items with `read: none` or without `transcript_source`, and a defensive reader skips those. The curator sees what was left out, counted by reason, in `health.json` (section 10).

| Member | What it is for |
| --- | --- |
| `id` | Unique in the source and stable across runs: the date and ten characters of a hash of the publisher's own identifier (its guid; without one, the item's own page). It never depends on a fallback link. |
| `title`, `date`, `duration_seconds`, `tags` | What the item is. |
| `link` | The publisher's page for it: where to send the owner for the original. The other kind of address the format allows. |
| `link_kind` (1.1) | `episode`: `link` is the publisher's page for this one item. `show`: the publisher gives no page per item, so `link` is the show's site. Absent in a 1.0 file: treat as `episode`. |
| `teaser` (240) | One or two sentences, so the assistant can propose the item without opening its digest. |
| `stale`, `stale_reason` | True when the last attempt to refresh this item failed and its files are from an earlier run. |
| `bytes` | The size of the item's files together, for the storage choice. |
| `digest` | Path, SHA-256, size, and what kind of digest it is (`basis`, `grade`, `method`), repeated from the file so a reader can choose without opening it. |
| `transcript` | `available`: `yes`, `partial` or `no`; `reason`; `file` (path, SHA-256, size) or null. Since 1.1 also `read`: what the pipeline read at the publisher to make the digest (`full`, `partial`, `none`), whether or not the file is published. |
| `topics`, `topics_by` (1.2) | What the item is about: up to four `{"id", "score"}`, best first, ids of the vocabulary in `store.json` only; and how they were made, `keywords` or `model`. Optional, always together. An empty list means no topic was confident enough. Section 11. |
| `brief` (1.3) | Optional; present on every item of an output from generator 0.6.0 on. The item's brief file: `path`, `sha256`, `bytes`, and `kind` (`model` or `extractive`) and `covers` (`whole` or `partial`), repeated from the file so a reader can choose without opening it. **The brief's size is not counted in `bytes`**: `bytes` stays the digest plus the transcript, so a 1.2 reader's check of it still holds; the item's whole size is `bytes` plus `brief.bytes`. Section 12. |
| `transcript_source` | Since 1.1, optional. Where the publisher itself offers this item's transcript: `link`, `format`, `route`, `bytes`, and `extract` for an HTML page. Present on every item of an output from generator 0.5.0 on (it is what makes the item discussable). Section 6 describes it. |

Transcript reasons are typed:

| `available` | `reason` | Meaning |
| --- | --- | --- |
| `yes` | null | The whole transcript is in the output. |
| `partial` | `cut` | Its first part is; the file says where it stops. |
| `no` | `none_published` | The publisher lists no transcript, or its page for the episode holds none. |
| `no` | `fetch_failed` | One is listed but could not be fetched. It is asked for again on the next run. |
| `no` | `unreadable` | It arrived but is not a transcript the converter can read: a file of another kind, or a web page with too little text or a sign-in, paywall, cookie or robot-check page. |
| `no` | `withheld_terms` | Read by the pipeline, not republished: the digest was made from it, and the publisher's terms do not clearly allow republishing it. A reader that wants the whole text reads it from the publisher (`transcript_source`). |

Every item has a digest. An item never depends on a second download to be talked about: the digest repeats the title, date, link and source name.

## 4. The digest

`format` is `"pea-knowledge-digest"`. It is built for conversation. Each member below says what it is for.

| Member | Limit | What it is for in the conversation |
| --- | --- | --- |
| `source_id`, `source_name`, `item_id`, `title`, `date`, `link`, `link_kind` (1.1), `language`, `duration_seconds` | | What is being talked about, and where to send the owner. Never taken from a transcript or a model. |
| `basis` | | What the digest was made from: `transcript`, `notes` (the publisher's show notes) or `headline` (title and short description). The assistant says which. |
| `about` | 400 | The framing: what this is about in plain spoken sentences. What she says first. |
| `brief` | 900 in all | The compact form: the framing, up to three points (first, middle, last, so it still reads as a story), one short quote, one hook. For when one or two digests must fit in a prompt. Always built from the full form, so it never says anything the full form does not. |
| `talking_points` | 8 | The story in order. Each has `point` (280, one or two sentences), `why` it matters (200, or null), `at` (a pointer, below) and `ask` (160, a question worth asking, or null). A whole digest has five to eight. |
| `quotes` | 5 | Short notable quotes: `text` (240), `speaker`, `at`, and `exact`. `exact: true` means the text is, character for character, in the transcript segment `at` points to. Only then may she present it as a quotation. |
| `glossary` | 14 | The people, organisations and products that come up: `term`, `kind` (`person`, `organisation`, `product`, `other`) and a one-line `gloss` (140, or null), so she does not have to guess what a name means. |
| `numbers` | 6 | The figures that matter: `value` as written, `context` (200), `at`. |
| `background` | 400 | What a listener needs to know beforehand, or null. |
| `strongest_claim` | 280 | The strongest claim the item makes, with a pointer, or null. |
| `contested` | 3 × 200 | What is uncertain or disputed, so she does not state it as settled. |
| `connections` | 3 | Earlier items of the same source this one continues: `item_id` and `why` (120). A reader ignores an id it does not have. |
| `starters` | 3 × 160 | Things she can offer to open with. |
| `follow_ups` | 3 × 160 | Questions she can offer next. |
| `guests` (1.1) | 6 | Who the guest is: `name` (80) and `role` (140, or null). A name comes from the publisher's own marks (`podcast:person`), title or notes; a role is a piece of the notes or the transcript, word for word. Nothing is made up to fill it. |
| `mentioned_resources` (1.1) | 8 | Books, papers, tools, products and sites that are named: `name` (80), `kind` (`book`, `paper`, `tool`, `product`, `site`, `media`, `other`), `context` (140, or null) and `at`. **Names only.** The format carries no address here, also when the publisher's notes link the name: rule T3 holds for these texts as for all others, and a name that reads as a domain is dropped. |
| `chapters` (1.1) | 20 | The parts of the item in order of time: `title` (100), `start_seconds`, `end_seconds` (or null), `segment` (or null) and `origin`: `publisher` (the publisher's own chapter marks: `psc:chapter`, a `podcast:chapters` file, or lines in the notes that start with a time), `transcript` (cut from a timed transcript, one per talking point, titled with the opening words of that point) or `model` (titled by the model at the start of a transcript line). |
| `snippable_moments` (1.1) | 5 | Passages worth keeping, best first, for the app's snips: `quote` (240), `speaker`, `at`, `end_seconds` (or null), `label` (100: the publisher's own title when it marks the passage as a soundbite, else null). Every quote is, character for character, in the transcript segment `at` points to. Only in a digest made from a transcript. |
| `recap_cards` (1.1) | 3 | Question and answer pairs for a daily recap: `question` (140), `answer` (200). Always built by the processor from text the digest already holds, never taken from a model, so a card says nothing the digest does not. |
| `tone` | | A register hint: `news`, `analysis`, `technical`, `interview`, `conversational`, `light`, `unknown`. |
| `provenance` | | `method` (`extractive` or `model`), `model` (its id, or null), `transcript_sha256` (of the normalized transcript, or null). |
| `quality` | | `grade` and up to six plain `notes` on the digest's limits. |

**Pointers.** `at` is `{"time_seconds", "segment"}`. `segment` is the number of the transcript segment (0 is the first line after the header of the `.transcript.pea.txt` file); `time_seconds` is that segment's time. When the transcript is published, a reader opens it at `segment` to drill in. When it is not, `time_seconds` still tells the owner where to listen. Both are null when there is nothing to point at.

**Grades.** `full`: from a whole transcript, with at least five talking points. `partial`: from a cut transcript, from show notes, or with fewer points. `headline`: title and short description only. News items are always `headline`: the article text is never republished, so the assistant has the headline, a description of at most 280 characters and the link.

**Two ways a digest is made.** The extractive digest uses no model: points, quotes and glosses are sentences already in the transcript, `why` is null, names and their kinds are found by pattern and may be wrong. Its `quality.notes` say so. The model digest (optional) writes `why`, glosses and background in its own words; every quote, name, figure and time in it is checked against the transcript first (section 7).

**Size.** A digest file is at most 24,000 bytes, as in 1.0; a typical one is 8 to 12 KB with the 1.1 members. When a digest would be larger, what 1.1 added gives way first. The brief form is at most 900 characters of text, so two fit in an evidence budget of about 3,200 characters with room for labels.

### What 1.1 adds

Format 1.1 adds only optional members: `link_kind`, `transcript.read` and (since 2026-11-15) `transcript_source` in `items.json`, and `link_kind`, `guests`, `mentioned_resources`, `chapters`, `snippable_moments` and `recap_cards` in a digest. No member of 1.0 changed, no limit grew, no enumeration of 1.0 gained a value. A reader of 1.0 reads a 1.1 file by the rule of section 8: it ignores the members it does not know and still checks every text in the file against T1 to T4.

Where each comes from, without a model: guests from the publisher's marks, title and notes; resources from the names the notes link to (with a transcript, only those that are also said, each with the time it is first said) and from what a speaker introduces as "a book called ..."; chapters from the publisher's marks, else from the timed transcript; moments from the quotes, the strongest claim and the talking points the digest already holds, so they take no further words from a transcript that may not be republished; recap cards from the digest. From the example below:

```json
"link_kind": "episode",
"guests": [{"name": "Tobias Renn", "role": "keeper of the Grey Point lighthouse"}],
"mentioned_resources": [{"name": "the Wren", "kind": "other", "context": "Tobias Renn, keeper of the Grey Point lighthouse, reads from the ledger; its first entry is a coal barge, the Wren.", "at": {"time_seconds": 98, "segment": 5}}],
"chapters": [{"title": "Welcome to Grey Point", "start_seconds": 0, "end_seconds": 84, "segment": 0, "origin": "publisher"},
             {"title": "The keeper's ledger", "start_seconds": 84, "end_seconds": 252, "segment": 4, "origin": "publisher"}],
"snippable_moments": [{"quote": "The port records count tonnage, but the ledger records weather, crews and who was late and why.", "speaker": "Tobias",
                       "at": {"time_seconds": 126, "segment": 7}, "end_seconds": 154, "label": "What the ledger records"}],
"recap_cards": [{"question": "Who is the guest?", "answer": "Tobias Renn, keeper of the Grey Point lighthouse"}]
```

### A worked example

From `tests/golden/dist` (a made-up show), shortened:

```json
{
  "title": "The keeper's ledger, read aloud",
  "source_name": "Tide Tables", "date": "2026-11-12", "link": "https://tide.example.org/episodes/6",
  "basis": "transcript",
  "about": "The Grey Point Trust voted on it in March, and the old lamp won by 36 votes to nine. An electric lamp would have cost the Trust 120 thousand dollars before a single night of light.",
  "talking_points": [
    {"point": "Last winter the ledger showed 52 ships turning back at the bar, twice the number of the year before.",
     "why": null, "at": {"time_seconds": 126, "segment": 7},
     "ask": "Why does it matter to a fishing family in the town whether the count is forty or eighty?"}
  ],
  "quotes": [
    {"text": "The port records count tonnage, but the ledger records weather, crews and who was late and why.",
     "speaker": "Tobias", "at": {"time_seconds": 126, "segment": 7}, "exact": true}
  ],
  "glossary": [
    {"term": "Harbour Board", "kind": "organisation", "gloss": "The Harbour Board reportedly disputes that count and says its own radar logs show far fewer."}
  ],
  "numbers": [{"value": "66 percent", "context": "The Northwind Cooperative lands about 66 percent of the fish sold at the Saturday market.", "at": {"time_seconds": 224, "segment": 12}}],
  "contested": ["It is unclear whose count is right, because the radar at North Quay was down for most of January."],
  "connections": [{"item_id": "2026-11-09-8e6fef9855", "why": "also about North Quay"}],
  "starters": ["What was said about Harbour Board", "The figure 66 percent and where it comes from"],
  "tone": "conversational",
  "provenance": {"method": "extractive", "model": null, "transcript_sha256": "fa717b43..."},
  "quality": {"grade": "full", "notes": ["made without a model: points and glosses are sentences from the transcript; 'why' is not written"]}
}
```

How a conversation uses it. The owner says "what's new on Tide Tables?" The assistant has the listing's `whats_new` and each item's `teaser`, so she can name the newest item and offer it. The owner says yes: she opens with `about`, then offers a `starter`. She walks the `talking_points` in order; where a point has an `ask`, she can put that question to the owner. Asked "who is the Harbour Board?", she answers from the `glossary`. Asked "did he really say that?", she reads a quote whose `exact` is true and gives its time. She says the ship count is disputed because `contested` says so. Asked for more than the digest holds, she opens the transcript at the `segment` a point names; if the transcript is not published, she says where in the episode it is and offers the `link`. This digest is extractive, so `why` is null and she does not invent one.

## 5. A source's lifecycle

Every listing has a `state`. It lets the curator switch a source off for every app with one commit, with no app update.

| `state` | Meaning | What the output holds |
| --- | --- | --- |
| `active` | Normal. `freshness.status` may still be `stale` after a failed run: the items are the last good ones. | The items. |
| `paused` | An outage, or the publisher changed its format, or the curator paused it. | The last good items, unchanged; `freshness.status` is `stale`; `message` says why in plain words. |
| `withdrawn` | Taken out on purpose (licence, a takedown request, quality, or removed from the list). | No items and no files. The listing stays as a notice for a set number of days (90 by default), then is dropped. |

`message` is a short plain sentence for the owner: text only, at most 240 characters, always present when the state is `paused` or `withdrawn`. `state_reason` is typed (`manual`, `fetch_failed`, `robots_disallowed`, `format_changed`, `empty`, `invalid_output`, `licence`, `takedown`, `quality`, `removed`) with one sentence of detail. `purge: true`, allowed only with `withdrawn`, means every app must delete its local copy of that source's items.

A source that is no longer in `store.json` at all is to be treated as withdrawn without purge and without a message.

How the pipeline sets it:

- A manual `state` in `config/sources.json` always wins.
- **Only sources with enough discussable items are carried.** Of a source's newest `transcript_check_items` items (5), at least `min_discussable_items` (2) **and** at least `min_full_transcript_share` (60 percent) must be discussable (section 3). This is one count and one rule: the older 60 percent rule is this rule, not a second one. A source that reads without trouble but falls short is counted as a source that cannot be read, with a detail that starts "full transcripts for": reason `empty` when none of its newest items is discussable and none ever was, `format_changed` when it used to have discussable items. So it keeps its last good items, is paused after the usual number of runs, and is withdrawn (reason `quality`) after `withdraw_without_transcripts_days` (30) in that pause. It is still read every run and returns by itself when its items are discussable again. A transcript that the pipeline itself cut at its size cap counts as read (`partial`). This is also how a source read from web pages is stopped when the site changes its markup: new episodes stop reading, the count falls, and the source is paused with its last good items. `min_full_transcript_share` 0 together with `min_discussable_items` 0 switches the rule off.
- **A publisher that refuses the app is not carried either.** The pipeline fetches with its own User-Agent and obeys robots.txt; the phone does neither, and some hosts refuse clients that are not browsers. So for the newest discussable item of each source one request is made the way the app makes it (section 10, "The phone-style probe"). When it fails, the source is counted as failed with reason `fetch_failed` and the detail "the publisher refuses requests like the app's" (and why), and then follows the same path: paused after the usual number of runs, withdrawn after 30 days, back by itself when the probe passes. An older item whose probe failed is left out of `items.json` while the source goes on.
- A source that cannot be read (fetch failed, robots.txt forbids it, the feed is not the expected shape, or its new output does not validate) keeps its last good items and is marked stale. After `auto_pause_after_failed_runs` failures in a row (3 by default) it becomes `paused` with a typed reason. It is still tried every run, and returns to `active` by itself when it reads again.
- A source whose new output does not validate is never published; its last good copy is. The other sources publish as usual.
- A source set to `withdrawn`, or removed from the config, gets a withdrawn listing with no items for `tombstone_days`, then disappears.

`tests/golden/lifecycle/` has `store.json` after each of these changes.

## 6. Transcripts

A transcript in the output is a PEA transcript v1 file, exactly as specified in `spec/transcript-v1/SPEC.md` (a copy of the open specification with its schema, tools and fixtures). The processor adds nothing to that format. A reader validates the file by that specification's writer rules and treats its text as untrusted (its section 14).

A transcript is published only for a source whose `publish` is `full`. The default is `digest_only`.

### Where the publisher offers the transcript: `transcript_source`

No source permits republishing its transcripts, so the output carries none of them. An item instead says where the publisher itself offers the transcript, so that a reader (the app) can fetch it there, normalize it on the device and keep it. Nothing is hosted here.

```json
"transcript_source": {
  "link": "https://talkpython.fm/episodes/show/568/cloudflare-python-workers.vtt",
  "format": "vtt",
  "route": "feed_tag",
  "bytes": 140451
}
```

| Member | Meaning |
| --- | --- |
| `link` | The publisher's own public https address of the transcript, as its feed or site gives it. It is named `link` because `site` and `link` are the only members of the format that may hold an address (rule T3); it is checked like every `link`: https, port 443, a public host name, no credentials. |
| `format` | `vtt`, `srt`, `json` (Podcasting 2.0), `text`, `markdown` or `html`. What the pipeline found there, not what the publisher declared. |
| `route` | How the address was found: `feed_tag` (the publisher's feed or index lists it for this item), `notes_link` (the item's notes link to it), `page` (it is the item's page, or follows from it). |
| `bytes` | The size of what the pipeline read, after decompression, or null. A hint for showing a size; never more than 1,500,000. |
| `extract` | Only with `html`: which elements of the page hold the transcript (below). |

- The member is present exactly when the pipeline read a transcript at that address in this run or an earlier one, without signing in (`transcript.read` is `full` or `partial`). It is absent when none is offered (`none_published`), when it could not be fetched or read, and for news.
- It changes nothing else: `publish` stays `digest_only`, `transcript.available` stays `no` with `withheld_terms`, and the digest is complete without it.
- **Privacy.** A reader that fetches `link` talks to the publisher directly: the publisher (or its file host) sees the device's network address and that it asked for this episode's transcript, as with any podcast app that downloads an episode. Nothing else is sent: no cookie, no account, no identifier, no referrer.
- The address and what comes back are untrusted. A reader checks the address by the rules of `link`, follows redirects only to public https addresses, reads at most 1,500,000 bytes, and treats the text as quoted data (section 7). When anything fails it carries on with the digest.
- The pipeline's own copy is cut at 150,000 characters of speech (`read: partial`); the publisher's file may be longer.

### Reading an HTML transcript page

Some publishers post the transcript as a web page. `extract` says which elements to read, as lists of simple selectors: `tag`, `.class`, `#id`, `tag.class` or `tag#id` (one tag name, one class or id, nothing else). It is data; it is never code, and a reader MUST NOT treat it as anything else.

```json
"transcript_source": {
  "link": "https://lexfridman.com/preston-stewart-michael-kofman-transcript",
  "format": "html",
  "route": "notes_link",
  "bytes": 343790,
  "extract": {"row": [".ts-segment"], "speaker": [".ts-name"], "time": [".ts-timestamp"]}
}
```

| Member of `extract` | Meaning |
| --- | --- |
| `within` | The elements that hold the transcript. Only text inside one of them is read. |
| `row` | The element of one turn: one speaker, one time, their text. Without `within`, only text inside a row is read. |
| `speaker` | Elements whose text is the speaker's name ("Mara", "Mara (00:01:23)"). The name holds for what follows until the next one, or until the row ends. |
| `time` | Elements whose text holds a time ("(00:09:39)", "9:39"). It is the time of the text that follows. |
| `drop` | Elements left out, beyond what is always left out. |

The reference is `src/pea_knowledge/htmlpage.py`; `tests/test_htmlpage.py` and the pages under `tests/fixtures/web/lamp/` show each case. The steps:

1. Nothing is executed and nothing more is fetched: no script, no style sheet, no frame, no image.
2. One pass over the markup. Comments, declarations and the content of `script`, `style`, `template`, `noscript`, `iframe`, `svg`, `math`, `textarea`, `select`, `title`, `object`, `canvas`, `audio` and `video` are skipped. A `<` that starts no tag is a character. A tag that never ends takes the rest of the page with it.
3. An element and everything in it is dropped when it is `head`, `nav`, `header`, `footer`, `aside`, `form`, `button`, `figure`, `figcaption`, a heading, `label`, `dialog`, `menu`, `summary`, `del`, `s` or `map`; when it is hidden (`hidden`, `aria-hidden="true"`, an inline style with `display:none`, `visibility:hidden`, `opacity:0`, `font-size:0`, a large negative offset, a zero clip or a transparent colour, or a class such as `hidden`, `sr-only`, `visually-hidden`, `screen-reader-text`, `d-none`); when a `drop` selector names it; or, unless `within` or `row` names it, when its class or id is one of the usual names for advertising, sharing, comments and tables of contents, or a style sheet in the page hides that class or id.
4. Block elements (`p`, `div`, `li`, `dt`, `dd`, `tr`, `blockquote`, `section`, a row, and `br`) end a block of text. Inline elements add nothing. Entities are decoded once; `<` and `>` that remain are written as single guillemets, so the text can never be read as markup.
5. With `extract`, the blocks inside `within` (or inside the rows) are the transcript; each takes the speaker and time its row or the marks before it state. Without `extract`, `cite` and `dt` are speakers and `time` is a time; the transcript is the innermost element whose id or class contains "transcript" and that still holds at least four fifths of such text, and failing that an `article`, `main` or the body, but then only when the text reads like a transcript (speaker labels or times throughout).
6. Where the page marks no speakers, they are read from the text: a paragraph that starts "Lex Fridman: (00:01:23) ..." or "Lex Fridman (00:01:23) ...", or the label rule of PEA transcript v1 ("MARA: ..." on at least two lines), and times in brackets inside a line.
7. From there on the page is treated like any other transcript: caption clean-up, segments of one speaker, the sponsor rule, the size cap with its cut mark. The file says `format: HTML page`.
8. Refusals, never a part of a page: fewer than 1,500 characters of transcript text, or fewer than 150 per minute of the episode's stated length, is `unreadable`; so is a transcript inside an element whose class or id says paywall, and a short page that asks to sign in, subscribe, accept cookies or prove one is not a robot; a page where no transcript block is found is `none_published`. A page that takes more than ten seconds to read is `unreadable`.

## 7. Hostile input

Everything a publisher wrote is untrusted data: titles, descriptions, show notes, transcripts. So is everything a model wrote. The format is built so that none of it can change what a reader does.

**Rules every text member obeys** (a reader MUST check them and refuse a file that breaks one, with reason `text_rule`):

- T1. No control characters, no line breaks, no line or paragraph separators, no characters that reorder or hide text (U+202A to U+202E, U+2066 to U+2069, U+FEFF).
- T2. Nothing that reads as an HTML or XML tag, comment or declaration.
- T3. No address: no scheme followed by `://`, no word starting with `www.`, no `mailto:`, `javascript:`, `data:`, `tel:` or `sms:` link.
- T4. One line, trimmed, single spaces.

**Addresses.** The only addresses in the format are `site` (in a listing) and `link` (in an item and its digest). Each MUST be a normalized public https address: no credentials, port 443, a real public host name (not a number, not `localhost`, not a private suffix). A reader refuses anything else with reason `address`. A reader shows `link` to the owner and opens it only when the owner asks.

**Structure.** Every member has a type, every string a length limit, every list a count limit, every file a size limit (section 9). Enumerations are closed. Paths are fixed by rule: a file must be exactly where its source and item ids put it, so no path in the format can point outside the folder.

**JSON.** Strict: UTF-8, no byte order mark, no NaN or Infinity, no number too large for a float, no key written twice.

**Instructions.** Text in this format is material to describe, never instructions to follow. That is a rule for readers: the app puts digest text into a prompt as quoted evidence, never as part of its own instructions. As one more layer, the processor does not pick a sentence addressed to "the assistant" (ignore previous instructions, a new system prompt, reveal your prompt) for a digest, and drops such a field from a model's answer. This layer is a pattern and can be evaded; the defence is the fixed structure and the reader's rule. The validator does not judge wording, because an AI news show talks about prompt injection all the time.

**What the model path adds** (`src/pea_knowledge/model_digest.py`): the call has no tools; a guest must be named in the transcript, the notes or the title, and a role must be a piece of them word for word; a mentioned resource must be named in the transcript, takes its time from there, and never carries an address; a chapter must start where a transcript line starts, later than the one before; a moment is checked like a quote; recap cards are never read from the answer. Further: the answer must be one JSON object; only known members are read, each through its own check; what identifies the item never comes from the model; a quote must be found character for character in a transcript segment or it is dropped, and its time and speaker are taken from the transcript; a time the model gives must be the start of a segment or it is dropped; a name or figure must occur in the transcript or it is dropped; text that breaks T1 to T4 is dropped, not repaired; fewer than five valid talking points, or no valid framing, means the extractive digest is used instead.

**What the processor does to publisher text** before it becomes a text member: script and style blocks out, tags out, entities decoded, tags out again, addresses out, forbidden characters out, spaces collapsed, cut to the limit. Each step is one pass, so no input makes it slow.

## 8. Versions and compatibility

`format_version` is `MAJOR.MINOR`, and every JSON file carries it.

- **Within a major version, changes are additive only**: new optional members, new files. No member is removed or renamed, no type or meaning changes, no limit grows, no enumeration gains a value a reader must act on. A new enumeration value needs a new major version, because the enumerations are closed.
- **1.1 (2026-11-15)** added the members listed under "What 1.1 adds". A reason a source is paused for want of transcripts uses the existing code `format_changed`: a code of its own would be a new enumeration value, which needs 2.0.
- **1.2 (2026-11-15)** added topics (section 11): `topics` at the top of `store.json`, `topics` in a listing, and `topics` with `topics_by` on an item. All optional; nothing else changed. A digest is as in 1.1, except that it says 1.2. Why not within 1.1: a reader whose known minor is 1 holds a 1.1 file to the letter, so a new member in a file that still said 1.1 would have been refused as `schema`. A file that says 1.2 is read by that same reader with the new members ignored. A reader that wants topics raises its known minor to 2 and takes the 1.2 schemas.
- **1.3 (2026-11-17)** added briefs (section 12): a new file per item, `sources/<source>/<item>.brief.json`, named by an optional `brief` member of the item in `items.json`, and optional `briefs` members in `health.json` and `state.json`. Nothing else changed; every file says 1.3. A 1.2 reader ignores `brief` on an item (a newer minor) and never fetches the brief file; `bytes` keeps its meaning, so its cross-check still holds. A reader that wants briefs raises its known minor to 3 and takes the 1.3 `items` and `brief` schemas.
- **A reader accepts every file whose major it knows.** When the file's minor is newer than the reader's, the reader ignores members it does not know. When the minor is the reader's own or older, an unknown member is an error (`schema`): at the same version the writer is held to the letter.
- **A reader refuses a major it does not know** with reason `unsupported_version`, keeps what it has, and tells the owner an update is needed.
- `min_app_version` lets the curator say "this output needs at least this app" before a major change arrives.
- The transcript format has its own version line (`PEA-TRANSCRIPT v1`) and its own rules.

## 9. How a reader verifies a file

Limits, refused unread when exceeded (`too_large`): `store.json` 512,000 bytes; `items.json` 512,000; a digest 24,000; a brief 8,000; a transcript 1,000,000.

In order, for each file:

1. Size against the limit, then against the size its index entry states (`size_mismatch`), then SHA-256 against the entry (`hash_mismatch`). `store.json` has no entry: it is the root.
2. Strict JSON (`not_json`), `format_version` (`unsupported_version`), the schema (`schema`), the text rules (`text_rule`), the addresses (`address`).
3. The cross-checks of that file:
   - `store.json`: ids unique; topic ids unique, and every topic a source names is in the vocabulary of the same file (`inconsistent`); an items file is at `sources/<id>/items.json` (`path_invalid`); a withdrawn source lists nothing; a paused or withdrawn source has a message, a reason and a time; `purge` only with `withdrawn`; `item_count` and `items_file` agree; a paused source is stale (`inconsistent`).
   - `items.json`: `source_id` is the listing's (`identity_mismatch`); the count is the listing's; ids unique; each file is at `sources/<source>/<item>.digest.json` or `.transcript.pea.txt` (`path_invalid`); `bytes` is the sum; `available`, `reason` and `file` agree; no transcript file in a `digest_only` source; a `transcript_source` only on an item whose transcript was read, with `extract` exactly when its format is `html`; `topics` and `topics_by` together or not at all, every topic id in the vocabulary of the `store.json` that named the file, no id twice, scores with at most two decimals and best first; newest first (`inconsistent`). `transcript_source.link` is checked as an address (`address`).
   - a brief (1.3): source, source name, item, title, date and link are those of the index, and `brief_kind` and `covers` those of the item's `brief` (`identity_mismatch`); the visible text is within 1,800 characters and the talk size within 1,050 (`brief_too_long`); the date exists (`schema`); at least one claim (`inconsistent`); no markup, app label or instruction in an authored text (`text_rule`; contract/README.md); a `model` brief names its model, has at least four claims each with a ref, and a `new`; an `extractive` one has no model; a `partial` brief has a `covers_note` and a `whole` one none; every topic is in the vocabulary of the `store.json`; when the transcript is in the output, every ref names one of its lines and every quote is in it (`inconsistent`). The brief is at `sources/<source>/<item>.brief.json` (`path_invalid`).
   - a transcript: conforms to PEA transcript v1 (`transcript_invalid`); cut or not as the index says.
   - a digest: source, item, title, date, link, duration, basis, grade and method are those of the index (`identity_mismatch`); the brief form is within 900 characters (`brief_too_long`); no quotes and no moments without a transcript basis; chapters in order of time and not overlapping; `link_kind` as in the index; when the transcript is in the output, `transcript_sha256` is its hash, every pointer names a segment it has, and every `exact` quote and every moment is in the segment it points to (`inconsistent`).

A file with any problem is not used, and the typed reason is kept for the owner and for diagnostics. `tests/golden/hostile/` has files a reader must refuse, with the reason for each in `manifest.json`.

## 10. health.json

For the curator. `mode` (`live` or `offline`), `briefs` (1.3: whether model briefs were asked for and a key given, the model, calls, briefs written, reused from the cache, retried, fallen back, stopped by a cap and kept extractive by terms, tokens, this run's spend and the month's in US cents against both caps, the briefs in the output by kind, the count of flags, and a note), what the model cost (`calls`, `accepted`, `fell_back`, `skipped_for_budget`, tokens, `cost_usd`), and per source: what the run did (`ok`, `unchanged`, `failed`, `skipped`, `removed`), the state, the reason, how many items are new, reused, kept, stale and pruned, transcripts by outcome (of the listed items), digests by method, `dropped`, `phone_probe`, and plain notes (skipped entries, a feed that changed shape, a transcript that could not be refreshed, the first few items that were left out).

- `dropped`: the items of the feed that are **not** in `items.json` because they are not discussable, counted by typed reason: `none_published` (no transcript is offered for the item), `fetch_failed` (the pipeline could not fetch it; asked again next run), `unreadable` (fetched, but not a transcript or too little text), `no_source` (read, but no address to fetch the whole text from) and `phone_probe` (the probe failed for it). They are not in `items`, `new` or any other counter. On a run that finds the feed unchanged the counts of the last run that read it are shown again.
- `phone_probe`: `null` when no probe ran this run (the feed was unchanged, nothing was discussable, the source failed first, or the probe is off: `phone_probe` false), otherwise `{"item", "result", "reason", "checked_at", "reused"}`. `result` is `ok` or `failed`; `reason` is `{"code", "detail"}` with a code of `refused` (401, 402, 403), `not_found`, `rate_limited`, `http_status` (anything else but 200), `timeout`, `network`, `content_type`, `too_large` or `unreadable`. `reused` is true when an ok result under 24 hours old (`phone_probe_reuse_hours`) for the same item and address was reused instead of asking again.

### The phone-style probe

For each source, after the rule of section 5 has passed, **one** request is made to `transcript_source.link` of the newest discussable item, with exactly the headers the app sends (`User-Agent: PEA/<app version> (a personal assistant app; reads public pages its owner asks for)` and the app's `Accept`; the constants are in `src/pea_knowledge/probe.py` with a pointer to the app's `PublicFetcher`), **without** reading robots.txt, with the app's time limits (10 seconds to answer, 25 in all), at most 4 redirects each checked as always, and at most 1,500,000 bytes. It passes only when the answer is a 200; has the type that the item's `format` is expected to be served as (`probe.EXPECTED_TYPES`: for example `text/vtt`, `text/plain` or a generic download for a `vtt` file, `text/html` for `html`); is not cut at the size cap; and converts with this repository's own converter (an `html` item with the page reader and the item's `extract`). It is one request per source per run, not retried, and an ok result is reused for 24 hours while the item and its address are unchanged. A probe is made only on a run that read the feed.

## 11. Topics

Since 1.2. Every item is tagged with topics from one controlled vocabulary, the same for every source, so that a reader can answer "I want to talk tech" (or politics, religion, wellness, supplements, leadership) with items from all the sources its owner follows. The tags cost nothing to make: they need no model.

### The vocabulary

`topics` at the top of `store.json`, from `config/topics.json`: about thirty topics in the curator's order.

```json
{"id": "supplements-nutrition", "label": "Supplements and nutrition",
 "synonyms": ["supplements", "vitamins", "nutrition", "diet", "food", "eating", "fasting", "protein", "healthy eating"],
 "description": "What people eat and take: diet, nutrients, vitamins, supplements and fasting."}
```

| Member | Meaning |
| --- | --- |
| `id` | Lower-case words joined by hyphens, at most 32 characters. It never changes once published; a new topic is added at the end. A topic that is retired leaves the vocabulary, and no item keeps its id. |
| `label` (40) | The name to show. |
| `synonyms` (12) | Plain lower-case words and phrases a person might say for the topic. A word may stand under more than one topic, on purpose: `investing` is both economics and startups. |
| `description` (120) | One line on what the topic covers. |

An id is valid only when the vocabulary of the same `store.json` has it. No text of a publisher or a model can add one: the tagger chooses among the ids, it never makes one.

The ids on 2026-11-15: `technology`, `ai`, `software-engineering`, `security-privacy`, `science`, `health`, `wellness`, `supplements-nutrition`, `fitness`, `mental-health`, `politics`, `policy-law`, `world-news`, `economics-finance`, `business`, `startups-investing`, `leadership-management`, `careers-work`, `religion-spirituality`, `philosophy`, `history`, `culture-media`, `education`, `relationships-family`, `creativity-writing`, `sports`, `environment-climate`, `crypto`, `self-improvement`, `podcasting-media`.

### How a reader turns a spoken word into ids

No model is needed. The reference is `resolve` in `src/pea_knowledge/topics.py`:

1. Every topic has names: its `id` with the hyphens as spaces, its `label`, and each of its `synonyms`.
2. Text is cut into words: lower case, a curly apostrophe read as a straight one, then every run of letters and digits (`[a-z0-9]+`, with one `'s`-like ending allowed). Each word loses its ending: everything from an apostrophe on; then `ies` becomes `y` (words longer than four letters); `sses`, `shes`, `ches`, `xes`, `zes` lose `es` (longer than four); otherwise a final `s` goes, unless the word ends in `ss`, `us` or `is` or has three letters or fewer. Nothing else is cut. Names and what was said are cut the same way, so "supplement" finds `supplements`.
3. Go through the words of what was said. At each word take the longest name (up to eight words) that starts there, add every topic that carries it, and go on after it. So "mental health" gives `mental-health` and not `health` as well.
4. The answer is those topics in the vocabulary's order. It may be several ("investing"), one ("tech" gives `technology`), or none: then the reader asks, or searches titles, and does not guess.

"I want to talk tech" gives `technology`; "faith" gives `religion-spirituality`; "parenting" gives `relationships-family`; "money" gives `economics-finance`; "careers" gives `careers-work`; "AI" gives `ai`.

### Topics on an item and on a source

```json
"topics": [{"id": "ai", "score": 0.85}, {"id": "economics-finance", "score": 0.81}],
"topics_by": "keywords"
```

- At most four, best first; ties in the vocabulary's order. `score` is a number from 0 to 1 with at most two decimals.
- **What a score means.** How strongly the item's own text points to the topic. It is a saturating count of evidence, not a probability: 0.5 is the least that is published and means "clearly there in the title or the notes"; around 0.7 the topic runs through the notes and the digest; 0.85 and more means the item is plainly about it. Scores of different items can be compared; a score never says how good an item is.
- **An empty list is an answer**: nothing was confident enough. A wrong tag is worse than a missing one, so the tagger stays silent when in doubt. A reader then falls back to the `topics` of the source, and says that this is the show's usual ground, not what this item is known to be about.
- `topics_by` says how the list was made, also when it is empty: `keywords` or `model` (below). A reader shows that honestly.
- An item written before 1.2 has neither member. A reader treats that like an empty list.
- A listing's `topics` are the curator's judgement of the source's beat, up to six ids. They are not computed from the items.

### How the keyword tagger works (`topics_by: keywords`)

Always on, deterministic, standard library only: the same item gives the same tags. `config/topic_lexicon.json` holds, per topic, words and phrases with a weight: 3 for a strong phrase ("clinical trial", "venture capital"), 2 for a clear word ("doctor", "investor"), 1 for a weak word that only counts beside others ("company", "story").

1. Four texts of the item are read: the title, the publisher's description and notes (without sponsor lines: a sentence that names a sponsor and the two after it), the digest's talking points, quotes and glossary, and the first 30,000 characters of the transcript without sponsor reads.
2. Each text is cut into words as above. At each word the longest phrase of the lexicon (up to four words) is taken, so "machine learning model" counts once, for AI. The lexicon also lists phrases that use a word in another sense ("in good faith", "role model", "third party", "to supplement", "price war", "version history"); they take their words with them and count for nothing. Bare words that mean too many things (model, party) are not counted at all.
3. A phrase counts its weight times the weight of the text (title 3, notes 2, digest 2, transcript 1) times the square root of how often it occurs there, at most five times. A weak word counts only in the title and the notes. A clear word counts in the transcript only when it is said at least twice.
4. A topic needs evidence: two different phrases, or one strong phrase (in the transcript: said three times). And it must show in the title, the notes or the digest, not only in passing talk.
5. The source's own topics add a small fixed amount to a topic that already has evidence. They are never a reason by themselves.
6. The sum becomes the score, sum / (sum + 18). A topic is kept when its score is at least 0.5 and either the title names it with a clear or strong phrase or its sum is at least 0.4 of the best topic's sum. The best four are published.

What it cannot do: it reads words, not meaning. It misses an item that never uses the usual words for its subject, and it can be wrong when an item spends many words on a side subject (a guest who owns a basketball team in an interview about business). Measured on 94 real items of the eleven live sources, labelled by hand (`tests/data/topics_labelled.json`, `python3 tests/eval_topics.py <output folder>`): about 96 percent of the tags given were right and about 94 percent of the main topics were found; README.md has the numbers. Those sources are mostly about technology, AI, software, podcasting, security and health; topics they rarely touch (sports, religion, fitness, education) are tested with made-up texts only.

### Topics from a model (`topics_by: model`)

Optional and off by default (`"model": {"topics": true}` in `config/sources.json`, on top of the model digest). The model that writes the digest is then shown the ids and labels of the vocabulary and may answer with up to four `{"id", "score"}`. Its answer is checked before anything is made of it:

- only an id of the vocabulary, each once; a score that is a number from 0.3 to 1;
- only a topic for which the title, the notes and the checked digest hold the evidence a keyword tag needs (two different phrases of the lexicon, or one strong one). The model decides which of the topics that the text bears out the item is about, and how much; it cannot tag an item with a topic its own digest does not mention, and text in a transcript that addresses the model cannot add an id;
- when nothing of the answer holds up, or there is no model digest, the keyword tagger decides and `topics_by` says `keywords`.

It costs about 500 tokens more per call, inside the same limits. Like the model digest, it is tested against a local stand-in only and has not been run against the real service.

### When the vocabulary or the lexicon changes

Every item is made anew on the next run (its key holds a hash of both files), so no item keeps a tag from an older version. An item kept from an earlier run for another reason loses any id the vocabulary no longer has. `"topics": {"enabled": false}` in the config switches topics off: no vocabulary, no topics anywhere.

## 12. Briefs (format 1.3)

A brief is one short summary of one item in a fixed shape, so an app can keep the briefs of many items on the phone, find the best two or three for what the owner asks by plain text search, and put them in a prompt with their source and date. **Every listed item has one** (from generator 0.6.0 on): a `model` brief where a model wrote one that passed every check, otherwise an `extractive` brief built from the item's digest.

| Member | Limit | What it is |
| --- | --- | --- |
| `format`, `format_version` | | `"pea-knowledge-brief"`, `"1.3"`. |
| `source_id`, `source_name`, `item_id`, `title`, `date`, `link` | | What the brief is about. The same as the index; never taken from a transcript or a model. |
| `brief_kind` | | `model`: written by a model from the transcript and checked against it. `extractive`: built from the digest by the processor, no model. |
| `model` | 80 | The model id for a `model` brief; null for `extractive`. |
| `covers`, `covers_note` | 200 | `whole`: the brief covers the whole item. `partial`: only part of it, and `covers_note` says which in one sentence (a cut transcript, "covers the first 3 parts of the transcript, to 02:30:00", or a digest made from notes only). A `whole` brief has a null note. |
| `headline` | 160 | One sentence: what this item is about. |
| `claims` | 8 × 220 | Specific statements (a name, a number, a date, a position), one sentence each, in order, each with `ref`: where in the transcript it comes from, its time `HH:MM:SS`, or `L<n>` for the n-th transcript line (counted from 1, sponsor reads included) when the line has no time; null only in an extractive brief with nothing to point at. A `model` brief has 4 to 8 claims, each with a ref. Refs are for the processor and for a deep dive; they are not read out. |
| `new` | 300 | What is new or changed, as far as the item itself says; null in an extractive brief (it does not say). "Nothing in the text marks it as new." is a valid answer. |
| `quotes` | 2 | At most two short quotes: `text` (300), `speaker` (80, or `unknown`), `time` (a ref as above). Each was checked word for word against the transcript by the processor (whitespace, case and typographic quotes and dashes aside). |
| `topics` | 4 | Ids of the vocabulary in `store.json` (section 11); empty when the output has no vocabulary. |
| `keywords` | 5 × 40 | Short search words or phrases, lower case. |
| `entities` | 12 × 80 | Names only: people, companies, organisations, products, places. |
| `transcript_sha256` | | SHA-256 of the normalized transcript the brief was made from, or null. |

**Size.** The visible text (headline, claim texts, `new`, quote texts and speakers, topics, keywords and entities, all together) is at most **1,800 characters**; a file is at most 8,000 bytes. A typical brief is 1,200 to 1,700 characters of text and 2 to 3 KB on disk.

**How a model brief is made and checked** (`src/pea_knowledge/brief.py`, the writer prompt of phase 1, spike/WRITER-PROMPT-v3.md, with its ten rules). The model sees the item's title, show and date and the transcript with one mark per line, and answers one JSON object. Before anything is kept: exact keys and types; every limit above; text rules T1 to T4 and no text addressed to the assistant; topics only from the vocabulary; every quote word for word in the transcript and its `time` a line of it; a quote's speaker the speaker of that line, and (rule 8) the speaker named by any claim that uses the same line; a claim whose ref is no line is dropped; fewer than four claims left fails. Names and numbers in claims that are nowhere in the transcript are counted as flags (`health.json`), not refused. A brief that fails is sent back once with the list of problems; if the second answer fails too, the item gets the extractive brief. A transcript longer than `briefs.chunk_chars` (60,000 characters) is written in up to `max_chunks` (4) parts, one partial brief each, and the partial briefs are merged in one more call, checked against the whole transcript; parts beyond the last make the brief `partial`.

**How an extractive brief is made**: the headline is the first sentence of the digest's `about`, the claims its talking points (shortened to 220), the quotes its first two exact quotes, the entities its guests and the people, organisations and products of the glossary, the keywords the other glossary terms and mentioned resources, the topics the item's. Over the cap, keywords, entities, quotes and claims give way in that order.

**Cost.** Model briefs are made for new items and, a few per run, for listed items whose brief is extractive (`briefs.upgrade_per_run`, newest first across all sources, only items whose digest was made from a transcript, of sources whose terms allow a model brief): the fetch job, which never has the key, fetches their transcripts again when it is told that the brief step will have one (`PEA_BRIEFS_KEY_EXPECTED`, set from the dispatch input `expect_key` or the repository variable of that name) or when the last published `state.json` says the last brief step had one. A brief is reused, without a call, when the item is made again from the same transcript (`transcript_sha256`) by the same model. Spending is capped per run and per calendar month in US cents (`brief_budget`: `per_run_cents` 100, `monthly_cents` 200 by default); before each call the worst case (the prompt at three characters a token, plus `max_output_tokens`) must fit both. The cost of a call is the provider's own figure (`usage.cost`) or its token counts at the configured prices, whichever is higher (the provider gave 0 for every call of the first real run). When a cap is reached the run stops calling the model and every remaining item gets an extractive brief. The month's spend is kept in `state.json` (`briefs`: `month`, `spent_cents`, `calls`, and whether the last brief step had a key), which each run restores from the published output, so the cap holds across scheduled runs. A source whose terms forbid quotes or derived summaries is marked `brief_writer: extractive` in the config and is never sent to a model.

**Terms.** A brief is an original short summary with at most two short quotes and a link back. No transcript text is written to the output beyond those quotes, and the transcripts themselves are still withheld (`withheld_terms`).

## 13. The briefs index (`briefs-index.json`, 1.3, additive)

One small file beside `store.json` that lists the shows the output holds briefs for, how many each, and their newest briefs, so an app can say truthfully what it holds ("briefs from 11 shows; the newest are ...") and choose one brief per show without loading every items file. It is written by every build from generator 0.7.0 on. **It carries nothing the items files do not already say**: it is made from them after they are written, and the validator makes it again from them and refuses an index that differs in any member. A reader that does not know the file never fetches it; the format stays 1.3.

| Member | What it is |
| --- | --- |
| `format`, `format_version` | `"pea-knowledge-briefs-index"`, `"1.3"`. |
| `generated_at` | The `generated_at` of the `store.json` it was made with. An index whose time differs is from another run and is not used. |
| `shows` | Every source with at least one listed brief (withdrawn sources have none), newest first by its newest brief, then by id. At most 60. |
| `shows[].id`, `name`, `kind` | As in `store.json`. |
| `shows[].brief_count` | How many listed items of the source have a brief (1 to 500). |
| `shows[].latest` | Its newest briefs, in the order of its items file (newest first), at most 5. |
| `latest_overall` | The newest briefs across every show, at most 12: by date (newest first), then show id, then the order of the items file. Each also has `show_id`. |
| `item_id` | The item's id. The brief is at `sources/<show>/<item_id>.brief.json`, named with its hash in the items file. |
| `title` | The item's title, shortened to 120 characters (at a space, ended with `…`). |
| `date` | The item's date. |
| `method` | The brief's `brief_kind`: `model` or `extractive`. |
| `partial` | True when the brief's `covers` is `partial` (it covers only part of the item). |

**Size.** About 11 KB for the published feed of 2026-11-19 (fourteen sources, eleven with briefs); fourteen sources of five briefs with titles of usual length stay under 15 KB. A reader refuses one over 32,000 bytes unread.

**How a reader checks it.** Fetch it after `store.json` (no hash names it), refuse it over 32,000 bytes, read it like any file (strict JSON, version, `schema/briefs-index.schema.json`, text rules), check `generated_at` against `store.json`, and check that every brief it names is listed in the items file of its show. Where it fails any check, or is absent (an output of 0.6.0), a reader makes the same list from `store.json` and the items files it holds; `briefs_index.build` is the reference. `python3 -m pea_knowledge validate` refuses an index that names a brief that is not listed (`missing`), whose counts, titles, kinds or order differ from the items files (`inconsistent`), or that was made with another `store.json` (`identity_mismatch`). The `index-*` samples in `tests/golden/hostile/` are checked against `tests/golden/dist/`.
