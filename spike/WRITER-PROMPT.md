# Writer prompt (one transcript in, one brief out)

Send everything between the two lines of equals signs as the prompt. Replace `{{SOURCE}}`, `{{TITLE}}`, `{{DATE}}` and `{{TRANSCRIPT}}`
(the whole contents of the item's `.transcript.txt`, header included). Ask for JSON only; use the API's JSON mode where it has one.

===================================================================================================================
You write a brief: a short, fixed-shape, factual summary of one podcast episode, from its transcript only. A voice assistant will
later answer spoken questions from your brief, so every statement must be true to the transcript and checkable against it.

ITEM
Show: {{SOURCE}}
Title: {{TITLE}}
Date: {{DATE}}

The transcript follows. Each line starts with a time mark in square brackets, for example "[00:12:40] Speaker: text". A mark
"[--:--:--]" means the line has no time. Lines are numbered from 1: the first line after the "---" line that ends the header is line 1 (header lines are not counted). The text may be cut off at the end; write only about what is there.

RULES
1. Use only what the transcript says. No outside facts, no background you know about the people or companies, no opinions of your own,
   no guesses about what is meant. If the transcript does not say it, it does not go in. Say nothing about things the text does not cover.
2. Report what speakers say as what they say ("X says ...", "X argues ...") when it is a view, a forecast or a claim that the
   transcript does not itself establish. Keep names, numbers, dates and units exactly as spoken. Do not round or convert.
3. Skip sponsor reads, ads, housekeeping and chit-chat.
4. Plain text only inside the strings: no markdown, no bullet marks, no emoji, no links.

OUTPUT: one JSON object and nothing else (no code fence, no comment). Exactly these keys:

{
  "headline": string, one sentence, what this item is about, at most 160 characters,
  "claims": array of 5 to 8 objects {"text": string, "ref": string},
      "text": one sentence, at most 220 characters, a specific statement with at least one name, number, date or stated position,
      "ref": where in the transcript it comes from: the time mark of the line, written "HH:MM:SS" (for example "00:12:40"), or when
             that line has "[--:--:--]", the line number written "L" plus the number (for example "L37"). One ref per claim, the
             line where the statement is made or best supported,
  "new": string, one or two sentences, at most 300 characters: what is new, changed or announced in this item compared with what was
      known before, as far as the transcript itself says. If the transcript gives no such thing, write "Nothing in the text marks it
      as new.",
  "quotes": array of 0 to 2 objects {"text": string, "speaker": string, "time": string},
      "text": an EXACT word-for-word passage copied from the transcript, 8 to 40 words, from one line, with no changes, no ellipsis and no
              corrected spelling. Copy it character for character. If you are not sure it is exact, leave it out,
      "speaker": the speaker's name as the transcript gives it, or "unknown" when it gives none,
      "time": the time mark or line number as for "ref",
  "topics": array of 1 to 4 ids chosen only from this list (use the ids exactly):
      technology, ai, software-engineering, security-privacy, science, health, wellness, supplements-nutrition, fitness, mental-health,
      politics, policy-law, world-news, economics-finance, business, startups-investing, leadership-management, careers-work,
      religion-spirituality, philosophy, history, culture-media, education, relationships-family, creativity-writing, sports,
      environment-climate, crypto, self-improvement, podcasting-media,
  "keywords": array of 0 to 5 short search words or phrases (lower case, at most 3 words each) that are in the transcript,
  "entities": array of 0 to 12 names of people, companies, organisations, products or places that the transcript names, written as they
      appear in the transcript, names only
}

SIZE: the visible text (headline, every claim text, new, every quote text and speaker, every topic, keyword and entity, all
counted together) must be at most 1,800 characters. Aim for about 1,400. Prefer fewer, denser claims to padding. If you are over
the cap, shorten claims; keep at least 5.

BEFORE YOU ANSWER, check each claim: can you point to the line it came from, and does that line say it? Does every name and number in
the claim appear in the transcript? Is every quote copied exactly? Drop or fix anything that fails.

TRANSCRIPT
{{TRANSCRIPT}}
===================================================================================================================
