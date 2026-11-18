# What the app must do: the reader's contract

This is the app's side of the PEA knowledge format (docs/FORMAT.md). It says exactly what the iPhone reader validates, what it refuses and why, how it treats each lifecycle state, how it keeps items on the device, and how it refreshes. `python3 -m pea_knowledge validate` and `src/pea_knowledge/validate.py` are the reference: the app's checks should mirror them, and the app's tests can copy `tests/golden/` as it is.

Base address: `https://gptkiosk.github.io/pea-knowledge-processor/`. Every path in the format is relative to it.

## 1. What the app fetches, and privacy

- The app downloads static files with plain GET requests. It sends no account, no cookie, no identifier, no query string and nothing about the owner or the conversation. The only headers that vary are `If-None-Match` and `If-Modified-Since`.
- **Browsing the store needs `store.json` only.** Everyone who opens the store downloads the same file, so the host learns nothing about what one owner is interested in. The card (name, description, categories, cadence, typical length and size, the three newest titles, what is available, the terms) is all in that file.
- **Adding a source is visible to the host.** When the owner adds a source, the app fetches `sources/<id>/items.json` and that source's digests. The static host (GitHub Pages) can see which paths an address requested, so it can tell which sources that address follows. The app says this once, in plain words, where the owner adds a source. An owner who wants to hide it can switch on "download every source's items" (the app then fetches all of them and shows only the added ones): more data, no signal. The app never fetches `state.json` or `health.json`.
- The app never fetches an item's `link` or a source's `site` by itself. It shows them, and opens one only when the owner asks.
- **Reading a whole transcript goes to the publisher.** The output carries no transcripts. When the owner wants to talk about an episode in full, the app fetches `transcript_source.link` (section 8) from the publisher itself. The publisher, or the host of its files, then sees the phone's network address and which episode's transcript it asked for, as with any podcast app downloading an episode. The app says this once where the owner switches it on, sends nothing else, and never does it for an item the owner did not add or open.

## 2. Validation, in order

For every file: the size limit, the size and SHA-256 its index entry states, strict JSON, the version, the schema, the text rules, the addresses, then the cross-checks. FORMAT.md section 9 lists them; the limits are 512,000 bytes for `store.json` and `items.json`, 24,000 for a digest, 1,000,000 for a transcript, and 900 characters for the text of a brief form.

A file that fails is not used: not shown, not stored over a good copy, never put in a prompt. The app records the typed reason:

| Reason | Meaning | What the owner sees |
| --- | --- | --- |
| `missing` | A file the index names is not there (404). | "Could not get this item. It will be tried again." |
| `too_large` | Over the limit for its kind; refused unread. | "This item was refused: too large." |
| `not_json` | Not strict JSON (also NaN, a key written twice, not UTF-8, a web page instead of a file). | "The source list could not be read." |
| `unsupported_version` | A major version the app does not know. | "Update PEA to read the curated sources." |
| `schema` | Not the stated shape (a wrong type, an over-long text, too many entries, an unknown value). | "This item was refused: not in the expected form." |
| `text_rule` | A text holds markup, an address, a control or direction character, or bad spacing. | the same |
| `address` | `site` or `link` is not a public https address. | the same |
| `path_invalid` | A path that is not exactly where that file belongs. | the same |
| `size_mismatch`, `hash_mismatch` | The bytes are not the ones the index promised. | "This item did not arrive intact. It will be tried again." |
| `identity_mismatch` | A file says it is something other than what the index says. | "This item was refused: not in the expected form." |
| `inconsistent` | Members that contradict one another. | the same |
| `brief_too_long` | The brief form is over 900 characters. | the same |
| `transcript_invalid` | Not a conforming PEA transcript v1 file. | "The transcript was refused; the digest is still there." |

Two rules that matter most:

- **`store.json` that fails validation is ignored whole.** The app keeps the last good one and everything it has, and says "couldn't check for updates". It never disables, pauses or deletes anything because of a file it refused.
- **A source or item that fails is refused alone.** The other sources and items are used as normal.

