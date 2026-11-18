"""Fetch the transcripts of the spike items from their publishers and write spike/data/.

Run from the repository root:  python3 -I spike/fetch_data.py
Uses the project's own Fetcher (robots.txt, polite pauses, size caps) and read_answer (PEA transcript v1).
Needs the network; the rest of the spike does not.
"""
import json, os, sys, urllib.request
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from pea_knowledge import fetch, pipeline  # noqa: E402

BASE = "https://gptkiosk.github.io/pea-knowledge-processor/"
SOURCES = ["ai-daily-brief", "lex-fridman", "diary-of-a-ceo", "darknet-diaries", "80000-hours"]
PER_SOURCE = 2
CAP = 120_000
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")


def get_json(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "pea-knowledge-processor spike"}), timeout=60) as r:
        return json.load(r)


def main():
    store = get_json(BASE + "store.json")
    cards = {s["id"]: s for s in store["sources"]}
    config = json.load(open(os.path.join(ROOT, "config", "sources.json")))
    defaults = config.get("defaults", {})
    fetcher = fetch.Fetcher(log=lambda m: print("  [fetch]", m))
    os.makedirs(os.path.join(HERE, "data"), exist_ok=True)
    index, failures = [], []
    for sid in SOURCES:
        card = cards[sid]
        if card.get("state") != "active":
            failures.append((sid, "source not active"))
            continue
        src = next(s for s in config["sources"] if s["id"] == sid) if "sources" in config else None
        source = dict(defaults); source.update(src or {})
        items = sorted(get_json(BASE + card["items_file"]["path"])["items"], key=lambda i: i["date"], reverse=True)[:PER_SOURCE]
        for it in items:
            ts = it["transcript_source"]
            item = {"title": it["title"], "date": it["date"], "duration_seconds": it.get("duration_seconds")}
            try:
                answer = fetcher.get(ts["link"], fetch.TRANSCRIPT_BYTES)
                status, why, detail, text, _ = pipeline.read_answer(source, item, ts["link"], "", answer)
            except fetch.FetchError as e:
                failures.append((it["id"], "fetch: " + e.detail)); continue
            if text is None:
                failures.append((it["id"], "read: %s %s" % (why, detail))); continue
            cut = len(text) > CAP
            body = text[:CAP] if cut else text
            open(os.path.join(HERE, "data", it["id"] + ".transcript.txt"), "w", encoding="utf-8").write(body)
            digest = get_json(BASE + it["digest"]["path"])
            index.append({"id": it["id"], "source": sid, "title": it["title"], "date": it["date"], "transcript_chars": len(text),
                          "kept_chars": len(body), "cut": "yes" if cut else "no", "publisher_quality": status,
                          "digest_brief": digest.get("brief")})
            print(sid, it["id"], len(text), "cut" if cut else "whole", status)
    json.dump(index, open(os.path.join(HERE, "data", "index.json"), "w"), indent=1, ensure_ascii=False)
    for f in failures:
        print("FAILED", *f)


if __name__ == "__main__":
    main()
