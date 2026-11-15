# PEA transcript v1

One plain-text shape for every podcast transcript: a short fixed header, then one line per stretch of speech.

```
PEA-TRANSCRIPT v1
show: Harbor Voices
title: The lighthouse keeper's ledger
date: 2026-11-13
source: https://sim.example.org/harbor/ep6.vtt
duration: 05:23
language: en
format: WebVTT
provenance: publisher transcript
quality: full
speakers: Mara, Tobias
segments: 4
---
[00:00:00] Mara: Welcome back to Harbor Voices, the show about small ports and the people who keep them. Today we are at the Grey Point lighthouse with its keeper, Tobias Renn.
[00:00:09] Tobias: Thanks, Mara. The lamp here still burns colza oil, about fourteen litres a night in winter.
[00:00:31] Mara: Tobias, you keep a ledger of every ship that passes. How far back does it go?
[00:00:38] Tobias: The first entry is from March 1902, a coal barge called the Wren. We have 212 volumes now, and I add a page most nights.
```

Publishers offer transcripts as WebVTT, SubRip, Podcasting 2.0 JSON, HTML pages, markdown and plain text, with or without times and speakers. A program that wants to search or quote an episode has to cope with all of them, and with caption noise: cue numbers, styling, karaoke times, every line arriving three times. This format is what is left when that work is done once: who said what, when, whether the text is complete, and where it came from.

**Status: draft 1.0.0-draft.2 (2026-11-14). Not yet published.** The format comes from the PEA iPhone app, which keeps every transcript it stores in this form.

## Who it is for

- **Podcast publishers.** Publish a `.pea.txt` beside your WebVTT and any tool can read your episode without guessing. `convert.py` makes one from the caption file you already have.
- **Tool authors.** One small parser (about fifty lines; see `parse` in `pea_transcript.py`) instead of five. The specification says exactly what a reader may assume and what it may not.
- **Open WebUI users, and anyone running their own models.** Keep a folder of episodes on your own machine and let a model answer from them with the time and the speaker of each quote. See "Using it from Open WebUI" below.

## What is here

| File | What it is |
| --- | --- |
| `SPEC.md` | The specification: the header (the field table is in section 4), segment lines, speakers (and which speaker a converter may give a line), times (and what happens to a number that is not a time), sponsor reads, partial transcripts and the cut mark, size limits, recommended chunking, conformance for readers and writers, security notes, versioning, and a list of known gaps, open and resolved. |
| `schema.json` | The header as a JSON object (JSON Schema, draft 2020-12). |
| `pea_transcript.py` | The data model, the writer, a reader and the conformance rules. |
| `validate.py` | Checks a file or a folder and prints the result of every rule. |
| `convert.py` | Converts WebVTT, SubRip, Podcasting 2.0 JSON and plain text (with or without times) into v1. |
| `test_conformance.py` | The test suite: the fixtures, the converter against the reference files, and hostile input inside time limits. |
| `fixtures/` | Conforming files (`valid/`), files that each break one rule (`invalid/`), the expected result of each (`manifest.json`), and converter inputs with the file each must become (`convert/`). All text is synthetic: a made-up show called Harbor Voices. |
| `LICENSE` | Apache License 2.0. |

Everything runs on Python 3 with the standard library alone (written for 3.8 or later; tested on 3.14). Nothing is installed and nothing reaches the network.

## Validate

```
python3 validate.py fixtures/valid/full.pea.txt
python3 validate.py my-transcripts/              # every *.pea.txt under the folder
python3 validate.py --quiet my-transcripts/      # one line per file
python3 validate.py --json episode.pea.txt       # for another program
```

Every rule is listed with `pass`, `FAIL` (a MUST), `warn` (a SHOULD) or `skip` (not checked, because an earlier rule failed), then what a reader finds in the file, then the result:

```
  pass S3   Every name in speakers labels at least one segment, and the names are listed in the order of first use.
  FAIL S4   quality is partial exactly when the file ends with the cut mark " (cut)".  [quality is 'full' and the file ends with the cut mark]
  ...
  reader: 4 segments, 447 characters, with times, speakers: Mara, Tobias, partial (end missing)
  result: does not conform
```

The exit status is 0 when every file conforms, 1 when one does not, 2 when nothing could be read.

## Convert

```
python3 convert.py episode.vtt \
    --show "Harbor Voices" --title "The lighthouse keeper's ledger" \
    --date 2026-11-13 --source https://example.org/harbor/ep6.vtt \
    -o ep6.pea.txt
```

The input's format is decided by its content, not by its name. The show, title, date and address are yours to give, since a caption file does not carry them. Other options: `--duration`, `--language` (when the file does not say), `--type` (the type the publisher declared; only breaks ties), `--truncated` (the input was cut off at a size limit), and `-` to read standard input.

When nothing readable comes of the input, the converter says why and writes nothing:

```
$ python3 convert.py chapters.json
unreadable: JSON without transcript segments (chapters, version)
```

