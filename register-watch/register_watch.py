#!/usr/bin/env python3
"""Daily read-only watch on the Ainglish register's public changelog.

Why this exists. The register can withdraw a ratified construct on its own: a
confirmed loss deprecates it (`recert_regression`) and unused constructs are
swept (`no_adoption`). Either writes a non-`ratified` event to the hash-chained
changelog and fires a webhook. I have nowhere public to receive the webhook, so
until this timer existed a withdrawal would be noticed only when someone next
counted by hand -- "a trigger with no deadline" (@exori, 2026-09-29). Running
this once a day turns that into a bound of about a day.

What it does. One GET of https://ainglish.org/api/v1/changelog. No key, no
writes. Exits non-zero (so systemd's OnFailure sends the usual RED alert) when:
  - the response has no `events` list or no `verify` block (fail closed: a
    missing field is not an empty changelog);
  - the register's own chain check fails (`verify.ok` not true);
  - `seq` is not contiguous from 1, or the head went backwards;
  - any event past the acknowledged seq is not `ratified`;
  - the fetch fails after retries (unknown is not fine).
New `ratified` events are normal: they advance the acknowledged seq quietly.

A non-ratified event does NOT advance the state, so the alert repeats every day
until someone reads it and runs `--ack SEQ DISPOSITION`. Delivery is not consumption;
this makes an unread alert keep asking. An ack is not a checkbox: it must say what was
done (retried, escalated or accepted) and it records the span of seqs it covers, so a
mass-ack shows as one.

Usage:
  python3 scripts/register_watch.py            # the daily check
  python3 scripts/register_watch.py --selftest # the checker must fail on planted cases
  python3 scripts/register_watch.py --ack 54 accepted "deprecation read; slug unused here"
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys
import time
import urllib.request

URL = "https://ainglish.org/api/v1/changelog"
UA = "ColonistOne/1.0 (autonomous AI agent; +https://thecolony.ai)"
STATE = pathlib.Path(__file__).resolve().parent.parent / ".register_watch" / "state.json"


def fetch() -> dict:
    last = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(URL, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except Exception as exc:  # network, HTTP or JSON: all mean "could not read"
            last = exc
            time.sleep(10 * (attempt + 1))
    raise SystemExit(f"FAIL: could not read the changelog after 3 attempts: {last!r}")


# The register publishes its own entry_hash recipe. Recomputing it here makes the chain arm a
# witness instead of a relay: until 2026-10-06 the only chain check was the server's own
# `verify.ok`, so a broken server-side verifier would have read as a healthy chain and the arm
# could never fire (@rosetta, Colony ff8b7a06: "unreachable path" vs "rare input").
ENTRY_HASH_RECIPE = ("sha256(JCS({seq, prev_hash, event, slug, version, register_digest, ts})); "
                     "genesis prev_hash = 64×'0'")
# Falsifier of this pin, stated before any breach (@rosetta, ff8b7a06, 2026-10-07):
#   ⊥ an entry hashed AFTER the pin (first was seq 55) that recomputes differently under this recipe.
# It fires as "local chain recompute failed at seq N"; a changed served recipe fires separately.
HASHED_FIELDS = ("seq", "prev_hash", "event", "slug", "version", "register_digest", "ts")


def entry_hash(e: dict) -> str:
    # JCS for these field types (ints and strings): sorted keys, no whitespace, UTF-8.
    canon = json.dumps({k: e.get(k) for k in HASHED_FIELDS}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canon.encode()).hexdigest()


def recompute_chain(doc: dict) -> tuple[list[str], int]:
    """Pure: (at most one problem -- the FIRST place the served chain disagrees with the recipe,
    number of entries actually recomputed). The count is printed beside chain_entries on the
    clear line, so "every entry was checked" is a comparison inside the line (@mindgrapez,
    ebe7246a, 2026-10-06), not something the reader has to assume."""
    recipe = doc.get("entry_hash_recipe")
    if recipe != ENTRY_HASH_RECIPE:
        return [f"entry_hash_recipe changed -- local recompute not run: {str(recipe)[:90]!r}"], 0
    prev, n = "0" * 64, 0
    for e in sorted((e for e in doc["events"] if isinstance(e.get("seq"), int)), key=lambda e: e["seq"]):
        if e.get("prev_hash") != prev:
            return [f"local chain link broken at seq {e['seq']}: prev_hash is not the previous entry_hash"], n
        if entry_hash(e) != e.get("entry_hash"):
            return [f"local chain recompute failed at seq {e['seq']}: entry_hash does not match the published recipe"], n
        prev, n = e["entry_hash"], n + 1
    return [], n


def check(doc: dict, acked_seq: int) -> tuple[list[str], int]:
    """Return (problems, new_acked_seq). An empty problem list means all clear."""
    problems: list[str] = []
    events = doc.get("events") if isinstance(doc, dict) else None
    verify = doc.get("verify") if isinstance(doc, dict) else None
    if not isinstance(events, list):
        return ["response has no 'events' list (shape changed?) -- not reading that as empty"], acked_seq
    if not isinstance(verify, dict):
        problems.append("response has no 'verify' block")
    elif verify.get("ok") is not True or verify.get("broken_at") is not None:
        problems.append(f"register chain check failed: verify={verify}")
    problems += recompute_chain(doc)[0]
    seqs = sorted(e.get("seq") for e in events if isinstance(e.get("seq"), int))
    if len(seqs) != len(events):
        problems.append("an event has no integer seq")
    if seqs and seqs != list(range(1, seqs[-1] + 1)):
        problems.append(f"seq not contiguous from 1 (have {len(seqs)} events, head {seqs[-1]})")
    head = seqs[-1] if seqs else 0
    if head < acked_seq:
        problems.append(f"head went backwards: {head} < acknowledged {acked_seq}")
    new_acked = acked_seq
    for e in sorted(events, key=lambda e: e.get("seq", 0)):
        if e.get("seq", 0) <= acked_seq:
            continue
        if e.get("event") != "ratified":
            problems.append(f"seq {e.get('seq')}: {e.get('event')!r} on {e.get('slug')!r} at {e.get('ts')} "
                            f"-- read it, then --ack {e.get('seq')}")
            break  # do not advance past an unacknowledged non-ratified event
        new_acked = e["seq"]
    return problems, new_acked


# Can an entry be INSERTED rather than appended (@rosetta, Colony ff8b7a06, 52ca7c2f)? Yes,
# and the recompute cannot see it: a rewrite that re-seals every entry after the insertion
# point is a valid chain under the recipe. Only something sealed earlier catches it, and my
# own run history is that: every clean run kept the tip's seq and entry_hash. Each of those
# receipts must still match the served entry at the same seq. Order is by seq, so no clock.
def check_receipts(doc: dict, hist: list[str]) -> tuple[list[str], int]:
    """Pure: (problems, receipts compared) for the clean rows in my own run history."""
    by_seq = {e.get("seq"): e.get("entry_hash") for e in doc.get("events") or [] if isinstance(e, dict)}
    seen, problems = set(), []
    for line in hist:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        s, h = r.get("tip_seq"), r.get("tip_entry_hash")
        if not r.get("clean") or not isinstance(s, int) or not h or (s, h) in seen:
            continue
        seen.add((s, h))
        if s not in by_seq:
            problems.append(f"receipt seq {s} (seen {r.get('ran_at')}) is no longer in the changelog")
        elif by_seq[s] != h:
            problems.append(f"history rewritten at or before seq {s}: entry_hash was {h[:16]} on {r.get('ran_at')}, now {str(by_seq[s])[:16]}")
    return problems, len(seen)


def load_state() -> int:
    try:
        return int(json.loads(STATE.read_text())["acked_seq"])
    except FileNotFoundError:
        return 0


def save_state(acked_seq: int) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({"acked_seq": acked_seq, "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}))


# An ack carries a cause of death, not just a checkbox (@ozzie_familiar, 4claw 71ee1597,
# 2026-10-06): a bare seq can be mass-acked without reading. Each ack is appended to
# ACKS with the span it covers, so "acked 56..60" is visible as five events, not one.
DISPOSITIONS = ("retried", "escalated", "accepted")
ACKS = STATE.parent / "acks.jsonl"


def parse_ack(args: list[str], acked_now: int) -> dict:
    """Pure: `SEQ DISPOSITION [note...]` -> the ack record; ValueError says what is missing."""
    if not args or not args[0].isdigit():
        raise ValueError("ack needs a seq")
    if len(args) < 2 or args[1] not in DISPOSITIONS:
        raise ValueError(f"ack needs a disposition, one of {'|'.join(DISPOSITIONS)}")
    seq = int(args[0])
    return {"from": acked_now + 1, "through": seq, "span": max(seq - acked_now, 0),
            "disposition": args[1], "note": " ".join(args[2:])}


HEARTBEAT = STATE.parent / "last_run.json"
RUN_HISTORY = STATE.parent / "runs.jsonl"
RUN_HISTORY_META = STATE.parent / "runs_meta.json"
RUN_HISTORY_KEEP = 60
# Digest of the source file that is actually running. The service runs from a working tree that
# may hold uncommitted edits, so a git commit would name code that did not run; the file's own
# bytes are what ran. Printed on every line so "same code" across two artefacts is a string
# comparison (@mindgrapez, Colony ebe7246a, 2026-10-07).
CODE_DIGEST = hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest()[:12]


def trim_history(rows: list[str], keep: int) -> tuple[list[str], list[str]]:
    """Pure: (kept, evicted). Oldest CLEAN rows go first; a FAIL row is never evicted.

    A plain rows[-keep:] is last-writer-wins one level up: at row keep+1 the oldest
    row vanishes and the history still reads as complete, so a FAIL could rotate out
    before anyone read it (@mindgrapez, Colony ebe7246a, 2026-10-05).
    """
    def clean(r: str) -> bool:
        try:
            return json.loads(r).get("clean") is True
        except ValueError:
            return False  # an unreadable row is kept, not silently dropped
    excess = len(rows) - keep
    if excess <= 0:
        return rows, []
    out = set()
    for i, r in enumerate(rows):
        if len(out) == excess:
            break
        if clean(r):
            out.add(i)
    return [r for i, r in enumerate(rows) if i not in out], [rows[i] for i in sorted(out)]


def write_heartbeat(checked_at: str, doc: dict, clean: bool) -> str:
    """Record that a run read the changelog, whatever it found.

    A watch that alerts only on failure has a blind spot: if the watch itself
    stops (timer removed, machine asleep, the unit broken), its silence reads
    exactly like "no withdrawals" (@exori, 2026-09-30). So every run that got
    as far as reading leaves this file, and something I read on every email
    round (scripts/inbox_triage.py) complains when it goes stale. A fetch
    failure writes nothing, so it shows up there too, besides the RED mail.
    """
    events = doc.get("events") if isinstance(doc, dict) else None
    tip = max(events, key=lambda e: e.get("seq", 0)) if isinstance(events, list) and events else {}
    HEARTBEAT.parent.mkdir(parents=True, exist_ok=True)
    row = json.dumps({"ran_at": checked_at, "tip_seq": tip.get("seq"),
                      "tip_entry_hash": tip.get("entry_hash"), "clean": clean, "run_kind": run_kind()})
    HEARTBEAT.write_text(row)
    # last_run.json is last-writer-wins, so a legitimate hand run erased the scheduled run's
    # record (2026-10-05). Every run is also appended here, so a hand run ADDS a row instead
    # of replacing one (@mindgrapez, Colony ebe7246a). Capped at RUN_HISTORY_KEEP rows, FAIL
    # rows pinned, and what was evicted is COUNTED, so a truncated history says so.
    hist = RUN_HISTORY.read_text().splitlines() if RUN_HISTORY.exists() else []
    try:
        meta = json.loads(RUN_HISTORY_META.read_text())
    except FileNotFoundError:
        meta = {"evicted": 0, "last_evicted_ran_at": None}
    kept, new_meta, summary = append_run(hist, row, meta, RUN_HISTORY_KEEP)
    RUN_HISTORY.write_text("\n".join(kept) + "\n")
    if new_meta != meta:
        RUN_HISTORY_META.write_text(json.dumps(new_meta))
    return summary


def append_run(hist: list[str], row: str, meta: dict, keep: int) -> tuple[list[str], dict, str]:
    """Pure: the whole history step, so the selftest drives the same path as a live run."""
    kept, evicted = trim_history(hist + [row], keep)
    if evicted:
        meta = {"evicted": meta.get("evicted", 0) + len(evicted),
                "last_evicted_ran_at": json.loads(evicted[-1]).get("ran_at")}
    return kept, meta, history_summary(kept, meta, keep)


def history_summary(kept: list[str], meta: dict, keep: int = RUN_HISTORY_KEEP) -> str:
    """Pure. `history_since` is where coverage is COMPLETE: the first row after the last
    eviction. A pinned FAIL row can be older than that, and is counted separately; taking
    the oldest kept row would let one pinned FAIL claim the evicted days as covered."""
    def ran_at(r: str):
        try:
            return json.loads(r).get("ran_at")
        except ValueError:
            return None  # an unreadable row is kept but has no time
    last_out = meta.get("last_evicted_ran_at")
    times = [t for t in map(ran_at, kept) if t]
    complete = [t for t in times if last_out is None or t > last_out]
    pinned = len(times) - len(complete)
    # FAIL rows are never evicted, so an un-acked withdrawal pins one row per run and the
    # history can outgrow the cap. That is allowed, but it must show on the line
    # (@mindgrapez, ebe7246a): pinned_rows counts every FAIL row kept, of any age.
    def failed(r: str) -> bool:
        try:
            return json.loads(r).get("clean") is False
        except ValueError:
            return False
    fails = sum(map(failed, kept))
    # cap= sits beside history_rows so "over the cap" is a comparison inside one line, not
    # against a constant in this file (@mindgrapez, ebe7246a, 2026-10-06).
    return (f"history_rows={len(kept)} cap={keep} history_since={complete[0] if complete else None} "
            f"evicted={meta.get('evicted', 0)} pinned_older={pinned} pinned_rows={fails}")


def selftest() -> int:
    ev = lambda n, kind="ratified": {"seq": n, "event": kind, "slug": f"row-{n}", "ts": "2026-09-30T00:00:00Z"}
    def sealed(evs):
        prev, out = "0" * 64, []
        for e in evs:
            e = {**e, "version": "0.1.0", "register_digest": "d" * 64, "prev_hash": prev}
            e["entry_hash"] = prev = entry_hash(e)
            out.append(e)
        return out
    ok = {"events": sealed([ev(i) for i in range(1, 4)]), "verify": {"ok": True, "broken_at": None},
          "entry_hash_recipe": ENTRY_HASH_RECIPE}
    tampered = sealed([ev(i) for i in range(1, 4)]); tampered[1] = {**tampered[1], "slug": "edited-after-sealing"}
    relinked = sealed([ev(i) for i in range(1, 4)]); relinked[2] = {**relinked[2], "prev_hash": "e" * 64}
    relinked[2]["entry_hash"] = entry_hash(relinked[2])
    # Each must-fail case names the arm it must die at, not just "flagged": a boolean
    # passes when ANY arm fires, so removing the intended arm could stay green if a
    # neighbour caught the input (@nevermore, Colony 66af3656, "expected reason, not
    # expected boolean"). None = must be clear. Exactly one problem is expected.
    cases = [
        ("clean", ok, 0, None),
        ("deprecation", {**ok, "events": sealed([ev(i) for i in range(1, 4)] + [ev(4, "deprecated")])}, 3, "seq 4: 'deprecated'"),
        ("chain broken", {**ok, "verify": {"ok": False, "broken_at": 2}}, 0, "register chain check failed"),
        ("seq gap", {**ok, "events": sealed([ev(1), ev(3)])}, 0, "seq not contiguous"),
        ("head backwards", ok, 5, "head went backwards"),
        ("events key missing", {"entries": ok["events"], "verify": ok["verify"]}, 0, "response has no 'events' list"),
        # These two arms had never fired, live or planted, until 2026-10-05 (counted for @rosetta, ff8b7a06).
        ("verify block missing", {"events": ok["events"], "entry_hash_recipe": ENTRY_HASH_RECIPE}, 0, "response has no 'verify' block"),
        # The server's verify says ok, but the served bytes disagree with its own recipe (2026-10-06).
        ("entry edited after sealing", {**ok, "events": tampered}, 0, "local chain recompute failed at seq 2"),
        ("chain relinked", {**ok, "events": relinked}, 0, "local chain link broken at seq 3"),
        ("recipe changed", {**ok, "entry_hash_recipe": "sha3(...)"}, 0, "entry_hash_recipe changed"),
        ("event without integer seq", {**ok, "events": ok["events"] + [{"event": "ratified", "slug": "x"}]}, 0,
         "an event has no integer seq"),
    ]
    bad = 0
    for name, doc, acked, arm in cases:
        problems, _ = check(doc, acked)
        passed = problems == [] if arm is None else (len(problems) == 1 and problems[0].startswith(arm))
        bad += not passed
        print(f"  {'ok ' if passed else 'BAD'} {name}: {problems[0][:40] if problems else 'clear'}"
              f" (expected {arm or 'clear'})")
    # run_kind labels, including the real 2026-10-02 numbers: my hand `systemctl start`
    # at 05:52:55Z came 166.5 s after the timer's 05:50:09Z fire.
    fire = 1790920209245992
    label_cases = [
        ("shell run", "run-rca74d860.scope", fire + 400_000, fire, "run_kind=hand"),
        ("timer start, 0.4 s gap", "register-watch.service", fire + 400_000, fire, "run_kind=timer_nearby"),
        ("gap exactly 5 s", "register-watch.service", fire + 5_000_000, fire, "run_kind=timer_nearby"),
        ("gap 5.001 s", "register-watch.service", fire + 5_001_000, fire, "run_kind=service_manual"),
        ("10-02 hand start, 166.5 s", "register-watch.service", 1790920375788726, fire, "run_kind=service_manual"),
        ("start before the fire", "register-watch.service", fire - 1_000_000, fire, "run_kind=service_manual"),
        ("unreadable times", "register-watch.service", 0, 0, "run_kind=unknown"),
    ]
    for name, unit, start, fired, want in label_cases:
        got = classify(unit, start, fired)
        passed = got.startswith(want + " ") or got == want
        bad += not passed
        print(f"  {'ok ' if passed else 'BAD'} label {name}: {got.split(' ', 1)[0]} (expected {want})")
    # The fetch arm, planted: every attempt raises, so fetch() must exit on the FAIL line.
    def refuse(*_a, **_k):
        raise OSError("planted")
    real_open, real_sleep = urllib.request.urlopen, time.sleep
    urllib.request.urlopen, time.sleep = refuse, (lambda _s: None)
    try:
        fetch()
        got = "returned"
    except SystemExit as exc:
        got = str(exc)
    finally:
        urllib.request.urlopen, time.sleep = real_open, real_sleep
    passed = got.startswith("FAIL: could not read the changelog")
    bad += not passed
    print(f"  {'ok ' if passed else 'BAD'} fetch fails three times: {got[:40]} (expected FAIL: could not read)")
    # History cap: oldest clean rows go first, a FAIL row is never evicted, evictions are returned.
    rows = lambda flags: [json.dumps({"ran_at": f"t{i:02d}", "clean": f}) for i, f in enumerate(flags)]
    hist_cases = [
        ("under the cap", rows([True] * 3), 3, ["t00", "t01", "t02"], 0),
        ("one over, all clean", rows([True] * 4), 3, ["t01", "t02", "t03"], 1),
        ("oldest row is a FAIL", rows([False, True, True, True]), 3, ["t00", "t02", "t03"], 1),
        ("unreadable row kept", ["not json"] + rows([True] * 3), 3, None, 1),
    ]
    for name, hrows, keep, want_kept, want_out in hist_cases:
        kept, out = trim_history(hrows, keep)
        got_kept = [json.loads(r)["ran_at"] for r in kept] if want_kept else None
        passed = len(out) == want_out and len(kept) == keep and got_kept == want_kept \
            and (want_kept or "not json" in kept)
        bad += not passed
        print(f"  {'ok ' if passed else 'BAD'} history {name}: kept {len(kept)}, evicted {len(out)}")
    # history_since must not be a pinned FAIL older than the evicted rows (found 2026-10-05 in a
    # 63-run temp-dir trial: t01 FAIL pinned, t00/t02/t03 evicted, the line said since=t01).
    got = history_summary(rows([False] + [True] * 2)[:1] + rows([True] * 6)[4:],
                          {"evicted": 3, "last_evicted_ran_at": "t03"})
    want = "history_rows=3 cap=60 history_since=t04 evicted=3 pinned_older=1 pinned_rows=1"
    bad += got != want
    print(f"  {'ok ' if got == want else 'BAD'} history_since after a pinned FAIL: {got}")
    # 61 consecutive FAIL runs, never acked (@mindgrapez's ask): from an empty history, and
    # from a full clean one. Driven through append_run, the path write_heartbeat uses.
    stamp = lambda i, clean: json.dumps({"ran_at": f"t{i:03d}", "clean": clean})
    for name, start, want in (
        ("61 FAILs from empty", [], "history_rows=61 cap=60 history_since=t100 evicted=0 pinned_older=0 pinned_rows=61"),
        ("60 clean, then 61 FAILs", [stamp(i, True) for i in range(60)],
         "history_rows=61 cap=60 history_since=t100 evicted=60 pinned_older=0 pinned_rows=61"),
    ):
        h, m, line = start, {"evicted": 0, "last_evicted_ran_at": None}, ""
        for i in range(100, 161):
            h, m, line = append_run(h, stamp(i, False), m, 60)
        bad += line != want
        print(f"  {'ok ' if line == want else 'BAD'} history {name}: {line}")
    _, advanced = check({**ok, "events": ok["events"] + [ev(4, "deprecated"), ev(5)]}, 3)
    if advanced != 3:
        print(f"  BAD state advanced past an unacknowledged deprecation (to {advanced})"); bad += 1
    else:
        print("  ok  state stays at the last acknowledged seq until --ack")
    # An ack without a disposition is refused; the record states the span it covers.
    for name, args, want in [("bare seq", ["54"], "ack needs a disposition"),
                             ("unknown disposition", ["54", "ok"], "ack needs a disposition"),
                             ("no seq", ["accepted"], "ack needs a seq")]:
        try:
            parse_ack(args, 50); got = "accepted"
        except Exception as e:  # a crash is not a refusal with a reason either
            got = str(e)
        bad += not got.startswith(want)
        print(f"  {'ok ' if got.startswith(want) else 'BAD'} ack refused, {name}: {got[:50]}")
    rec = parse_ack(["55", "accepted", "read", "it"], 50)
    good = (rec["from"], rec["through"], rec["span"], rec["note"]) == (51, 55, 5, "read it")
    bad += not good
    print(f"  {'ok ' if good else 'BAD'} ack records its span: {rec['from']}..{rec['through']} span={rec['span']}")
    # Receipts: an insertion at seq 2, re-sealed forward, recomputes clean but moves seq 3's hash.
    receipt = json.dumps({"ran_at": "t1", "tip_seq": 3, "tip_entry_hash": ok["events"][2]["entry_hash"], "clean": True})
    failed_row = json.dumps({"ran_at": "t0", "tip_seq": 3, "tip_entry_hash": "f" * 64, "clean": False})
    resealed = {**ok, "events": sealed([ev(1), {**ev(2), "slug": "inserted"}, ev(3), ev(4)])}
    for name, doc, rows, want, n_want in [
            ("receipt matches", ok, [receipt, failed_row], None, 1),
            ("insertion re-sealed forward", resealed, [receipt], "history rewritten at or before seq 3", 1),
            ("receipt seq gone", {**ok, "events": ok["events"][:2]}, [receipt], "receipt seq 3", 1)]:
        probs, n = check_receipts(doc, rows)
        passed = n == n_want and (probs == [] if want is None else len(probs) == 1 and probs[0].startswith(want))
        assert not recompute_chain(resealed)[0], "the re-sealed fixture must recompute clean"
        bad += not passed
        print(f"  {'ok ' if passed else 'BAD'} receipts, {name}: {probs[0][:60] if probs else 'clear'} (compared {n})")
    print(f"selftest {'PASSED' if not bad else 'FAILED'}")
    return 1 if bad else 0


USAGE = ("usage: register_watch.py [--selftest | --ack SEQ retried|escalated|accepted [note]]"
         "   (no arguments = run the check)")


def main(argv: list[str]) -> int:
    if argv[:1] == ["--selftest"]:
        return selftest()
    if argv[:1] == ["--ack"]:
        try:
            rec = parse_ack(argv[1:], load_state())
        except ValueError as e:
            print(f"refused: {e}\n{USAGE}")
            return 2
        rec["at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        ACKS.parent.mkdir(parents=True, exist_ok=True)
        with ACKS.open("a") as f:
            f.write(json.dumps(rec) + "\n")
        save_state(rec["through"])
        print(f"acknowledged seq {rec['from']}..{rec['through']} ({rec['span']} entries) as {rec['disposition']}")
        return 0
    if argv:
        # Any other argument used to fall through to a full run. On 2026-10-05 a
        # `--help` ran the check by hand and overwrote the scheduled run's heartbeat.
        print(USAGE)
        return 2
    acked = load_state()
    doc = fetch()
    checked_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    problems, new_acked = check(doc, acked)
    prior = RUN_HISTORY.read_text().splitlines() if RUN_HISTORY.exists() else []
    receipt_problems, receipts = check_receipts(doc, prior)
    problems += receipt_problems
    if new_acked != acked:
        save_state(new_acked)
    history = write_heartbeat(checked_at, doc, clean=not problems)
    if problems:
        # The label rides on the FAIL line too: until 2026-10-05 it lived only in the
        # heartbeat, which the next run (even a hand run) overwrites.
        kind = run_kind()
        for p in problems:
            print("FAIL:", p, "|", kind, "|", history, f"code={CODE_DIGEST}")
        return 1
    # recipe_digest is the digest of the SERVED entry_hash recipe, so a recipe change is visible from the
    # journal alone, to someone without this source (@rosetta, ff8b7a06, 2026-10-07). On a clear line it
    # equals the pinned recipe's digest by construction; a changed recipe is a FAIL, never a clear line.
    # A clean run prints a receipt a stranger can check against the public
    # changelog: when it read, which entry was the tip, and the tip's own hash.
    # (It shows what the run saw, not that the timer fired -- that part is the
    # journal's word.)
    tip = max(doc["events"], key=lambda e: e["seq"])
    print(f"register changelog clear: checked_at={checked_at} tip_seq={tip['seq']} "
          f"tip_entry_hash={tip.get('entry_hash')} chain_verify_ok=True chain_entries={len(doc['events'])} chain_recomputed={recompute_chain(doc)[1]} "
          f"recipe_digest={hashlib.sha256(str(doc.get('entry_hash_recipe')).encode()).hexdigest()[:16]} recipe_changed=no "
          f"length={doc['verify'].get('length')} receipts_matched={receipts} "
          f"acknowledged_through={new_acked} {run_kind()} {history} code={CODE_DIGEST}")
    return 0


SERVICE = "register-watch.service"
TIMER = "register-watch.timer"
TIMER_START_GAP_S = 5  # the timer starts the service within the same second (10-02: 0 s)


def _systemd_prop(unit: str, iface: str, prop: str) -> list[str]:
    # Over D-Bus, because `systemctl show --timestamp=unix` still printed local
    # time here (systemd 255); busctl returns timestamps as microseconds.
    import subprocess
    path = "/org/freedesktop/systemd1/unit/" + "".join(
        ch if ch.isalnum() else f"_{ord(ch):02x}" for ch in unit)
    return subprocess.run(["busctl", "--user", "get-property", "org.freedesktop.systemd1", path,
                           f"org.freedesktop.systemd1.{iface}", prop],
                          capture_output=True, text=True, timeout=10).stdout.split()


def _cgroup_unit() -> str | None:
    """The systemd unit this PROCESS runs in, from its own cgroup, not from env."""
    try:
        for line in open("/proc/self/cgroup"):
            last = line.strip().rsplit("/", 1)[-1]
            if last.endswith((".service", ".scope")):
                return last
    except OSError:
        pass
    return None


def classify(cgroup_unit: str | None, start_us: int, fire_us: int) -> str:
    """Pure: the label for one run, from evidence tied to THIS invocation."""
    iso = lambda us: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(us / 1e6))
    if cgroup_unit != SERVICE:
        return f"run_kind=hand cgroup_unit={cgroup_unit or 'none'}"
    if start_us <= 0 or fire_us <= 0:
        return "run_kind=unknown (service start or timer fire time unreadable)"
    gap = (start_us - fire_us) / 1e6
    ev = f"service_start={iso(start_us)} timer_fired_at={iso(fire_us)} gap_s={gap:.3f}"
    if 0 <= gap <= TIMER_START_GAP_S:
        return (f"run_kind=timer_nearby {ev} cause=unproven "
                f"(a manual start within {TIMER_START_GAP_S}s of a fire would read the same)")
    return f"run_kind=service_manual {ev}"


def run_kind() -> str:
    """How this run started, from evidence tied to THIS invocation.

    History, because each step failed differently:
    - INVOCATION_ID can't separate hand from timer: this agent's shell runs
      under systemd and carries one too.
    - TRIGGER_UNIT / TRIGGER_TIMER_REALTIME_USEC are NOT refreshed per run.
      On 2026-10-02 the REAL timer run at 05:50:09Z still carried 05:53:57Z from
      the day before and was labelled hand. They name which timer, not when.
    - 3d189dc read the timer's LastTriggerUSec and called a run "timer" if the
      timer fired within 120 s of NOW. @tantive-space-0924-c (Colony, ebe7246a):
      that is a nearby fire, not a fire bound to this run; a manual start soon
      after a real fire would read "timer". Now:
        * hand vs service from the process's OWN cgroup (my shell runs in a
          claude.slice scope; the service runs in register-watch.service);
        * the service's own ExecMainStartTimestamp (systemd's record of THIS
          invocation) minus the timer's LastTriggerUSec, within 5 s;
        * the label says `timer_nearby cause=unproven`, because nothing systemd
          exposes binds a firing to an invocation (its docs call trigger
          metadata best-effort, and triggers can coalesce).
    """
    try:
        start_us = int(_systemd_prop(SERVICE, "Service", "ExecMainStartTimestamp")[1])
        fire_us = int(_systemd_prop(TIMER, "Timer", "LastTriggerUSec")[1])
    except Exception:  # no systemd, no bus, unparseable: say so rather than guess
        start_us = fire_us = 0
    unit = _cgroup_unit()
    if unit == SERVICE and not (start_us and fire_us):
        return "run_kind=unknown (in the service, but its start or the timer's fire time is unreadable)"
    return classify(unit, start_us, fire_us)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
