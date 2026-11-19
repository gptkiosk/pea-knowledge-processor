# Copyright 2026 The PEA knowledge processor authors
# SPDX-License-Identifier: Apache-2.0
"""The command line.

    python3 -m pea_knowledge run --config config/sources.json --out dist
    python3 -m pea_knowledge run --config tests/fixtures/sources.json --out /tmp/dist --offline-fixtures tests/fixtures/web
    python3 -m pea_knowledge validate dist
    python3 -m pea_knowledge briefs --dry-run --limit 5     # which items would get a model brief, and the cost; no model call

`run` does everything. `fetch`, `digest`, `briefs` and `build` are its parts, for running them as separate jobs;
`restore` brings back the last published output, which is the pipeline's memory between runs.
"""
import argparse
import datetime
import os
import shutil
import sys
import tempfile

from . import fetch, jsonschema_lite, pipeline, validate


def _now(text):
    if text:
        return pipeline.parse_timestamp(text)
    if os.environ.get("SOURCE_DATE_EPOCH", "").isdigit():
        return datetime.datetime.fromtimestamp(int(os.environ["SOURCE_DATE_EPOCH"]), datetime.timezone.utc).replace(tzinfo=None)
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None, microsecond=0)


def _log(message):
    print(message, file=sys.stderr)


def _fetcher(args):
    if args.offline_fixtures:
        return fetch.fixture_fetcher(args.offline_fixtures, log=_log), "offline"
    return fetch.Fetcher(log=_log), "live"


def _work_time(work):
    return pipeline.parse_timestamp(jsonschema_lite.loads(pipeline.read(os.path.join(work, "work.json")))["now"])


def cmd_fetch(args):
    config = pipeline.load_config(args.config)
    fetcher, mode = _fetcher(args)
    shutil.rmtree(args.work, ignore_errors=True)
    os.makedirs(args.work)
    pipeline.fetch_stage(config, args.work, fetcher, pipeline.Previous(args.previous), _now(args.now), mode, _log)
    return 0


def cmd_briefs(args):
    """Stage 3b, or with --dry-run a list of what it would do and cost. A dry run never calls a model; when the work
    folder is not there it first fetches into a temporary one (from the publishers, or from --offline-fixtures)."""
    config = pipeline.load_config(args.config)
    previous = pipeline.Previous(args.previous)
    if not args.dry_run:
        pipeline.brief_stage(config, args.work, previous, log=_log, limit=args.limit)
        return 0
    work, temporary = args.work, None
    if not os.path.isfile(os.path.join(work, "work.json")):
        temporary = work = tempfile.mkdtemp(prefix="pea-knowledge-dry-")
        fetcher, mode = _fetcher(args)
        _log("no work folder at %s: fetching into a temporary one first (no model is called)" % args.work)
        # As the scheduled run's fetch job does when the secret is there: extractive briefs to upgrade are fetched again too.
        environment = dict(os.environ, **{pipeline.br.KEY_EXPECTED_VARIABLE: "true"})
        pipeline.fetch_stage(config, work, fetcher, previous, _now(args.now), mode, _log, environment)
    try:
        rows, t = pipeline.brief_estimate(config, work, previous, limit=args.limit)
    finally:
        if temporary:
            shutil.rmtree(temporary, ignore_errors=True)
    print("Dry run: no model was called. Model %s, %s; prices USD %s / %s per million tokens in / out." % (
        t["model"], ("on" if t["enabled"] else "off") + (", a key is set" if t["key"] else ", no key is set (a real run would write extractive briefs only)"),
        t["price"][0], t["price"][1]))
    print("Caps: %s US cents per run, %s per month; spent in %s so far: %s." % (t["run_cap_cents"], t["monthly_cap_cents"], t["month"], round(t["month_spent_cents"], 4)))
    for sid, iid, title, parts, calls, tin, tout, cents, what in rows:
        print("  %s/%s  %s  [%s]  calls %d, about %d + %d tokens, about %.4f US cents" % (sid, iid, title[:60], what, calls, tin, tout, cents))
    print("%d items listed (limit %s), %d by terms extractive; about %d calls and %.4f US cents in all (an estimate: the real count comes from the provider)." % (
        t["items"], args.limit if args.limit is not None else "none", t["by_terms"], t["calls"], t["cents"]))
    return 0


