# Copyright 2026 The PEA knowledge processor authors
# SPDX-License-Identifier: Apache-2.0
"""Shared by the tests and by make_golden.py: where things are, an offline run, and the lifecycle walk."""
import copy
import datetime
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))

from pea_knowledge import fetch, jsonschema_lite, pipeline  # noqa: E402

WEB = os.path.join(HERE, "fixtures", "web")
CONFIG = os.path.join(HERE, "fixtures", "sources.json")
GOLDEN = os.path.join(HERE, "golden")
T0 = datetime.datetime(2026, 11, 14, 12, 0, 0)
QUIET = lambda message: None  # noqa: E731


def load_config(change=None):
    """The fixture config, optionally changed by `change(config)`, loaded the way the pipeline loads it."""
    with open(CONFIG, encoding="utf-8") as f:
        raw = json.load(f)
    if change:
        change(raw)
    path = os.path.join(HERE, ".test-output-config-%d.json" % os.getpid())
    with open(path, "w", encoding="utf-8") as f:
        json.dump(raw, f)
    try:
        return pipeline.load_config(path)
    finally:
        os.remove(path)


def web_copy(target, change=None):
    """A copy of the saved web whose manifest `change(responses)` may alter. Returns the folder."""
    shutil.copytree(WEB, target)
    if change:
        path = os.path.join(target, "manifest.json")
        with open(path, encoding="utf-8") as f:
            manifest = json.load(f)
        change(manifest["responses"])
        with open(path, "w", encoding="utf-8") as f:
            json.dump(manifest, f)
    return target


def run(out, now=T0, config=None, web=WEB, environment=None, work=None):
    """One whole offline run into `out` (what is there is the previous output). Returns the health report."""
    config = config or load_config()
    work = work or out + ".work"
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    previous = pipeline.Previous(out)
    fetcher = fetch.fixture_fetcher(web, log=QUIET)
    pipeline.fetch_stage(config, work, fetcher, previous, now, "offline", QUIET)
    pipeline.digest_stage(config, work, environment if environment is not None else {}, QUIET)
    health = pipeline.build_stage(config, work, previous, out, now, QUIET)
    shutil.rmtree(work, ignore_errors=True)
    return health


def tree(folder):
    """{relative path: bytes} for every file under `folder`."""
    out = {}
    for base, _, names in os.walk(folder):
        for name in names:
            path = os.path.join(base, name)
            with open(path, "rb") as f:
                out[os.path.relpath(path, folder).replace(os.sep, "/")] = f.read()
    return out


def store(folder):
    with open(os.path.join(folder, "store.json"), encoding="utf-8") as f:
        return json.load(f)


def listing(folder, sid):
    return next((s for s in store(folder)["sources"] if s["id"] == sid), None)


def items(folder, sid):
    with open(os.path.join(folder, "sources", sid, "items.json"), encoding="utf-8") as f:
        return json.load(f)["items"]


def digest_of(folder, sid, iid):
    with open(os.path.join(folder, "sources", sid, iid + ".digest.json"), encoding="utf-8") as f:
        return json.load(f)


def broken_tide(responses):
    responses["https://tide.example.org/feed.xml"] = {"status": 503}


def walk_lifecycle(base, snapshot):
    """Runs the pipeline through every lifecycle change, one run every six hours on the same output folder, and calls
    `snapshot(name, folder)` after each named step. Used for the golden store.json of each state and by the tests."""
    out = os.path.join(base, "dist")
    broken = web_copy(os.path.join(base, "web-broken"), broken_tide)
    step = [0]

    def go(change=None, web=WEB, days=0):
        now = T0 + datetime.timedelta(hours=6 * step[0], days=days)
        step[0] += 1
        return run(out, now, load_config(chain(no_topics, change) if change else no_topics), web)

    def manual(sid, **values):
        def change(raw):
            for s in raw["sources"]:
                if s["id"] == sid:
                    s.update(values)
        return change

    def chain(*changes):
        def change(raw):
            for c in changes:
                c(raw)
        return change

    def no_topics(raw):
        """The walk is about states, so it leaves the vocabulary out: each store.json stays small enough to read."""
        raw["topics"] = {"enabled": False}

    def drop(sid):
        def change(raw):
            raw["sources"] = [s for s in raw["sources"] if s["id"] != sid]
        return change

    go()
    snapshot("01-active", out)
    go(web=broken)
    snapshot("02-stale-after-one-failure", out)
    go(web=broken)
    go(web=broken)
    snapshot("03-paused-automatically", out)
    go()
    snapshot("04-recovered", out)
    pause = manual("harbor-voices", state="paused", message="Paused while the publisher changes its transcript format. What you have stays readable.")
    go(pause)
    snapshot("05-paused-by-the-curator", out)
    withdraw = manual("quay-notes", state="withdrawn", state_reason="quality", message="Removed because the notes were too thin to talk about.")
    go(chain(pause, withdraw))
    snapshot("06-withdrawn", out)
    purge = manual("port-gazette", state="withdrawn", state_reason="takedown", purge=True, message="Removed at the publisher's request. Local copies must be deleted.")
    go(chain(pause, withdraw, purge))
    snapshot("07-withdrawn-with-purge", out)
    go(chain(withdraw, purge, drop("harbor-voices")))
    snapshot("08-removed-from-the-config", out)
    go(chain(drop("quay-notes"), drop("port-gazette"), drop("harbor-voices")), days=100)
    snapshot("09-notices-expired", out)
    return out
