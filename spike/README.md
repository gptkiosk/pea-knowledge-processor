# Briefs spike (phase 1 of the briefs plan)

Phase 2 moved the useful parts into the package: the prompt of `WRITER-PROMPT-v3.md` (with its ten extra rules) and the checks of `validate_brief.py` are in `src/pea_knowledge/brief.py`, and the pipeline writes briefs as format 1.3 (docs/FORMAT.md section 12). This folder is kept as the record of the spike.

Data and a validator for trying out model-written briefs. No brief is written here and no API key is used or needed.

## Files

- `fetch_data.py`: picks the newest 2 items of 5 active sources (ai-daily-brief, lex-fridman, diary-of-a-ceo, darknet-diaries, 80000-hours) from the live catalog, fetches each transcript from the publisher with the project's own `Fetcher` (robots.txt, polite pauses), converts it with `pipeline.read_answer` to PEA transcript v1 and writes `data/<item-id>.transcript.txt` (cut at 120,000 characters when longer; the header counts) and `data/index.json` (id, source, title, date, transcript chars, cut yes/no, the published extractive `digest_brief` for comparison). Needs the network.
- `data/`: the output. The transcripts are **git-ignored**: the sources' terms withhold them, so they are never committed. Only `index.json` is. Run `fetch_data.py` to recreate them.
- `WRITER-PROMPT.md`: the exact prompt for one transcript to one brief (strict JSON). Fill `{{SOURCE}}`, `{{TITLE}}`, `{{DATE}}`, `{{TRANSCRIPT}}`.
- `validate_brief.py`: checks a brief against its transcript. No network.
- `test_validate_brief.py`: unit tests with a tiny fixture.
- `topics.json`: copy of `config/topics.json`, the 30-term vocabulary.

## Run

From the repository root (Python 3.11, standard library only):

```
python3 -I spike/fetch_data.py                                   # once, about 10 requests
python3 -I spike/test_validate_brief.py                          # the validator's tests
python3 -I spike/validate_brief.py brief.json spike/data/<item-id>.transcript.txt
python3 -I spike/validate_brief.py --dir spike/briefs            # every spike/briefs/<item-id>.brief.json against spike/data
```

Add `--json` for machine-readable results. Exit code 1 when any brief fails.

## What the validator checks

Errors (brief fails): exact keys; counts (claims 5 to 8, quotes 0 to 2, topics 1 to 4 from the vocabulary, keywords up to 5 of at most 3 words, entities up to 12); headline 160, claim 220, new 300 characters; visible text at most 1,800; every quote a verbatim substring of the transcript (whitespace-normalized, case-insensitive, curly quotes and dashes made plain); every claim and quote ref exists (`HH:MM:SS` of a line, or `L<n>`, the n-th segment line after the header, for lines with no time); fewer than 4 claims with a valid ref.

Flags (a person looks; the brief still passes): a number in a claim not found in the transcript (digits or number words such as "two hundred"), a capitalized non-initial word in a claim not found in the transcript, an entity not found, a quote outside 8 to 40 words. Flags are a cheap heuristic and will miss paraphrased wrong facts and flag harmless words; they do not replace reading the claims against the transcript.