Versions: the app accepts major 1. The output is format 1.2 since 0.4.0 of the processor (topics, section 9); a reader written for 1.0 or 1.1 keeps working unchanged, because every later member is optional and unknown to it (see "Reading 1.1" and "Topics" below). For a file whose minor is newer than the app knows, unknown members are ignored. `min_app_version` newer than the app: keep everything, show "update PEA to get new items", fetch nothing new.

## 3. Caching and refresh

1. Fetch `store.json` with `If-None-Match` (the ETag of the last good copy). `304`: nothing changed anywhere; stop.
2. `200`: validate it. If it fails, keep the old one (section 2).
3. For each source the owner added: if `items_file.sha256` is the one already stored, skip the source. Otherwise fetch `items.json`, validate it against the listing.
4. For each item the app wants to hold (section 5): if the stored copy's `sha256` is the one in the index, keep it. Otherwise fetch the file and validate it. **Keep the old copy until the new one has validated**, then replace it. If the new one fails, the old one stays and the item is shown as "update pending".
5. Never fetch a file whose hash is already held. Hashes, not times, decide.

How often: on opening the store, on the owner's pull to refresh, and at most once every six hours in the background (the pipeline runs every six hours). Back off after a failure: 15 minutes, an hour, then six hours.

A corrected item upstream (the publisher fixed a transcript, the digest was rebuilt) is simply a new hash under the same item id: step 4 handles it. Notes the owner made about an item stay attached to its id.

## 4. Lifecycle states: what the app does

| What the app finds | What it does |
| --- | --- |
| `state: active`, `freshness: fresh` | Normal. |
| `state: active`, `freshness: stale` | Normal, with a quiet "last updated <last_ok>". Keep fetching. |
| `state: paused` | A calm banner on the source with `message` (for example "This source is paused: <message>"). Kept items stay readable and can be talked about. Stop fetching that source's files (keep checking `store.json`). Leave it out of suggestions. Her prompt says what she has from it and that the source is paused, so she does not promise new items. |
| `state: withdrawn`, `purge: false` | Switch the source off and hide it from conversation and suggestions. Show one plain note: "The curator removed this source: <message>". The owner may keep or delete the local items; kept items are marked "from a source that was removed" and are not offered by the assistant unless the owner opens them. |
| `state: withdrawn`, `purge: true` | As above, and delete the local copy of that source's items, digests and transcripts, pinned or not. Notes the owner wrote are the owner's and stay; quotes copied into them stay. Tell the owner what was deleted and why. |
| A source the owner added is no longer in `store.json` | Treat as withdrawn without purge and without a message: "The curator removed this source." |
| A source returns to `active` | Remove the banner, resume fetching, include it in suggestions again. |
| `store.json` cannot be fetched at all | Keep everything as it is. Show "couldn't check for updates" with the time of the last good check. **Never disable anything because of a network failure.** |
| `store.json` fails validation | Ignore it and keep the last good one. The same notice. |

`message` is text the curator wrote, checked by the text rules: no links, no markup, one line, at most 240 characters. The app shows it as plain text and never as part of her instructions. `tests/golden/hostile/` has messages a reader must refuse (a link, markup, a line break, hidden direction marks, too long).

A state change takes effect on the next good `store.json`, with no app update.

Item level: an item with `stale: true` is usable; show "may be out of date" in its details.

## 5. Keeping items on the device

Retention is the owner's choice. The catalog only suggests.

