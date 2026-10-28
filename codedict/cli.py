"""codedict CLI."""
import argparse
import json
import signal
import sys
from pathlib import Path

from . import __version__
from .indexer import index_project
from .query import callees_text, callers_text, find_symbols, group_modules, routes_text, search_text, show_text, tables_text
from .render_ai import AGENT_SNIPPET, module_map, overview, write_ai
from .render_human import write_docs
from .store import connect


def _root(args) -> Path:
    p = Path(args.root).resolve()
    while not (p / ".codedict" / "index.db").exists() and p.parent != p and args.cmd != "index":
        p = p.parent
    return p if (p / ".codedict").exists() or args.cmd == "index" else Path(args.root).resolve()


def main(argv=None):
    ap = argparse.ArgumentParser(prog="codedict", description="Deterministic code dictionary for LLMs and developers.")
    ap.add_argument("--root", default=".", help="project root (default: current dir)")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("index", help="index/update the project and regenerate outputs")
    p.add_argument("path", nargs="?", default=None)
    p.add_argument("--rebuild", action="store_true")
    p.add_argument("--no-ai", action="store_true", help="skip .codedict/ai output")
    p.add_argument("--no-docs", action="store_true", help="skip .codedict/docs output")
    p.add_argument("--budget", type=int, default=3000, help="token budget for ai/INDEX.md")
    p.add_argument("--docs-lang", default="en", choices=["en", "pt"])
    p.add_argument("--docs-out", default=None, help="human docs folder (default .codedict/docs)")

    sub.add_parser("overview", help="L0 overview for an LLM").add_argument("--budget", type=int, default=3000)
    sub.add_parser("modules", help="list module groups")
    p = sub.add_parser("map", help="L1 map of one module")
    p.add_argument("module")
    p.add_argument("--full", action="store_true", help="include properties")
    p = sub.add_parser("search", help="find symbols by words (name, path, doc)")
    p.add_argument("query")
    p.add_argument("-n", type=int, default=10)
    p.add_argument("--budget", type=int, default=None, help="cap the output at about N tokens (for small LLM contexts)")
    p = sub.add_parser("show", help="symbol card + exact source lines")
    p.add_argument("name", nargs="+", help="one or more names: one call, one turn")
    p.add_argument("--no-source", action="store_true")
    p.add_argument("--max-lines", type=int, default=200)
    for name in ("callers", "callees"):
        sub.add_parser(name, help=f"{name} of a symbol").add_argument("name")
    sub.add_parser("routes", help="HTTP routes / pages").add_argument("filter", nargs="?", default="")
    sub.add_parser("tables", help="SQL tables and who uses them").add_argument("filter", nargs="?", default="")
    p = sub.add_parser("note", help="attach a manual note to a symbol (survives reindex)")
    p.add_argument("name")
    p.add_argument("text")
    p = sub.add_parser("eval", help="score the index against a gold file (TOML)")
    p.add_argument("gold")
    p = sub.add_parser("audit", help="random sample for manual precision/recall check")
    p.add_argument("kind", choices=["calls", "missed"])
    p.add_argument("-n", type=int, default=30)
    p.add_argument("--confidence", choices=["high", "medium", "low"])
    p.add_argument("--seed", type=int, default=1)
    sub.add_parser("stats", help="index statistics")
    sub.add_parser("agent-snippet", help="print instructions to paste into CLAUDE.md / AGENTS.md")
    sub.add_parser("mcp", help="run MCP server over stdio (needs: pip install mcp)")
    p = sub.add_parser("setup", help="Claude Code: install global hooks (auto index + context on every prompt)")
    p.add_argument("--settings", default=str(Path.home() / ".claude" / "settings.json"))
    p.add_argument("--remove", action="store_true", help="uninstall the hooks")
    sub.add_parser("hook", help="internal: called by Claude Code hooks (JSON on stdin)")

    args = ap.parse_args(argv)
    if args.cmd in ("setup", "hook"):
        from .claude_code import run_hook, setup
        print(setup(Path(args.settings), args.remove)) if args.cmd == "setup" else run_hook()
        return
    if args.cmd == "index" and args.path:
        args.root = args.path
    root = _root(args)
    if hasattr(signal, "SIGPIPE"):
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)  # allow `codedict ... | head`
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if args.cmd == "index":
        summary = index_project(root, rebuild=args.rebuild)
        fresh = summary["changed"] or summary["removed"] or args.rebuild
        con = connect(root)
        if not fresh and (root / ".codedict" / "ai" / "INDEX.md").exists():
            args.no_ai = args.no_ai or True
        if not fresh and (Path(args.docs_out) if args.docs_out else root / ".codedict" / "docs" / "README.md").exists():
            args.no_docs = True
        if not args.no_ai:
            write_ai(con, root, args.budget)
        if not args.no_docs:
            write_docs(con, root, Path(args.docs_out) if args.docs_out else None, args.docs_lang)
        con.close()
        print(json.dumps(summary, indent=2))
        return
    if args.cmd == "agent-snippet":
        print(AGENT_SNIPPET)
        return
    if args.cmd == "mcp":
        from .mcp_server import run
        run(root)
        return
    con = connect(root)
    if args.cmd == "overview":
        print(overview(con, args.budget))
    elif args.cmd == "modules":
        for label, files in group_modules(con).items():
            print(f"{label}  ({len(files)} files)")
    elif args.cmd == "map":
        print(module_map(con, args.module, args.full))
    elif args.cmd == "search":
        print(search_text(con, args.query, args.n, root=root, budget=args.budget))
    elif args.cmd == "show":
        print("\n\n".join(show_text(con, root, n, not args.no_source, args.max_lines) for n in args.name))
    elif args.cmd == "callers":
        print(callers_text(con, args.name))
    elif args.cmd == "callees":
        print(callees_text(con, args.name))
    elif args.cmd == "routes":
        print(routes_text(con, args.filter))
    elif args.cmd == "tables":
        print(tables_text(con, args.filter))
    elif args.cmd == "note":
        rows = find_symbols(con, args.name)
        if len(rows) != 1:
            print("Need exactly one match; use the qualified name or #id." if rows else "Not found.")
            return
        con.execute("INSERT OR REPLACE INTO notes VALUES (?, ?)", (rows[0]["qualified"], args.text))
        con.commit()
        print(f"note saved on {rows[0]['qualified']}")
    elif args.cmd == "eval":
        from .evaluate import run_eval
        print(run_eval(con, root, Path(args.gold)))
    elif args.cmd == "audit":
        from .evaluate import audit
        print(audit(con, root, args.kind, args.n, args.confidence, args.seed))
    elif args.cmd == "stats":
        q = lambda sql: con.execute(sql).fetchall()
        print("files by lang:", dict(q("SELECT lang, COUNT(*) FROM files GROUP BY lang")))
        print("symbols by kind:", dict(q("SELECT kind, COUNT(*) FROM symbols GROUP BY kind")))
        print("calls by confidence:", dict(q("SELECT COALESCE(confidence,'?'), COUNT(*) FROM calls GROUP BY 1")))
        print("routes:", q("SELECT COUNT(*) FROM routes")[0][0], "| sql refs:", q("SELECT COUNT(*) FROM sql_refs")[0][0])
        errs = q("SELECT path, meta FROM files WHERE meta LIKE '%\"error\"%'")
        if errs:
            print("parse errors:", [e[0] for e in errs][:20])
    con.close()


if __name__ == "__main__":
    main()
