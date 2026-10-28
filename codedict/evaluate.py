"""Measure quality against a gold file and sample edges for manual audit. No AI involved."""
import random
import tomllib
from pathlib import Path

from .query import find_symbols, search
from .text import estimate_tokens


def _match(qualified: str, expect: str) -> bool:
    return qualified == expect or qualified.endswith("." + expect)


def run_eval(con, root: Path, gold_path: Path) -> str:
    gold = tomllib.loads(gold_path.read_text(encoding="utf-8"))
    out, fails = [], []

    cases = gold.get("search", [])
    if cases:
        hits = {1: 0, 5: 0, 10: 0}
        rr = 0.0
        saved = []
        for c in cases:
            rows = search(con, c["query"], 10)
            pos = next((i for i, r in enumerate(rows, 1) if _match(r["qualified"], c["expect"])), None)
            for k in hits:
                hits[k] += bool(pos and pos <= k)
            rr += 1 / pos if pos else 0
            if not pos:
                fails.append(f"search '{c['query']}' expected {c['expect']}; got " + ", ".join(r["qualified"] for r in rows[:3]))
            elif pos:
                r = rows[pos - 1]
                try:
                    whole = estimate_tokens((root / r["path"]).read_text(encoding="utf-8", errors="replace"))
                    part = estimate_tokens(" ".join(x["signature"] or "" for x in rows[:5])) + \
                        (r["end_line"] - r["start_line"] + 1) * 12
                    saved.append(1 - part / max(whole, 1))
                except OSError:
                    pass
        n = len(cases)
        out.append(f"SEARCH ({n} cases): recall@1 {hits[1]/n:.0%} | @5 {hits[5]/n:.0%} | @10 {hits[10]/n:.0%} | MRR {rr/n:.2f}")
        if saved:
            out.append(f"  est. token saving vs reading whole file: {sum(saved)/len(saved):.0%}")

    calls = gold.get("calls", [])
    if calls:
        ok = wrong = missing = 0
        for c in calls:
            src = [s for s in find_symbols(con, c["src"], 50) if _match(s["qualified"], c["src"])]
            found, other = False, False
            for s in src:
                for e in con.execute("SELECT d.qualified, c.confidence FROM calls c JOIN symbols d ON d.id = c.dst_id "
                                     "WHERE c.src_id = ?", (s["id"],)):
                    if _match(e["qualified"], c["dst"]):
                        found = True
                    elif e["qualified"].split(".")[-1] == c["dst"].split(".")[-1]:
                        other = True  # same name resolved to a different symbol
            if found:
                ok += 1
            elif other:
                wrong += 1
                fails.append(f"call {c['src']} -> {c['dst']} resolved to a DIFFERENT symbol")
            else:
                missing += 1
                fails.append(f"call {c['src']} -> {c['dst']} not found")
        n = len(calls)
        out.append(f"CALLS ({n} edges): found {ok/n:.0%} | wrong target {wrong/n:.0%} | missing {missing/n:.0%}")

    routes = gold.get("routes", [])
    if routes:
        ok = 0
        for r in routes:
            row = con.execute("SELECT 1 FROM routes WHERE method = ? AND path = ?", (r["method"].upper(), r["path"])).fetchone()
            ok += bool(row)
            if not row:
                fails.append(f"route {r['method']} {r['path']} not found")
        out.append(f"ROUTES ({len(routes)}): found {ok/len(routes):.0%}")

    syms = gold.get("symbols", [])
    if syms:
        ok = 0
        for s in syms:
            row = [r for r in find_symbols(con, s["name"], 50) if _match(r["qualified"], s["name"])
                   and (not s.get("file") or r["path"].endswith(s["file"]))]
            ok += bool(row)
            if not row:
                fails.append(f"symbol {s['name']} not found")
        out.append(f"SYMBOLS ({len(syms)}): found {ok/len(syms):.0%}")

    if fails:
        out += ["", "FAILURES:"] + [f"  - {f}" for f in fails[:40]]
    return "\n".join(out) or "Gold file has no [[search]], [[calls]], [[routes]] or [[symbols]] entries."


def audit(con, root: Path, kind: str, n: int, confidence: str | None, seed: int) -> str:
    rnd = random.Random(seed)
    if kind == "calls":
        rows = list(con.execute(
            "SELECT c.line, c.confidence, c.name, f.path, s.qualified AS src, d.qualified AS dst, "
            "d.start_line AS dline, df.path AS dpath FROM calls c JOIN files f ON f.id = c.file_id "
            "LEFT JOIN symbols s ON s.id = c.src_id JOIN symbols d ON d.id = c.dst_id JOIN files df ON df.id = d.file_id "
            + ("WHERE c.confidence = ?" if confidence else ""), (confidence,) if confidence else ()))
        rnd.shuffle(rows)
        out = [f"Audit {min(n, len(rows))} of {len(rows)} resolved calls"
               + (f" [{confidence}]" if confidence else "") + ". Mark each OK / WRONG:\n"]
        for i, r in enumerate(rows[:n], 1):
            out.append(f"{i:>2}. [{r['confidence']}] {r['path']}:{r['line']}\n"
                       f"    code:   {_line(root, r['path'], r['line'])}\n"
                       f"    linked: {r['dst']}  ({r['dpath']}:{r['dline']})")
        return "\n".join(out)
    rows = list(con.execute(
        "SELECT c.line, c.name, c.receiver, f.path FROM calls c JOIN files f ON f.id = c.file_id "
        "WHERE c.confidence = 'external' AND EXISTS (SELECT 1 FROM symbols s WHERE s.name = c.name "
        "AND s.kind IN ('function','method','class','procedure','constructor'))"))
    rnd.shuffle(rows)
    out = [f"{len(rows)} calls marked external although a symbol with the same name exists. "
           f"Sample {min(n, len(rows))}; count how many SHOULD have been linked (= missed links):\n"]
    for i, r in enumerate(rows[:n], 1):
        cands = [x["qualified"] for x in con.execute("SELECT qualified FROM symbols WHERE name = ? LIMIT 3", (r["name"],))]
        out.append(f"{i:>2}. {r['path']}:{r['line']}\n    code:       {_line(root, r['path'], r['line'])}\n"
                   f"    candidates: {', '.join(cands)}")
    return "\n".join(out)


def _line(root: Path, path: str, line: int) -> str:
    try:
        return (root / path).read_text(encoding="utf-8", errors="replace").splitlines()[line - 1].strip()[:140]
    except (OSError, IndexError):
        return "?"
