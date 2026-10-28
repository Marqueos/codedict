"""LLM-facing dictionary: L0 overview (token-budgeted) + L1 module maps. L2 = `codedict show`."""
import json
from collections import Counter, defaultdict
from pathlib import Path

from .query import ABBR, ENTRY_FILES, MAP_HIDDEN, describe, group_modules, is_test_path, loc, sym_line, vocabulary, _SYM_SQL
from .text import estimate_tokens, one_line, slug

USAGE = ("Navigate: read this overview → `codedict map <module>` (L1) → `codedict search \"<words>\"` → "
         "`codedict show <name>` (exact lines) · `codedict callers|callees <name>` · `codedict routes` · `codedict tables`. "
         "Legend: ↑N = called by N places, ⇢Nf = name used in N other files, → = calls, [VERB /path] = route, {sql} = tables touched.")


def _module_rows(con, files):
    if not files:
        return []
    q = ",".join("?" * len(files))
    return list(con.execute(_SYM_SQL + f" WHERE f.path IN ({q})", files))


def _summaries(con, modules):
    out = []
    for label, files in modules.items():
        rows = _module_rows(con, files)
        out.append({"label": label, "files": files, "rows": rows,
                    "test": all(is_test_path(f) for f in files) if files else False})
    return out


def _module_line(label, nfiles, rows, sub=0) -> str:
    top = sorted((r for r in rows if not r["private"] and r["kind"] not in {"namespace"} | MAP_HIDDEN
                  and not is_test_path(r["path"])), key=lambda r: -r["rank"])[:4]
    line = f"- `{label}` {nfiles} files, {len(rows)} symbols" + (f", {sub} modules" if sub > 1 else "")
    vocab = vocabulary(rows)
    if vocab:
        line += " — vocab: " + ", ".join(vocab)
    if top:
        line += " — key: " + ", ".join(f"`{r['name']}`" for r in top)
    return line


def _aggregate(summaries, depth):
    agg = {}
    for m in summaries:
        parts = m["label"].rstrip("*").rstrip("/").split("/")
        key = "/".join(parts[:depth]) + "/" if parts[0] not in ("", ".") else m["label"]
        a = agg.setdefault(key, {"files": 0, "rows": [], "sub": 0})
        a["files"] += len(m["files"])
        a["rows"] += m["rows"]
        a["sub"] += 1
    return [_module_line(k, v["files"], v["rows"], v["sub"]) for k, v in agg.items()]


def module_lines(summaries, budget_tokens):
    """Pick the deepest module granularity that fits the budget (hierarchy for big repos)."""
    main = [m for m in summaries if not m["test"]]
    tests = [m for m in summaries if m["test"]]
    full = [_module_line(m["label"], len(m["files"]), m["rows"]) for m in main]
    if estimate_tokens("\n".join(full)) <= budget_tokens:
        lines = full
    else:
        lines = None
        for depth in (4, 3, 2, 1):
            cand = _aggregate(main, depth)
            if estimate_tokens("\n".join(cand)) <= budget_tokens:
                lines = cand
                break
        lines = lines or _aggregate(main, 1)
        lines.append("- (collapsed: full list in `.codedict/ai/MODULES.md` or `codedict modules`)")
    if tests:
        nf = sum(len(m["files"]) for m in tests)
        ns = sum(len(m["rows"]) for m in tests)
        lines.append(f"- tests: {len(tests)} modules, {nf} files, {ns} symbols (excluded from key symbols)")
    return lines


def overview(con, budget_tokens: int = 3000, modules=None, summaries=None) -> str:
    modules = modules or group_modules(con)
    summaries = summaries or _summaries(con, modules)
    meta = dict(con.execute("SELECT key, value FROM meta").fetchall())
    nfiles = con.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    nsyms = con.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
    langs = Counter(dict(con.execute("SELECT lang, COUNT(*) FROM files GROUP BY lang").fetchall()))
    out = [f"# Code dictionary: {meta.get('root', '?')}",
           f"Indexed {meta.get('indexed_at', '?')} · {nfiles} files · {nsyms} symbols · "
           + ", ".join(f"{l} {n}" for l, n in langs.most_common(8)),
           USAGE, "", "## Modules"]
    out += module_lines(summaries, int(budget_tokens * 0.45))
    entries = [r["path"] for r in con.execute("SELECT path FROM files")
               if r["path"].rsplit("/", 1)[-1].lower() in ENTRY_FILES and not is_test_path(r["path"])]
    if entries:
        out += ["", "## Entry points", "- " + ", ".join(f"`{p}`" for p in sorted(entries, key=len)[:12])]
    nroutes = con.execute("SELECT COUNT(*) FROM routes").fetchone()[0]
    ntables = con.execute("SELECT COUNT(DISTINCT table_name) FROM sql_refs").fetchone()[0]
    if nroutes or ntables:
        out += ["", f"## Interfaces\n- {nroutes} routes (`codedict routes`) · {ntables} SQL tables referenced (`codedict tables`)"]
        top_tables = [f"{r[0]}({r[1]})" for r in con.execute(
            "SELECT table_name, COUNT(*) n FROM sql_refs GROUP BY table_name ORDER BY n DESC LIMIT 15")]
        if top_tables:
            out.append("- most used tables: " + ", ".join(top_tables))
    out += ["", "## Key symbols (most depended on, tests excluded)"]
    used = estimate_tokens("\n".join(out))
    for r in con.execute(_SYM_SQL + " WHERE s.private = 0 AND s.kind != 'namespace' ORDER BY s.rank DESC LIMIT 2000"):
        if is_test_path(r["path"]):
            continue
        line = "- " + sym_line(r)
        cost = estimate_tokens(line)
        if used + cost > budget_tokens:
            break
        out.append(line)
        used += cost
    return "\n".join(out) + "\n"


