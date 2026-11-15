# Copyright 2026 The PEA knowledge processor authors
# SPDX-License-Identifier: Apache-2.0
"""Measures the topic tags of an output folder against the hand-labelled items in tests/data/topics_labelled.json.

    python3 -m pea_knowledge run --config config/sources.json --out /tmp/pea-dist
    python3 tests/eval_topics.py /tmp/pea-dist            # add --all to list every item, not only the wrong ones

A tag is correct when the label lists it under `topics` or `also`. Precision is correct tags over tags given; recall
is how many of the `topics` (the main ones) were given. Items that have left the feeds since they were labelled are
counted as "not in this output" and left out. The numbers say how the tagger does on these sources, not on any other.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def measure(folder, labelled):
    """Per split: [items, tags given, correct, wrong, main topics, main topics missed, items without a tag]."""
    found, lines, totals = {}, [], {}
    with open(os.path.join(folder, "store.json"), encoding="utf-8") as f:
        store = json.load(f)
    for listing in store["sources"]:
        if listing["items_file"]:
            with open(os.path.join(folder, *listing["items_file"]["path"].split("/")), encoding="utf-8") as f:
                for item in json.load(f)["items"]:
                    found[(listing["id"], item["id"])] = item
    for row in labelled:
        item = found.get((row["source"], row["id"]))
        if item is None or "topics" not in item:
            continue
        got = [t["id"] for t in item["topics"]]
        allowed = set(row["topics"]) | set(row["also"])
        wrong, missed = [g for g in got if g not in allowed], [m for m in row["topics"] if m not in got]
        for name in (row["split"], "all"):
            t = totals.setdefault(name, [0] * 7)
            for n, value in enumerate((1, len(got), len(got) - len(wrong), len(wrong), len(row["topics"]), len(missed), int(not got))):
                t[n] += value
        lines.append((row, item, wrong, missed))
    return totals, lines


def main(argv):
    if not argv or argv[0].startswith("-"):
        print(__doc__)
        return 2
    with open(os.path.join(HERE, "data", "topics_labelled.json"), encoding="utf-8") as f:
        labelled = json.load(f)["items"]
    totals, lines = measure(argv[0], labelled)
    for row, item, wrong, missed in lines:
        if wrong or missed or "--all" in argv:
            tags = " ".join("%s:%.2f" % (t["id"], t["score"]) for t in item["topics"]) or "-"
            print("%-18s %-60s %s%s%s" % (row["source"], row["title"][:60], tags, "  WRONG " + ",".join(wrong) if wrong else "", "  MISSED " + ",".join(missed) if missed else ""))
    print("%d of %d labelled items are in this output" % (len(lines), len(labelled)))
    for name, (items, given, correct, wrong, main, missed, empty) in sorted(totals.items()):
        print("%-9s %3d items, %3d tags, %3d correct, %2d wrong: precision %.1f%%; %d of %d main topics found: recall %.1f%%; %d items without a tag" % (
            name, items, given, correct, wrong, 100.0 * correct / max(1, given), main - missed, main, 100.0 * (main - missed) / max(1, main), empty))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
