# The curated sources and their terms

Checked on 2026-11-14 by fetching each file named below. This is a record of what was read and what follows from it. It is not legal advice; the points marked **for the owner** need a decision or a question to the publisher.

## The rule

- A source's `publish` level is `digest_only` unless the publisher clearly permits redistributing transcripts. Every source below is `digest_only`.
- With `digest_only`, the pipeline may read the transcript at run time to build the digest. The transcript is never written to the public output; the item says `withheld_terms`.
- A digest of a `digest_only` source takes at most `excerpt_budget_chars` characters (1,500 by default) from the transcript, as short separate sentences with the time and a link back.
- A news source is always headline, a description of at most 280 characters and the link. The article text is never republished. The configuration refuses any other setting for `kind: news`.
- `robots.txt` is obeyed on every host, also on the host a transcript is served from, and a `Crawl-delay` is honoured (up to 30 seconds).
- Every item links back to the publisher, and every listing carries an attribution line.

## The sources

### The AI Daily Brief (`ai-daily-brief`)

- Read: `https://aidailybrief.ai/agent.json` (a machine index of 137 editions, each with a page, a markdown twin, structured JSON and a transcript), `https://aidailybrief.ai/llms.txt`, `https://aidailybrief.ai/robots.txt`.
- robots.txt: everything allowed for every robot except `/admin`, `/api/admin` and one sponsor page.
- Licence or terms: none found. `agent.json` and `llms.txt` state none; `https://aidailybrief.ai/terms` is a 404.
- What follows: the publisher offers its editions to agents in machine-readable form, which invites reading. Nothing permits republishing transcripts. `digest_only`.
- **For the owner:** reading is clearly invited; a public digest with short quoted sentences is not addressed either way. Asking the publisher would settle it, and they might well agree to more.

### Podcasting 2.0 (`podcasting-20`)

- Read: `https://feeds.podcastindex.org/pc20.xml` (211 episodes; `podcast:transcript` in SubRip on `mp3s.nashownotes.com`), robots.txt on both hosts.
- robots.txt: none on the feed host (404). The transcript host's file disallows nothing and asks for ten seconds between requests.
- Licence or terms: the feed states no licence and no copyright line. `podcast:locked` is set; that concerns moving the feed to another host, not reuse of the content.
- What follows: public, unrestricted for reading; no written permission to republish. `digest_only`.
- **For the owner:** the show's makers promote open podcasting and value for value, so permission to publish full transcripts is plausible, but it is not written anywhere that was found. Ask before changing `publish` to `full`.

### Build Your SaaS (`build-your-saas`)

- Read: `https://feeds.transistor.fm/build-your-saas` (163 episodes; transcripts in WebVTT, SubRip, JSON and text on `share.transistor.fm`), robots.txt on both hosts.
- robots.txt: the feed host answers 400 for robots.txt (treated as "nothing restricted", as RFC 9309 says for a 4xx). The transcript host allows everything for robots in general.
- Licence or terms: `<copyright>© 2025 Transistor, Inc.</copyright>`, no licence.
- What follows: `digest_only`.
- The newest episode is from April 2026, so this source has a longer retention (400 days) and three items; with the default 45 days it would be empty.
- **For the owner:** the hosting company's general terms of service were not read.

### Buzzcast (`buzzcast`)

- Read: `https://rss.buzzsprout.com/231452.rss` (the address `feeds.buzzsprout.com/231452.rss` redirects there; 269 episodes; transcripts as HTML, JSON, SubRip and WebVTT on `www.buzzsprout.com`), robots.txt on the hosts.
- robots.txt: `www.buzzsprout.com` disallows one unrelated feed; `rss.buzzsprout.com` has none (404).
- Licence or terms: `<copyright>© 2026 Buzzsprout</copyright>`, no licence; `podcast:locked` is set.
- What follows: `digest_only`.
- **For the owner:** the SubRip transcript names a speaker only where the speaker changes, and the converter carries a name forward, so a quote can be credited to the wrong host. Treat speaker names from this source as likely, not certain. The hosting company's general terms were not read.

### EFF Deeplinks (`eff-deeplinks`), the news source

