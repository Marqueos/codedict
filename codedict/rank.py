"""PageRank over the call graph: what the rest of the code depends on ranks higher."""
from collections import defaultdict

WEIGHT = {"high": 1.0, "medium": 0.7, "low": 0.4}
PARENT_WEIGHT = 0.2


def compute_rank(con, iterations: int = 30, damping: float = 0.85) -> None:
    ids = [r[0] for r in con.execute("SELECT id FROM symbols")]
    if not ids:
        return
    n = len(ids)
    out = defaultdict(lambda: defaultdict(float))
    for r in con.execute("SELECT src_id, dst_id, confidence FROM calls WHERE dst_id IS NOT NULL AND src_id IS NOT NULL"):
        if r[0] != r[1]:
            out[r[0]][r[1]] += WEIGHT.get(r[2], 0.3)
    for sid, parent in con.execute("SELECT id, parent_id FROM symbols WHERE parent_id IS NOT NULL"):
        out[sid][parent] += PARENT_WEIGHT
    totals = {s: sum(d.values()) for s, d in out.items()}
    rank = dict.fromkeys(ids, 1.0 / n)
    for _ in range(iterations):
        nxt = dict.fromkeys(ids, (1 - damping) / n)
        dangling = sum(rank[s] for s in ids if s not in totals)
        share = damping * dangling / n
        for s in ids:
            nxt[s] += share
        for s, targets in out.items():
            r = damping * rank.get(s, 0) / totals[s]
            for t, w in targets.items():
                if t in nxt:
                    nxt[t] += r * w
        rank = nxt
    import math
    refs = dict(con.execute("SELECT id, refs FROM symbols"))
    scale = n  # 1.0 = average symbol; lexical usage across files boosts types used via DI/type references
    con.executemany("UPDATE symbols SET rank = ? WHERE id = ?",
                    [(rank[s] * scale * (1 + math.log1p(refs.get(s) or 0)), s) for s in ids])
