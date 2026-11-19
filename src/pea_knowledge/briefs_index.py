# Copyright 2026 The PEA knowledge processor authors
# SPDX-License-Identifier: Apache-2.0
"""briefs-index.json: a compact list of the shows the output holds briefs for and their newest briefs.

An app uses it to say truthfully which shows it holds briefs for, how many, and which are newest, and to pick one brief
per show ("give me three across three different podcasts") without loading every items file. It carries nothing that
the items files and briefs do not already say: it is made from them, and the validator makes it again and refuses an
index that differs. Additive in format 1.3: a reader that does not know the file never fetches it.
"""
import json

from . import FORMAT_VERSION, textrules

INDEX_FILE = "briefs-index.json"
INDEX_BYTES = 32_000         # a reader refuses a larger file unread; the fourteen-source feed gives about 11 KB
LATEST_PER_SHOW = 5
LATEST_OVERALL = 12
TITLE_CHARS = 120


def _entry(item):
    b = item["brief"]
    return {"item_id": item["id"], "title": textrules.shorten(item["title"], TITLE_CHARS), "date": item["date"],
            "method": b["kind"], "partial": b["covers"] == "partial"}


def build(store, items_by_source, stamp):
    """The index as a value. `items_by_source` is {source id: the parsed items file}; a source without one has no briefs.
    Shows are listed newest first (by their newest brief, then id); a show's briefs in the order of its items file
    (newest first); `latest_overall` the newest briefs across shows (date, then show id, then the item order)."""
    shows, everything = [], []
    for listing in store["sources"]:
        items = [i for i in (items_by_source.get(listing["id"]) or {"items": []})["items"] if i.get("brief")]
        if not items:
            continue
        entries = [_entry(i) for i in items]
        shows.append({"id": listing["id"], "name": listing["name"], "kind": listing["kind"], "brief_count": len(items),
                      "latest": entries[:LATEST_PER_SHOW]})
        for n, e in enumerate(entries):
            everything.append(((e["date"], listing["id"], -n), dict(e, show_id=listing["id"])))
    shows.sort(key=lambda s: s["id"])
    shows.sort(key=lambda s: s["latest"][0]["date"], reverse=True)
    everything.sort(key=lambda x: (x[0][1], x[0][2]))
    everything.sort(key=lambda x: x[0][0], reverse=True)
    return {"format": "pea-knowledge-briefs-index", "format_version": FORMAT_VERSION, "generated_at": stamp,
            "shows": shows, "latest_overall": [e for _, e in everything[:LATEST_OVERALL]]}


def dumps(index):
    """The index as bytes. Compact (no indent), keys sorted, so the same data always gives the same bytes and the file
    stays small; the one exception to the two-space indent of the other files."""
    return (json.dumps(index, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def known_view(index):
    """Only the members this version defines, so a newer minor's additions do not make an index differ."""
    keys = ("item_id", "title", "date", "method", "partial")
    return {"generated_at": index["generated_at"],
            "shows": [{k: s[k] for k in ("id", "name", "kind", "brief_count")} | {"latest": [{k: e[k] for k in keys} for e in s["latest"]]} for s in index["shows"]],
            "latest_overall": [{k: e[k] for k in keys + ("show_id",)} for e in index["latest_overall"]]}
