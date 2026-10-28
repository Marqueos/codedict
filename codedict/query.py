"""Read-side API shared by CLI, MCP server and renderers."""
import json
import math
import re
from collections import Counter, defaultdict

from .text import QUERY_STOPWORDS, one_line, split_identifier, strip_accents, vocabulary_words

ABBR = {"namespace": "ns", "class": "cls", "interface": "ifc", "struct": "struct", "record": "rec",
        "enum": "enum", "type": "type", "function": "fn", "method": "m", "constructor": "ctor",
        "property": "prop", "procedure": "proc", "view": "view", "table": "tbl", "trigger": "trg"}
MAP_HIDDEN = {"property"}
ENTRY_FILES = {"main.py", "__main__.py", "app.py", "manage.py", "wsgi.py", "asgi.py", "program.cs",
               "startup.cs", "main.go", "index.ts", "index.js", "server.ts", "server.js", "main.ts",
               "app.ts", "app.js", "main.java", "application.java"}


TEST_RE = re.compile(
    r"(^|/)(tests?|specs?|__tests__|testing|e2e)(/|$)|(^|/)test_[^/]*$|_tests?\.\w+$|\.(spec|test)\.\w+$"
    r"|[.\-_](unit|integration|functional)?tests?(/|$)", re.I)


def is_test_path(path: str) -> bool:
    return bool(TEST_RE.search(path))


# ---------------------------------------------------------------- modules
def group_modules(con, max_modules: int = 5000, max_symbols: int = 400) -> dict[str, list[str]]:
    """Adaptive grouping: split the biggest directory until groups are small or the cap is hit."""
    counts = {r["path"]: r["n"] for r in con.execute(
        "SELECT f.path, COUNT(s.id) n FROM files f LEFT JOIN symbols s ON s.file_id = f.id GROUP BY f.id")}

    def files_under(prefix, recursive):
        out = []
        for p in counts:
            d = p.rsplit("/", 1)[0] if "/" in p else ""
            if recursive and (prefix == "" or p.startswith(prefix + "/")):
                out.append(p)
            elif not recursive and d == prefix:
                out.append(p)
        return out

    groups = {("", True): list(counts)}
    frozen = set()
    while len(groups) < max_modules:
        cand = [(sum(counts[f] for f in fs), k) for k, fs in groups.items() if k[1] and k not in frozen]
        if not cand:
            break
        size, key = max(cand)
        if size <= max_symbols:
            break
        prefix = key[0]
        depth = 0 if prefix == "" else prefix.count("/") + 1
        subs = sorted({f.split("/")[depth] for f in groups[key] if f.count("/") > depth})
        if not subs:
            frozen.add(key)
            continue
        del groups[key]
        direct = files_under(prefix, False)
        if direct:
            groups[(prefix, False)] = direct
        for s in subs:
            sp = f"{prefix}/{s}" if prefix else s
            groups[(sp, True)] = files_under(sp, True)
    result = {}
    for (prefix, recursive), fs in sorted(groups.items()):
        if recursive:
            label = prefix + "/" if prefix else "./"
        else:
            label = prefix + "/*" if prefix else "./*"
        result[label] = sorted(fs)
    return result


def module_for(con, path: str, modules=None) -> str | None:
    modules = modules or group_modules(con)
    for label, fs in modules.items():
        if path in fs:
            return label
    return None


# ---------------------------------------------------------------- lookups
def find_symbols(con, name: str, limit: int = 20):
    name = name.strip()
    if name.startswith("#") and name[1:].isdigit():
        return list(con.execute(_SYM_SQL + " WHERE s.id = ?", (int(name[1:]),)))
    rows = list(con.execute(_SYM_SQL + " WHERE s.qualified = ? ORDER BY s.rank DESC LIMIT ?", (name, limit)))
    if not rows:
        rows = list(con.execute(_SYM_SQL + " WHERE s.name = ? OR s.qualified LIKE ? ORDER BY s.rank DESC LIMIT ?",
                                (name, "%." + name, limit)))
    return rows


