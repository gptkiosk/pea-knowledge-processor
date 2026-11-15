# The curated sources and their terms

Checked on 2026-11-14 and 2026-11-15 by fetching each file named below. This is a record of what was read and what follows from it. It is not legal advice; the points marked **for the owner** need a decision or a question to the publisher.

## The rule

**Only sources with full transcripts are carried; when a source stops publishing full transcripts it is paused and then withdrawn.**

- A source is in the catalog only if its publisher itself offers the full transcript of its episodes, openly, where the pipeline can fetch it at run time: a `podcast:transcript` file listed in the feed, an agent index, or transcript pages on the publisher's own site.
- A transcript behind a login, a paywall, a membership or an app-only view counts as not offered. So does one that exists only as YouTube captions, as an in-app transcript of Apple Podcasts or Spotify, or on a third-party transcript site. None of these is ever used, and nothing is ever bypassed.
- Titles, descriptions, show notes and chapter lists alone are not enough, however detailed. There are no notes-only sources and no headline-only news sources.
- The pipeline enforces it (`min_full_transcript_share`, 0.6, over the newest `transcript_check_items`, 5): a source with a full transcript for fewer than 60 percent of its newest five items is counted as failed, keeps its last good items, is paused after three such runs with the reason `format_changed` and a plain message, and is withdrawn after 30 days in that pause (`withdraw_without_transcripts_days`). It is still read every run and comes back by itself when the transcripts do. One item without a transcript in a source that otherwise has them still gets a digest from its notes, graded `partial` or `headline`.
- Every source's `publish` level is `digest_only`: the transcript is read at run time to build the digest and is never written to the public output; the item says `withheld_terms` and `read: full`. `full` would need a licence or a written permission that clearly allows redistributing the transcript. No source has one.
- A digest takes at most `excerpt_budget_chars` characters (1,500) from a transcript, as short separate sentences with the time and a link back. The members format 1.1 added (chapters, moments, recap cards) reuse those same sentences and take no more.
- `robots.txt` is obeyed on every host, also the host a transcript or a chapter file is served from, and a `Crawl-delay` is honoured (up to 30 seconds). One User-Agent that names this repository; conditional requests; a pause between requests to one host.
- Every item links back to the publisher (its own page where the feed gives one, otherwise the show's site, marked `link_kind: show`), and every listing carries an attribution line.

## The sources (12)

Each entry in `config/sources.json` records the feed and site, the adapter, `transcript_route`, `chosen_because`, the hosts, the store card and the `terms` that were read. The table is the summary; the notes below it say what is uncertain.

| Source | Feed | Full transcript route | Per-episode link | Cadence | robots.txt | Licence or terms found |
| --- | --- | --- | --- | --- | --- | --- |
| The AI Daily Brief (`ai-daily-brief`) | `https://aidailybrief.ai/agent.json` | agent.json lists a markdown transcript with a time every minute for every edition. | yes | daily | Allows everything for every robot except /admin, /api/admin and one sponsor page. Read 2026-11-14. | No licence statement was found: not in agent.json, not in llms.txt, and there is no page at /terms (404). The site publishes agent.json and llms.txt as a machine-readable offering for agents, listing a page, a markdown twin, structured JSON and a transcript for each edition. That invites reading; it says nothing about republishing. |
| Podcasting 2.0 (`podcasting-20`) | `https://feeds.podcastindex.org/pc20.xml` | podcast:transcript in the feed: SubRip captions on mp3s.nashownotes.com for every episode. | yes (podpage.com) | weekly | No robots file on the feed host (404), so nothing is restricted. The transcript host (mp3s.nashownotes.com) has one that disallows nothing and asks for ten seconds between requests. | The feed states no licence and no copyright line. It is marked podcast:locked, which is about moving the feed to another host, not about the content. None found for the show. |
| Build Your SaaS (`build-your-saas`) | `https://feeds.transistor.fm/build-your-saas` | podcast:transcript in the feed: WebVTT, SubRip, JSON and text on share.transistor.fm for every episode. | yes (share.transistor.fm) | rare (newest 2026-04-17) | The transcript host allows everything for robots in general. The feed host answers 400 for robots.txt, which restricts nothing. | The feed carries a copyright line (Transistor, Inc.) and no licence. None found for the show itself. The hosting company's general terms were not read. |
| Buzzcast (`buzzcast`) | `https://rss.buzzsprout.com/231452.rss` | podcast:transcript in the feed: SubRip, WebVTT and JSON on www.buzzsprout.com for 257 of 269 episodes. | yes, from the enclosure (the feed has no link) | weekly | Disallows one unrelated feed only; the show's feed and transcript files are not restricted. | The feed carries a copyright line (Buzzsprout) and no licence. It is marked podcast:locked. None found for the show itself. The hosting company's general terms were not read. |
| The Diary Of A CEO (`diary-of-a-ceo`) | `https://rss2.flightcast.com/xmsftuzjjykcmqwolaqn6mdn.rss` | podcast:transcript in the feed: WebVTT on rss.flightcast.com for the newest episodes (335 of 910 entries; all of the newest eight). | **no**: links to the show | twice a week | Allows everything for robots in general except a few administrative paths, and asks for one second between requests. The feed host rss2.flightcast.com restricts nothing that the run reads. Read 2026-11-15. | The feed carries no copyright line and no licence. podcast:locked is no. The hosting company's terms (last updated 2026-08-15) bar reaching its services by bots, crawlers or scrapers without permission, search engines and browsers excepted. They do not say how a published RSS feed and the transcripts it lists may be read by others. |
| Lenny's Podcast (`lennys-podcast`) | `https://api.substack.com/feed/podcast/10845.rss` | podcast:transcript in the feed: WebVTT on api.substack.com for 350 of 369 episodes. | yes | weekly | For robots in general it disallows private feeds, sign-in and a few interface paths; the public podcast feed and the transcript files are not among them. Read 2026-11-15. | The feed's copyright line names Lenny Rachitsky; no licence. The hosting company's terms (last updated 2026-10-06) forbid crawling, scraping or spidering any part of Substack and copying a significant portion of its content. They do not mention RSS feeds. |
| Darknet Diaries (`darknet-diaries`) | `https://podcast.darknetdiaries.com/` | podcast:transcript in the feed: WebVTT or text on f.prxu.org for 177 of 183 episodes; the site also has a transcript page for each episode. | yes | fortnightly | The feed host podcast.darknetdiaries.com has no robots file (404), which restricts nothing; the transcript host f.prxu.org did not restrict the transcript files. Checked by the run of 2026-11-15. | The feed's copyright line names Jack Rhysider; the site's footer has a bare copyright year. No licence. No terms page was found on the site (its footer links to none). |
| 80,000 Hours Podcast (`80000-hours`) | `https://feeds.transistor.fm/80000-hours-podcast` | podcast:transcript in the feed: plain text on share.transistor.fm for the newer episodes (209 of 370; all of the newest eight). | yes | several a week | The transcript host allows everything for robots in general. The feed host answers 400 for robots.txt, which restricts nothing. Read 2026-11-15. | The feed says all rights reserved. The site's legal page says its materials are copyrighted, all rights reserved, and asks to be contacted before redistributing, translating or adapting them. Nothing on automated access. |
| Talk Python To Me (`talk-python`) | `https://talkpython.fm/episodes/rss` | podcast:transcript in the feed: WebVTT on talkpython.fm for every episode; the publisher also keeps the transcripts in a public repository and invites their use. | yes | weekly | The feed and the transcript files are on this one host; its robots file was read by the run of 2026-11-15 and did not restrict them. | The feed has a copyright line without a licence. The publisher's public transcript repository says to feel free to use the files to explore the conversations; the name of its licence was not read. None found on the episode pages. |
| Python Bytes (`python-bytes`) | `https://pythonbytes.fm/episodes/rss` | podcast:transcript in the feed: WebVTT on pythonbytes.fm for every episode. | yes | weekly | The feed and the transcript files are on this one host; its robots file was read by the run of 2026-11-15 and did not restrict them. | The feed has a copyright line without a licence. None read. |
| Oxide and Friends (`oxide-and-friends`) | `https://feeds.transistor.fm/oxide-and-friends` | podcast:transcript in the feed: WebVTT, SubRip, JSON and text on share.transistor.fm for every episode. | yes (share.transistor.fm) | weekly | The transcript host allows everything for robots in general. The feed host answers 400 for robots.txt, which restricts nothing. Read 2026-11-15. | The feed's copyright line names Oxide Computer Company; no licence. None found for the show. The hosting company's general terms were not read. |
| Podnews Daily (`podnews-daily`) | `https://podnews.net/rss` | podcast:transcript in the feed: WebVTT on podnews.net for 150 of 151 episodes. | yes | daily | The feed and the transcript files are on this one host; its robots file was read by the run of 2026-11-15 and did not restrict them. | The feed's copyright line names Podnews LLC; no licence. None read. |

What is uncertain, per source (**for the owner**):

- **The AI Daily Brief.** Whether the publisher is content with short quoted excerpts in a public digest. Reading is clearly invited; republishing is not addressed. Asking the publisher would settle it. Chosen because: The owner's daily AI show; number five on Snipd's most-listened list (read 2026-11-15); the publisher offers transcripts to agents in machine-readable form.
- **Podcasting 2.0.** The show is produced on a value-for-value basis and its makers promote open use of feeds, but no licence says so in writing. If the owner wants full transcripts published, ask the publisher. Chosen because: The show of the people who define podcast:transcript; every episode has captions, chapters and named people in the feed.
- **Build Your SaaS.** The hosting company's terms of service were not read; they govern its customers more than readers of a feed, but the owner may want to check. Chosen because: Full transcripts with named speakers in four formats. Episodes are rare (the newest is from April 2026): the first candidate to drop if the list must shrink.
- **Buzzcast.** The transcript marks a speaker only where the speaker changes, so a quote can be credited to the previous speaker. Speaker names in this source's quotes should be treated as likely, not certain. Chosen because: Weekly, with transcripts, chapter marks and soundbites in the feed.
- **The Diary Of A CEO.** The hosting company's terms forbid automated access to its services in general words; a podcast feed and the files it lists exist to be read by programs, but the terms do not say so. Asking the publisher would settle it. The feed gives no page per episode, so every item links to the show's site and is marked link_kind show. Chosen because: Named by the owner; number two on Snipd's most-listened list (read 2026-11-15). The publisher's own feed carries full WebVTT transcripts.
- **Lenny's Podcast.** The hosting company's terms forbid crawling and scraping in general words while its robots file leaves the public feed open, and a podcast feed exists to be read by programs. Whether reading the transcript files the feed lists is within those terms is not stated. The owner should decide or ask the publisher. Chosen because: Number nine on Snipd's most-listened list (read 2026-11-15); full WebVTT transcripts, chapter lists and per-episode pages in the publisher's feed.
- **Darknet Diaries.** No terms of use were found, so nothing is written either way about short quoted excerpts in a public digest. Chosen because: A widely followed security show that publishes a full transcript for nearly every episode, with a page per episode.
- **80,000 Hours Podcast.** The publisher asks to be contacted before its work is adapted. A digest with short quotes is not redistribution of the work, but asking would be courteous and would settle it. Chosen because: Full transcripts in the feed, long notes, a page per episode; a strong source on AI policy and safety.
- **Talk Python To Me.** The licence file of the publisher's transcript repository was not read. If it allows redistribution, this source could publish full transcripts. Chosen because: Every one of 567 episodes has a transcript in the feed, and the publisher says of them: feel free to use the files.
- **Python Bytes.** The site's terms were not read. Chosen because: Short, weekly, and every one of 504 episodes has a transcript in the feed; a sister show of Talk Python To Me.
- **Oxide and Friends.** The hosting company's terms of service were not read. Chosen because: Every one of 192 episodes has a transcript with named speakers; the feed names the people in each episode.
- **Podnews Daily.** The site's terms were not read. Chosen because: Daily and short, with a transcript for nearly every episode and a page per episode.

A live run on 2026-11-15 read all twelve: 56 items, 55 full transcripts fetched and converted, no source failed. One chapter file (Podcasting 2.0, on `reflex.livewire.io`) is disallowed by that host's robots file and was not read; the chapters of those items are cut from the transcript instead.

## Removed from the catalog

- **EFF Deeplinks** (`eff-deeplinks`), one of the first five. It is a news feed carried as headline, short description and link. It has no transcript, so it fails the rule. Removing it from the config makes the next run list it as withdrawn ("The curator removed this source.") for 90 days, so every app learns of it; nothing is purged on the phones. The other four of the first five pass and stay.

## The four shows the owner named first

| Show | Result | Evidence (read 2026-11-15) |
| --- | --- | --- |
| The Diary Of A CEO (Steven Bartlett) | **Pass, carried** | The publisher's feed `https://rss2.flightcast.com/xmsftuzjjykcmqwolaqn6mdn.rss` lists a WebVTT transcript on `rss.flightcast.com` for 335 of 910 entries, all of the newest eight; the live run fetched five. The transcript host's robots file allows it (Crawl-delay 1). The feed gives no page per episode. Flag: the host's terms forbid automated access in general words (see above). |
| Huberman Lab | **Fail** | No transcript in the feed `https://feeds.megaphone.fm/hubermanlab`. The episode page on hubermanlab.com says full episode transcripts are for Huberman Lab Premium members. A membership is a paywall. Scicomm Media's copyright guidelines also ask for permission before content is adapted. |
| Hard Fork (The New York Times) | **Fail** | No transcript in the feed `https://feeds.simplecast.com/l2i9YnTd`, and every item links to the same column page, not to an episode. Transcripts are on nytimes.com article pages, which sit behind the subscription. `https://www.nytimes.com/robots.txt` disallows the whole site for AI robots by name (anthropic-ai, ClaudeBot, GPTBot, CCBot), and the publisher's feeds say RSS is for personal use in a news reader or a non-commercial blog, subject to its terms of service. The terms page itself could not be fetched. |
| Your Undivided Attention (Center for Humane Technology) | **Fail** | No transcript in the feed `https://feeds.simplecast.com/rZ0cYk12` (172 entries, none with `podcast:transcript`). The two newest episode pages on humanetech.com were fetched: show notes and recommended reading, and the word "transcript" does not occur in the page. The Simplecast page has none either. humanetech.com's robots file allows everything, so an open transcript there would be readable; its terms of use forbid reproducing the site's material. |

## Snipd's ten most-listened shows

Ranking source: `https://share.snipd.com/top-podcasts` ("Most listened podcast of the Snipd app"), linked from the footer of snipd.com as "Popular podcasts"; read 2026-11-15. The page states no method and no date. Only the public names and their order were read; no transcript, summary, chapter or other output of Snipd was read or used. Everything below comes from the publishers' own feeds and sites.

| # | Show | Feed | Publisher's full transcript | Decision |
| --- | --- | --- | --- | --- |
| 1 | Modern Wisdom | `https://feeds.megaphone.fm/SIXMSB5088139739` (over 8 MB) | None in the feed. Notes have 14 to 35 chapter lines. The publisher's site was not searched further. | **Dropped: no official transcript.** |
| 2 | The Diary Of A CEO | `https://rss2.flightcast.com/xmsftuzjjykcmqwolaqn6mdn.rss` | WebVTT in the feed for new episodes. | **Carried with transcripts.** |
| 3 | Huberman Lab | `https://feeds.megaphone.fm/hubermanlab` | Members only. | **Dropped: transcript behind a membership.** |
| 4 | All-In | `https://allinchamathjason.libsyn.com/rss` | None in the feed; notes are a chapter list of five or six lines. | **Dropped: no official transcript.** |
| 5 | The AI Daily Brief | `https://aidailybrief.ai/agent.json` | A markdown transcript for every edition, offered to agents. | **Carried with transcripts.** |
| 6 | The Cal Newport Show | `https://feeds.buzzsprout.com/1121972.rss` | None in the feed; no page per episode. | **Dropped: no official transcript.** |
| 7 | The Tim Ferriss Show | `https://rss.art19.com/tim-ferriss-show` (over 8 MB) | Free on tim.blog for every episode, with written terms: up to 500 words may be quoted non-commercially with credit and a link. But tim.blog answers 403 to this pipeline's client, for its robots file and for the transcript index alike, and the feed has no transcript and no page per episode. | **Dropped: the site refuses automated clients.** Passing needs the publisher's permission or a transcript in the feed. |
| 8 | The Daily (The New York Times) | `https://feeds.simplecast.com/54nAGcIl` (over 8 MB) | None in the feed; as Hard Fork. | **Dropped: subscription and terms.** |
| 9 | Lenny's Podcast | `https://api.substack.com/feed/podcast/10845.rss` | WebVTT in the feed for 350 of 369 episodes. | **Carried with transcripts** (flag: the host's terms). |
| 10 | My First Million | `https://feeds.megaphone.fm/HS2300184645` | None in the feed. Notes have chapter lines. | **Dropped: no official transcript.** |