def cmd_digest(args):
    pipeline.digest_stage(pipeline.load_config(args.config), args.work, log=_log)
    return 0


def cmd_build(args):
    config = pipeline.load_config(args.config)
    health = pipeline.build_stage(config, args.work, pipeline.Previous(args.previous or args.out), args.out, _work_time(args.work), _log)
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as f:
            f.write(pipeline.health_summary(health))
    return 0


def cmd_run(args):
    config = pipeline.load_config(args.config)
    fetcher, mode = _fetcher(args)
    previous = pipeline.Previous(args.out)
    work = args.work or tempfile.mkdtemp(prefix="pea-knowledge-work-")
    try:
        if args.work:
            shutil.rmtree(work, ignore_errors=True)
            os.makedirs(work)
        now = _now(args.now)
        pipeline.fetch_stage(config, work, fetcher, previous, now, mode, _log)
        pipeline.digest_stage(config, work, log=_log)
        pipeline.brief_stage(config, work, previous, log=_log)
        health = pipeline.build_stage(config, work, previous, args.out, now, _log)
    finally:
        if not args.work:
            shutil.rmtree(work, ignore_errors=True)
    sys.stdout.write(pipeline.health_summary(health))
    return 0


def cmd_validate(args):
    report = validate.check_folder(args.folder)
    for p in report.problems:
        print(repr(p))
    print("%s: %d sources, %d items, %d files, %d bytes, %d problems" % ("valid" if report.ok else "NOT VALID", report.sources, report.items, report.files,
                                                                        report.bytes, len(report.problems)))
    return 0 if report.ok else 1


def cmd_summary(args):
    health, problems = validate.read_json(pipeline.read(os.path.join(args.folder, "health.json")), "health", "health.json", validate.HEALTH_BYTES)
    if health is None:
        print(problems[0])
        return 1
    sys.stdout.write(pipeline.health_summary(health))
    return 0


