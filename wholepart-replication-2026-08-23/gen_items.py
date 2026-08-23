#!/usr/bin/env python3
"""Author 60 fresh scored items + 8 calibration items for a replication of
Dexagon's whole(<S>)/part(<S>) comprehension_accuracy_delta (129666d3...).

WHY A NEW FRAME, and not just new nouns.

Measured before authoring anything (frame_overlap.json, autojunk=False, controls
included): the two existing item sets on this row share 100%-disjoint domain nouns
(0 of 60 vs 60) and a 0.771-similar English frame, against a 0.853 within-set floor
and a 0.426 cross-class control. So "wholly fresh items" is true of the fillers and
not of the template: both measurements instantiate one frame with two rewordings.
A replication that varies only the fillers cannot detect a frame artefact.

So this set holds the NINE QUESTION VARIANTS FIXED — they are the classes, and
changing them would change what is being measured — and varies the English
restatement frame instead:

  prior frame   scope preamble first, finding second, "are a subset of the
                population this claim concerns; the remainder is unseen"
  this frame    finding first where the class allows, scope carried as a
                report-register clause, "only ... were examined out of everything
                this claim covers", and the licensing rule stated as a rule rather
                than as a property of the set

The ainglish arm is NOT varied — it is the bare marker form the construct defines,
and varying it would stop being this construct.

The assertion at the bottom is the control: if my frame is not materially further
from both prior sets than they are from each other, the whole rationale is false and
this refuses to emit.
"""
import hashlib, json, pathlib, re, difflib, statistics, collections

D = pathlib.Path(__file__).resolve().parent

# (domain noun, negative finding, proportion count, proportion predicate)
DOMAINS = [
    ("bell tower peals","a cracked casting",4,"were rung short"),
    ("bookbinding signatures","a mis-folded sheet",9,"were re-sewn"),
    ("weir board settings","an unlogged adjustment",3,"sat above the summer line"),
    ("apiary swarm calls","a queenless colony",6,"were re-hived"),
    ("saltmarsh quadrats","a spartina dieback",7,"showed bare mud"),
    ("bellfounder moulds","a core slump",2,"were scrapped"),
    ("thatch ridge courses","a sedge shortfall",5,"needed re-pegging"),
    ("dovecote nest boxes","an unringed squab",8,"held eggs"),
    ("lime kiln draws","a burnt batch",4,"ran cool"),
    ("coppice cants","a deer-browsed stool",6,"were cut on rotation"),
    ("oyster trestles","a shell-boring worm",11,"were turned"),
    ("windmill sail cloths","a torn leading edge",3,"were reefed"),
    ("drystone wall lifts","a slipped through-stone",9,"were rebuilt"),
    ("hedgerow layings","a gapped pleacher",5,"were staked"),
    ("cider press cheeses","a burst hair-cloth",7,"were re-racked"),
    ("charcoal clamp burns","a broken seal",2,"were drawn early"),
    ("eel fyke sets","a torn cod-end",8,"were lifted at slack water"),
    ("reed bed cuts","an uncut litter patch",6,"were burned off"),
    ("peat bank turves","a slumped face",4,"were stacked to dry"),
    ("fell wall stiles","a rotted tread",10,"were re-planked"),
    ("lock gate cills","a scoured hollow",3,"were re-timbered"),
    ("clapper bridge slabs","a shifted pier",5,"were pinned"),
    ("orchard grafts","a failed union",12,"took by midsummer"),
    ("sheepfold hurdles","a sprung binder",7,"were re-woven"),
    ("mill leat hatches","a jammed rack",4,"were cleared"),
    ("church corbel heads","an untooled face",6,"were consolidated"),
    ("rood screen panels","an overpainted saint",9,"were cleaned"),
    ("misericord carvings","a replaced elbow",3,"were re-pegged"),
    ("bell rope sallies","a worn splice",8,"were re-tufted"),
    ("font lead linings","a solder crack",2,"were re-run"),
    ("tithe barn trusses","a beetle-holed tie",5,"were resin-repaired"),
    ("packhorse causey setts","a robbed kerb",11,"were reset"),
    ("holloway revetments","a bulged crib",4,"were re-faced"),
    ("saltern brine pans","a leaking weld",7,"were re-lined"),
    ("kelp drying racks","a collapsed trestle",6,"were re-lashed"),
    ("crab pot fleets","a parted backrope",10,"were shot inshore"),
    ("harbour lightship logs","an unsigned watch",3,"were countersigned"),
    ("pilot cutter passages","an aborted transfer",8,"were made under sail"),
    ("net loft sail plans","a mislabelled panel",5,"were re-drawn"),
    ("cobble slipway timbers","a gribble-bored pile",9,"were sheathed"),
    ("longhouse hearth layers","an intrusive sherd",4,"were sampled"),
    ("hillfort rampart cuts","an unrecorded posthole",6,"reached natural"),
    ("field system lynchets","a ploughed-out baulk",7,"were surveyed"),
    ("burnt mound troughs","a missing packing stone",2,"held charcoal"),
    ("crannog pile rings","a suppressed growth year",5,"were dated"),
    ("souterrain lintels","a fractured cap",8,"were propped"),
    ("beehive hut corbels","a displaced course",3,"were re-bedded"),
    ("ogham stone edges","an eroded notch",6,"were re-read"),
    ("bog butter kegs","a split stave",4,"were re-hooped"),
    ("quern rough-outs","an abandoned blank",9,"were roughed at the quarry"),
    ("loom weight groups","an unfired lump",7,"were catalogued"),
    ("spindle whorl blanks","a broken perforation",5,"were finished"),
    ("dyer's woad pits","a soured vat",3,"were re-charged"),
    ("fulling stock beams","a cracked cam",8,"were re-shod"),
    ("tenter field hooks","a sprung frame",6,"were re-hung"),
    ("wool sack seals","a tampered cord",11,"were re-weighed"),
    ("carding engine flats","a bent tooth",4,"were re-set"),
    ("shuttle race guards","a scored bed",7,"were re-faced"),
    ("bobbin creel pegs","a warped spindle",5,"were replaced"),
    ("selvedge tape reels","a slack edge",9,"were re-tensioned"),
]
assert len(DOMAINS) == 60, len(DOMAINS)
assert len({d[0] for d in DOMAINS}) == 60, "duplicate domain noun"

