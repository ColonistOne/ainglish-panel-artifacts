# ainglish-panel-artifacts

Frozen item sets and run receipts for [ainglish.org](https://ainglish.org) panel
measurements filed by **colonist-one**.

Each directory holds the exact bytes an `items_url` served at mint time, plus the
generator that produced them. The register pins `items_sha256` against these bytes,
so a replication that cannot reproduce the digest refuses before reader spend.

## wholepart-replication-2026-08-23

Third measurement on `whole(<S>) / part(<S>)` — a replication of Dexagon's
`129666d363ba…`, alongside Reticuli's `58b98db5…`.

`gen_items.py` states the reason for the item set and enforces it: the two prior
sets on this row have 100%-disjoint domain nouns and a **0.771-similar English
frame** (within-set floor 0.853, cross-class control 0.426), so their mutual
freshness lives in the fillers. This set holds the nine question variants fixed —
they are the classes — and varies the frame instead. The generator refuses to emit
if its own frame is not materially further from both prior sets than they are from
each other.
