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

### Outcome, 2026-08-23 — both attempts aborted, nothing filed

| attempt | value | interval | dead_rate | faults | truncations | state |
|---|---:|---|---:|---:|---|---|
| `83629a98` | +12.73 | [−6.28, 31.53] | 0.1184 | 4 (all english) | 5 (all ainglish) | aborted |
| `e3acc899` | −4.17 | [−25.41, 16.26] | 0.0789 | 0 | 6 (5 ainglish, 1 english) | aborted |

Second run changed transport only (`max_tokens` 2048→4096, `timeout_s` 240→600) and
cleared every gate the runspec declared. It aborted on the gate the harness freezes
for you — zero faults **and zero truncations** — which is the one the author did not
write down.

Two runs of an identical design span **16.9 pp with opposite signs at the point
estimate**, and each value sits inside the other's 95% interval. The row's
`replication_comparison` tolerance is `effective: 1.944`, about nine times tighter
than that. Truncation was imbalanced toward the ainglish arm in both runs, while the
construct's `token_delta` is −11 — cheaper to write, dearer to read, and only the
first direction has a metric.

Stopped at two runs: a third after seeing two values is a third draw.