def cmd_restore(args):
    """Downloads the published output the way an app would: store.json first, then every file it names, each checked
    against its size and hash. Nothing published yet (404) gives an empty folder. Any other failure stops with an error,
    because running without the last output would forget what was kept."""
    base = args.url.rstrip("/") + "/"
    fetcher, _ = _fetcher(args)
    shutil.rmtree(args.out, ignore_errors=True)
    os.makedirs(args.out)

    def get(relative, limit):
        return fetcher.get(base + relative, limit).body

    try:
        data = get("store.json", validate.STORE_BYTES)
    except fetch.FetchError as e:
        if e.code == "not_found":
            _log("nothing is published yet at %s: starting empty" % base)
            return 0
        _log("the published output could not be read: %s" % e)
        return 2
    store, problems = validate.check_store(data)
    if store is None:
        _log("the published store.json does not validate (%s): starting empty" % problems[0])
        return 0
    pipeline.write(os.path.join(args.out, "store.json"), data)
    try:
        for listing in store["sources"]:
            ref = listing["items_file"]
            if ref is None:
                continue
            data = get(ref["path"], validate.ITEMS_BYTES)
            items, problems = validate.check_items(data, listing, store.get("topics", []))
            if items is None:
                _log("%s: the published items file does not validate (%s)" % (listing["id"], problems[0]))
                continue
            pipeline.write(os.path.join(args.out, *ref["path"].split("/")), data)
            for item in items["items"]:
                for file, limit in ((item["digest"], validate.DIGEST_BYTES), (item["transcript"]["file"], validate.TRANSCRIPT_BYTES), (item.get("brief"), validate.BRIEF_BYTES)):
                    if file is not None:
                        data = get(file["path"], limit)
                        if not validate.check_file(data, file, file["path"]):
                            pipeline.write(os.path.join(args.out, *file["path"].split("/")), data)
        for name in ("state.json", "health.json"):
            pipeline.write(os.path.join(args.out, name), get(name, validate.HEALTH_BYTES))
        try:   # the briefs index (1.3) is made anew by every build; an output of 0.6.0 has none
            pipeline.write(os.path.join(args.out, "briefs-index.json"), get("briefs-index.json", validate.INDEX_BYTES))
        except fetch.FetchError as e:
            if e.code != "not_found":
                raise
    except fetch.FetchError as e:
        _log("the published output could not be read in full: %s" % e)
        return 2
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="pea_knowledge", description="Processes a curated list of sources into the PEA knowledge format.")
    sub = p.add_subparsers(dest="command", required=True)

    def common(c, config=True):
        if config:
            c.add_argument("--config", default="config/sources.json", help="the curated source list")
        c.add_argument("--offline-fixtures", metavar="FOLDER", help="answer every request from this folder instead of the network")
        c.add_argument("--now", metavar="YYYY-MM-DDTHH:MM:SSZ", help="the time of the run (default: now, or SOURCE_DATE_EPOCH)")

    c = sub.add_parser("run", help="fetch, normalize, digest and build")
    common(c)
    c.add_argument("--out", default="dist", help="the output folder; what is in it is the previous output")
    c.add_argument("--work", help="keep the work folder here (default: a temporary folder)")
    c.set_defaults(run=cmd_run)
    c = sub.add_parser("fetch", help="stages 1 and 2: fetch and normalize into a work folder")
    common(c)
    c.add_argument("--work", required=True)
    c.add_argument("--previous", help="the previous output folder")
    c.set_defaults(run=cmd_fetch)
    c = sub.add_parser("digest", help="stage 3: write digests into the work folder (reads OPENROUTER_API_KEY when the model is switched on)")
    c.add_argument("--config", default="config/sources.json")
    c.add_argument("--work", required=True)
    c.set_defaults(run=cmd_digest)
    c = sub.add_parser("briefs", help="stage 3b: write model briefs into the work folder (format 1.3; reads OPENROUTER_API_KEY; without it, writes nothing)")
    common(c)
    c.add_argument("--work", default="work", help="the work folder of a fetch (a dry run fetches into a temporary one when it is not there)")
    c.add_argument("--previous", help="the previous output folder: its briefs are reused when the transcript is unchanged, and its state.json holds the month's spend")
    c.add_argument("--dry-run", action="store_true", help="print which items would get a model brief and the estimated cost; no model call")
    c.add_argument("--limit", type=int, help="at most this many items")
    c.set_defaults(run=cmd_briefs)
    c = sub.add_parser("build", help="stage 4: write the output folder from the work folder and the previous output")
    c.add_argument("--config", default="config/sources.json")
    c.add_argument("--work", required=True)
    c.add_argument("--previous", help="the previous output folder (default: what is in --out)")
    c.add_argument("--out", default="dist")
    c.add_argument("--summary", help="append the health report as Markdown to this file")
    c.set_defaults(run=cmd_build)
    c = sub.add_parser("validate", help="check an output folder against the schemas, the text rules and the hashes")
    c.add_argument("folder")
    c.set_defaults(run=cmd_validate)
    c = sub.add_parser("summary", help="print the health report of an output folder as Markdown")
    c.add_argument("folder")
    c.set_defaults(run=cmd_summary)
    c = sub.add_parser("restore", help="download the published output into a folder, checking every file")
    common(c, config=False)
    c.add_argument("--url", required=True, help="where store.json is published")
    c.add_argument("--out", required=True)
    c.set_defaults(run=cmd_restore)
    args = p.parse_args(argv)
    try:
        return args.run(args)
    except (pipeline.ConfigError, RuntimeError) as e:
        _log("error: %s" % e)
        return 2
