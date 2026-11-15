# What the app must do: the reader's contract

This is the app's side of the PEA knowledge format (docs/FORMAT.md). It says exactly what the iPhone reader validates, what it refuses and why, how it treats each lifecycle state, how it keeps items on the device, and how it refreshes. `python3 -m pea_knowledge validate` and `src/pea_knowledge/validate.py` are the reference: the app's checks should mirror them, and the app's tests can copy `tests/golden/` as it is.

Base address: `https://gptkiosk.github.io/pea-knowledge-processor/`. Every path in the format is relative to it.

## 1. What the app fetches, and privacy

- The app downloads static files with plain GET requests. It sends no account, no cookie, no identifier, no query string and nothing about the owner or the conversation. The only headers that vary are `If-None-Match` and `If-Modified-Since`.
- **Browsing the store needs `store.json` only.** Everyone who opens the store downloads the same file, so the host learns nothing about what one owner is interested in. The card (name, description, categories, cadence, typical length and size, the three newest titles, what is available, the terms) is all in that file.
- **Adding a source is visible to the host.** When the owner adds a source, the app fetches `sources/<id>/items.json` and that source's digests. The static host (GitHub Pages) can see which paths an address requested, so it can tell which sources that address follows. The app says this once, in plain words, where the owner adds a source. An owner who wants to hide it can switch on "download every source's items" (the app then fetches all of them and shows only the added ones): more data, no signal. The app never fetches `state.json` or `health.json`.
- The app never fetches `link` or `site` by itself. It shows them, and opens one only when the owner asks.

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

Versions: the app accepts major 1. The output is format 1.1 since 2026-11-15; a reader written for 1.0 keeps working unchanged, because every 1.1 member is optional and unknown to it (see "Reading 1.1" below). For a file whose minor is newer than the app knows, unknown members are ignored. `min_app_version` newer than the app: keep everything, show "update PEA to get new items", fetch nothing new.

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
- `chapters`: a chapter list for the item's screen and for "what is the part about X?". `origin` says whose they are; say "the publisher's chapters" only for `publisher`.
- `snippable_moments`: candidates for a snip or a finding, best first. Each quote is exact and has its time; `label` is the publisher's own title for the passage when there is one. The owner chooses; nothing is saved by itself.
- `guests` and `mentioned_resources`: "who was on?" and "which book was that?". A resource is a name and nothing more: the app never builds a link or a search from it without the owner asking. `role` and `context` may be null; she does not make one up.
- `recap_cards`: up to three question and answer pairs for a daily recap card. They repeat the digest and add nothing.
- Extra cross-checks a 1.1 reader makes (FORMAT.md section 9): chapters in order and not overlapping, no moments without a transcript basis, `link_kind` as in the index, every moment in the segment it points to when the transcript is published.
- All of it is quoted evidence like the rest of the digest, under the same text rules; `tests/golden/hostile/` has five 1.1 samples (a link in a resource name, markup in a chapter title, a line break in a role, a link in a recap answer, hidden direction marks in a moment) that a 1.0 reader refuses too, as `text_rule`.

## 8. What the app's tests should cover

Copy `tests/golden/`:

- `dist/`: validate the whole folder; every hash; one source with transcripts (`tide-tables`) and three without; items with and without a page of their own (`link_kind`), with the publisher's chapters, a chapter file, and chapters cut from the transcript.
- `lifecycle/*/store.json`: each state and each change between states (section 4).
- `hostile/`: every file refused with the reason in `manifest.json`; `unknown-member-newer-minor` accepted.
- Tamper with a file: one byte changed (`hash_mismatch`), one byte added (`size_mismatch`), a file removed (`missing`).
- The fetch rules of section 3 against a local server: `304`, an unchanged items hash, the old copy kept when the new one fails.
- Offline: kept items usable, nothing evicted or disabled.