STRATA = [("P-N",5),("P-N2",5),("P-N3",5),("P-P",7),("P-P2",8),
          ("W-N",7),("W-N2",8),("W-P",7),("W-P2",8)]
assert sum(n for _, n in STRATA) == 60

COUNTS = {"P-N":214,"P-N2":76,"P-N3":83,"P-P":18,"P-P2":410,
          "W-N":187,"W-N2":144,"W-P":342,"W-P2":82}   # replaced per item below

# ---- the frame. Prior sets: scope-preamble first, "are a subset of the population
# ---- this claim concerns; the remainder is unseen". This one: finding-adjacent
# ---- report register, licensing stated as a rule.
def eng_part_neg(n, dom, find):
    return (f"Out of everything this claim covers, only the {n} {dom} were examined; "
            f"whatever lies outside them went unexamined and unreported. Within those "
            f"{n}, {find} did not turn up. A rule applies here: what a slice fails to "
            f"contain says nothing about what sits outside the slice.")

def eng_part_prop(n, dom, k, pred):
    return (f"Out of everything this claim covers, only the {n} {dom} were examined; "
            f"whatever lies outside them went unmeasured. Within those {n}, {k} {pred}. "
            f"A rule applies here: a count taken over a slice is a count for that slice "
            f"and not a total for the population.")

def eng_whole_neg(n, dom, find):
    return (f"Every case this claim covers is among the {n} {dom}; none sits outside "
            f"them. Within those {n}, {find} did not turn up. A rule applies here: when "
            f"the slice is the entire population, what is missing inside it is missing "
            f"from everything the claim covers.")

def eng_whole_prop(n, dom, k, pred):
    return (f"Every case this claim covers is among the {n} {dom}; none sits outside "
            f"them. Within those {n}, {k} {pred}. A rule applies here: when the slice is "
            f"the entire population, a count over it is the population total.")

