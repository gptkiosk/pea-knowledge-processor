#!/usr/bin/env python3
# Copyright 2026 The PEA transcript authors
# SPDX-License-Identifier: Apache-2.0
"""Validates PEA transcript v1 files against SPEC.md and prints the result of every rule.

    python3 validate.py episode.pea.txt
    python3 validate.py transcripts/            every *.pea.txt under the folder
    python3 validate.py --quiet transcripts/    one line per file
    python3 validate.py --json episode.pea.txt  machine-readable

Exit status: 0 when every file conforms (warnings allowed), 1 when one does not, 2 when nothing could be read.
Standard library only. The file is treated as data: nothing in it is run, fetched or followed.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pea_transcript as pt  # noqa: E402

MAXIMUM_BYTES = 4_000_000  # far above any conforming file (150,000 characters of text); larger input is refused unread


def files_in(path):
    if os.path.isdir(path):
        found = []
        for folder, _, names in os.walk(path):
            found += [os.path.join(folder, n) for n in names if n.endswith(".pea.txt")]
        return sorted(found)
    return [path]


def check(path):
    """(results, summary) for one file. `summary` is what a reader finds, or None when it is not readable as v1."""
    if os.path.getsize(path) > MAXIMUM_BYTES:
        raise OSError("larger than %d bytes; not read" % MAXIMUM_BYTES)
    with open(path, "rb") as f:
        data = f.read()
    results = pt.validate(data)
    summary = None
    try:
        t = pt.parse(data.decode("utf-8"))
    except UnicodeDecodeError:
        t = None
    if t is not None:
        summary = {
            "segments": len(t.segments), "speakers": t.speakers, "timed": t.timed, "partial": t.partial, "chars": t.chars,
            "sponsor_segments": sum(1 for s in t.segments if pt.is_ad(s.text)),
        }
    return results, summary


def main(argv=None):
    p = argparse.ArgumentParser(description="Validate PEA transcript v1 files.")
    p.add_argument("paths", nargs="+", help="files, or folders searched for *.pea.txt")
    p.add_argument("--quiet", action="store_true", help="one line per file")
    p.add_argument("--json", action="store_true", help="print the results as JSON")
    a = p.parse_args(argv)
    paths = [f for path in a.paths for f in files_in(path)]
    if not paths:
        print("no *.pea.txt files found", file=sys.stderr)
        return 2
    report, bad, unread = [], 0, 0
    for path in paths:
        try:
            results, summary = check(path)
        except OSError as e:
            unread += 1
            print("%s: cannot be read (%s)" % (path, e.strerror or e), file=sys.stderr)
            continue
        ok = pt.conforms(results)
        bad += 0 if ok else 1
        failed = [r for r in results if r.status == "fail"]
        errors = [r.rule for r in failed if r.level == "error"]
        warnings = [r.rule for r in failed if r.level == "warning"]
        if a.json:
            report.append({"file": path, "conforms": ok, "fails": errors, "warnings": warnings, "reader": summary,
                           "rules": [{"rule": r.rule, "level": r.level, "status": r.status, "detail": r.detail} for r in results]})
            continue
        verdict = "conforms" if ok else "does not conform"
        if warnings and ok:
            verdict += " (%d warning%s)" % (len(warnings), "" if len(warnings) == 1 else "s")
        if a.quiet:
            print("%s: %s%s" % (path, verdict, "" if ok else ": " + ", ".join(errors)))
            continue
        print(path)
        for r in results:
            mark = {"pass": "pass", "fail": "FAIL" if r.level == "error" else "warn", "skip": "skip"}[r.status]
            print("  %-4s %-4s %s%s" % (mark, r.rule, pt.RULE_TEXT[r.rule], "  [" + r.detail + "]" if r.detail else ""))
        if summary is None:
            print("  reader: not readable as PEA transcript v1")
        else:
            print("  reader: %d segment%s, %s characters, %s, speakers: %s, %s%s" % (
                summary["segments"], "" if summary["segments"] == 1 else "s", "{:,}".format(summary["chars"]),
                "with times" if summary["timed"] else "no times", ", ".join(summary["speakers"]) or "none",
                "partial (" + summary["partial"] + ")" if summary["partial"] is not None else "full",
                ", %d sponsor or housekeeping" % summary["sponsor_segments"] if summary["sponsor_segments"] else ""))
        print("  result: " + verdict)
    if a.json:
        json.dump(report, sys.stdout, indent=1, ensure_ascii=False)
        sys.stdout.write("\n")
    elif len(paths) > 1:
        print("%d file%s: %d conform, %d do not%s" % (len(paths), "" if len(paths) == 1 else "s", len(paths) - bad - unread, bad,
                                                     ", %d could not be read" % unread if unread else ""))
    if unread == len(paths):
        return 2
    return 1 if bad or unread else 0


if __name__ == "__main__":
    sys.exit(main())
