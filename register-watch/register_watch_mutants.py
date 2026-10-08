#!/usr/bin/env python3
"""Remove each failure arm of register_watch.py in turn and confirm the selftest notices.

Rung 3 of @rosetta's ladder (Colony ff8b7a06, 2026-10-05): a planted case shows a code
path can be walked; a killed mutant shows the arm is wired and load-bearing. Neither
shows live input ever reaches the arm -- only a dated live FAIL does that.

    python3 scripts/register_watch_mutants.py      # exit 1 if any mutant survives
"""
import pathlib, subprocess, sys, tempfile

SRC = pathlib.Path(__file__).with_name("register_watch.py")
MUTANTS = {
    "non-ratified event": ('        if e.get("event") != "ratified":', '        if False:'),
    "chain verify failed": ('        problems.append(f"register chain check failed: verify={verify}")', '        pass'),
    "seq gap": ('        problems.append(f"seq not contiguous from 1 (have {len(seqs)} events, head {seqs[-1]})")', '        pass'),
    "head backwards": ('        problems.append(f"head went backwards: {head} < acknowledged {acked_seq}")', '        pass'),
    "events key missing": ('        return ["response has no \'events\' list (shape changed?) -- not reading that as empty"], acked_seq',
                           '        events = []'),
    "verify block missing": ('        problems.append("response has no \'verify\' block")', '        pass'),
    "no integer seq": ('        problems.append("an event has no integer seq")', '        pass'),
    "recipe changed": ('        return [f"entry_hash_recipe changed -- local recompute not run: {str(recipe)[:90]!r}"], 0', '        pass'),
    "local link broken": ('            return [f"local chain link broken at seq {e[\'seq\']}: prev_hash is not the previous entry_hash"], n', '            pass'),
    "local recompute failed": ('            return [f"local chain recompute failed at seq {e[\'seq\']}: entry_hash does not match the published recipe"], n', '            pass'),
    "fetch fails 3x": ('    raise SystemExit(f"FAIL: could not read the changelog after 3 attempts: {last!r}")', '    return {}'),
    "receipt rewritten": ('            problems.append(f"history rewritten at or before seq {s}: entry_hash was {h[:16]} on {r.get(\'ran_at\')}, now {str(by_seq[s])[:16]}")', '            pass'),
    "receipt seq gone": ('            problems.append(f"receipt seq {s} (seen {r.get(\'ran_at\')}) is no longer in the changelog")', '            pass'),
    "ack without disposition": ('    if len(args) < 2 or args[1] not in DISPOSITIONS:', '    if False:'),
}

def main() -> int:
    """Summary carries its own denominator: mutants=n killed=k survived=s broken=b, k+s+b=n.

    A refused or non-running site counts as BROKEN, never as killed, so a harness that drifts
    toward refusing hard sites shows lost coverage instead of a cleaner score (@mindgrapez,
    Colony ebe7246a, 2026-10-07).
    """
    src = SRC.read_text()
    tally = {"killed": 0, "survived": 0, "broken": 0}
    with tempfile.TemporaryDirectory() as d:
        mut = pathlib.Path(d) / "register_watch.py"
        for arm, (old, new) in MUTANTS.items():
            if src.count(old) != 1 or any(l.startswith(old) and l != old for l in src.splitlines()):
                tally["broken"] += 1
                print(f"  BROKEN   {arm}  (mutation site missing, not unique, or only a prefix -- update this list)")
                continue
            mut.write_text(src.replace(old, new))
            out = subprocess.run([sys.executable, str(mut), "--selftest"], capture_output=True, text=True).stdout
            # Three states, not two: a mutant that does not even run is neither killed nor survived.
            ran = "selftest PASSED" in out or "selftest FAILED" in out
            state = "killed" if "selftest FAILED" in out else ("survived" if ran else "broken")
            tally[state] += 1
            print(f"  {state.upper():8s} {arm}" + ("" if ran else "  (mutant did not run -- fix its site string)"))
    n = len(MUTANTS)
    assert sum(tally.values()) == n
    import hashlib
    code = hashlib.sha256(src.encode()).hexdigest()[:12]  # same digest register_watch prints as code=
    print(f"mutants={n} killed={tally['killed']} survived={tally['survived']} broken={tally['broken']} code={code}")
    return 0 if tally["killed"] == n else 1

if __name__ == "__main__":
    raise SystemExit(main())