_SYM_SQL = ("SELECT s.*, f.path, f.lang, n.note AS manual_note FROM symbols s JOIN files f ON f.id = s.file_id "
            "LEFT JOIN notes n ON n.qualified = s.qualified")


def loc(r) -> str:
    return f"{r['path']}:{r['start_line']}-{r['end_line']}"


def describe(r) -> str:
    """Deterministic description: manual note > doc comment > humanized name."""
    text = r["manual_note"] if "manual_note" in r.keys() and r["manual_note"] else r["doc"]
    return one_line(text, 140) if text else ""


def sym_line(r, extra: str = "") -> str:
    up = f" ↑{r['callers']}" if r["callers"] else ""
    if "refs" in r.keys() and r["refs"]:
        up += f" ⇢{r['refs']}f"
    d = describe(r)
    return f"{ABBR.get(r['kind'], r['kind'])} `{r['qualified']}` {loc(r)}{up}{extra}" + (f" — {d}" if d else "")


def _ambiguous(rows) -> str:
    lines = ["Multiple matches. Use the qualified name or #id:"]
    lines += [f"  #{r['id']} {sym_line(r)}" for r in rows]
    return "\n".join(lines)


# ---------------------------------------------------------------- search
def _query_words(query: str) -> list[str]:
    words = []
    for w in re.findall(r"[\w]+", strip_accents(query)):
        words += [w.lower()] + split_identifier(w)
    words = [re.sub(r"[^a-z0-9_]", "", w) for w in dict.fromkeys(words)]
    return [w for w in words if len(w) > 1 and w not in QUERY_STOPWORDS]


# Portuguese nouns made from verbs: questions say 'exclusão'/'geração', code says excluir/gerar.
PT_NOUN = ("coes", "soes", "cao", "sao", "mentos", "mento")
ALWAYS_EXTRA = ("ed", "ing") + PT_NOUN  # endings that are never a plain word: the stem is always an extra term


