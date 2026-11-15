# PEA transcript v1

**Specification 1.0.0-draft.2, 2026-11-14. Status: draft, not yet published.**

PEA transcript v1 is a plain-text format for the transcript of one spoken episode (a podcast, a talk, a broadcast). Whatever a publisher offers (WebVTT, SubRip, Podcasting 2.0 JSON, an HTML page, markdown or plain text, with or without times and speakers) becomes the same thing: a short fixed header, then one line per stretch of speech.

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

This document was derived from the implementation in the PEA iPhone app (called the reference implementation below: its writer, its reader and its normalizer). A first draft recorded every place where that code, its documentation and this text disagreed. Most of those were then fixed in the code; [section 17, Known gaps](#17-known-gaps) lists what is still open and what was resolved, and nothing there has been smoothed over.

## 1. Purpose and scope

The format exists so that a program which searches, quotes or summarizes episodes can read every transcript the same way, and can say truthfully what it holds:

- where in the episode a sentence was said (a time to the second, when the publisher gives times);
- who said it (when the publisher names speakers);
- whether the text is the whole transcript or only its first part, and why;
- which lines are sponsor reads, so they are not offered as content;
- where the text came from and who made it.

It is a storage and interchange format for finished text. It is not a caption format: it has no end times, no positioning and no styling, and it cannot be played against audio frame by frame. It does not describe audio, chapters or show notes.

## 2. Terms

The key words MUST, MUST NOT, REQUIRED, SHALL, SHALL NOT, SHOULD, SHOULD NOT, RECOMMENDED, MAY and OPTIONAL are to be interpreted as described in RFC 2119 and RFC 8174 when, and only when, they appear in capitals.

- **File**: one transcript in this format, whether stored as a file of its own or carried inside something else (Appendix B).
- **Writer**: a program that produces a file. **Reader**: a program that consumes one. **Converter**: a writer that makes a file from a transcript in another format.
- **Segment**: one line of speech after the header: one speaker, one starting time.
- **Character**: one Unicode code point. (The reference implementation counts differently for some text; see G-9.)
- **Space**: U+0020. **LF**: U+000A.
- Rule ids in parentheses, such as (H7), name the conformance rules of section 13.2. `validate.py` reports each by its id.

## 3. The file

### 3.1 Name and media type

A file stored by itself SHOULD have a name ending in `.pea.txt` and SHOULD be served as `text/plain; charset=utf-8`. No media type is registered. (The name is proposed by this specification; PEA does not store transcripts as files of their own. See G-10.)

### 3.2 Encoding and line ends

- The file MUST be UTF-8 without a byte order mark and MUST NOT contain U+0000 (F1).
- Lines MUST be separated by LF alone. CR (U+000D) MUST NOT appear anywhere (F2).
- The file MUST NOT end with a line break: its last character is the last character of the last segment, or of the cut mark (F3). A reader MUST accept line breaks at the very end all the same, and removes them before it looks for the cut mark (section 13.1).
- Three backticks in a row (U+0060 three times) MUST NOT appear anywhere in the file (F4). A writer replaces them with three apostrophes (`'''`). See section 14.
- Control characters other than LF SHOULD NOT appear (W4). A converter turns each control character and each line or paragraph separator (U+0000 to U+001F, U+007F to U+009F, U+2028, U+2029) inside a line of speech or a speaker's name into a space.

### 3.3 Layout

```
line 1        PEA-TRANSCRIPT v1
lines 2-12    the eleven header lines, in the fixed order
line 13       ---
lines 14-     one segment per line
```

There are no blank lines, no comments and no continuation lines.

## 4. The header

Line 1 MUST be exactly `PEA-TRANSCRIPT v1` (H1). Lines 2 to 12 MUST be the eleven keys below, in this order, each written as the key, a colon, one space, and the value (H2). Line 13 MUST be exactly `---` (H3). Every key is REQUIRED; a value that is not known is written with the word given in the table, never left out. Keys are lower case. A file conforming to this version MUST NOT contain other keys.

| # | Key | Value | When not known | Limit | Rules |
| --- | --- | --- | --- | --- | --- |
| 2 | `show` | The show's name. | empty (the line is `show: `, with the space) | 200 characters | H4, H14 |
| 3 | `title` | The episode's title. | empty (`title: `) | 200 characters | H4, H14 |
| 4 | `date` | The episode's date. SHOULD be `YYYY-MM-DD` (W1). | `unknown` | 1 to 40 characters | H5, H14 |
| 5 | `source` | The public address the transcript was read from. | `unknown` | 1 to 400 characters | H6, H14 |
| 6 | `duration` | The episode's length: `MM:SS` under an hour, `H:MM:SS` from one hour on. | `unknown` | | H7 |
| 7 | `language` | The language of the text. SHOULD be a BCP 47 tag such as `en` or `zh-Hans` (W2). | `unknown` | 1 to 12 characters: ASCII letters, digits, `-` and `_` | H8 |
| 8 | `format` | What the transcript was written in before it was normalized: one of the six values below. | (always known) | | H9 |
| 9 | `provenance` | Who made the text, in a few words. | (always given) | 1 to 80 characters | H10, H14 |
| 10 | `quality` | `full`, or `partial (reason)`. Section 9. | (always given) | reason 1 to 120 characters | H11, H14, S4 |
| 11 | `speakers` | The speakers' names in the order they first speak, joined by a comma and a space. Section 6. | `none` | each name 1 to 40 characters | H12, S3 |
| 12 | `segments` | The number of segment lines that follow, in decimal digits with no leading zero. | (always known) | | H13 |

`schema.json` describes the same header as a JSON object (JSON Schema, draft 2020-12), for tools that pass headers around as JSON.

### 4.1 One-line values

The values of `show`, `title`, `date`, `source`, `provenance` and `quality` MUST have no space at either end and no two spaces in a row (H14). A writer makes a value fit by replacing three backticks with three apostrophes, turning every line break into a space, collapsing runs of spaces into one, and then cutting the value at its limit.

A value MAY contain a colon followed by a space; the key ends at the first colon-space on the line.

### 4.2 `duration`

Under one hour the value is two digits of minutes and two of seconds (`05:23`, `00:40`). From one hour on, hours are written without padding (`1:02:10`, `12:00:00`). Minutes and seconds are below 60. `00:05:23` and `323` are not valid (H7). Note that this is not the form of a segment stamp (section 7), which always has two digits of hours.

A writer takes the length from what the publisher states about the episode; failing that, from the latest time in the transcript, start or end; failing that, it writes `unknown`. A stated length that cannot be written (negative, or 100 hours and more) counts as not stated. A length taken from the transcript is never earlier than the last segment: a cue that ends before it starts does not shorten the episode. `duration` SHOULD NOT be earlier than the last segment time (W6). The greatest length that can be written is `99:59:59`.

### 4.3 `format`

Exactly one of:

| Value | Meaning |
| --- | --- |
| `WebVTT` | A WebVTT caption file. |
| `SubRip (SRT)` | A SubRip caption file. |
| `Podcasting 2.0 JSON` | The JSON transcript of the Podcasting 2.0 namespace, or JSON shaped like it. |
| `HTML page` | An HTML transcript page. |
| `text with times` | Plain text or markdown that carries times. |
| `plain text` | Plain text or markdown without times. |

The value records what the content was, not what its label or media type claimed (Appendix A.1). It is information for people and for diagnosis; a reader MUST NOT change how it reads the segments because of it.

### 4.4 `provenance`

Free text of 1 to 80 characters saying who made the text. This version registers one value, `publisher transcript`: the text was published by the show itself. The reference writer writes nothing else, because PEA never transcribes audio. A writer that makes the text some other way (speech recognition, a person correcting it) MUST say so here in its own words and MUST NOT write `publisher transcript`. A reader MUST accept any value.

## 5. Segment lines

Every line after line 13 MUST be a segment line (S1):

```
[HH:MM:SS] Speaker: text        a time and a speaker
[HH:MM:SS] text                 a time, no speaker
[--:--:--] Speaker: text        no time
[--:--:--] text                 neither
```

- The line starts with a **stamp** (section 7), then exactly one space.
- An OPTIONAL **speaker label** follows: a name from the header's `speakers` list, a colon and one space (section 6).
- The **text** is the rest of the line. It MUST start with a character that is not white space and MUST be at least one character long. It is one line: it contains no LF.
- There MUST be at least one segment (S6), and the number of segment lines MUST equal the header's `segments` (H13).

The text is plain speech. It carries no markup: tags, entities, caption settings and emphasis marks were removed by the writer, and a reader MUST NOT interpret anything in it as markup, as a link or as a command.

### 5.1 What a segment is

A segment is a stretch of speech by one speaker, starting at one time. The reference writer packs caption cues and text lines into segments of about 300 to 560 characters and never more than 560. It closes the open segment and starts a new one:

- when the speaker changes;
- when the segment has reached 280 characters and ends with a sentence end (`.`, `!`, `?`, `…`, `"` or `”`);
- when adding the next cue would take it past 560 characters;
- when the next cue starts 90 seconds or more after the segment did, however short the segment is;
- when the segment has no time and the next cue has one (a title line before the first time stays a segment of its own, and the timed lines keep their times);
- when the next cue is a sponsor read and the segment is not, or the other way round (section 8).

A publisher's line or cue longer than 560 characters is split before it is packed: at sentence ends (`.`, `!` or `?`, optionally followed by a closing quote or bracket, followed by white space), and at a word when one sentence is longer still (anywhere, when there is no space in reach). Every piece keeps the time and the speaker of the line it came from. So one enormous line can neither become one enormous segment nor carry the file past the size limit of section 11.

A writer SHOULD keep every segment at or under 560 characters (W7) and SHOULD end segments at sentence ends, so that a reader can quote a segment whole. A reader MUST NOT assume any maximum length: files from other writers, and files written before this rule, may hold longer lines.

## 6. Speakers

- The header's `speakers` value is `none`, or one or more names joined by a comma and a space (H12).
- A name is one line of 1 to 40 characters, has no space at either end, MUST NOT contain a colon followed by a space or a comma followed by a space, and MUST NOT be the word `none`. A writer cleans a publisher's name in this order: three backticks become three apostrophes, control characters and line breaks become spaces, runs of spaces collapse, the name is cut to 40 characters, and a comma-space or colon-space inside it becomes a single space. A name that is empty after that, or is exactly `none`, is no speaker: the segment is written without a label.
- Names MUST be unique, MUST each label at least one segment, and MUST be listed in the order in which they first label a segment (S3).
- Names are compared exactly: `Mara` and `mara` are two speakers.

**How a reader finds the speaker of a segment.** After the stamp and its space, the reader tests the names of the header list in order; the first name that the rest of the line starts with, directly followed by a colon and a space, is the speaker, and the text begins after that space. If no name matches, the segment has no speaker, and whatever stands before a colon is part of the text. A name before a colon is a speaker **only** when it is in the header's list.

A segment has at most one speaker. A segment without a label has no stated speaker; a reader MUST NOT carry the previous segment's speaker over to it.

Because of the rule above, a writer MUST NOT write an unlabelled segment whose text starts with a listed name, a colon and a space: a reader would take the name for its speaker. (Nothing in the file can show this happened; `validate.py` can only warn about the one visible sign, two labels in a row, W5. See G-6.)

Speaker names are what the publisher wrote. They are labels, not identities: `Speaker 1`, `Host` and `SPEAKER_4` are as valid as a person's name.

### 6.1 Which speaker a converter gives a line

A converter MUST NOT credit speech to a speaker the publisher did not state for it. The speaker of one cue or line is carried to the next unlabelled one **only where the source format itself continues it**:

| Source | An unlabelled piece |
| --- | --- |
| Captions (WebVTT, SubRip) | keeps the last voice: a caption file names the voice when it changes. |
| JSON rows | keeps the last row's speaker. |
| An HTML transcript page | the paragraphs under a `<cite>` keep its speaker until the next `<cite>`. |
| Text written as `Name 0:12` or `Speaker 1 (00:12):` lines | the block under such a line keeps its speaker until the next such line, blank lines or not. |
| Other text with `Name:` labels | a line directly under a labelled line, with no blank line between, is the same paragraph and keeps the speaker. A line after a blank line that has no label of its own has **no** stated speaker. |

In the last case the unlabelled paragraph starts a new segment without a label, even when the paragraph before it was labelled.

## 7. Times

A stamp is `[HH:MM:SS]`: two digits of hours, two of minutes, two of seconds, minutes and seconds below 60 (S2). It is the whole number of seconds, rounded down, from the start of the episode to the start of the segment. The greatest time that can be written is `[99:59:59]`.

A segment whose starting time is not known has the stamp `[--:--:--]`. A writer MUST use it, and MUST NOT invent a time, when the publisher gives none, and also for a time it cannot write (section 7.1). The text of such a segment is kept.

A file may mix the two: a transcript whose first lines come before the publisher's first time mark has untimed segments followed by timed ones. A transcript is **timed** when at least one segment has a time.

Times SHOULD NOT go backwards from one timed segment to the next (W3). A reader MUST NOT rely on that; the order of the lines is the order of the speech.

There are no end times. A segment lasts until the next one starts.

### 7.1 Numbers that are not times

Times come from files written by strangers. A reader, a writer and a converter MUST NOT fail, trap, overflow or hang on any number or any text that stands where a time should be. Every time, whatever its source (a caption timing line, a JSON number, a clock string, a stamp or a `duration` in a file, a length stated by an episode index), goes through **one checked conversion before any other arithmetic**:

- the value is a finite number, not negative, and less than 360,000 seconds (100 hours): then the time is that number rounded down to a whole second;
- anything else (not a number, `nan`, infinite, negative, 100 hours or more, too large to hold) is **not known**. It is written as `[--:--:--]`, or as `duration: unknown`, and the text is kept. It is never clamped to a nearby valid time and never written as it stands.

A **clock string** (`18:20`, `1:02:10.500`, `00:00:01,360`) is two or three parts separated by colons; each part is 1 to 12 ASCII digits with at most one point (a comma counts as a point). So `nan:00`, `-1:00`, `1e308:00` and `0x1p3:00` are not times. The parts are summed (hours, minutes, seconds) and the sum goes through the conversion above, so `100:00:00` and `999999999999:00:00` are not known either.

Every stamp a conforming writer writes therefore lies between `[00:00:00]` and `[99:59:59]`.

## 8. Sponsor reads and housekeeping

A sponsor read, and housekeeping such as "subscribe to our newsletter", is speech that was really said, so it stays in the file. It is kept apart from the talk around it so that a reader can leave it out of what it offers.

**There is no mark in the file.** A sponsor segment is recognized by its text. A segment is a sponsor segment when its text matches this pattern, without regard to case, with `\b` a word boundary:

```
\b(sponsor(?:ed|s)?|brought to you by|presented by|use (?:the )?(?:code|promo)|promo code|patreon|subscribe|newsletter|ad-free|ad free|visit [a-z0-9.\-]+\.(?:com|ai|io|co)|is hiring|we are hiring|now hiring|link in the (?:show )?notes)\b
```

- A writer MUST NOT put speech that matches the pattern and speech that does not into the same segment when they arrive as separate cues or lines. (A publisher's single line that mixes both stays one segment, and matches.)
- A reader that offers passages to a person or a model SHOULD treat matching segments as sponsor segments: keep them, count them, and not offer them as content (section 12).
- The pattern is part of version 1 and does not change within it. It is English only and it is a rule of thumb: it will miss sponsor reads worded otherwise and will catch a sentence that merely says "newsletter". It is not a filter to rely on for safety (G-5).

## 9. Partial transcripts and the cut mark

A file is **full** when it holds the whole transcript the writer was given, and **partial** when the end is missing.

A partial file says so in two places, and both are REQUIRED (S4):

1. The header says `quality: partial (reason)`, where the reason is 1 to 120 characters in plain words.
2. The file ends with the **cut mark**: a space followed by `(cut)`, six characters in all, placed directly after the last character of the last segment with no line break before or after it.

```
quality: partial (cut at 150,000 chars; 481 of 680 segments kept, up to 40:00 of 56:40)
...
[00:40:00] Host: Sentence number 2404 about the harbor and its tides and boats. (cut)
```

A full file says `quality: full` and MUST NOT end with the cut mark. When the speech of a whole transcript itself ends with those six characters (somebody's last words were "(cut)"), the writer adds a full stop after them, so the file is not read as cut (`fixtures/valid/speech-ending-in-cut.pea.txt`). The cut mark is not part of the last segment's text; a reader removes it before reading the segments.

A transcript MUST be cut only between segments, never inside one, so nothing stops in the middle of a sentence.

**Reasons.** The reference writer writes one of two, and other writers SHOULD use the same wording when the same thing happened:

| When | Reason |
| --- | --- |
| The text was over the size limit of section 11 | `cut at 150,000 chars; K of N segments kept`, then `, up to T` when the kept segments have times, then ` of D` when the length is known. K and N are counts; T is the last kept time and D the length, both written like `duration`. |
| The input itself arrived cut off (a download stopped at a size limit) | `the file was over 1.5 MB; end missing`, then `, kept up to T` when the kept segments have times. |

**Reader rules.**

- Line breaks at the very end of the file are removed first; the cut mark is looked for after that.
- `quality` starting with the word `partial` means partial. Any other value means full.
- When `quality` says partial without a reason in parentheses, or the file ends with the cut mark although `quality` does not say partial, the transcript is partial and the reason is `end missing`.
- A reader that shortens a transcript further, or quotes a piece of a partial one, SHOULD put the cut mark only where the kept text actually stops (in section 12: on the last passage alone).

**Saying it.** A reader that describes a transcript to a person or to a model SHOULD say plainly when it is partial. PEA uses these two forms on its status line, and they are RECOMMENDED:

```
full transcript (34,528 chars, 30 min)
transcript PARTIAL (first 149,924 chars; cut at 150,000 chars; 481 of 680 segments kept, up to 40:00 of 56:40)
```

The word `PARTIAL` is written in capitals, followed by the number of characters held and the header's reason. (This line is not part of the file.)

## 10. Quality, provenance and language

**Quality** has two grades in this version: `full` and `partial`. It grades completeness only. It says nothing about how accurate the text is; that is what `provenance` is for.

PEA grades a whole source item on a wider scale (Clean, Partial, Headlines only, Listing, Unreadable). That scale is outside the file. For orientation: an episode held with a full transcript is Clean, one whose transcript was cut is Partial, and an input a converter could not read never becomes a file at all (Appendix A.7).

**Provenance** is described in section 4.4.

**Language.** One tag for the whole file. A writer takes it from the publisher (a WebVTT `Language:` header line, the `language` or `lang` member of a JSON transcript, the feed's own language tag) and writes `unknown` otherwise. A writer MAY detect the language from the text; it then SHOULD do so only with at least 200 characters to go on. From a publisher's value only ASCII letters, digits, `-` and `_` are kept, and at most 12 of them; if nothing is left the language is not known. (So a value with line breaks in it cannot write header lines of its own.) A reader MUST treat the value as a hint: it may be wrong, and it may be `unknown` (G-11).

## 11. Size limits

| What | Limit | Rule |
| --- | --- | --- |
| Segment text in all (stamps and speaker labels not counted) | 150,000 characters | S5 |
| `show`, `title` | 200 characters each | H4 |
| `date` | 40 characters | H5 |
| `source` | 400 characters | H6 |
| `language` | 12 characters | H8 |
| `provenance` | 80 characters | H10 |
| the reason in `quality` | 120 characters | H11 |
| a speaker's name | 40 characters | H12 |
| one segment's text | 560 characters (SHOULD) | W7 |
| a stamp | `[99:59:59]` | S2 |

A writer whose transcript is longer than 150,000 characters keeps whole segments from the start for as long as the total stays within the limit, drops the rest, and marks the file partial (section 9). Because long lines are split first (section 5.1), this holds even when the whole transcript arrives as one line. 150,000 characters is roughly two hours of speech.

A conforming file is therefore normally well under a megabyte. A reader SHOULD refuse input far beyond that instead of reading it (`validate.py` refuses anything over 4,000,000 bytes).

There is no minimum size for a file. A converter, however, MUST NOT produce a file from an input with fewer than 200 characters of speech: such an input is almost always an error page or a sign-in page, and the converter reports it as unreadable (Appendix A.7).

## 12. Recommended chunking for readers

This section is a RECOMMENDATION. It describes how PEA cuts a file into passages for search, so that two readers that follow it give the same passage the same place. A reader MAY chunk differently and still conform.

**Sections.**

- The header is never indexed. Only segments are.
- In a timed transcript, a section is five minutes of the episode. A segment at second `s` belongs to block `s / 300` (rounded down). A new section starts at the first segment whose block is higher than every block before it; its heading is `Transcript from T`, with T the start of the block written like `duration` (`Transcript from 00:00`, `Transcript from 05:00`, `Transcript from 1:00:00`). An untimed segment in a timed transcript stays in the section of the segment before it. Empty five-minute blocks make no section.
- In an untimed transcript, a section is ten segments: `Transcript, part 1`, `Transcript, part 2`, and so on.

**Passages.**

- A passage lies inside one section and is at most about 700 characters.
- Each segment contributes its speaker label and text (`Mara: Welcome back ...`, or the text alone), so every passage shows who is speaking. Stamps are not part of passage text.
- Segments are added to the open passage, joined by one space, until the next one would take it past 700 characters; then a new passage starts. A segment longer than 700 characters is first split into sentences (at `.`, `!` or `?`, optionally followed by a closing quote or bracket, followed by white space, so `5.2` and `$1.5B` stay whole), and a sentence longer than 700 characters is cut at a word.
- A sponsor piece (section 8) and a piece that is not one never share a passage. A sponsor passage is kept, marked and counted, so that "passage 24 of 30" stays true, but it is never offered as an answer.
- A passage's time is the time of the first segment in it. Its place is said as `transcript at 05:02`.
- In a partial transcript, only the passage where the kept text stops ends with the cut mark.

**Ids.** Sections and passages are numbered from 1 in file order, passages across the whole item, not per section. A passage id is `s<section>.p<passage>`, for example `s2.p14`. Ids are stable for an unchanged file.

For the six segments of `fixtures/valid/ads.pea.txt` this gives two sections (`Transcript from 00:00`, `Transcript from 05:00`) and four passages, two of them sponsor passages (at 00:24 and at 05:18).

## 13. Conformance

### 13.1 Reader

A conforming reader:

1. MUST refuse input whose first line is not exactly `PEA-TRANSCRIPT v1`: the text is that line alone, or starts with that line followed by LF. In particular `PEA-TRANSCRIPT v10`, `PEA-TRANSCRIPT v1.1`, `PEA-TRANSCRIPT v2`, a first line with a space or CR after the marker, and a marker in other letter case are not this format. Input that is not PEA transcript v1 is not an error of the format; the reader simply reports that it is something else (the reference implementation then reads the text as an older, unmarked transcript, which never fails). A reader given bytes MUST either refuse bytes that are not UTF-8 or read each faulty sequence as U+FFFD; it MUST NOT fail on them.
2. MUST read header lines up to the first line that is exactly `---`. A file with no such line is refused.
3. MUST take the key of a header line to end at the first colon followed by a space, MUST ignore header lines that have no colon-space, and MUST ignore keys it does not know. It MUST accept the known keys in any order. When a key appears more than once, the **first** counts and the later lines are ignored, so a line further down cannot overrule the header. It MUST use these values for a key that is missing: empty for `show`, `title`, `date` and `source`; unknown for `duration` and `language`; `plain text` for `format`; `publisher transcript` for `provenance`; full for `quality`; no speakers.
4. MUST read `unknown` in `date`, `source`, `duration` and `language` as "not known", and `none` in `speakers` as an empty list (empty names in the list are dropped). A `format` value that is not one of the six is read as `plain text`. A `duration` that is not a clock string in range (section 7.1) is not known.
5. MUST remove every LF at the very end of the text, and then apply the reader rules of section 9 for `quality` and the cut mark.
6. MUST read each following line that starts with `[` as follows, and skip every other line. Find the first `]` among the first 32 characters; what stands between is the stamp's inside.
   - The inside is eight characters long (the usual case, `]` being the tenth character of the line): the character after `]` is the separator, and the rest of the line is the speaker label (section 6) and the text. The inside `--:--:--` means no time; otherwise it is read as a clock string (section 7.1), and one that cannot be read is no time.
   - The inside has another length: the line is a segment only when the inside is not empty, is made of ASCII digits, `:` and `-` alone, and is followed by one space within those 32 characters. The segment keeps its text and has **no time**. (Files from the first build of the reference writer could hold `[00:00:-5]` and `[111:06:40]`; such a segment must not be lost.)
   - In both cases a line with nothing after the separator is not a segment.
7. MUST NOT trust the header's `segments` number; it counts the segments it reads.
8. MUST NOT fail, trap, hang or stop on any input, whatever it contains: any number where a time should be (section 7.1), a line of any length, any number of lines, a header that never ends. It MUST treat every value and every segment as untrusted text (section 14).

A reader is deliberately more forgiving than a writer is allowed to be. `pea_transcript.parse` is a reader of this kind.

### 13.2 Writer

A conforming writer produces files that pass every rule below whose level is MUST. `validate.py` checks them and reports each by its id.

| Id | Level | Rule |
| --- | --- | --- |
| F1 | MUST | The file is valid UTF-8 with no byte order mark and no NUL character. |
| F2 | MUST | Lines end with LF only: no CR anywhere. |
| F3 | MUST | The file does not end with a line break. |
| F4 | MUST | Three backticks in a row appear nowhere in the file. |
| H1 | MUST | Line 1 is exactly `PEA-TRANSCRIPT v1`. |
| H2 | MUST | Lines 2 to 12 are the eleven header keys in the fixed order, each written `key: value`. |
| H3 | MUST | Line 13 is exactly `---`. |
| H4 | MUST | `show` and `title` are at most 200 characters. |
| H5 | MUST | `date` is `unknown` or 1 to 40 characters. |
| H6 | MUST | `source` is `unknown` or 1 to 400 characters. |
| H7 | MUST | `duration` is `unknown`, `MM:SS` (under an hour) or `H:MM:SS`. |
| H8 | MUST | `language` is `unknown` or 1 to 12 characters, each an ASCII letter, a digit, `-` or `_`. |
| H9 | MUST | `format` is one of the six registered values. |
| H10 | MUST | `provenance` is 1 to 80 characters. |
| H11 | MUST | `quality` is `full` or `partial (reason)` with a reason of 1 to 120 characters. |
| H12 | MUST | `speakers` is `none` or names joined by a comma and a space: each 1 to 40 characters, unique, without a colon-space, none called `none`. |
| H13 | MUST | `segments` is a whole number equal to the number of segment lines. |
| H14 | MUST | `show`, `title`, `date`, `source`, `provenance` and `quality` have no space at either end and no doubled space. |
| S1 | MUST | Every line after the header is a segment line: a stamp, one space, then text that starts with a non-space character. |
| S2 | MUST | Every stamp is `[HH:MM:SS]` with minutes and seconds under 60, or `[--:--:--]`. |
| S3 | MUST | Every name in `speakers` labels at least one segment, and the names are listed in the order of first use. |
| S4 | MUST | `quality` is partial exactly when the file ends with the cut mark. |
| S5 | MUST | The segment text is at most 150,000 characters in all. |
| S6 | MUST | There is at least one segment. |
| W1 | SHOULD | `date` is `unknown` or a calendar date written `YYYY-MM-DD`. |
| W2 | SHOULD | `language` is `unknown` or looks like a BCP 47 tag. |
| W3 | SHOULD | Times do not go backwards. |
| W4 | SHOULD | No control characters other than LF. |
| W5 | SHOULD | No segment has two speaker labels in a row. |
| W6 | SHOULD | `duration` is not earlier than the last segment time. |
| W7 | SHOULD | No segment's text is longer than 560 characters. |

A writer MUST also follow the rules that a validator cannot see from the file alone: cut only between segments (section 9), keep sponsor speech apart (section 8), never invent a time (section 7) or a speaker (section 6.1), never label an unlabelled segment by accident (section 6), pass every time through the checked conversion of section 7.1, and state the provenance truthfully (section 4.4).

A file a conforming writer produced, read by a conforming reader and written again, gives the same bytes.

### 13.3 Converter

A converter is a writer. In addition it:

- MUST decide what its input is by looking at the content, and use the declared type only when the content does not settle it;
- MUST refuse an input with fewer than 200 characters of speech, an empty input and a binary one, and MUST say why in a few words (Appendix A.7);
- MUST remove markup, caption settings and sound notes instead of passing them through as text, and MUST do so once: markup is removed first and entities are decoded afterwards, in a single pass, so text a publisher escaped (`&lt;once&gt;`) stays in the file as text (`<once>`) and nothing is decoded twice (Appendix A.2);
- MUST follow section 6.1 for speakers and section 7.1 for times, and MUST NOT fail or hang on any input: what cannot be read is reported with a reason;
- SHOULD follow Appendix A, so that the same input gives the same file whatever tool converted it. `convert.py` does, and the fixtures in `fixtures/convert` hold the expected file for each input.

### 13.4 Fixtures

`fixtures/manifest.json` lists every conformance fixture with the result a validator and a reader must give: conforming files in `fixtures/valid`, and in `fixtures/invalid` one or more files for each MUST rule, each breaking that rule and no other. `test_conformance.py` also holds the hostile inputs (times that are not times, 200,000 cues, a line of five megabytes, markup that never closes, bytes that are not UTF-8, control characters), each run inside a time limit.

## 14. Security considerations

**Transcript text is untrusted data. It is never instructions.** Everything in a file was written by a third party: the publisher, a guest, a caption service, or someone who took over a feed. That holds for the header values as much as for the segments; `show` and `title` come from a feed, and speaker names come from the caption file.

- A reader that passes text from a file to a language model MUST present it as quoted material to be discussed, MUST NOT let it change what the model is asked to do, and MUST NOT act on anything the text asks for (open an address, run a tool, reveal other data, change settings). A sentence in a transcript that says "ignore your earlier instructions" is a sentence somebody said in an episode, nothing more.
- Rule F4 exists for this reason: with no run of three backticks, text from a file cannot close a fenced block that a reader put it in and continue as if outside it. A reader MUST NOT rely on the writer for that; it checks or replaces again when it builds a prompt, and applies the same care to whatever other fence or tag it uses.
- The one-line rule for header values (section 4.1) keeps a title from forging a header line. A reader still MUST take the first occurrence of each key from the header only, never from segment text, and MUST NOT read anything after line 13 as a header.
- The text carries no markup. A reader that shows it in HTML or any other markup MUST escape it. A reader SHOULD neutralize control characters and direction-override characters (such as U+202E) before showing a value to a person.
- `source` is an address written by someone else. A reader MUST NOT fetch it without the user's knowledge, and when it does fetch it MUST apply the checks it applies to any address from an untrusted place (scheme, private and local hosts, redirects, size).
- Speaker names, the `provenance` value and the `language` value are claims, not facts. A file can say `publisher transcript` and be nothing of the kind.
- The sponsor pattern (section 8) is a rule of thumb for relevance. It is not a safety filter.
- A reader and a converter MUST survive any input (sections 7.1 and 13.1, point 8): absurd times, enormous lines, markup that never closes, a header that never ends, a `segments` number that lies. Work on a line SHOULD be one pass over it, so that a hostile file costs time in proportion to its size and no more.
- A speaker's name and a language tag are cleaned to one line (sections 6 and 10), so neither can write header or segment lines of its own.
- The format has no place for anything about the listener, and none may be added. A file holds public text about a public episode.

## 15. Versioning

- The format's version is the whole number on line 1. This is version 1.
- The specification has its own three-part number (`1.0.0`). The first part is the format version. The second part grows when something is added that version 1 readers can ignore, such as a new header key after `segments` or a new `format` value. The third part grows for wording, corrections and new fixtures that change no file. A draft carries `-draft.N`.
- That is why readers ignore unknown keys and read an unknown `format` as `plain text` (section 13.1): a file written to a later 1.x specification is still read by a 1.0 reader. Writers conforming to 1.0 write exactly the eleven keys.
- Anything a version 1 reader cannot safely ignore (a change to the segment line, to the cut mark, to the meaning of a key, to the sponsor pattern) needs `PEA-TRANSCRIPT v2`, which version 1 readers refuse.
- Line 1 is compared whole. `PEA-TRANSCRIPT v1.1` is not a valid first line.

## 16. Changelog

| Version | Date | Change |
| --- | --- | --- |
| 1.0.0-draft.1 | 2026-11-14 | First written specification, derived from the reference implementation as it stood that day. Adds what the implementation left open: the `.pea.txt` name, the exact first line, rules H13, S3 and S5 as checks, the reader's duty to survive any input. Not published. |
| 1.0.0-draft.2 | 2026-11-14 | Brought in line with the reference implementation after the review that draft 1 caused. New: section 6.1 (which speaker a converter gives a line), section 7.1 (numbers that are not times: one checked conversion, out of range means not known, nothing may trap), the 560-character ceiling and the splitting of long lines (5.1, new rule W7), no 120-character floor on the ninety-second rule, an untimed segment never takes a timed cue, markup removed once and entities decoded once, `Speaker 1 (00:12):` and `0:31:` lines (Appendix A). Changed: rule H8 (the `language` value is ASCII letters, digits, `-` and `_`), reader rules 1, 3, 5 and 6 of section 13.1 (the exact first line, the first of a repeated key, line breaks at the end, stamps of another length), the full stop after speech ending in "(cut)" (section 9). Section 17 now separates open gaps from resolved ones. `convert.py` and `pea_transcript.py` follow; six new fixtures and the hostile-input tests. Not published. |

## 17. Known gaps

Draft 1 of this specification listed every place where the reference implementation, its documentation and this text disagreed, or where the implementation left a question open. The implementation was then reviewed and most entries were fixed in it. The entries keep their numbers. "Spec" says what this document decided.

### 17.1 Open

- **G-5. Sponsor reads have no mark in the file.** A sponsor read is always kept in a segment of its own, but nothing in the file marks it; a reader finds it again with the pattern of section 8. Three consequences: a segment made of several non-sponsor cues can match once they are joined ("...you can use the" + "code we wrote..."); a publisher's single line that mixes talk and a sponsor mention is a sponsor segment as a whole (the second segment of `fixtures/convert/expected/timed.md.pea.txt`); and the pattern is English only. Spec: section 8 states the pattern as part of version 1. An explicit mark would need a version 2 or a new header key.
- **G-9. What a character is.** The reference implementation counts characters as a person sees them (a letter with a combining accent, or a multi-part emoji, is one). `validate.py` and `convert.py` count Unicode code points. The two agree for most text and can differ by a few characters near a limit (560, 40, 200, 150,000) for text with combining marks or emoji. Spec: a character is a code point (section 2), because that is what other languages can count without a Unicode library; the reference writer is then, at worst, slightly more generous with such text.
- **G-10. No file of its own in PEA.** PEA stores a transcript inside a larger file, after a `Transcript:` label (Appendix B), so the implementation has no file name, extension or media type. Spec: `.pea.txt` and `text/plain` (3.1). This is a proposal for the owner to confirm.
- **G-19. `date` is free text.** The reference writer writes whatever the feed gave, up to 40 characters. Spec: SHOULD be `YYYY-MM-DD` (W1), anything up to 40 characters is allowed.
- **G-20. Unknown values are read silently.** In the reference reader an unknown `format` becomes `plain text`, any `quality` that does not start with `partial` is full, and `provenance` is never interpreted. Spec: kept, because it is what makes later 1.x additions safe (section 15), and stated as reader rules.
- **G-23. `convert.py` does not read HTML.** The format value `HTML page` exists and the reference normalizer writes it; the Python converter covers WebVTT, SubRip, JSON and text, and reports an HTML input as unreadable. The 200-character minimum belongs to the converter only: a reader accepts a file of any size.
- **G-24. The JSON parser's edges** (new in draft 2). What counts as "JSON that does not parse" is decided by the parser a converter uses. The reference normalizer's parser refuses lists and objects nested 512 deep or more, a positive number too large to hold (`1e309`; `-1e309` is read, and is then not a time), and a `\u` escape that is half a surrogate pair; where an object has the same key twice, the first counts. `convert.py` does the same on purpose, so the two give the same file or the same refusal. Spec: Appendix A.2 states these edges; another converter may draw them elsewhere, as long as it refuses with a reason and never fails.

### 17.2 Partly resolved

- **G-3. The reader checks almost nothing.** Resolved: the documentation no longer claims the reader requires the fixed header, and when a key appears twice the first now counts (13.1, point 3). Open, and intended: the reader takes keys in any order, supplies defaults, never looks at `segments`, and skips lines it cannot read without saying so. Spec: two levels; the strictness is on the writer (13.2), the tolerance on the reader (13.1).
- **G-6. Speaker labels can be mistaken.** Resolved: (b) a publisher's speaker called `none` is now no speaker; (d) a name is passed through the one-line clean-up, so it can carry neither three backticks, a control character nor a line break into the header (section 6). Open: (a) an unlabelled segment whose text starts with a listed name and a colon-space is read as that speaker's; forbidden for writers but not checkable from the file (W5 warns about the one visible sign); (c) the writer replaces a comma-space or colon-space inside a name with a space, so `Smith, Jane` becomes `Smith Jane`.
- **G-11. Language.** Resolved: a language value from a feed or a file is now limited to ASCII letters, digits, `-` and `_` (rule H8, section 10). Open: PEA fills `language` from Apple's on-device language recognizer when the publisher names none; no other platform can reproduce that value. `convert.py` writes `unknown` unless given `--language`; the converter fixtures record which expected files got their language that way. Spec: detection is optional, the value is a hint (section 10).

### 17.3 Resolved

Fixed in the reference implementation on 2026-11-14 (code `2b2bd73`, its checks `0711dad`, its documentation `a9aca00`). `convert.py` and `pea_transcript.py` follow, and the tests named `Review` in `test_conformance.py` hold each one in place.

| Entry | What was wrong | Now | Fixed in |
| --- | --- | --- | --- |
| G-1 | Code comment, documentation and check counted the header as eleven, twelve and thirteen lines. | All say: the marker line, eleven keys, `---`; thirteen lines (sections 3.3 and 4). | `2b2bd73`, `a9aca00` |
| G-2 | The reader matched line 1 as a prefix, so `PEA-TRANSCRIPT v10` and `v1.1` were read as version 1. | Line 1 is compared whole (13.1, point 1); other versions fall to the reading of an unmarked older file. | `2b2bd73` |
| G-4 | A single cue or line of any length became one segment. | Lines over 560 characters are split at sentence ends; no segment is longer (5.1). | `2b2bd73` |
| G-7 | A final line break hid the cut mark; ` (cut)` stayed in the last segment's text. | Line breaks at the end are removed before the mark is looked for (section 9). | `2b2bd73` |
| G-8 | A full transcript whose speech ended in " (cut)" was read as partial. | The writer adds a full stop after such an ending (section 9). | `2b2bd73` |
| G-12 | (1) A JSON time of `"nan"`, `"inf"` or `1e300` was turned into a whole number without a check. (2) So was a stamp or `duration` of `1e308:00` in a stored file. (3) A negative time was written `[00:00:-5]` and 100 hours or more `[111:06:40]`, and the reader then dropped such segments. | One checked conversion for every time; out of range is not known and is written `[--:--:--]`; a segment with an unreadable stamp keeps its text (7.1; 13.1, point 6). | `2b2bd73`, checks `0711dad` |
| G-13 | An untimed first line (a title) swallowed the timed lines after it. | A segment without a time never takes a cue that has one (5.1). | `2b2bd73` |
| G-14 | `0:31:` at the start of a line was not read as a time. | It is (Appendix A.2). | `2b2bd73` |
| G-15 | `Speaker 1 (00:12):` was not read as a speaker line. | A name may end in a number of up to three digits (Appendix A.2). | `2b2bd73` |
| G-16 | Once any line had a speaker, every later unlabelled line got the last speaker. | The speaker is carried only where the format continues it (6.1). | `2b2bd73` |
| G-17 | (1) Escaped angle brackets (`&lt;once&gt;`) were decoded and then deleted as a tag. (2) Double escapes (`&amp;lt;`) came out differently from run to run. | Markup is removed once, then entities are decoded once in a single pass; `&amp;lt;` is always `&lt;` (Appendix A.2). | `2b2bd73` |
| G-18 | The ninety-second rule applied only once a segment had 120 characters. | The floor is gone (5.1). | `2b2bd73` |
| G-21 | The first segment was always kept whatever its size, so one enormous line exceeded the 150,000 limit. | No segment is over 560 characters, so the limit holds (section 11). The limit still counts segment text only, by design. | `2b2bd73` |
| G-22 | A code comment said "parts of eight passages"; code and documentation said ten segments. | The comment says ten segments (section 12). | `2b2bd73` |

Also fixed in the same change, without an entry of their own in draft 1: the first of a repeated header key counts; control characters inside a line become spaces; a stated episode length that cannot be written is dropped, and a length taken from the transcript is never earlier than the last segment; work on a line is one pass, so input such as a million `<` no longer takes time out of proportion.

## Appendix A. How the reference normalizer converts (informative)

This appendix describes the reference normalizer as fixed on 2026-11-14. `convert.py` follows it step by step; `fixtures/convert` holds inputs and the files the reference normalizer wrote for them.

### A.1 Deciding what the input is

Line ends are normalized to LF and byte order marks removed. Then, looking at the first 4,000 characters, in this order:

1. starts with `WEBVTT`: WebVTT;
2. starts with `{`, or with `[` followed by `{` or `[`: JSON;
3. contains a caption timing line (`00:00:01.000 -->`): SubRip when the times use a comma, otherwise WebVTT;
4. looks like HTML (`<!doctype html`, `<html`, `<body`, `<cite`, `<div`, or `<p` with `</p>`): HTML;
5. the declared type contains `json`, or the address ends in `.json`: JSON;
6. otherwise text: "text with times" when the whole input has two or more times in brackets or parentheses, three or more lines starting with a time (`0:31 text`, `0:31: text`), or three or more `Name 0:12` lines; else "plain text".

The declared type and the address are used only in step 5.

### A.2 Reading each format

**Markup and entities, once.** Every piece of publisher text goes through the same clean-up exactly once, in this order:

1. SubRip position codes are removed: from `{\` to the next `}`.
2. Tags and karaoke times are removed: from `<` to the next `>`, when that `>` is at most 200 characters on. A `<` with no `>` in reach stays (so `a < b` is text).
3. Entities are decoded in a single pass from left to right. Each `&name;` or `&#number;` is replaced where it stands and the result is not read again: `&lt;once&gt;` becomes the text `<once>` and stays; `&amp;lt;` becomes `&lt;`. Known names: `amp`, `lt`, `gt`, `quot`, `apos`, `nbsp`, `mdash`, `ndash`, `hellip`, `rsquo`, `lsquo`, `ldquo`, `rdquo`, `middot`, `copy`; numbers in decimal or hexadecimal. Anything else is left as written.
4. Three backticks become three apostrophes; control characters and line separators become spaces; a leading `>>` is dropped; runs of spaces, tabs and no-break spaces collapse to one space.

Steps 1 to 3 are never applied a second time to text that has been through them.

- **WebVTT and SubRip.** The header block, `NOTE`, `STYLE` and `REGION` blocks, cue numbers, cue names and cue settings are dropped. `<v Name>` gives the speaker; a second voice inside one cue starts a new cue at the same time. A `Language:` line in the WebVTT header gives the language.
- **JSON.** Rows are taken from a top-level list, or from the first non-empty list under `segments`, `cues`, `results`, `transcript`, `utterances`, `paragraphs` or `monologues`. In a row, the text is `body`, `text`, `content` or `transcript`; the speaker is `speaker`, `speakerName` or `name`; the start is `startTime`, `start`, `start_time` or `begin`; the end is `endTime`, `end` or `end_time`. A time may be a number, a number in a string, or a clock string; it goes through the conversion of section 7.1, and a row whose time is not known keeps its text. Word-by-word rows are glued into sentences; a row of punctuation only becomes a space. With no rows, one long string under `text`, `transcript` or `body` is read as text. The language is `language` or `lang`. The file is "JSON that does not parse" when it is not JSON, when lists and objects are nested 512 deep or more, when a positive number is too large to hold, or when a `\u` escape is half a surrogate pair; of a key written twice in one object the first counts (G-24).
- **Text and markdown.** Markdown links keep their words; emphasis marks, quote marks, rules, a first heading line and bare address lines are dropped. Three things set the time of what follows:
  - a time in brackets or parentheses anywhere in a line (`[00:01:00]`, `(2:30)`);
  - a time at the start of a line, when at least three lines start that way: `0:31 text`, `0:31: text`, `0:31 - text`, or the time alone on its line;
  - a name-and-time line, when at least three lines are written that way and they outnumber the lines with a time in their middle: `Mara Lind 0:03`, `Speaker 1 (00:12):`, `Guest 10 [0:10]`. The name starts with a capital letter, is at most four words, and may end in a number of one to three digits; such a line also names the speaker of the block under it (section 6.1).

  A blank line starts a new paragraph, which matters for speakers (section 6.1).
- **HTML** (reference normalizer only; G-23). `<cite>` gives the speaker, `<time>` the time, `<p>` the text; menus, scripts, headings and footers are dropped; a page without those marks is read as text.

Input bytes that are not UTF-8 are read with U+FFFD in place of each faulty sequence; they do not make the input unreadable by themselves.

### A.3 Speakers written into the text

When no cue has a speaker, a `Name: ` at the start of a cue counts as one if the same name labels at least two cues and is not an ordinary word such as `Note`, `Warning` or `Question`. Which unlabelled lines then keep that speaker is decided by section 6.1.

### A.4 Clean-up

Empty cues and bare sound notes (`[MUSIC]`, `(engine starts)`, a line starting with a music sign) are dropped. A caption line repeated from one of the three lines before it is kept once (a line of 12 or more letters and digits). A line that only grows the previous one keeps just the new words. Words repeated between the end of one cue and the start of the next (three to twelve) are kept once. A run of three or more words said twice in a row is kept once; a single doubled word is left as spoken.

### A.5 Packing into segments

As in section 5.1: long lines are split first, then the pieces are packed. A speaker's name is cleaned as section 6 says.

### A.6 Header values and the size limit

`duration` is the stated length when it can be written, or else the latest start or end time seen (section 4.2). `language` is cleaned as section 10 says. The limit and the two partial reasons are those of sections 9 and 11.

### A.7 What cannot be read

A converter gives one of these reasons instead of a file:

| Reason | When |
| --- | --- |
| `an empty file` | nothing but white space |
| `not a text file` | a NUL character in the first 4,000 characters |
| `JSON that does not parse` | |
| `a JSON file over 1.5 MB, cut off before its end` | JSON that does not parse, and the input was cut off |
| `JSON without transcript segments (KEYS)` | KEYS: the first five top-level keys in alphabetical order, `a list` for a list, `empty` for an empty object |
| `no speech text in the FORMAT file` | nothing left after clean-up; FORMAT is the `format` value |
| `only N characters of speech text` | fewer than 200 |

## Appendix B. How PEA stores a transcript (informative)

PEA keeps one text file per episode. It holds the episode's notes (after the label `Episode notes:`), then, when there is a transcript, an empty line, the label `Transcript:` on a line of its own, and the PEA transcript v1 text:

```
Episode notes:
<title and notes>

Transcript:
PEA-TRANSCRIPT v1
show: ...
```

Everything after the first `Transcript:` label is the v1 file, exactly as section 3 describes it, including the cut mark at the very end. Files kept before 2026-11-14 have no header after the label and are read the old way; so is anything whose first line is not exactly the version 1 marker.

## Appendix C. References

- RFC 2119 and RFC 8174, key words for use in RFCs to indicate requirement levels.
- BCP 47, tags for identifying languages.
- WebVTT: The Web Video Text Tracks Format (W3C).
- Podcasting 2.0 namespace, the `podcast:transcript` tag and its JSON transcript format.
- JSON Schema, draft 2020-12.
