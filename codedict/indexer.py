"""Incremental indexing pipeline: walk -> hash -> extract -> store -> resolve -> rank -> fts."""
import json
import time
from pathlib import Path

from . import __version__
from .config import OTHER_EXTS, load_languages
from .extract import GENERATED_RE, REGEX_EXTRACTORS, TreeSitterExtractor
from .rank import compute_rank
from .resolve import resolve_calls
from .store import connect
from .text import split_identifier
from .walker import file_ext, list_files, sha256_bytes


def index_project(root: Path, rebuild: bool = False, verbose: bool = True) -> dict:
    t0 = time.time()
    root = root.resolve()
    langs = load_languages(root / ".codedict" / "languages")
    if rebuild:
        notes = []
        db = root / ".codedict" / "index.db"
        if db.exists():
            old = connect(root)
            notes = old.execute("SELECT qualified, note FROM notes").fetchall()
            old.close()
            for suffix in ("", "-wal", "-shm"):
                p = db.with_name(db.name + suffix)
                if p.exists():
                    p.unlink()
    con = connect(root, create=True)
    if rebuild and notes:
        con.executemany("INSERT OR REPLACE INTO notes VALUES (?, ?)", [tuple(n) for n in notes])
    wanted = set(langs) | OTHER_EXTS
    paths = list_files(root, wanted)
    known = {r["path"]: (r["id"], r["sha256"]) for r in con.execute("SELECT id, path, sha256 FROM files")}
    extractors = {}
    changed = parsed = errors = 0
    seen = set()
    for rel in paths:
        seen.add(rel)
        try:
            data = (root / rel).read_bytes()
        except OSError:
            continue
        digest = sha256_bytes(data)
        if rel in known and known[rel][1] == digest:
            continue
        changed += 1
        if rel in known:
            con.execute("DELETE FROM files WHERE id = ?", (known[rel][0],))
        ext = file_ext(rel)
        cfg = langs.get(ext)
        if cfg is not None and GENERATED_RE.search(data[:3000]):
            con.execute("INSERT INTO files(path, lang, sha256, lines, meta) VALUES (?,?,?,?,?)",
                        (rel, "generated", digest, data.count(b"\n") + 1, json.dumps({"generated_from": cfg.name})))
            continue
        if cfg is None:
            con.execute("INSERT INTO files(path, lang, sha256, lines, meta) VALUES (?,?,?,?,?)",
                        (rel, ext.lstrip(".") or "other", digest, data.count(b"\n") + 1, "{}"))
            continue
        try:
            if cfg.extractor == "treesitter":
                if cfg.name not in extractors:
                    extractors[cfg.name] = TreeSitterExtractor(cfg)
                res = extractors[cfg.name].extract(rel, data)
            else:
                res = REGEX_EXTRACTORS[cfg.extractor](rel, data)
        except Exception as e:  # keep indexing; record the failure
            errors += 1
            if verbose:
                print(f"  ! {rel}: {e}")
            con.execute("INSERT INTO files(path, lang, sha256, lines, meta) VALUES (?,?,?,?,?)",
                        (rel, cfg.name, digest, data.count(b"\n") + 1, json.dumps({"error": str(e)})))
            continue
        parsed += 1
        _store(con, rel, digest, res)
    removed = [known[p][0] for p in known if p not in seen]
    con.executemany("DELETE FROM files WHERE id = ?", [(i,) for i in removed])
    if changed or removed or rebuild:
        _orphans(con)
        stats = resolve_calls(con, root)
        _count_refs(con)
        compute_rank(con)
        _rebuild_fts(con)
    else:
        stats = {}
    con.execute("INSERT OR REPLACE INTO meta VALUES ('version', ?)", (__version__,))
    con.execute("INSERT OR REPLACE INTO meta VALUES ('root', ?)", (root.name,))
    con.execute("INSERT OR REPLACE INTO meta VALUES ('indexed_at', ?)", (time.strftime("%Y-%m-%d %H:%M"),))
    con.commit()
    summary = {"files": len(paths), "changed": changed, "parsed": parsed, "removed": len(removed),
               "errors": errors, "calls": stats, "seconds": round(time.time() - t0, 2)}
    con.close()
    return summary


def _store(con, rel, digest, res):
    cur = con.execute("INSERT INTO files(path, lang, sha256, lines, meta) VALUES (?,?,?,?,?)",
                      (rel, res.lang, digest, res.lines, json.dumps(res.meta)))
    fid = cur.lastrowid
    ids = []
    for s in res.symbols:
        parent = ids[s.parent] if s.parent is not None else None
        cur = con.execute(
            "INSERT INTO symbols(file_id, parent_id, kind, name, qualified, start_line, end_line, signature,"
            " doc, decorators, private) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (fid, parent, s.kind, s.name, s.qualified, s.start_line, s.end_line, s.signature, s.doc,
             json.dumps(s.decorators) if s.decorators else None, int(s.private)))
        ids.append(cur.lastrowid)
    sid = lambda i: ids[i] if i is not None else None
    con.executemany("INSERT INTO calls(file_id, src_id, name, receiver, line) VALUES (?,?,?,?,?)",
                    [(fid, sid(c[0]), c[1], c[2], c[3]) for c in res.calls])
    con.executemany("INSERT INTO imports(file_id, text) VALUES (?,?)", [(fid, t) for t in res.imports])
    con.executemany("INSERT INTO idents(file_id, name) VALUES (?,?)", [(fid, n) for n in res.idents])
    con.executemany("INSERT INTO routes(file_id, symbol_id, method, path, handler) VALUES (?,?,?,?,?)",
                    [(fid, sid(r[0]), r[1], r[2], r[3]) for r in res.routes])
    con.executemany("INSERT INTO sql_refs(file_id, symbol_id, table_name, op) VALUES (?,?,?,?)",
                    [(fid, sid(r[0]), r[1], r[2]) for r in res.sql_refs])


def _orphans(con):
    con.execute("UPDATE calls SET dst_id = NULL WHERE dst_id NOT IN (SELECT id FROM symbols)")


def _rebuild_fts(con):
    con.execute("DELETE FROM symbols_fts")
    rows = con.execute(
        "SELECT s.id, s.name, s.qualified, s.doc, s.signature, f.path FROM symbols s JOIN files f ON f.id = s.file_id")
    batch = []
    for r in rows:
        terms = " ".join(split_identifier(r["name"]) + [r["name"]])
        sig_words = " ".join(split_identifier(r["signature"] or ""))
        path_words = " ".join(split_identifier(r["path"]))
        batch.append((r["id"], terms, r["qualified"], path_words, f"{r['doc'] or ''} {sig_words}"))
    con.executemany("INSERT INTO symbols_fts(rowid, terms, qualified, path, doc) VALUES (?,?,?,?,?)", batch)


def _count_refs(con):
    """Lexical usage: in how many other files does a type-like symbol name appear."""
    from collections import defaultdict
    files_by_name = defaultdict(set)
    for fid, name in con.execute("SELECT file_id, name FROM idents"):
        files_by_name[name].add(fid)
    updates = []
    for sid, name, fid in con.execute(
            "SELECT id, name, file_id FROM symbols WHERE kind IN "
            "('class','interface','struct','record','enum','type','function','method')"):
        short = name.split(".")[-1]
        n = len(files_by_name.get(short, set()) - {fid})
        updates.append((n, sid))
    con.executemany("UPDATE symbols SET refs = ? WHERE id = ?", updates)
