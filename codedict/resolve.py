"""Link call names to symbols with graded confidence (no type checker, no AI)."""
import re
from collections import defaultdict

from .config import load_languages
from .text import split_identifier

FAMILY = {"python": "py", "csharp": "net", "razor": "net", "javascript": "js", "typescript": "js",
          "tsx": "js", "java": "jvm", "go": "go", "sql": "sql"}
SELF_LIKE = ("self", "this", "base", "super", "cls")
CALLABLE_KINDS = {"function", "method", "constructor", "class", "struct", "record", "interface",
                  "type", "enum", "procedure", "view", "table"}
AMBIGUOUS_LIMIT = 25
# Very generic member names: when the receiver does not look like the owner, assume external.
COMMON_NAMES = {
    "get", "set", "add", "save", "find", "update", "delete", "remove", "run", "execute", "send", "load",
    "query", "open", "close", "write", "read", "map", "filter", "push", "emit", "call", "apply", "start",
    "stop", "init", "create", "build", "parse", "format", "log", "info", "error", "debug", "warn", "then",
    "catch", "append", "extend", "insert", "pop", "clear", "copy", "keys", "items", "values", "join", "split",
    "replace", "first", "where", "select", "any", "all", "count", "tostring", "equals", "dispose", "invoke",
    "include", "post", "put", "patch", "fetch", "list", "show", "hide", "render", "validate", "process",
}


CLASS_KINDS = {"class", "struct", "record", "interface"}
TYPED = {"net", "jvm", "py", "js", "go"}  # families with classes/structs and typed receivers
IMPLICIT_THIS = {"net", "jvm"}  # a bare `Foo()` may call an own method only in C#/Java


def _dir(path: str) -> str:
    return path.rsplit("/", 1)[0] if "/" in path else ""


def _bases(signature: str) -> list[str]:
    """'class A : B<T>, IFoo' / 'class A extends B implements C' / 'class A(B, C):' -> base names."""
    sig = re.sub(r"<[^<>]*>", "", signature or "")
    py = re.match(r"\s*class\s+\w+\s*\((.*)\)\s*:?\s*$", sig)
    if py:
        return [n.strip().split(".")[-1] for n in py.group(1).split(",") if n.strip() and "=" not in n]
    m = re.search(r"(?::|\bextends\b)\s*(.+?)(?:\bwhere\b|\{|$)", sig)
    if not m:
        return []
    names = re.split(r",|\bimplements\b", m.group(1))
    return [n.strip().split(".")[-1] for n in names if n.strip()]


def _var_types(text: str, patterns) -> dict[str, str]:
    """variable -> declared type, from the language's [types] patterns (groups `var` and `type`)."""
    # ponytail: one map per file, ignores scope; a same-named variable with two types keeps the last.
    types = {}
    for rx in patterns:
        for m in rx.finditer(text):
            types[m["var"]] = m["type"]
    return types