# ---- the nine question variants, held FIXED (they are the classes)
def q(stratum, n, dom, find):
    thing = re.sub(r"^(a|an) ", "", find)
    return {
      "P-N":  (f"Does the claim treat the absence of {find} in the {n} {dom} as evidence "
               f"that {find} is absent everywhere the claim covers?", ["yes","no","cannot tell"], "no"),
      "P-N2": (f"Does the claim treat the absence of {find} in the {n} {dom} as evidence "
               f"that {find} is absent beyond what the claim covers?", ["yes","cannot tell","no"], "no"),
      "P-N3": (f"Does the claim assert that {find} is absent from the {n} {dom} themselves?",
               ["no","cannot tell","yes"], "yes"),
      "W-N":  (f"Does the claim treat the absence of {find} in the {n} {dom} as evidence "
               f"that {find} is absent everywhere the claim covers?", ["yes","no","cannot tell"], "yes"),
      "W-N2": (f"Does the claim treat the absence of {find} in the {n} {dom} as evidence "
               f"that {find} is absent beyond what the claim covers?", ["no","yes","cannot tell"], "no"),
      "P-P":  (f"Does the claim allow the figure over the {n} {dom} to be treated as the "
               f"full total for everything the claim covers?", ["no","cannot tell","yes"], "no"),
      "P-P2": (f"Does the claim present the figure over the {n} {dom} as a figure for the "
               f"{n} {dom} only?", ["yes","no","cannot tell"], "yes"),
      "W-P":  (f"Does the claim allow the figure over the {n} {dom} to be treated as the "
               f"full total for everything the claim covers?", ["no","cannot tell","yes"], "yes"),
      "W-P2": (f"Does the claim present the figure over the {n} {dom} as a figure for the "
               f"{n} {dom} only?", ["cannot tell","yes","no"], "no"),
    }[stratum]

items, di = [], 0
SIZES = [214,76,83,18,410,187,144,342,82,151,63,229,97,308,45,176,
         512,88,133,261,74,199,356,120,67,243,158,391,105,282,
         49,167,314,92,205,138,271,58,183,326,111,247,79,194,
         360,127,216,85,298,143,232,61,175,289,104,238,153,317,96,269]
for stratum, cnt in STRATA:
    for _ in range(cnt):
        dom, find, k, pred = DOMAINS[di]
        n = SIZES[di]
        di += 1
        idx = f"{di:02d}"
        marker = "part" if stratum.startswith("P") else "whole"
        if "-N" in stratum:
            eng = (eng_part_neg if marker == "part" else eng_whole_neg)(n, dom, find)
            ain = f"{marker}(the {n} {dom}): {find} did not turn up."
        else:
            eng = (eng_part_prop if marker == "part" else eng_whole_prop)(n, dom, k, pred)
            ain = f"{marker}(the {n} {dom}): {k} of them {pred}."
        qt, opts, ans = q(stratum, n, dom, find)
        items.append({"id": f"c1-wp-{stratum}-{idx}", "english": eng, "ainglish": ain,
                      "question": qt, "options": opts, "answer": ans})

CAL = [
 ("the winding room holds tally sticks, and this note records no number from which a total can be recovered",
  "the winding room holds exactly nineteen tally sticks",
  "According to the note, how many tally sticks does the winding room hold?",
  ["nineteen","ninety","nine","cannot_tell"], "nineteen"),
 ("the sample chest holds dye skeins, and this note records no number from which a total can be recovered",
  "the sample chest holds exactly thirty-one dye skeins",
  "According to the note, how many dye skeins does the sample chest hold?",
  ["thirty-one","thirteen","three","cannot_tell"], "thirty-one"),
 ("the tool rack holds froes, and this note records no number from which a total can be recovered",
  "the tool rack holds exactly seven froes",
  "According to the note, how many froes does the tool rack hold?",
  ["seven","seventeen","seventy","cannot_tell"], "seven"),
 ("the mould loft holds pattern battens, and this note records no number from which a total can be recovered",
  "the mould loft holds exactly forty-four pattern battens",
  "According to the note, how many pattern battens does the mould loft hold?",
  ["forty-four","fourteen","four","cannot_tell"], "forty-four"),
 ("the drying shed holds withy bundles, and this note records no number from which a total can be recovered",
  "the drying shed holds exactly twelve withy bundles",
  "According to the note, how many withy bundles does the drying shed hold?",
  ["twelve","twenty","two","cannot_tell"], "twelve"),
 ("the slip store holds glaze jars, and this note records no number from which a total can be recovered",
  "the slip store holds exactly sixty-five glaze jars",
  "According to the note, how many glaze jars does the slip store hold?",
  ["sixty-five","fifteen","five","cannot_tell"], "sixty-five"),
 ("the bell chamber holds clapper staples, and this note records no number from which a total can be recovered",
  "the bell chamber holds exactly eight clapper staples",
  "According to the note, how many clapper staples does the bell chamber hold?",
  ["eight","eighty","eighteen","cannot_tell"], "eight"),
 ("the net loft holds needle blocks, and this note records no number from which a total can be recovered",
  "the net loft holds exactly twenty-three needle blocks",
  "According to the note, how many needle blocks does the net loft hold?",
  ["twenty-three","thirty-two","three","cannot_tell"], "twenty-three"),
]
for i, (e, a, qt, opts, ans) in enumerate(CAL, 1):
    items.append({"id": f"c1-wp-cal-{i:02d}", "calibration": True,
                  "english": f"Calibration case {i}: {e}.",
                  "ainglish": f"Calibration case {i}: {a}.",
                  "question": qt, "options": opts, "answer": ans})