- **The setting.** Per source: how many items to keep (default: the listing's `suggested_keep`). Overall: a storage ceiling shown in MB. The store card shows the typical size per item (`avg_bytes`, for example "about 9 KB each") so the owner can choose; the settings screen shows what is used now. The owner can set a source to keep none (browse only) or raise it. The catalog never forces a number: `suggested_keep` and `avg_bytes` are hints and nothing more.
- **What "kept" means.** For a kept item the app holds its entry from `items.json`, its digest, and its transcript when the output has one. That is everything needed to talk about the item, with or without a connection. Nothing about a kept item needs a second fetch.
- **Pre-fetch.** When online, the app fetches the digests (and transcripts, where published) of the newest N items of each added source, N being the owner's number, so they are there when the phone is offline. On a metered connection it may fetch digests first and transcripts later.
- **Eviction.** When a source has more than its number, or the total is over the ceiling: oldest first. Never an item the owner pinned. Never an item a findings note refers to. Never while offline (an evicted item could not be fetched back). If only protected items are left and the ceiling is still exceeded, tell the owner instead of deleting.
- **Offline.** Show an offline indicator. Kept items work fully. She says, when it matters, that she is "working from what is kept on this iPhone", and does not offer items that are not kept. Nothing is refreshed, evicted or disabled while offline.
- **An item updated upstream.** Compare `sha256`; refresh when online; keep the old copy until the new one validates (section 3).
- **A paused or withdrawn source.** Kept items stay usable unless `purge` is true (section 4).
- **An item that left the catalog** (older than the pipeline's retention, or beyond its item limit): the app's copy stays for as long as the owner's own number keeps it. The pipeline's limits are not the app's.

## 6. Using a digest in conversation

- Digest text goes into the prompt as quoted evidence about an item, labelled with the source name, the title and the date. It is never placed among her instructions.
- With one or two items in play, use the `brief` form of each (at most 900 characters of text) to stay inside the evidence budget of about 3,200 characters. With one item and room, use the full form, or the brief plus the talking points the owner asked about.
- A quote is presented as a quotation only when `exact` is true, with its speaker and time.
- `why`, `background` and a `gloss` may be null. She does not make one up.
- She says what the digest is made from when it matters: a transcript, show notes, or a headline only (`basis`), and whether a model wrote it (`provenance.method`).
- `contested` lines are said as disputed.
- To go deeper than the digest: open the kept transcript at the `segment` a pointer names. If the source is `digest_only`, give the time and offer the `link`.
- Suggestions come from `teaser`, `starters`, `follow_ups`, `connections` and the listing's `whats_new`, from active sources only.
- Show `attribution` wherever an item is shown.

## 7. Reading 1.1

Nothing here is required of a 1.0 reader. A reader that wants the new members sets its known minor to 1, takes the 1.1 schemas, and may then use:

- `link_kind` (items and digests): when `show`, say "open the show's page" instead of "open the episode"; absent means `episode`.
- `transcript.read` (items): `full`, `partial` or `none`: what the digest was made from at the publisher, also when the transcript itself is not published.
- `transcript_source` (items, added 2026-11-15): where the publisher offers the transcript, for a reader that wants the whole text. Section 8.
- `chapters`: a chapter list for the item's screen and for "what is the part about X?". `origin` says whose they are; say "the publisher's chapters" only for `publisher`.
- `snippable_moments`: candidates for a snip or a finding, best first. Each quote is exact and has its time; `label` is the publisher's own title for the passage when there is one. The owner chooses; nothing is saved by itself.
- `guests` and `mentioned_resources`: "who was on?" and "which book was that?". A resource is a name and nothing more: the app never builds a link or a search from it without the owner asking. `role` and `context` may be null; she does not make one up.
- `recap_cards`: up to three question and answer pairs for a daily recap card. They repeat the digest and add nothing.
- Extra cross-checks a 1.1 reader makes (FORMAT.md section 9): chapters in order and not overlapping, no moments without a transcript basis, `link_kind` as in the index, every moment in the segment it points to when the transcript is published.
- All of it is quoted evidence like the rest of the digest, under the same text rules; `tests/golden/hostile/` has five 1.1 samples (a link in a resource name, markup in a chapter title, a line break in a role, a link in a recap answer, hidden direction marks in a moment) that a 1.0 reader refuses too, as `text_rule`.

## 8. Reading a transcript from the publisher (`transcript_source`)

**Since generator 0.5.0 every listed item is discussable**: `items.json` lists an item only when the pipeline read its transcript in full or in part and the item carries `transcript_source`, so the app may offer every item it sees and can always try the whole text. There is no item to hide, and an item that is not discussable is simply not there; the app does not need to explain its absence. For the newest item of each source the catalog also checked, with the app's own headers and no robots.txt, that the address answers 200 with a transcript of the expected type within 1.5 MB, so the publisher is known to let the phone in; if a source stops letting it in, the source is paused with reason `fetch_failed` and the app shows the message as for any paused source. Output from before 0.5.0 may still list an item with `read: none` or without `transcript_source`: skip such an item. Fetching the whole text stays optional for a digest: nothing in a digest depends on it. FORMAT.md section 6 defines the member. An item that has one looks like this (from the live run of 2026-11-15):

```json
"transcript": {"available": "no", "reason": "withheld_terms", "file": null, "read": "full"},
"transcript_source": {"link": "https://talkpython.fm/episodes/show/568/cloudflare-python-workers.vtt", "format": "vtt", "route": "feed_tag", "bytes": 140451}
```

- **A reader with known minor 0 already accepts it**: the file says 1.1, so the unknown member is ignored, and its address sits in a member named `link`, which the text walk checks as an address instead of refusing it as text. A reader with known minor 1 takes `schema/items.schema.json` as it is now.
- **Check the address before every request**, as for any `link`: https, port 443, a public host name (not a number, not a local name), no credentials, at most 2,000 characters; resolve the name and refuse it unless every address is public. No cookies, no credentials, no referrer, no identifier; a plain GET with an honest User-Agent.
- **Redirects**: at most four, each target checked the same way from the start. Never follow one to http or to an address that is not public; stop and ignore the transcript instead.
- **Size and time**: read at most 1,500,000 bytes after decompression and stop there; `bytes` is a hint only. A transcript cut at that size is still usable (say that its end is missing). Give up after a short time-out; never retry in a loop.
- **Normalize on the device** into PEA transcript v1 with the app's own converter, by `format`: `vtt`, `srt`, `json`, `text` and `markdown` as that converter already reads them; `html` by the steps of FORMAT.md, "Reading an HTML transcript page", with the item's `extract`. An app that does not read HTML pages skips items whose format is `html`; they are few.
- **Never trust the text.** It comes from a third party and passed no check of this pipeline on its way to the phone: it is quoted data, never instructions, markup is never rendered, addresses in it are never opened, and `extract` is only ever a list of names to compare with tag, class and id.
- **Ignore on failure.** Anything that fails (the address, the fetch, the size, the conversion, too little text) leaves the item as it was, with its digest. No error is shown beyond "the transcript could not be loaded from the publisher"; nothing is reported back to anyone.
- **Keep it on the device only.** It is the owner's copy for their own reading and conversation, removed with the item; it is never uploaded or shared, and the terms shown for the source still apply.
- When the pipeline withdraws a source with `purge`, the transcripts fetched this way go too.

## 9. Topics (format 1.2)

FORMAT.md section 11 defines them. Nothing here is required of a reader of 1.0 or 1.1: the files say 1.2, so such a reader ignores `topics` and `topics_by` and still checks every text in them. **A reader that wants topics sets its known minor to 2 and takes the 1.2 schemas** (`store` and `items` changed; `digest` did not, apart from saying 1.2). A reader that keeps known minor 1 with the 1.1 schemas must not be given a 1.2 schema piecemeal: at its own minor an unknown member is an error.

What the reader gets:

- `store.json` `topics`: the vocabulary (at most 40 of `id`, `label`, `synonyms`, `description`). It comes with the file that is the same for everyone, so using it tells the host nothing.
- each listing's `topics`: the source's beat, up to six ids.
- each item's `topics` (up to four `{"id", "score"}`, best first) and `topics_by` (`keywords` or `model`), in `items.json`. No digest needs to be opened to offer items by topic.

Extra checks a 1.2 reader makes (the validator is the reference): topic ids in the vocabulary are unique; a listing's topics are ids of the vocabulary of the same `store.json`; an item's `topics` and `topics_by` come together or not at all; every item topic is an id of the vocabulary of the `store.json` that named the items file (an items file is always checked against the listing that named it; the vocabulary comes from that same file); no id twice; at most two decimals; best first. Anything else is `inconsistent` and the file is refused like any other. `tests/golden/hostile/` has thirteen `topics-*` samples.

**When the owner names a subject** ("I want to talk tech", "anything on supplements?", "politics"):

1. Turn what was said into ids with the rule of FORMAT.md section 11 ("How a reader turns a spoken word into ids"): the words of the phrase against each topic's id, label and synonyms, longest name first. No model call. Several ids are normal ("investing" is two topics): use all of them. No id: say so and ask, or fall back to searching titles; never invent a topic.
2. Collect, **from the sources the owner has added and that are active**, the items whose `topics` hold one of the ids. Newest first; among items of the same day the higher `score` first. Offer the newest few (three is a good number) across sources, each with its source name, its title and its `teaser`, so one show does not crowd out the rest.
3. If that gives nothing, offer the newest items of the added sources whose own `topics` (the listing's) hold the id, and say plainly that this is what the show usually covers, not what the episode is known to be about.
4. If that gives nothing either, say that none of the owner's sources has it at the moment. The store card of a source the owner has not added may be mentioned as a suggestion to add (its `topics` are in `store.json`); its items are not fetched for this.

**Showing confidence honestly:**

- `topics_by: keywords` means words and phrases were counted in the title, the notes, the digest and the start of the transcript. Say "tagged by keywords", not "about". `topics_by: model` means a model proposed the topic and the processor checked it against the digest.
- `score` is strength of evidence from 0.5 (the least that is published) to 1, not a probability and not a rating. A simple reading: 0.85 and more "mostly about", 0.65 to 0.85 "covers", below that "touches on". Do not show the number as a percentage of anything.
- **Never claim more than the tag says.** A tag says the item's text points to the topic. It does not say what position anyone takes, that the item is good, or that it is suitable advice: an item tagged `health` or `supplements-nutrition` is a conversation that someone had, not guidance, and she says whose it is (`attribution`, the guests).
- An item with an empty list has no confident topic. It is never offered as being about something because its source usually is, except through step 3 and in those words.
- An item from before 1.2 (no `topics`) is treated like an empty list until its source is rebuilt, which the first run of 0.4.0 does.

**In a prompt.** Topic ids and labels are identifiers from a fixed list, checked against the vocabulary, so they may be used to select and label evidence. They are still data: the app never puts a label, a synonym or a description among her instructions.

**Caching.** The vocabulary changes rarely and only with `store.json`. When it changes, the processor makes every item anew, so the ordinary refresh of section 3 brings the tags that fit the new vocabulary; a reader never has to reconcile old tags with a new vocabulary beyond dropping an id it no longer finds there.

## 10. Briefs (format 1.3): what the app may rely on

FORMAT.md section 12 defines them. They are what the app searches on the phone and talks from. A reader of 1.2 is not affected: it ignores `brief` on an item and never fetches a brief file. **A reader that wants briefs sets its known minor to 3 and takes the 1.3 `items` and `brief` schemas.**

**The app may rely on these, for every item listed by an output of generator 0.6.0 or later:**

1. **Every listed item has a brief.** The item's `brief` names it with path, SHA-256 and size; it is fetched and checked like a digest (section 2), at most 8,000 bytes, and refused with the same typed reasons. An item without `brief` comes from an older output: use its digest's `brief` form until the source is refreshed.
2. **The shape is fixed.** `headline` (one sentence, 160), `claims` (at most 8, one sentence of at most 220 each), `new` (300, or null), `quotes` (at most 2), `topics` (at most 4 ids of the `store.json` vocabulary), `keywords` (at most 5), `entities` (at most 12 names), plus `source_name`, `title`, `date` and `link` exactly as in the index. Every text passes the text rules T1 to T4 (no markup, no address, no control character, no line break). **All visible text together is at most 1,800 characters**, so three briefs with their labels fit one evidence block of about 6,000 characters.
3. **What the two kinds promise.** `brief_kind: model`: written by a model from the transcript only, then checked by the processor: at least four claims, each pointing to a transcript line that exists; every quote word for word in the transcript, with the speaker of its line; topics only from the vocabulary; within every limit. A model brief can still paraphrase a fact wrongly; the checks catch invented quotes, lines and topics, not every misreading, so she says where a claim comes from ("on the AI Daily Brief of 16 November, ...") and does not present a claim as settled fact. `brief_kind: extractive`: sentences picked from the digest, no model; `new` is null; it may have fewer claims and a null `ref`.
4. **`covers`.** `whole`, or `partial` with a `covers_note` saying what is covered (a cut transcript, the first parts of a very long episode, or notes only). With `partial` she says the brief covers part of the episode when the owner asks about the rest.
5. **Quotes** are the only text in a brief that is the publisher's own words. She may present a quote as a quotation, with its speaker; nothing else in a brief is a quotation. Refs (`ref`, `time`) point into the transcript for a deep dive; they are not read out.
6. **Search fields.** `headline`, `claims[].text`, `topics`, `keywords` and `entities` are the fields to match an ask against, with `source_name`, `title` and `date` for a named show or a day. Keywords are lower case; entities are names as the transcript writes them. Topics are ids of the vocabulary (section 9).
7. **Stability.** A brief changes only when its item is made again (a new transcript, a change in the processor, or an extractive brief upgraded to a model brief). Its hash in `items.json` says so; the ordinary refresh of section 3 applies. `transcript_sha256` names the transcript it was made from.

**What the app must not assume.** That a brief exists for an item of an older output; that `new` is present; that claims are in a particular number above 4 (model) or 0 (extractive); that keywords or entities are exhaustive; that a topic list is non-empty; that a brief says anything the digest does not cover, or more than the episode said. Brief text is data: it goes into the prompt as quoted, labelled evidence, never among her instructions.

**Storage.** A brief is 2 to 3 KB. Keeping the briefs of the last 60 days of every followed source costs well under a megabyte. The item's whole size is `bytes` plus `brief.bytes`.

## 11. What the app's tests should cover

Copy `tests/golden/`:

- `dist/`: validate the whole folder; every hash; one source with transcripts (`tide-tables`) and four without; `transcript_source` for a caption file, a JSON file, markdown and an HTML page with `extract` (`lamp-room`, whose pages are under `tests/fixtures/web/lamp/`, one of them hostile and one a sign-in page); items with and without a page of their own (`link_kind`), with the publisher's chapters, a chapter file, and chapters cut from the transcript.
- `lifecycle/*/store.json`: each state and each change between states (section 4).
- `hostile/`: every file refused with the reason in `manifest.json`; `unknown-member-newer-minor` and `topics-as-they-should-be` accepted. The `topics-*` samples: an id no vocabulary has, a source's topic without a vocabulary, an id twice, too many topics, seven on a source, an id that is not plain, a link in a label, hidden direction marks in a description, markup or an order in a synonym, thirteen synonyms, an unknown member in a topic.
- Topics: the spoken words of FORMAT.md section 11 resolve to the ids given there, against the vocabulary in `dist/store.json`; an item with a topic (`quay-notes`, "Four generations of ice"), items with an empty list, and the fallback to a source's topics; an items file whose item names an id outside the vocabulary is refused (`tests/test_topics.py`, `test_a_reader_refuses_topics_that_do_not_fit`, lists every case).
- Tamper with a file: one byte changed (`hash_mismatch`), one byte added (`size_mismatch`), a file removed (`missing`).
- The fetch rules of section 3 against a local server: `304`, an unchanged items hash, the old copy kept when the new one fails.
- Offline: kept items usable, nothing evicted or disabled.
- Briefs (1.3): every item of `dist/` names a brief that validates (`brief_kind: extractive` there, made without a model); `hostile/brief-*` refused with their reasons and `brief-as-it-should-be` accepted; an item without `brief` (an older output) falls back to the digest.