def resolve_calls(con, root=None) -> dict:
    syms = {}
    by_name = defaultdict(list)
    for r in con.execute(
            "SELECT s.id, s.name, s.kind, s.parent_id, s.qualified, s.file_id, f.path, f.lang "
            "FROM symbols s JOIN files f ON f.id = s.file_id"):
        syms[r["id"]] = r
        if r["kind"] in CALLABLE_KINDS:
            short = r["name"].split(".")[-1]
            by_name[short].append(r["id"])
    names = {sid: syms[sid]["name"] for sid in syms}
    imports = defaultdict(str)
    for r in con.execute("SELECT file_id, text FROM imports"):
        imports[r["file_id"]] += " " + r["text"]
    file_path, file_lang = {}, {}
    for r in con.execute("SELECT id, path, lang FROM files"):
        file_path[r["id"]], file_lang[r["id"]] = r["path"], r["lang"]

    def module_hints(sid):
        s = syms[sid]
        path = s["path"]
        stem = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        hints = {stem}
        if "." in s["qualified"]:
            hints.add(s["qualified"].rsplit(".", 1)[0].rsplit(".", 1)[-1])
        anc = s["parent_id"]
        while anc is not None and anc in syms:
            hints.add(syms[anc]["name"].split(".")[-1])
            if syms[anc]["kind"] == "namespace":
                hints.add(syms[anc]["name"])
                hints.update(syms[anc]["name"].split("."))
            anc = syms[anc]["parent_id"]
        return {h for h in hints if h}

    langs = load_languages(root / ".codedict" / "languages" if root else None).values()
    outside = {cfg.name for cfg in langs if cfg.receiver_field}  # languages whose methods live outside the type
    # Class graph: partial classes share a qualified name; bases come from the signature.
    class_by_short = defaultdict(set)
    bases = defaultdict(set)
    for s in syms.values():
        if FAMILY.get(s["lang"]) not in TYPED:
            continue
        if s["kind"] in CLASS_KINDS or s["kind"] == "type":
            class_by_short[s["name"].split(".")[-1]].add(s["qualified"])
        elif s["kind"] == "method" and s["parent_id"] is None and s["lang"] in outside:
            # method declared outside its type (Go): Owner from `module.Owner.Method`, like a partial class part
            owner = s["qualified"].rsplit(".", 1)[0]
            class_by_short[owner.rsplit(".", 1)[-1]].add(owner)
    for r in con.execute("SELECT qualified, signature, kind FROM symbols WHERE signature IS NOT NULL"):
        if r["kind"] in CLASS_KINDS:
            bases[r["qualified"]].update(_bases(r["signature"]))
    family_cache = {}

    def family(qual):
        """The class itself (all partial parts) plus every base class found in the project."""
        if qual not in family_cache:
            seen, todo = set(), [qual]
            while todo:
                q = todo.pop()
                if q in seen:
                    continue
                seen.add(q)
                for b in bases.get(q, ()):
                    todo.extend(class_by_short.get(b, ()))
            family_cache[qual] = seen
        return family_cache[qual]

    def owner_class(sid):
        if sid not in syms:
            return None
        p = syms[sid]["parent_id"]
        while p is not None and p in syms and syms[p]["kind"] not in CLASS_KINDS:
            p = syms[p]["parent_id"]
        if p in syms:
            return syms[p]["qualified"]
        if syms[sid]["kind"] == "method" and syms[sid]["parent_id"] is None and syms[sid]["lang"] in outside:
            return syms[sid]["qualified"].rsplit(".", 1)[0]
        return None

    var_types = {}
    type_rx = {} if root is None else {cfg.name: [re.compile(p) for p in cfg.types] for cfg in langs}

    def receiver_type(file_id, receiver):
        """Declared type of a variable/field receiver in this file, if the source says it."""
        patterns = type_rx.get(file_lang.get(file_id))
        if not patterns:
            return None
        if file_id not in var_types:
            try:
                var_types[file_id] = _var_types(
                    (root / file_path[file_id]).read_text(encoding="utf-8", errors="replace"), patterns)
            except OSError:
                var_types[file_id] = {}
        return var_types[file_id].get(receiver.split(".")[-1])

    hint_cache = {}
    stats = defaultdict(int)
    updates = []
    for c in con.execute("SELECT id, file_id, src_id, name, receiver FROM calls"):
        fam = FAMILY.get(file_lang.get(c["file_id"]), "?")
        cands = [x for x in by_name.get(c["name"], [])
                 if FAMILY.get(syms[x]["lang"]) == fam or syms[x]["lang"] == "sql" and syms[x]["kind"] in ("procedure", "function")]
        if not cands:
            updates.append((None, "external", c["id"]))
            stats["external"] += 1
            continue
        if len(cands) > AMBIGUOUS_LIMIT:
            updates.append((None, "ambiguous", c["id"]))
            stats["ambiguous"] += 1
            continue
        src_path = file_path[c["file_id"]]
        src_parent = syms[c["src_id"]]["parent_id"] if c["src_id"] in syms else None
        receiver = (c["receiver"] or "").lower()
        oo = fam in TYPED
        src_family = family(owner_class(c["src_id"])) if oo and owner_class(c["src_id"]) else set()
        # Typed receiver: `TagList customerTags;` makes customerTags.X() look for TagList (and its bases).
        rtype = receiver_type(c["file_id"], c["receiver"]) if oo and receiver and receiver not in SELF_LIKE else None
        rtype_family = set().union(*(family(q) for q in class_by_short.get(rtype, ()))) if rtype else set()
        scored = []
        if not receiver:
            def reachable(x):
                p = syms[x]["parent_id"]
                if p is None or syms[p]["kind"] in ("namespace",):
                    return True
                if p in (src_parent, c["src_id"]):
                    return True
                if syms[p]["kind"] in ("function", "method", "constructor"):
                    return False  # nested/local function: only visible inside its parent
                if syms[x]["kind"] in ("method", "property"):
                    # same file, another part of a partial class, or an inherited member
                    return fam in IMPLICIT_THIS and (syms[x]["file_id"] == c["file_id"] or owner_class(x) in src_family)
                return True
            cands = [x for x in cands if reachable(x)]
            if not cands:
                updates.append((None, "external", c["id"]))
                stats["external"] += 1
                continue
        for cand in cands:
            s = syms[cand]
            score, mismatch = 0.0, False
            if s["file_id"] == c["file_id"]:
                score += 3
            parent_name = names.get(s["parent_id"], "") if s["parent_id"] else ""
            raw = parent_name.split(".")[-1]
            pshort = raw.lower()
            iface = raw[1:].lower() if len(raw) > 2 and raw[0] == "I" and raw[1].isupper() else pshort
            in_family = oo and owner_class(cand) in src_family
            if not receiver and in_family:
                score += 3  # own member: this part, another partial part, or a base class
            if receiver:
                r = receiver.lstrip("_")
                if s["lang"] == "sql":
                    if s["qualified"].lower().startswith(receiver + "."):
                        score += 3
                elif receiver in SELF_LIKE:
                    if (s["parent_id"] is not None and s["parent_id"] == src_parent) or in_family:
                        score += 3
                elif rtype_family and owner_class(cand) in rtype_family:
                    score += 3  # declared type of the variable/field
                elif pshort and (r == pshort or r == iface or pshort.endswith(r) or r.endswith(iface)
                                 or _fuzzy(r, raw)):
                    score += 2.5
                else:
                    if cand not in hint_cache:
                        hint_cache[cand] = module_hints(cand)
                    if r in {h.lower() for h in hint_cache[cand]}:
                        score += 2  # module.func() / Namespace.Type
                    else:
                        score -= 2
                        mismatch = True
            if cand not in hint_cache:
                hint_cache[cand] = module_hints(cand)
            imp = imports.get(c["file_id"], "")
            if imp and any(h in imp for h in hint_cache[cand]):
                score += 2
            if _dir(s["path"]) == _dir(src_path):
                score += 1
            elif s["path"].split("/", 1)[0] == src_path.split("/", 1)[0]:
                score += 0.5
            is_iface = syms[s["parent_id"]]["kind"] == "interface" if s["parent_id"] in syms else False
            scored.append((score, not is_iface, mismatch, cand))
        scored.sort(reverse=True)
        best_score, _, best_mismatch, best = scored[0]
        if best_mismatch:
            updates.append((None, "external", c["id"]))
            stats["external"] += 1
            continue
        top = [x for x in scored if x[0] == best_score]
        if len(top) > 1:
            impls = [x for x in top if x[1]]
            if len({syms[x[3]]["qualified"] for x in top}) == 1:
                # ponytail: overloads of one method; links the first, argument count would pick the exact one
                best = min(x[3] for x in top)
            elif len(impls) == 1 and len(top) - 1 == len([x for x in top if not x[1]]):
                best = impls[0][3]  # interface + single implementation: link to the implementation
            else:
                updates.append((None, "ambiguous", c["id"]))
                stats["ambiguous"] += 1
                continue
        elif len(scored) > 1 and best_score < 1:
            updates.append((None, "ambiguous", c["id"]))
            stats["ambiguous"] += 1
            continue
        conf = "high" if best_score >= 3 else "medium" if best_score >= 1.5 else "low"
        updates.append((best, conf, c["id"]))
        stats[conf] += 1
    con.executemany("UPDATE calls SET dst_id = ?, confidence = ? WHERE id = ?", updates)
    con.execute("UPDATE symbols SET callers = 0")
    con.execute(
        "UPDATE symbols SET callers = (SELECT COUNT(DISTINCT COALESCE(src_id, -file_id)) FROM calls "
        "WHERE calls.dst_id = symbols.id) WHERE id IN (SELECT dst_id FROM calls WHERE dst_id IS NOT NULL)")
    return dict(stats)


def _fuzzy(receiver: str, owner: str) -> bool:
    """'calc' ~ 'TaxCalculator', 'orderRepo' ~ 'OrderRepository' (word prefix overlap)."""
    rw = [w for w in split_identifier(receiver) if len(w) >= 3]
    ow = split_identifier(owner)
    return bool(rw) and all(any(o.startswith(w) for o in ow) for w in rw)