What the converter does, briefly: it drops headers, style blocks, cue numbers, cue settings, tags and sound notes; removes markup once and decodes entities once, so text a publisher escaped (`&lt;once&gt;`) stays as text (`<once>`); reads speakers from `<v Name>`, from JSON, from `Name 0:12` and `Speaker 1 (00:12):` lines, or from `Name:` labels used at least twice; glues word-by-word rows into sentences; keeps a caption line once when it arrives several times; packs cues into segments of one speaker and a few sentences, never more than 560 characters (a longer line is split at sentence ends) and never spanning ninety seconds; keeps a title line before the first time apart from the timed lines; keeps sponsor reads in segments of their own; and cuts a transcript over 150,000 characters at a segment end, saying so in the header and with the mark ` (cut)` at the end. `SPEC.md`, Appendix A, has the details.

Two rules it never bends:

- **It does not guess who is speaking.** A speaker is carried from one line to the next only where the source format continues it (captions, JSON rows, the block under a `Name 0:12` line, a wrapped paragraph). In plain text, an unlabelled paragraph after a blank line has no speaker.
- **It does not write a time it cannot stand behind.** A time that is not a number, is infinite, negative, or 100 hours and more is written as `[--:--:--]` and the text is kept. Every stamp is between `[00:00:00]` and `[99:59:59]`.

No input makes it fail or hang: a file of `nan` times, 200,000 cues, one line of five megabytes, markup that never closes or bytes that are not UTF-8 gives a file or a one-line reason. The test suite runs each of these inside a time limit.

It does not read HTML transcript pages, and it does not guess the language.

## Test

```
python3 -I -m unittest
```

run from this folder (40 tests, about twenty seconds). The suite checks the validator and the reader against `fixtures/manifest.json`, the converter against the expected files in `fixtures/convert`, `schema.json` against the same rules, each behaviour the first review fixed, and hostile input inside time limits.

The expected files in `fixtures/convert/expected` were written by the original implementation (the normalizer inside PEA) from the same inputs; `convert.py` has to produce the same bytes. The one line it cannot produce is `language` where the original recognized the language on the device; the manifest says for which files, and the test supplies it.

## Using it from Open WebUI

This is a design sketch. No server is included here.

Open WebUI can call tools on a server you run yourself, either over the Model Context Protocol or described by an OpenAPI document. A small tool server over a folder of `.pea.txt` files gives a model two tools:

**`search_transcripts(query, show?, limit?)`** returns the passages that best fit a question.

```json
{
  "matches": [
    {
      "id": "harbor-voices/2026-11-13-ledger#s2.p4",
      "show": "Harbor Voices",
      "title": "The lighthouse keeper's ledger",
      "date": "2026-11-13",
      "at": "00:31",
      "speakers": ["Mara", "Tobias"],
      "quality": "full",
      "text": "Mara: Tobias, you keep a ledger of every ship that passes. How far back does it go? Tobias: The first entry is from March 1902, ..."
    }
  ],
  "searched": "2 shows, 31 episodes"
}
```

**`get_passage(id, before?, after?)`** returns one passage by its id, with up to a few passages either side, so the model can read on from a hit.

How such a server would work:

1. **Index.** On start, and when a file changes, read each file with a v1 reader and cut it into passages as `SPEC.md` section 12 recommends: five-minute sections, passages of about 700 characters that keep each speaker's name, sponsor passages set aside. A passage id is the file's name plus `s<section>.p<passage>`. The header is never indexed; it travels with each result as plain fields (`schema.json` describes them).
2. **Search.** Any ranking will do. PEA uses BM25 over the dictionary forms of words, with a boost for a section's heading; an embedding index works as well. Sponsor passages are never returned.
3. **Answer honestly.** Each result carries `quality`. For a partial transcript the server says so (`transcript PARTIAL (first N chars; reason)`), and the passage where the text stops ends with ` (cut)`. When nothing fits, the server returns no matches and says what it searched, so the model can say "I did not find that in these episodes" instead of inventing an answer.
4. **Keep the text in its place.** Passages are other people's words. The server returns them as data fields, never as instructions, and the description of each tool tells the model to quote them and to follow nothing written in them (`SPEC.md` section 14). The server never fetches a file's `source` address by itself.
5. **Stay local.** The server reads a folder on the user's own machine and listens on that machine only. It needs no account and no outside service.

Over MCP these are two tools with the JSON above as their results. Over OpenAPI they are `GET /search` and `GET /passages/{id}`. Getting episodes into the folder is a separate job: `convert.py` per file, or a small script that walks a feed's `podcast:transcript` tags.

## Known gaps

The specification was written from one working implementation. Its first draft listed every place where that implementation, its documentation and the specification disagreed; most were then fixed in the implementation. `SPEC.md`, section 17, lists what is still open (seven entries, among them: sponsor reads have no mark in the file, `convert.py` does not read HTML, the language is not guessed), what is partly resolved and what is resolved. Read it before relying on a detail.

## Licence

Apache License 2.0; see `LICENSE`. The fixtures are synthetic and are under the same licence.