def module_map(con, label: str, full: bool = False, modules=None) -> str:
    modules = modules or group_modules(con)
    if label not in modules:
        matches = [m for m in modules if m.rstrip("/*").endswith(label.rstrip("/*")) or label.strip("/") in m]
        if len(matches) == 1:
            label = matches[0]
        else:
            return "Unknown module. Modules:\n" + "\n".join(f"  {m}" for m in (matches or modules))
    files = modules[label]
    rows = _module_rows(con, files)
    by_file = defaultdict(list)
    for r in rows:
        by_file[r["path"]].append(r)
    ids = [r["id"] for r in rows]
    callees, routes, tables = defaultdict(list), defaultdict(list), defaultdict(set)
    if ids:
        q = ",".join("?" * len(ids))
        for c in con.execute(f"SELECT c.src_id, d.name FROM calls c JOIN symbols d ON d.id = c.dst_id "
                             f"WHERE c.src_id IN ({q}) ORDER BY d.rank DESC", ids):
            if c["name"] not in callees[c["src_id"]]:
                callees[c["src_id"]].append(c["name"])
        for r in con.execute(f"SELECT symbol_id, method, path FROM routes WHERE symbol_id IN ({q})", ids):
            routes[r["symbol_id"]].append(f"{r['method']} {r['path']}")
        for r in con.execute(f"SELECT symbol_id, table_name, op FROM sql_refs WHERE symbol_id IN ({q})", ids):
            tables[r["symbol_id"]].add(f"{r['table_name']} {r['op'][0]}")
    langs = {r["path"]: (r["lang"], r["lines"]) for r in con.execute(
        f"SELECT path, lang, lines FROM files WHERE path IN ({','.join('?' * len(files))})", files)}
    out = [f"# Module `{label}` — {len(files)} files, {len(rows)} symbols", USAGE, ""]
    bare = []
    for path in files:
        syms = by_file.get(path, [])
        if not syms:
            bare.append(path)
            continue
        lang, nlines = langs.get(path, ("?", 0))
        out.append(f"## {path} ({lang}, {nlines} lines)")
        shown = {}
        for r in sorted(syms, key=lambda r: r["start_line"]):
            if r["kind"] == "namespace" or (not full and r["kind"] in MAP_HIDDEN):
                continue
            depth, anc = 0, r["parent_id"]
            while anc is not None:
                if anc in shown:
                    depth = shown[anc] + 1
                    break
                anc = next((x["parent_id"] for x in syms if x["id"] == anc), None)
            shown[r["id"]] = depth
            label_txt = r["signature"] if r["kind"] in ("function", "method", "constructor") else r["name"]
            line = f"{'  ' * depth}- {ABBR.get(r['kind'], r['kind'])} {label_txt} L{r['start_line']}-{r['end_line']}"
            if r["callers"]:
                line += f" ↑{r['callers']}"
            if r["refs"]:
                line += f" ⇢{r['refs']}f"
            if callees.get(r["id"]):
                line += " →" + ",".join(callees[r["id"]][:4])
            if routes.get(r["id"]):
                line += " [" + "; ".join(routes[r["id"]][:3]) + "]"
            if tables.get(r["id"]):
                line += " {" + ", ".join(sorted(tables[r["id"]])[:4]) + "}"
            d = describe(r)
            if d:
                line += f" — {d}"
            out.append(line)
        out.append("")
    if bare:
        out.append("## Other files\n" + ", ".join(f"`{p}`" for p in bare))
    return "\n".join(out) + "\n"


def write_ai(con, root: Path, budget_tokens: int = 3000) -> Path:
    base = root / ".codedict" / "ai"
    mod_dir = base / "modules"
    mod_dir.mkdir(parents=True, exist_ok=True)
    for old in mod_dir.glob("*.md"):
        old.unlink()
    modules = group_modules(con)
    summaries = _summaries(con, modules)
    (base / "INDEX.md").write_text(overview(con, budget_tokens, modules, summaries), encoding="utf-8")
    (base / "MODULES.md").write_text(
        "# Modules\n" + USAGE + "\n\n" + "\n".join(_module_line(m["label"], len(m["files"]), m["rows"]) for m in summaries) + "\n",
        encoding="utf-8")
    for label in modules:
        (mod_dir / f"{slug(label.replace('*', 'files'))}.md").write_text(module_map(con, label, modules=modules), encoding="utf-8")
    return base


AGENT_SNIPPET = """## Code navigation (codedict)
In a repo with a `.codedict/` index, a code question may arrive with a `codedict` block (added by a hook).
If not, run `codedict search "<words from the question>"` first, before grep or reading files.
Either way, the top hits show file:line, signature, every call site (`called at`, `unlinked same-name calls`), `caller chain`, `call chain`, `calls`, `runs` and code.
They come from a full index of the repo, so the call sites are complete: answer from them, do not re-check with grep or file reads.
Need more code? Pass every name to ONE call: `codedict show A B C` (one call = one turn).
"""