Three of the ten pass.

## Other candidates that were checked

| Show | Result | Evidence (read 2026-11-15) |
| --- | --- | --- |
| Darknet Diaries, 80,000 Hours Podcast, Talk Python To Me, Python Bytes, Oxide and Friends, Podnews Daily | **Carried** | Full transcripts listed in the feed; see the table above. |
| Lex Fridman Podcast | **Passes the rule, not carried yet** | Each episode's notes link to a full transcript page on lexfridman.com (one was fetched: open, about 187,000 characters); the robots file restricts only ia_archiver; no terms were found. The pipeline reads transcript files, not web pages, so this needs a reader for HTML transcript pages first. |
| 99% Invisible | **Passes the rule, not carried yet** | Episode pages link to `/episode/<name>/transcript`, open without sign-in. Same need: an HTML transcript reader. Terms not read. |
| Syntax | **Not verified, not carried** | No transcript in the feed (`https://feed.syntax.fm/rss`, over 8 MB). Its episode pages are said to carry transcripts; not read. |
| Freakonomics Radio | **Fail as it stands** | The transcript is on each episode page, open, but the feed links every item to the home page, so the pipeline cannot find the page for an episode. |
| Dwarkesh Podcast | **Passes, held back** | WebVTT in the feed for the newest eight (79 of 146). Hosted on Substack: the same terms question as Lenny's Podcast. Add it when the owner has decided that question. |
| Latent Space | **Not carried** | WebVTT for five of the newest eight; the feed is on Substack while pages and transcripts are on beehiiv, so it is mid-move; notes are one or two sentences. Look again later. |
| Changelog shows | **Fail** | `https://changelog.com/robots.txt` disallows everything for robots in general. |
| This American Life | **Not verified, not carried** | Nothing in the feed (`https://www.thisamericanlife.org/podcast/rss.xml`, 16 entries with short notes). Its site is said to have transcript pages; they and its terms were not read. It would need the HTML transcript reader too. |
| Radiolab | **Fail** | No transcript in the feed; every item links to the home page. |
| Acquired | **Fail** | A transcript file for 5 of 218 entries only. |
| The Vergecast, The Dr. Hyman Show | **Fail** | No transcript in the feed (checked `feeds.megaphone.fm/vergecast` and `/thedoctorsfarmacy`); no page per episode. |
| Software Engineering Daily, Conversations with Tyler, EconTalk, Coder Radio, Security Now, Hacker Public Radio, Rework | **Fail** | No transcript file in the feed (Rework lists only an HTML page and has no new episode since August 2026). |
| NPR shows, Hidden Brain, 10% Happier, On Purpose, Feel Better Live More | **Not verified** | Their feeds were not located or not read in this round. Nothing was found that shows an open official transcript. Not carried. |
| News feeds with open licences (EFF, Global Voices CC BY 3.0, NASA, The Conversation, ProPublica) | **Out of scope** | No transcripts: the rule excludes headline-only sources. |

