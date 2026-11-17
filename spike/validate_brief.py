#!/usr/bin/env python3
"""Check one brief against its transcript. Standard library only, no network.

  python3 -I spike/validate_brief.py BRIEF.json TRANSCRIPT.txt [--json]
  python3 -I spike/validate_brief.py --dir BRIEFS_DIR [--data spike/data]   # BRIEFS_DIR/<item-id>.brief.json

Errors (the brief fails): schema, size caps, a quote that is not a verbatim substring (whitespace-normalized, case-insensitive),
a claim whose ref does not exist, fewer than 4 claims with a valid ref.
Flags (the brief still passes, a human looks): a number or a capitalized name in a claim that appears nowhere in the transcript.
"""
import json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
CAP = 1800
KEYS = {"headline", "claims", "new", "quotes", "topics", "keywords", "entities"}
SEG = re.compile(r"^\[([0-9:\-]+)\] ?(.*)$")
NO_TIME = "--:--:--"
NUMBER_WORDS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
                "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
                "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80,
                "ninety": 90, "hundred": 100, "first": 1, "second": 2, "third": 3}
# capitalized words that are not names (sentence openers, months and days are checked against the text like any word)
COMMON = {"the", "a", "an", "and", "but", "or", "in", "on", "at", "of", "to", "for", "with", "by", "from", "as", "that", "this", "it", "he",
          "she", "they", "we", "i", "you", "his", "her", "their", "its", "our", "if", "when", "while", "after", "before", "says", "said",
          "argues", "about", "new", "not", "no", "yes", "is", "are", "was", "were", "will", "there", "one", "two", "three"}


def load_vocabulary(path=None):
    path = path or os.path.join(HERE, "topics.json")
    data = json.load(open(path, encoding="utf-8"))
    return {t["id"] for t in data["topics"]}


def norm(s):
    """Whitespace collapsed, case folded, typographic quotes and dashes made plain."""
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"').replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", s).strip().casefold()


def parse_transcript(text):
    """-> (lines, body): lines = [(number, stamp, text)] of the segment lines, number from 1; body = all their text joined by spaces."""
    rows, started = [], False
    raw = text.split("\n")
    has_header = bool(raw) and raw[0].startswith("PEA-TRANSCRIPT")
    for line in raw:
        if has_header and not started:
            started = line == "---"
            continue
        m = SEG.match(line)
        if m:
            rows.append((len(rows) + 1, m.group(1), m.group(2)))
        elif rows and line.strip():   # a continuation line of the previous segment (plain text files)
            n, s, t = rows[-1]
            rows[-1] = (n, s, t + " " + line.strip())
        elif not has_header and line.strip():
            rows.append((len(rows) + 1, NO_TIME, line.strip()))
    return rows, " ".join(t for _, _, t in rows)


def ref_exists(ref, rows):
    if not isinstance(ref, str):
        return False
    ref = ref.strip()
    if re.fullmatch(r"L[0-9]+", ref):
        return 1 <= int(ref[1:]) <= len(rows)
    if re.fullmatch(r"[0-9]{1,3}:[0-9]{2}:[0-9]{2}", ref):
        want = [int(x) for x in ref.split(":")]
        for _, stamp, _ in rows:
            if stamp != NO_TIME and re.fullmatch(r"[0-9]+:[0-9]{2}:[0-9]{2}", stamp) and [int(x) for x in stamp.split(":")] == want:
                return True
    return False


def visible_text(b):
    parts = [b.get("headline", ""), b.get("new", "")]
    parts += [c.get("text", "") for c in b.get("claims", []) if isinstance(c, dict)]
    for q in b.get("quotes", []):
        if isinstance(q, dict):
            parts += [q.get("text", ""), q.get("speaker", "")]
    parts += [x for k in ("topics", "keywords", "entities") for x in b.get(k, []) if isinstance(x, str)]
    return "".join(p for p in parts if isinstance(p, str))


def numbers_in(text):
    out = []
    for m in re.finditer(r"(?<![\w.])\$?([0-9][0-9,]*(?:\.[0-9]+)?)", text):
        out.append(m.group(1).replace(",", "").rstrip("."))
    return out


