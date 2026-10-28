"""Developer-facing documentation (Markdown + Mermaid), generated from the same index."""
from collections import defaultdict
from pathlib import Path

from .query import ABBR, MAP_HIDDEN, describe, group_modules, vocabulary, _SYM_SQL
from .text import slug

LABELS = {
    "pt": {"title": "Dicionário de código", "files": "arquivos", "symbols": "símbolos", "module": "Módulo",
           "vocab": "Vocabulário", "key": "Principais", "lang": "Linguagens", "routes": "Rotas",
           "tables": "Tabelas SQL", "kind": "Tipo", "name": "Símbolo", "lines": "Linhas",
           "callers": "Chamado por", "desc": "Descrição", "graph": "Chamadas internas", "other": "Outros arquivos",
           "used_by": "Usada por", "back": "Voltar ao índice", "generated": "Gerado em"},
    "en": {"title": "Code dictionary", "files": "files", "symbols": "symbols", "module": "Module",
           "vocab": "Vocabulary", "key": "Key symbols", "lang": "Languages", "routes": "Routes",
           "tables": "SQL tables", "kind": "Kind", "name": "Symbol", "lines": "Lines",
           "callers": "Called by", "desc": "Description", "graph": "Internal calls", "other": "Other files",
           "used_by": "Used by", "back": "Back to index", "generated": "Generated"},
}


def _esc(s: str) -> str:
    return (s or "").replace("|", "\\|").replace("\n", " ")


def _mod_file(label: str) -> str:
    return slug(label.replace("*", "files")) + ".md"


def write_docs(con, root: Path, out_dir: Path | None = None, lang: str = "pt") -> Path:
    L = LABELS.get(lang, LABELS["en"])
    out = out_dir or root / ".codedict" / "docs"
    (out / "modules").mkdir(parents=True, exist_ok=True)
    for old in (out / "modules").glob("*.md"):
        old.unlink()
    to_root = Path(*([".."] * len((out / "modules").resolve().relative_to(root.resolve()).parts))).as_posix()
    to_root_idx = Path(*([".."] * len(out.resolve().relative_to(root.resolve()).parts))).as_posix()
    modules = group_modules(con)
    meta = dict(con.execute("SELECT key, value FROM meta").fetchall())

    idx = [f"# {L['title']}: {meta.get('root', '')}", "",
           f"{L['generated']} {meta.get('indexed_at', '')}", "",
           f"## {L['lang']}", "", "| | " + L["files"] + " |", "|---|---|"]
    idx += [f"| {r[0]} | {r[1]} |" for r in con.execute("SELECT lang, COUNT(*) FROM files GROUP BY lang ORDER BY 2 DESC")]
    idx += ["", f"## {L['module']}s", "", f"| {L['module']} | {L['files']} | {L['symbols']} | {L['vocab']} | {L['key']} |",
            "|---|---|---|---|---|"]
    for label, files in modules.items():
        rows = _rows(con, files)
        top = sorted((r for r in rows if not r["private"] and r["kind"] != "namespace"), key=lambda r: -r["rank"])[:3]
        idx.append(f"| [{label}](modules/{_mod_file(label)}) | {len(files)} | {len(rows)} | "
                   f"{', '.join(vocabulary(rows, 5))} | {', '.join('`' + r['name'] + '`' for r in top)} |")
        (out / "modules" / _mod_file(label)).write_text(_module_doc(con, label, files, L, to_root), encoding="utf-8")
    routes = list(con.execute(
        "SELECT r.method, r.path route, f.path, s.qualified, s.start_line FROM routes r JOIN files f ON f.id = r.file_id "
        "LEFT JOIN symbols s ON s.id = r.symbol_id ORDER BY r.path"))
    if routes:
        idx += ["", f"## {L['routes']}", "", "| | | |", "|---|---|---|"]
        idx += [f"| {r['method']} | `{_esc(r['route'])}` | [{r['qualified'] or r['path']}]({to_root_idx}/{r['path']}#L{r['start_line'] or 1}) |"
                for r in routes[:500]]
    tables = defaultdict(set)
    for r in con.execute("SELECT q.table_name, COALESCE(s.qualified, f.path) who FROM sql_refs q "
                         "JOIN files f ON f.id = q.file_id LEFT JOIN symbols s ON s.id = q.symbol_id"):
        tables[r["table_name"]].add(r["who"])
    if tables:
        idx += ["", f"## {L['tables']}", "", f"| | {L['used_by']} |", "|---|---|"]
        for t in sorted(tables, key=lambda t: -len(tables[t]))[:300]:
            who = sorted(tables[t])
            idx.append(f"| `{t}` | {', '.join(who[:8])}{' …' if len(who) > 8 else ''} |")
    (out / "README.md").write_text("\n".join(idx) + "\n", encoding="utf-8")
    return out


def _rows(con, files):
    if not files:
        return []
    return list(con.execute(_SYM_SQL + f" WHERE f.path IN ({','.join('?' * len(files))})", files))


def _module_doc(con, label, files, L, to_root) -> str:
    rows = _rows(con, files)
    by_file = defaultdict(list)
    for r in rows:
        by_file[r["path"]].append(r)
    doc = [f"# {L['module']} `{label}`", "", f"[← {L['back']}](../README.md)", "",
           f"{len(files)} {L['files']} · {len(rows)} {L['symbols']} · {L['vocab']}: {', '.join(vocabulary(rows, 8))}", ""]
    graph = _mermaid(con, rows)
    if graph:
        doc += [f"## {L['graph']}", "", "```mermaid", graph, "```", ""]
    bare = []
    for path in files:
        syms = [r for r in sorted(by_file.get(path, []), key=lambda r: r["start_line"])
                if r["kind"] != "namespace" and r["kind"] not in MAP_HIDDEN]
        if not syms:
            bare.append(path)
            continue
        doc += [f"## [{path}]({to_root}/{path})", "",
                f"| {L['kind']} | {L['name']} | {L['lines']} | {L['callers']} | {L['desc']} |", "|---|---|---|---|---|"]
        for r in syms:
            name = r["qualified"].split(".", r["qualified"].count(".") - 1)[-1] if r["parent_id"] else r["name"]
            doc.append(f"| {ABBR.get(r['kind'], r['kind'])} | [`{_esc(name)}`]({to_root}/{path}#L{r['start_line']}) | "
                       f"{r['start_line']}-{r['end_line']} | {r['callers'] or ''} | {_esc(describe(r))} |")
        doc.append("")
    if bare:
        doc += [f"## {L['other']}", "", ", ".join(f"[`{p}`]({to_root}/{p})" for p in bare)]
    return "\n".join(doc) + "\n"


def _mermaid(con, rows, max_edges: int = 40) -> str:
    ids = {r["id"]: r for r in rows}
    if not ids:
        return ""
    q = ",".join("?" * len(ids))
    edges = list(con.execute(
        f"SELECT DISTINCT c.src_id, c.dst_id FROM calls c JOIN symbols d ON d.id = c.dst_id "
        f"WHERE c.src_id IN ({q}) AND c.dst_id IN ({q}) AND c.src_id != c.dst_id "
        f"AND c.confidence IN ('high','medium') ORDER BY d.rank DESC LIMIT ?", list(ids) * 2 + [max_edges]))
    if not edges:
        return ""
    lines = ["graph LR"]
    for s, d in edges:
        lines.append(f"  n{s}[\"{_q(ids[s]['name'])}\"] --> n{d}[\"{_q(ids[d]['name'])}\"]")
    return "\n".join(lines)


def _q(s: str) -> str:
    return s.replace('"', "'")