## What to ask a publisher for

The same request fits every show that failed: **a `podcast:transcript` tag in the public feed, pointing to a WebVTT, SubRip, JSON or plain-text file that anyone can fetch**, or written permission to read the transcript pages of its site with this project's robot. For shows with members-only transcripts (Huberman Lab) that means opening them; for The Tim Ferriss Show it means letting the robot through or listing the files in the feed (his terms already allow short non-commercial quotes); for The New York Times it means a licence. And for the hosts whose terms speak against automated access in general words (Flightcast for The Diary Of A CEO, Substack for Lenny's Podcast): one sentence from the publisher that reading the feed and the transcripts it lists is fine.

## What is uncertain overall

1. **Short excerpts from `digest_only` transcripts.** Extractive digests are made of sentences from the transcript (up to 1,500 characters per episode, well under a tenth of it), with a link back. Whether that is acceptable to each publisher is a judgment this project cannot make for them. Options: lower `excerpt_budget_chars`, switch on the model digest (it paraphrases; only the quotes and moments are verbatim), or ask the publishers.
2. **Hosting companies' terms.** Flightcast and Substack forbid bots and scraping in general words; their robots files leave the feeds and transcript files open. The owner should decide whether to keep those two sources before or after asking.
3. **The work folder in CI.** Between the jobs of a run, normalized transcripts travel as a workflow artifact kept for one day. In a public repository, signed-in GitHub users can download artifacts of a run. That is a short-lived copy of transcripts that are not meant to be republished. If this matters, make the repository private (GitHub Pages for a private repository needs a paid plan) or run the three stages in one job, giving up the separation of the model key.
4. **Guests and named resources are found by pattern.** A name is always the publisher's own (its marks, title, notes or transcript), but which names are guests or resources can be wrong. The hosts listed for each source are never listed as guests.
5. **Terms change.** Each source records the day its terms were read (`terms.checked`). Read them again when a source changes host or adds a licence line, and at least once a year.