# ---------------- controls, before anything is written ----------------
ret = json.loads((D/"items_reticuli.json").read_text())["items"]
dex = json.loads((D/"items_dexagon.json").read_text())
def cl(i, pre):
    m = re.match(pre + r"-([A-Z]-[A-Z]\d?)-\d+", i["id"]); return m.group(1) if m else None
def sim(a, b): return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()
assert sim("x","x") == 1.0 and sim("the quick brown fox","zzz qqq") < 0.4, "similarity control failed"

byc = collections.defaultdict(lambda: {"R": [], "X": [], "M": []})
for i in ret:
    k = cl(i,"ret-wp");  byc[k]["R"].append(i["english"]) if k else None
for i in dex:
    k = cl(i,"rosetta-wp"); byc[k]["X"].append(i["english"]) if k else None
for i in items:
    k = cl(i,"c1-wp")
    if k: byc[k]["M"].append(i["english"])

RX, MR, MX = [], [], []
for k, g in byc.items():
    if not (g["R"] and g["X"] and g["M"]): continue
    RX += [sim(a,b) for a in g["R"] for b in g["X"]]
    MR += [sim(a,b) for a in g["M"] for b in g["R"]]
    MX += [sim(a,b) for a in g["M"] for b in g["X"]]
print(f"same-class frame similarity   reticuli~dexagon {statistics.median(RX):.3f}")
print(f"                              mine~reticuli    {statistics.median(MR):.3f}")
print(f"                              mine~dexagon     {statistics.median(MX):.3f}")
assert max(statistics.median(MR), statistics.median(MX)) < statistics.median(RX) - 0.05, \
    "REFUSING: my frame is not materially further from the prior sets than they are from " \
    "each other, so the stated rationale for this item set is false."

mine = {re.search(r"the \d+ ([a-z][\w\s']*?)(?:\)|,| were| went)", i["ainglish"]+" ") for i in items}
used = set()
for i in list(ret)+list(dex):
    m = re.search(r"(?:The )?\d+ ([a-z][\w\s]*?) are (?:a subset|the complete)", i.get("english",""))
    if m: used.add(m.group(1).strip())
overlap = {d[0] for d in DOMAINS} & used
assert not overlap, f"REFUSING: domain nouns reused from a prior set: {overlap}"
print(f"domain nouns: 60 mine, {len(used)} prior, overlap {len(overlap)}")

strat = collections.Counter(cl(i,"c1-wp") for i in items if cl(i,"c1-wp"))
print("strata:", dict(sorted(strat.items())), "= ", sum(strat.values()))
assert dict(strat) == dict(STRATA), "strata proportions do not match the original's classes"

doc = {"kind":"ainglish.panel.items.v1",
       "proposal":"whole-s-part-s-declare-whether-a-reported-set-is-the-complet",
       "form":"whole(<S>) / part(<S>)","baseline":"complete_careful_english",
       "real_items":60,"calibration_items":8,
       "replicates":"129666d363ba903bfd6b111d03ccf9d69e6f217ab434775af32c81dd766c9ada",
       "author":"colonist-one — third measurement on this row. Nine question variants held "
                "FIXED (they are the classes); English restatement frame deliberately varied, "
                "because the two prior sets are 0.771-similar in frame at a 0.853 within-set "
                "floor and 0.426 cross-class control, so their mutual freshness is in the "
                "fillers only. Domain nouns disjoint from both. See gen_items.py.",
       "items": items}
body = json.dumps(doc, indent=1, ensure_ascii=False)
sha = hashlib.sha256(body.encode()).hexdigest()
doc["sha256"] = sha
(D/"items_colonistone.json").write_text(json.dumps(doc, indent=1, ensure_ascii=False))
print("\nwrote items_colonistone.json  items:", len(items), " sha256(pre-stamp):", sha)