- Read: `https://www.eff.org/rss/updates.xml` (50 entries, each with the full article in its description), `https://www.eff.org/robots.txt`, `https://www.eff.org/copyright`.
- robots.txt: asks robots in general for thirty seconds between requests; the feed is not disallowed. The pipeline makes two requests to this host per run, thirty seconds apart.
- Licence: the copyright page says original material on the site may be freely distributed under Creative Commons Attribution 4.0 unless otherwise noted, and that material not original to the publisher may need permission.
- What follows: the licence would allow more, but the project's rule for news stands: headline, the first one or two sentences (at most 280 characters) and the link, with the credit line "Electronic Frontier Foundation, eff.org, CC BY 4.0". The article text in the feed is read and discarded.
- **For the owner:** this is commentary from an advocacy organisation, not a neutral wire. It was chosen because its licence is unambiguous. If a general news site is wanted instead, check its feed terms first: many allow headlines and links for personal use only.

## What is uncertain overall

1. **Short excerpts from `digest_only` transcripts.** Extractive digests are made of sentences from the transcript (up to 1,500 characters per episode, typically under a tenth of it), with a link back. Whether that is acceptable to each publisher is a judgment this project cannot make for them. Options: lower `excerpt_budget_chars`, switch on the model digest (it paraphrases; only the quotes are verbatim), or ask the publishers.
2. **The work folder in CI.** Between the jobs of a run, normalized transcripts travel as a workflow artifact kept for one day. In a public repository, signed-in GitHub users can download artifacts of a run. That is a short-lived copy of transcripts that are not meant to be republished. If this matters, make the repository private (GitHub Pages for a private repository needs a paid plan) or run the three stages in one job, giving up the separation of the model key.
3. **Terms change.** Each source records the day its terms were read (`terms.checked`). Read them again when a source changes host or adds a licence line, and at least once a year.

## Adding a source: the checklist

1. Fetch `robots.txt` on the feed host and on the host that serves transcripts. Is the path allowed for robots in general? Is there a crawl delay?
2. Look for a licence: in the feed (`<copyright>`, `podcast:license`, a Creative Commons element), on the site's footer, on a terms or copyright page. Record the address and what it says.
3. Look for terms of use that speak about automated access, republishing or AI use.
4. Decide `publish`: `full` only when a licence or a written permission clearly allows redistributing the transcript. Otherwise `digest_only`. News is always `digest_only`.
5. Write `terms` in `config/sources.json`: the day, what each of the three says, a summary for the store card, and anything uncertain.
6. Write the credit line (`attribution`).
7. Run it offline first if you can, then once live, and read `health.json`.
8. If the publisher ever asks for removal: set `state` to `withdrawn` with `state_reason: takedown` (and `purge: true` if copies must go) in one commit. See the README.


## Decisions taken before first publication (2026-11-14)

The project owner (Bamcio Ventures LLC) delegated these decisions. They are conservative defaults, not legal advice, and any publisher can ask for a change.

1. **Every source stays `digest_only`.** No publisher clearly permits republishing transcripts, so full transcripts are never published. The transcript is used only at run time to build the digest and its pointers.
2. **Excerpts are short.** The extractive digest takes at most 1,500 characters per episode (down from 3,000), as separate short sentences with their time and a link back to the original. The quotes list is exact and short (a few lines). Everything links to the publisher's original.
3. **EFF Deeplinks** (CC BY 4.0) is carried as headline, a short summary and a link, with attribution to the Electronic Frontier Foundation on its store card.
4. **Takedown is one commit.** A publisher or anyone else can open a GitHub issue; setting the source to `withdrawn` (with `purge: true` when a deletion is requested) removes it from the next published catalog and tells apps to delete their copy. Requests are honoured promptly.
5. **Politeness.** One identifiable User-Agent that names this repository, robots.txt respected, the 30-second crawl delay for EFF honoured, conditional requests, and a few requests per source per run.
6. **No model digest by default.** The model digest is off until the owner adds an API key and turns it on; its output is validated and quotes must be exact substrings of the source text.

### Still open (owner)
Whether a given publisher is content with short excerpts in a public digest. If in doubt, ask the publisher, or switch that source to headline-only.