def _stem(w: str) -> str | None:
    """'parsed' -> 'pars', 'running' -> 'run', 'sends' -> 'send', 'exclusao' -> 'exclu'. None when unchanged."""
    # ponytail: suffix strip, not a real stemmer; covers the forms questions use most
    for suf in PT_NOUN:
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            return w[:-len(suf)]
    for suf in ("ing", "ed", "es", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 3 and not w.endswith("ss"):
            s = w[:-len(suf)]
            return s[:-1] if len(s) > 3 and s[-1] == s[-2] and s[-1] not in "aeiou" else s
    return None


def _fts_term(w: str) -> str:
    return f'"{w}"*' if len(w) >= 4 else f'"{w}"'  # quoted: "not"/"near" stay terms


def _terms(con, words: list[str]) -> list[str]:
    """A word that matches nothing in the index falls back to its stem ('parsed' -> 'pars'*).
    Words that match keep their own form, so Portuguese plurals don't pull in noise."""
    out = []
    for w in words:
        s = _stem(w)
        if s and w.endswith(ALWAYS_EXTRA):
            out.append(s)
        elif s and not con.execute("SELECT 1 FROM symbols_fts WHERE symbols_fts MATCH ? LIMIT 1", (_fts_term(w),)).fetchone():
            w = s
        out.append(w)
    return list(dict.fromkeys(out))


def search(con, query: str, limit: int = 10) -> list:
    words = _query_words(query)
    if not words:
        return []
    # OR + bm25: symbols matching more words rank higher, one stray word no longer zeroes the right one.
    # Prefix match only from 4 letters, so "are"/"tem" don't hit Area*/Theme*/Tempo*.
    expr = " OR ".join(map(_fts_term, _terms(con, words)))
    rows = list(con.execute(
        "SELECT rowid, bm25(symbols_fts, 10.0, 4.0, 2.0, 1.0) AS score FROM symbols_fts "
        "WHERE symbols_fts MATCH ? ORDER BY score LIMIT 200", (expr,)))
    if not rows:
        return []
    ids = {r["rowid"]: -r["score"] for r in rows}
    syms = {r["id"]: r for r in con.execute(
        _SYM_SQL + f" WHERE s.id IN ({','.join('?' * len(ids))})", list(ids))}
    # Tests repeat the words of the code they test; rank them lower unless the question is about tests.
    test_weight = 1.0 if any(w.startswith(("test", "spec")) for w in words) else 0.5
    scored = sorted(((ids[i] * (1 + 0.25 * math.log1p(syms[i]["rank"]))
                      * (test_weight if is_test_path(syms[i]["path"]) else 1.0), syms[i]) for i in ids if i in syms),
                    key=lambda x: -x[0])
    return [s for _, s in scored[:limit]]


def _group_sites(sites, max_files: int) -> str:
    """[(path, line)] -> 'a.ts:3,9, b.cs:12' (one entry per file, lines deduped)."""
    by_file = defaultdict(set)
    for s in sites:
        by_file[s["path"]].add(s["line"])
    parts = [f"{p}:{','.join(map(str, sorted(ls)))}" for p, ls in sorted(by_file.items())]
    more = f" (+{len(parts) - max_files} more files)" if len(parts) > max_files else ""
    return ", ".join(parts[:max_files]) + more


def _brief(con, r, max_sites: int = 8, root=None, words=None) -> list[str]:
    """Signature + call sites, so the top hit answers 'where and who calls it' without another tool call."""
    out = []
    if r["signature"]:
        out.append("    sig: " + one_line(r["signature"], 160))
    linked = list(con.execute(
        "SELECT f.path, c.line FROM calls c JOIN files f ON f.id = c.file_id WHERE c.dst_id = ?", (r["id"],)))
    # Same-name calls the resolver did not link (inheritance, partial classes, typed fields...).
    # Skip ones whose receiver clearly names another class (Worker.Run is not Engine.Run).
    parts = r["qualified"].split(".")
    owner = parts[-2].lower() if len(parts) > 1 else ""

    def same_owner(recv):
        recv = (recv or "").split(".")[-1].lstrip("_")
        if not recv or not recv[0].isupper():  # no receiver, this/self, or a variable: may be ours
            return True
        return owner.endswith(recv.lower()) or recv.lower().endswith(owner)  # Type.Method: only our type
    unlinked = [x for x in con.execute(
        "SELECT f.path, c.line, c.receiver FROM calls c JOIN files f ON f.id = c.file_id "
        "WHERE c.name = ? AND c.dst_id IS NULL AND c.src_id IS NOT ?", (r["name"], r["id"])) if same_owner(x["receiver"])]
    for label, sites in (("called at", linked), ("unlinked same-name calls", unlinked)):
        if sites:
            out.append(f"    {label}: " + _group_sites(sites, max_sites))
    if not linked and not unlinked:
        out.append("    called at: none found")
    out += [f"    caller chain: {c}" for c in _caller_chains(con, r["id"])]
    if root is not None:
        out += _calls_line(con, root, r)
    out += [f"    call chain: {c}" for c in _callee_chains(con, r, words or [])]
    return out


def _callee_chains(con, r, words, depth: int = 4, max_lines: int = 2) -> list[str]:
    """Downstream path 'A -> B (f:l) -> C (f:l)', following callees named like the question first,
    so 'from X until Y' needs no extra reads. Only chains longer than the `calls` line."""
    chains = []

    def walk(sid, path, seen):
        rows = [x for x in con.execute(
            "SELECT DISTINCT d.id, d.qualified, d.name, f.path, d.start_line FROM calls c JOIN symbols d ON d.id = c.dst_id "
            "JOIN files f ON f.id = d.file_id WHERE c.src_id = ? AND c.confidence IN ('high', 'medium') ORDER BY c.line", (sid,))
                if x["id"] not in seen and not is_test_path(x["path"])]
        score = lambda x: sum(2 if x["name"].lower() == w else w in x["name"].lower() for w in words)
        named = sorted((x for x in rows if score(x)), key=lambda x: -score(x))  # stable: line order on ties
        if not named or len(path) > depth:
            if len(path) > 2:
                chains.append(" -> ".join(path))
            return
        for x in named[:2]:
            if len(chains) >= max_lines:
                return
            walk(x["id"], path + [f"{_short(x['qualified'])} ({x['path']}:{x['start_line']})"], seen | {x["id"]})

    walk(r["id"], [_short(r["qualified"])], {r["id"]})
    return chains


def _short(qualified: str) -> str:
    return ".".join(qualified.split(".")[-2:])


def _caller_chains(con, sid: int, depth: int = 3, width: int = 3, max_lines: int = 5) -> list[str]:
    """Upstream paths to the entry points: 'A (f:l) <- B (f:l) <- C (f:l)', so a flow question needs no grep."""
    chains = []

    def walk(node, path, seen):
        rows = list(con.execute(
            "SELECT s.id, s.qualified, f.path, MIN(c.line) AS line FROM calls c JOIN symbols s ON s.id = c.src_id "
            "JOIN files f ON f.id = c.file_id WHERE c.dst_id = ? GROUP BY s.id LIMIT 50", (node,)))
        # Real callers first: a chain through tests explains nothing about the app's flow.
        rows = sorted((x for x in rows if x["id"] not in seen), key=lambda x: is_test_path(x["path"]))[:width]
        if not rows or len(path) == depth:
            if len(path) > 1:  # depth 1 is already in "called at"
                chains.append(" <- ".join(path))
            return
        for x in rows:
            if len(chains) >= max_lines:
                return
            walk(x["id"], path + [f"{_short(x['qualified'])} ({x['path']}:{x['line']})"], seen | {x["id"]})

    walk(sid, [], {sid})
    return chains


def _calls_line(con, root, r, limit: int = 8) -> list[str]:
    """What the symbol calls, plus `npm run X` bridges (e.g. C# app -> TypeScript script) found in that code."""
    parts = []
    for d in con.execute(
            "SELECT DISTINCT d.id, d.qualified, d.start_line, d.end_line, f.path FROM calls c "
            "JOIN symbols d ON d.id = c.dst_id JOIN files f ON f.id = d.file_id WHERE c.src_id = ? LIMIT ?",
            (r["id"], limit)):
        bridge = _bridges(root, _code_text(root, d))
        parts.append(f"{_short(d['qualified'])} ({d['path']}:{d['start_line']})" + (f" -> {bridge}" if bridge else ""))
    own = _bridges(root, _code_text(root, r))
    out = [f"    calls: {', '.join(parts)}"] if parts else []
    return out + ([f"    runs: {own}"] if own else [])


def _code_text(root, r) -> str:
    try:
        lines = (root / r["path"]).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    body = lines[r["start_line"] - 1:r["end_line"]]
    return "\n".join(l for l in body if not l.lstrip().startswith(("//", "#", "*", "/*", "///")))  # code, not comments


_npm_cache = {}
# Code in one language that starts a program in another: the target file closes the flow across languages.
_RUNNERS = [(re.compile(r"\b(?:python3?|py)\s+-m\s+([\w.]+)"), "module"),
            (re.compile(r"\bgo run\s+([\w./-]+)"), "path"),
            (re.compile(r"\bdotnet run\s+--project\s+([\w./\\-]+)"), "path"),
            (re.compile(r"\b(?:python3?|node|deno run|bun|tsx|ts-node)\s+([\w./-]+\.(?:py|js|mjs|ts))\b"), "path")]


def _bridges(root, code: str) -> str:
    """'npm run report -- x' -> 'npm run report = scripts/report.ts'; also `python -m`, `go run`, `dotnet run`,
    `node x.js`. Only targets that exist in the project are listed."""
    # ponytail: no Makefile/justfile targets yet; add a runner row when a project needs one
    if root not in _npm_cache:
        try:
            _npm_cache[root] = json.loads((root / "package.json").read_text(encoding="utf-8")).get("scripts", {})
        except (OSError, ValueError):
            _npm_cache[root] = {}
    found = []
    for name, cmd in _npm_cache[root].items():
        if re.search(rf"(?:npm|pnpm|yarn|bun) run (?:--[\w-]+ )*{re.escape(name)}\b|\"{re.escape(name)} --", code):
            target = re.search(r"[\w./-]+\.(?:ts|js|mjs|py)\b", cmd)
            found.append(f"npm run {name} = {target.group(0) if target else cmd}")
    for rx, kind in _RUNNERS:
        for m in rx.finditer(code):
            arg = m.group(1)
            paths = [arg.replace(".", "/") + ".py", arg.replace(".", "/") + "/__main__.py"] if kind == "module" else [arg]
            hit = next((p for p in paths if (root / p).exists()), None)
            if hit:
                found.append(f"{m.group(0)} = {hit.lstrip('./')}")
    return ", ".join(dict.fromkeys(found))


def relevant(con, query: str) -> bool:
    """Does the best hit match at least 2 words of the query (or the only one)? Gate for automatic context."""
    # ponytail: word overlap, not a score threshold; tune `need` if chat prompts still get code context
    rows = search(con, query, 1)
    if not rows:
        return False
    words = _terms(con, _query_words(query))
    hit = con.execute("SELECT terms, qualified, path, doc FROM symbols_fts WHERE rowid = ?", (rows[0]["id"],)).fetchone()
    text = strip_accents(" ".join(x or "" for x in hit)).lower()
    found = sum(1 for w in words if re.search(rf"\b{re.escape(w)}", text))
    return found >= min(2, len(words))


def search_text(con, query: str, limit: int = 10, detail: int = 3, root=None, code_lines: int = 50,
                budget: int | None = None) -> str:
    """The retrieval step: question in, compact code context out. `budget` caps it in tokens (~4 chars each)."""
    text = _search_text(con, query, limit, detail, root, code_lines)
    if budget and len(text) > budget * 4:
        text = text[:budget * 4].rsplit("\n", 1)[0] + "\n… (cut at the token budget; ask `codedict show <name>`)"
    return text


def _search_text(con, query, limit, detail, root, code_lines) -> str:
    rows = search(con, query, limit)
    if not rows:
        return f"No symbols match '{query}'. Try other words, a module map, or grep."
    out = []
    words = [w for w in _terms(con, _query_words(query)) if len(w) >= 4]
    for i, r in enumerate(rows):
        out.append(f"#{r['id']} {sym_line(r)}")
        if i < detail:
            out += _brief(con, r, root=root, words=words)
        # Code of the best hit: saves the follow-up `show` turn, which costs far more than these lines.
        if i < detail and root is not None and r["kind"] not in ("namespace", "class", "interface", "struct", "record"):
            code = _source(root, r, code_lines if i == 0 else 40, f"codedict show {r['qualified']}")
            out += ["    " + l for l in code]
            out += _used_constants(root, r, "\n".join(code))
    return "\n".join(out)


# `private static readonly string X =` (C#/Java/TS), `const X =` / `var X =` (JS/Go), `X = ` / `X: int =` (Python, top level).
_CONST_DECL = (r"^\s*(?:(?:public|private|internal|protected|static|readonly|const|export|final|var|let)\s+)+"
               r"[\w<>\[\],.? ]*?\b{0}\s*[:=]|^{0}\s*(?::[^=]*)?=(?!=)")


def _used_constants(root, r, body: str, limit: int = 5) -> list[str]:
    """Declarations of same-file constants/static fields the code uses (e.g. the cache folder), one line each."""
    try:
        lines = (root / r["path"]).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    out = []
    for name in dict.fromkeys(re.findall(r"\b([A-Z]\w{2,})\b", body)):
        rx = re.compile(_CONST_DECL.format(re.escape(name)))
        for n, line in enumerate(lines, 1):
            if rx.match(line) and not r["start_line"] <= n <= r["end_line"]:
                decl = line.strip()
                if decl.endswith("=") and n < len(lines):  # value on the next line
                    decl += " " + lines[n].strip()
                out.append(f"    uses {name}: {one_line(decl, 160)} ({r['path']}:{n})")
                break
        if len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------- graph
def callers_text(con, name: str, limit: int = 30) -> str:
    rows = find_symbols(con, name)
    if not rows:
        return f"Symbol '{name}' not found."
    if len(rows) > 1 and rows[0]["qualified"] != name:
        return _ambiguous(rows)
    target = rows[0]
    out = [f"Callers of {sym_line(target)}"]
    for r in con.execute(
            "SELECT c.line, c.confidence, f.path, s.qualified, s.kind FROM calls c JOIN files f ON f.id = c.file_id "
            "LEFT JOIN symbols s ON s.id = c.src_id WHERE c.dst_id = ? ORDER BY c.confidence, f.path LIMIT ?",
            (target["id"], limit)):
        who = f"`{r['qualified']}`" if r["qualified"] else "(file level)"
        out.append(f"  {who} {r['path']}:{r['line']} [{r['confidence']}]")
    if len(out) == 1:
        out.append("  (no resolved callers)")
    return "\n".join(out)


def callees_text(con, name: str, limit: int = 40) -> str:
    rows = find_symbols(con, name)
    if not rows:
        return f"Symbol '{name}' not found."
    if len(rows) > 1 and rows[0]["qualified"] != name:
        return _ambiguous(rows)
    src = rows[0]
    out = [f"Calls made by {sym_line(src)}"]
    unresolved = Counter()
    for r in con.execute(
            "SELECT c.name, c.receiver, c.line, c.confidence, d.qualified, f.path, d.start_line FROM calls c "
            "LEFT JOIN symbols d ON d.id = c.dst_id LEFT JOIN files f ON f.id = d.file_id "
            "WHERE c.src_id = ? ORDER BY c.line LIMIT ?", (src["id"], limit * 3)):
        if r["qualified"]:
            out.append(f"  L{r['line']} → `{r['qualified']}` {r['path']}:{r['start_line']} [{r['confidence']}]")
        else:
            unresolved[(r["receiver"] + "." if r["receiver"] else "") + r["name"]] += 1
    if unresolved:
        out.append("  unresolved/external: " + ", ".join(k for k, _ in unresolved.most_common(25)))
    return "\n".join(out[: limit + 2])


def show_text(con, root, name: str, source: bool = True, max_lines: int = 200) -> str:
    rows = find_symbols(con, name)
    if not rows:
        return f"Symbol '{name}' not found. Try: codedict search \"{name}\""
    if len(rows) > 1 and rows[0]["qualified"] != name and not name.startswith("#"):
        return _ambiguous(rows)
    r = rows[0]
    out = [f"{r['kind']} {r['qualified']}  ({r['lang']})", f"location: {loc(r)}", f"signature: {r['signature']}"]
    if r["doc"]:
        out.append(f"doc: {r['doc']}")
    if r["manual_note"]:
        out.append(f"note: {r['manual_note']}")
    if r["decorators"]:
        out.append("decorators: " + " ".join(json.loads(r["decorators"])))
    routes = [f"{x['method']} {x['path']}" for x in con.execute("SELECT method, path FROM routes WHERE symbol_id = ?", (r["id"],))]
    if routes:
        out.append("routes: " + ", ".join(routes))
    tables = sorted({f"{x['table_name']}({x['op']})" for x in con.execute(
        "SELECT table_name, op FROM sql_refs WHERE symbol_id = ?", (r["id"],))})
    if tables:
        out.append("sql: " + ", ".join(tables))
    callers = [x["qualified"] or x["path"] for x in con.execute(
        "SELECT DISTINCT s.qualified, f.path FROM calls c JOIN files f ON f.id = c.file_id "
        "LEFT JOIN symbols s ON s.id = c.src_id WHERE c.dst_id = ? LIMIT 10", (r["id"],))]
    if callers:
        out.append(f"called by ({r['callers']}): " + ", ".join(callers))
    callees = [x["qualified"] for x in con.execute(
        "SELECT DISTINCT d.qualified FROM calls c JOIN symbols d ON d.id = c.dst_id WHERE c.src_id = ? LIMIT 15", (r["id"],))]
    if callees:
        out.append("calls: " + ", ".join(callees))
    children = list(con.execute("SELECT kind, name, start_line FROM symbols WHERE parent_id = ? ORDER BY start_line", (r["id"],)))
    if children:
        out.append("members: " + ", ".join(f"{ABBR.get(c['kind'], c['kind'])} {c['name']}:{c['start_line']}" for c in children[:40]))
    if source:
        out += _source(root, r, max_lines, "use --max-lines")
    return "\n".join(out)


def _source(root, r, max_lines: int, more_hint: str) -> list[str]:
    try:
        lines = (root / r["path"]).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    a, b = r["start_line"], min(r["end_line"], r["start_line"] + max_lines - 1)
    out = ["```"] + [f"{i:>5} {lines[i - 1]}" for i in range(a, b + 1) if i - 1 < len(lines)]
    if r["end_line"] > b:
        out.append(f"  … {r['end_line'] - b} more lines ({more_hint})")
    return out + ["```"]


def routes_text(con, flt: str = "", limit: int = 200) -> str:
    out = []
    for r in con.execute(
            "SELECT r.method, r.path AS route, r.handler, f.path, s.qualified, s.start_line FROM routes r JOIN files f ON f.id = r.file_id "
            "LEFT JOIN symbols s ON s.id = r.symbol_id WHERE r.path LIKE ? ORDER BY r.path LIMIT ?",
            (f"%{flt}%", limit)):
        target = f"`{r['qualified']}` {r['path']}:{r['start_line']}" if r["qualified"] else r["path"]
        h = f" handler `{r['handler']}`" if r["handler"] else ""
        out.append(f"{r['method']:6} {r['route']}  → {target}{h}")
    return "\n".join(out) or "No routes found."


def tables_text(con, flt: str = "", limit: int = 100) -> str:
    usage = defaultdict(lambda: defaultdict(set))
    for r in con.execute(
            "SELECT q.table_name, q.op, COALESCE(s.qualified, f.path) who FROM sql_refs q JOIN files f ON f.id = q.file_id "
            "LEFT JOIN symbols s ON s.id = q.symbol_id WHERE q.table_name LIKE ?", (f"%{flt}%",)):
        usage[r["table_name"]][r["op"]].add(r["who"])
    if not usage:
        return "No SQL table references found."
    out = []
    for t in sorted(usage, key=lambda t: -sum(len(v) for v in usage[t].values()))[:limit]:
        parts = [f"{op}: {', '.join(sorted(w)[:6])}{' …' if len(w) > 6 else ''}" for op, w in usage[t].items()]
        out.append(f"{t}  | " + " | ".join(parts))
    return "\n".join(out)


def vocabulary(rows, top: int = 6) -> list[str]:
    c = Counter()
    for r in rows:
        for w in vocabulary_words(r["name"]):
            c[w] += 1 + min(r["rank"], 5)
    return [w for w, _ in c.most_common(top)]