## Adding a source: the checklist

1. Does the publisher itself offer the full transcript, openly, where the pipeline can fetch it? If not, stop: the source is not added.
2. Fetch `robots.txt` on the feed host and on the host that serves transcripts. Is the path allowed for robots in general? Is there a crawl delay?
3. Look for a licence: in the feed (`<copyright>`, `podcast:license`, a Creative Commons element), on the site's footer, on a terms or copyright page. Record the address and what it says.
4. Look for terms of use that speak about automated access, republishing or AI use, also those of the hosting company.
5. Decide `publish`: `full` only when a licence or a written permission clearly allows redistributing the transcript. Otherwise `digest_only`.
6. Write the entry in `config/sources.json`: `terms` (the day, what each of the three says, a summary for the store card, and what is uncertain), `transcript_route`, `chosen_because`, `hosts`, the credit line.
7. Run it once live and read the summary: every new item should say a transcript was read.
8. If the publisher ever asks for removal: set `state` to `withdrawn` with `state_reason: takedown` (and `purge: true` if copies must go) in one commit. See the README.

## Decisions taken (2026-11-14 and 2026-11-15)

The project owner (Bamcio Ventures LLC) took or delegated these decisions. They are conservative defaults, not legal advice, and any publisher can ask for a change.

1. **Only sources with full transcripts** (2026-11-15), as stated at the top. A smaller catalog is fine: quality over count, no padding.
2. **Every source stays `digest_only`.** No publisher clearly permits republishing transcripts.
3. **Excerpts are short**: at most 1,500 characters per episode, as separate short sentences with their time and a link back.
4. **No transcription of audio, no YouTube, no Apple Podcasts or Spotify, no third-party transcript sites.**
5. **Takedown is one commit.** A publisher or anyone else can open a GitHub issue; setting the source to `withdrawn` (with `purge: true` when a deletion is requested) removes it from the next published catalog and tells apps to delete their copy.
6. **Politeness.** One identifiable User-Agent that names this repository, robots.txt respected, conditional requests, and a few requests per source per run (about 100 on a first run, about 20 on a run that finds nothing new).
7. **No model digest by default.** It is off until the owner adds an API key and turns it on; its output is validated and quotes must be exact substrings of the source text.