def transcript_numbers(body):
    found = set()
    for m in re.finditer(r"[0-9][0-9,]*(?:\.[0-9]+)?", body):
        found.add(m.group(0).replace(",", "").rstrip("."))
    seq = re.findall(r"[a-z]+", body.casefold())
    for i, w in enumerate(seq):
        if w in NUMBER_WORDS:
            found.add(str(NUMBER_WORDS[w]))
            if w == "hundred" and i and seq[i - 1] in NUMBER_WORDS:
                found.add(str(NUMBER_WORDS[seq[i - 1]] * 100))
            if NUMBER_WORDS[w] % 10 == 0 and 20 <= NUMBER_WORDS[w] <= 90 and i + 1 < len(seq) and 1 <= NUMBER_WORDS.get(seq[i + 1], 0) <= 9:
                found.add(str(NUMBER_WORDS[w] + NUMBER_WORDS[seq[i + 1]]))
    return found


def names_in(text):
    """Capitalized words that are not the first word of the sentence and not common words."""
    out = []
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        words = re.findall(r"[A-Za-z][A-Za-z'’\-]*", sentence)
        for i, w in enumerate(words):
            if i == 0 or not w[0].isupper() or w.casefold() in COMMON:
                continue
            out.append(w.rstrip("'").removesuffix("'s").removesuffix("’s"))
    return out


def word_present(word, words, folded_body):
    w = word.casefold()
    return w in words or w.rstrip("s") in words or w + "s" in words or w in folded_body


def validate(brief, transcript_text, vocabulary=None):
    vocabulary = vocabulary if vocabulary is not None else load_vocabulary()
    errors, flags = [], []
    rows, body = parse_transcript(transcript_text)
    folded = norm(body)
    words = set(re.findall(r"[a-z0-9'\-]+", folded))
    result = {"errors": errors, "flags": flags, "claims": 0, "claims_ok": 0, "quotes": 0, "quotes_ok": 0, "visible_chars": 0}
    if not isinstance(brief, dict):
        errors.append("brief is not a JSON object")
        return result
    missing, extra = KEYS - set(brief), set(brief) - KEYS
    if missing:
        errors.append("missing keys: " + ", ".join(sorted(missing)))
    if extra:
        errors.append("unexpected keys: " + ", ".join(sorted(extra)))
    if missing:
        return result
    for k in ("headline", "new"):
        if not isinstance(brief[k], str) or not brief[k].strip():
            errors.append("%s must be a non-empty string" % k)
    if isinstance(brief["headline"], str) and len(brief["headline"]) > 160:
        errors.append("headline over 160 characters")
    if isinstance(brief["new"], str) and len(brief["new"]) > 300:
        errors.append("new over 300 characters")
    for k, lo, hi in (("claims", 5, 8), ("quotes", 0, 2), ("topics", 1, 4), ("keywords", 0, 5), ("entities", 0, 12)):
        if not isinstance(brief[k], list):
            errors.append("%s must be a list" % k)
            return result
        if not lo <= len(brief[k]) <= hi:
            errors.append("%s has %d entries, wanted %d to %d" % (k, len(brief[k]), lo, hi))
    for k in ("topics", "keywords", "entities"):
        if any(not isinstance(x, str) or not x.strip() for x in brief[k]):
            errors.append("%s must hold non-empty strings" % k)
            return result
    for t in brief["topics"]:
        if t not in vocabulary:
            errors.append("topic not in the vocabulary: %r" % t)
    for k in brief["keywords"]:
        if len(k.split()) > 3:
            errors.append("keyword over 3 words: %r" % k)
    for c in brief["claims"]:
        if not (isinstance(c, dict) and isinstance(c.get("text"), str) and isinstance(c.get("ref"), str) and c["text"].strip()):
            errors.append("a claim is not {text, ref} strings")
            return result
    for q in brief["quotes"]:
        if not (isinstance(q, dict) and all(isinstance(q.get(k), str) and q[k].strip() for k in ("text", "speaker", "time"))):
            errors.append("a quote is not {text, speaker, time} strings")
            return result
    result["visible_chars"] = len(visible_text(brief))
    if result["visible_chars"] > CAP:
        errors.append("visible text is %d characters, cap %d" % (result["visible_chars"], CAP))
    if not rows:
        errors.append("transcript has no lines")

    # claims: ref exists, then the invented-fact heuristic
    have_numbers = transcript_numbers(body)
    result["claims"] = len(brief["claims"])
    for i, c in enumerate(brief["claims"], 1):
        if len(c["text"]) > 220:
            errors.append("claim %d over 220 characters" % i)
        if not ref_exists(c["ref"], rows):
            errors.append("claim %d: ref %r does not exist in the transcript" % (i, c["ref"]))
        else:
            result["claims_ok"] += 1
        for n in dict.fromkeys(numbers_in(c["text"])):
            if n not in have_numbers and n.lstrip("0") not in have_numbers:
                flags.append("claim %d: number %s not in the transcript" % (i, n))
        for name in dict.fromkeys(names_in(c["text"])):
            if not word_present(name, words, folded):
                flags.append("claim %d: name %r not in the transcript" % (i, name))
    if result["claims_ok"] < 4:
        errors.append("only %d claims have a valid ref (fewer than 4: the item falls back to the extractive digest)" % result["claims_ok"])

    # quotes: verbatim substring
    result["quotes"] = len(brief["quotes"])
    for i, q in enumerate(brief["quotes"], 1):
        n = len(q["text"].split())
        if not 8 <= n <= 40:
            flags.append("quote %d has %d words (wanted 8 to 40)" % (i, n))
        if norm(q["text"]) in folded:
            result["quotes_ok"] += 1
        else:
            errors.append("quote %d is not word for word in the transcript: %r" % (i, q["text"][:80]))
        if not ref_exists(q["time"], rows):
            errors.append("quote %d: time %r does not exist in the transcript" % (i, q["time"]))
    for key in ("entities",):
        for name in brief[key]:
            if not all(word_present(w, words, folded) for w in re.findall(r"[A-Za-z0-9][A-Za-z0-9'\-]*", name)):
                flags.append("entity %r not in the transcript" % name)
    return result


