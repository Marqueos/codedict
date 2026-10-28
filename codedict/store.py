"""SQLite storage: one .codedict/index.db per project. Source of truth for both renderers."""
import sqlite3
from pathlib import Path

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS files (
  id INTEGER PRIMARY KEY, path TEXT UNIQUE NOT NULL, lang TEXT, sha256 TEXT,
  lines INTEGER, meta TEXT);
CREATE TABLE IF NOT EXISTS symbols (
  id INTEGER PRIMARY KEY, file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  parent_id INTEGER, kind TEXT, name TEXT, qualified TEXT, start_line INTEGER, end_line INTEGER,
  signature TEXT, doc TEXT, decorators TEXT, private INTEGER DEFAULT 0, rank REAL DEFAULT 0,
  callers INTEGER DEFAULT 0, refs INTEGER DEFAULT 0, note TEXT);
CREATE INDEX IF NOT EXISTS ix_sym_name ON symbols(name);
CREATE INDEX IF NOT EXISTS ix_sym_file ON symbols(file_id);
CREATE INDEX IF NOT EXISTS ix_sym_qual ON symbols(qualified);
CREATE TABLE IF NOT EXISTS calls (
  id INTEGER PRIMARY KEY, file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  src_id INTEGER, name TEXT, receiver TEXT, line INTEGER, dst_id INTEGER, confidence TEXT);
CREATE INDEX IF NOT EXISTS ix_calls_src ON calls(src_id);
CREATE INDEX IF NOT EXISTS ix_calls_dst ON calls(dst_id);
CREATE TABLE IF NOT EXISTS imports (
  file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE, text TEXT);
CREATE INDEX IF NOT EXISTS ix_imp_file ON imports(file_id);
CREATE TABLE IF NOT EXISTS routes (
  file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE, symbol_id INTEGER,
  method TEXT, path TEXT, handler TEXT);
CREATE TABLE IF NOT EXISTS sql_refs (
  file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE, symbol_id INTEGER,
  table_name TEXT, op TEXT);
CREATE TABLE IF NOT EXISTS idents (
  file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE, name TEXT);
CREATE TABLE IF NOT EXISTS notes (
  qualified TEXT PRIMARY KEY, note TEXT);
CREATE INDEX IF NOT EXISTS ix_calls_file ON calls(file_id);
CREATE INDEX IF NOT EXISTS ix_routes_file ON routes(file_id);
CREATE INDEX IF NOT EXISTS ix_sql_file ON sql_refs(file_id);
CREATE INDEX IF NOT EXISTS ix_sym_parent ON symbols(parent_id);
CREATE INDEX IF NOT EXISTS ix_idents_file ON idents(file_id);
CREATE VIRTUAL TABLE IF NOT EXISTS symbols_fts USING fts5(
  terms, qualified, path, doc, tokenize = 'unicode61 remove_diacritics 2');
"""


def db_path(root: Path) -> Path:
    return root / ".codedict" / "index.db"


def connect(root: Path, create: bool = False) -> sqlite3.Connection:
    path = db_path(root)
    if not path.exists() and not create:
        raise SystemExit(f"No index at {path}. Run: codedict index {root}")
    path.parent.mkdir(parents=True, exist_ok=True)
    ignore = path.parent / ".gitignore"
    if not ignore.exists():  # git ignores the index by itself: no edit to the project's own .gitignore
        ignore.write_text("*\n", encoding="utf-8")
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con
