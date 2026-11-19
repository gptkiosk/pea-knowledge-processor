# First real briefs (2026-11-19)

The first model briefs written against the real service, on branch `briefs-pipeline`, with the publish job switched off
(nothing was published; the output was built and checked locally from the `digested` artifact). Model
`anthropic/claude-haiku-5.5` on OpenRouter, priced in the config at USD 0.10 / 0.50 per million tokens in / out (the live
price the owner checked). Caps: `per_run_cents` 10, `monthly_cents` 200, `upgrade_per_run` 3, `max_calls_per_run` 8 on
the first run and 14 on the second.

## Runs

| Run | What happened |
| --- | --- |
| [44531904122](https://github.com/gptkiosk/pea-knowledge-processor/actions/runs/44531904122) | 0 calls. Every item was reused and no transcript was fetched, so no item could get a model brief (root cause below). |
| [44534138156](https://github.com/gptkiosk/pea-knowledge-processor/actions/runs/44534138156) | 8 calls, 2 written, 1 stopped by the 8-call limit, 3 retried, 0 fell back. 129,877 + 20,792 tokens. Logged as 0.0000 US cents: the provider gave `usage.cost` 0 for every call. At the configured prices: **2.34 US cents**. |
| [44535475325](https://github.com/gptkiosk/pea-knowledge-processor/actions/runs/44535475325) | 14 calls, 3 written, 6 retried, 0 fell back, 0 over a cap. 221,708 + 32,438 tokens, **3.84 US cents** (now priced from the tokens). |

Both real runs together: 22 calls, about 6.2 US cents. The output built from each artifact passed `validate` (0 problems,
no transcript in it) and every model brief passed the strict brief contract (`check-briefs`, branch `brief-contract`) and
a fresh run of `brief.check` against its transcript (0 errors).

## Root cause of the empty first run, and the fix

Model briefs are written only for items whose transcript is in the run's work folder. Items already published are
reused and their transcripts are not fetched again, except for the few that `upgrade_per_run` selects. The fetch job
selected those only when it believed the brief step would have a key. It never has the key, so it went by the last
published `state.json`. That file had been written by a run without a key, so it said no, and the branch run could
never change it because it publishes nothing. On `main` the first keyed run would have spent nothing and only the
second would have started upgrading.

The fix: the fetch job is now told by `PEA_BRIEFS_KEY_EXPECTED` (from the dispatch input `expect_key`, or a repository
variable of that name; it never sees a secret), and the upgrades are chosen newest first across all sources: only items
digested from a transcript, of active sources whose terms allow a model brief, while the month's cap is not spent. The
dry run fetches as a keyed run would and marks these items `upgrade of an extractive brief`.

Two more fixes came out of the real runs:

- **Cost.** OpenRouter returned `usage.cost` 0, so the run and month caps would never have been reached. Only the call
  limit stopped the first run. A call now costs the provider's figure or its tokens at the configured prices, whichever
  is higher.
- **Merge wording.** On the first run the merged Lex Fridman brief said "a three-part episode" and "covers all three
  parts". Those parts were the transcript chunks, and the transcript was cut. The merge prompt now forbids any mention
  of the parts. On the second run the headline and `new` correctly said the transcript was cut.

## Per brief (second run)

| Item | Transcript | Calls (retries) | Tokens in + out | Seconds | US cents |
| --- | --- | --- | --- | --- | --- |
| Podnews Daily, 2026-11-19 | 4 k chars, whole | 1 (0) | 3,074 + 2,295 | 8.9 | 0.15 |
| Lex Fridman #505, 2026-11-19 | 149 k chars (cut at 150,000, to 2:37:43 of 3:26:58), 3 parts + merge | 7 (3) | 142,754 + 15,227 | 61.7 | 2.19 |
| Diary of a CEO (Bernie Sanders), 2026-11-19 | 88 k chars, 2 parts + merge | 6 (3) | 75,880 + 14,916 | 58.5 | 1.50 |

Seconds per call: fastest 4.2, median 9.9, slowest 16.3. Calls run one after another, so a long episode takes about a
minute. Each retry is cheaper than the first answer, because the first answers are long: 2,300 to 4,000 output tokens
for a JSON object of about 2 KB. That suggests the provider counts reasoning tokens in `completion_tokens`, but this was
not checked.

## Monthly cost at the real cadence

From the measurements: about 0.1 US cents per brief plus about 0.75 cents per hour of audio. That is about 52,000
transcript characters an hour, with retries at the rate seen here. An episode costs at most about 2.3 cents, because a
transcript is cut at 150,000 characters. The typical episode durations and cadences are those of `store.json`.

| Source | Cadence | Typical length | Briefs / month | US cents / month |
| --- | --- | --- | --- | --- |
| Diary of a CEO | several a week | 1 h 50 | ~13 | ~19 |
| The AI Daily Brief | daily | 27 min | ~30 | ~13 |
| Podcasting 2.0 | weekly | 1 h 40 | ~4.3 | ~6 |
| Lex Fridman | fortnightly | 3 h 35 (cut) | ~2.2 | ~5 |
| Oxide and Friends | weekly | 1 h 20 | ~4.3 | ~5 |
| Podnews Daily | daily | 5 min | ~30 | ~4.4 |
| 80,000 Hours | several a week | 19 min | ~13 | ~4.3 |
| Python Bytes | weekly | 34 min | ~4.3 | ~2.2 |
| Darknet Diaries | fortnightly | 1 h 10 | ~2.2 | ~2.1 |
| Talk Python | fortnightly | 1 h 05 | ~2.2 | ~2.0 |
| Buzzcast | weekly | 16 min | ~4.3 | ~1.3 |
| **All 11 active sources** | | | **~110** | **~65 (USD 0.65)** |

A feed of five of these costs between about 10 and 50 US cents a month, depending on which five (the sum of their rows).
On top of that, upgrading the roughly 50 extractive briefs already listed is a one-off of about 40 to 60 cents, spread
over runs at `upgrade_per_run` per run. All of this is well inside the 200-cent monthly cap.

## Quality

Of the claims checked against the transcript, almost all are faithful: they keep names and numbers, and they credit
views to the speaker who holds them ("Sanders says the primary reason for the war is that Israel pushed it on Trump", "Lawton says the FBI
offered him about two years and to keep his $6.1 million"). Hedges are kept ("reportedly", "apparently", "he guesses").
Every quote is word for word. Headlines are specific. The Podnews brief is accurate throughout, and its `new` names
the shows launched that day.

Problems seen:

1. **Retries are common.** 9 of 22 calls were retries. All passed on the second try, and none fell back. Causes: a
   headline over 160 characters, mostly in partial briefs of a chunk (6 times); a keyword over 3 words ("Buy Me A
   Coffee"); a claim over 220 characters; and one answer cut at `max_output_tokens` 4,000, which left invalid JSON.
   Retries roughly doubled the cost of the long episodes.
2. **A ref can point to the wrong line.** In the Lex Fridman brief, "held in the hole for 11 straight months" has ref
   01:46:54, but it is said at 01:51:05. The checker proves only that a ref names a real line, not that the line says
   the claim.
3. **Small readings.** On the first run, "Lawton says he served six years in prison" condensed "the only man who was in
   prison for six years, and I got charged with another federal crime". On the second run the claim was dropped.
4. The run's `flags` count (6 and 5) counts flags of partial briefs too. A fresh check of the final briefs gives none.

Verdict: good enough to publish as model briefs. The checker catches the format errors and the retry mends them. The
remaining faithfulness risk is a wrong ref rather than a wrong fact.

## For the owner to decide

- **Caps.** One long episode can need up to 10 calls (4 parts and a merge, each retried once). For upgrades and new items
  together, `max_calls_per_run` about 40 and `per_run_cents` about 25 would be enough. The branch still has 14 and 10.
  The monthly cap of 200 cents is about three times the expected spend.
- **Merging `briefs-pipeline` to `main`.** It needs a rebase onto `brief-contract`, and both branches touch
  `process.yml`, `pipeline.py` and `brief.py`. After the merge, set the repository variable `PEA_BRIEFS_KEY_EXPECTED` to
  `true` so scheduled runs upgrade from the first one. Without it the second scheduled run starts upgrading, once a
  published `state.json` says the key was there.
- **Billing.** Check the OpenRouter dashboard against the 6.2 cents estimated here, since the provider reported 0 per call.
- **Optional prompt work.** Tell the chunk prompt the headline limit more firmly. Consider `max_output_tokens` 6,000, or
  a reasoning setting, if the output tokens are reasoning.