def verdict(result):
    return "FAIL" if result["errors"] else ("PASS (flags)" if result["flags"] else "PASS")


def report(name, result):
    lines = ["%s: %s" % (name, verdict(result)),
             "  claims %d (valid ref %d), quotes %d (verbatim %d), visible chars %d, errors %d, flags %d" % (
                 result["claims"], result["claims_ok"], result["quotes"], result["quotes_ok"], result["visible_chars"],
                 len(result["errors"]), len(result["flags"]))]
    lines += ["  ERROR " + e for e in result["errors"]] + ["  flag  " + f for f in result["flags"]]
    return "\n".join(lines)


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    as_json = "--json" in argv
    jobs = []
    if "--dir" in argv:
        i = argv.index("--dir")
        folder = argv[i + 1]
        data = argv[argv.index("--data") + 1] if "--data" in argv else os.path.join(HERE, "data")
        for f in sorted(os.listdir(folder)):
            if f.endswith(".brief.json"):
                item = f[:-len(".brief.json")]
                jobs.append((item, os.path.join(folder, f), os.path.join(data, item + ".transcript.txt")))
    elif len(args) == 2:
        jobs.append((os.path.basename(args[0]), args[0], args[1]))
    else:
        print(__doc__)
        return 2
    results, failed = {}, 0
    for name, bpath, tpath in jobs:
        try:
            brief = json.load(open(bpath, encoding="utf-8"))
        except (OSError, ValueError) as e:
            results[name] = {"errors": ["cannot read the brief as JSON: %s" % e], "flags": [], "claims": 0, "claims_ok": 0, "quotes": 0, "quotes_ok": 0, "visible_chars": 0}
        else:
            results[name] = validate(brief, open(tpath, encoding="utf-8").read())
        failed += bool(results[name]["errors"])
        if not as_json:
            print(report(name, results[name]))
    if as_json:
        print(json.dumps(results, indent=1))
    elif len(jobs) > 1:
        print("%d briefs, %d pass, %d fail" % (len(jobs), len(jobs) - failed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
