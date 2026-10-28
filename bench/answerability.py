"""Zero-token check: does the first `codedict search` already answer the question?

A Claude Code session spends tokens per turn (each turn re-reads the whole context), so codedict
saves tokens when ONE search is enough. This check runs the searches real sessions typed and passes when:
  1. an expected symbol is in the top 3 hits (the ones printed with signature and call sites), and
  2. the call sites listed ("called at" + "unlinked same-name calls") cover every file grep finds.

No LLM, no tokens, runs in about a second.

Usage: python bench/answerability.py <indexed project> <cases.json>
cases.json: [{"name": "...", "expect": "Owner.method|Other.method", "queries": ["..."],
              "call_regex": "optional grep regex for call sites", "only_dir": "optional path prefix",
              "mentions": ["optional: names that must all appear in the output (flow questions)"]}]
"""
import json
import re
import subprocess
import sys
from pathlib import Path

from codedict.query import search_text
from codedict.store import connect

CODE_EXT = (".ts", ".tsx", ".js", ".py", ".cs", ".java", ".go")
COMMENT = ("//", "#", "*", "/*")


def grep_files(root: Path, pattern: str, definition: str, only_dir: str | None) -> set[str]:
    rx = re.compile(pattern)
    files = subprocess.run(["git", "-C", str(root), "ls-files", "-co", "--exclude-standard"],
                           capture_output=True, text=True, check=True).stdout.splitlines()
    hits = set()
    for rel in files:
        if not rel.endswith(CODE_EXT) or (only_dir and not rel.startswith(only_dir)):
            continue
        for i, line in enumerate((root / rel).read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if line.lstrip().startswith(COMMENT) or f"{rel}:{i}" == definition:
                continue
            if rx.search(line) and not re.search(r"\b(function|def|void|async)\b", line):  # skip definitions
                hits.add(rel)
    return hits


def listed_files(block: list[str]) -> set[str]:
    files = set()
    for line in block:
        m = re.match(r"\s+(called at|unlinked same-name calls): (.*)", line)
        if m:
            files |= {p.split(":")[0] for p in re.findall(r"[\w./-]+\.\w+:[\d,]+", m.group(2))}
    return files


def check(con, root: Path, case: dict, query: str) -> str | None:
    """None when the search answers the question, else the reason it does not."""
    out = search_text(con, query, root=root).splitlines()
    text = "\n".join(out)
    absent = [m for m in case.get("mentions", []) if m not in text]
    if absent:  # flow questions: every step of the chain must already be in this one output
        return f"output lacks {absent}"
    heads = [i for i, line in enumerate(out) if line.startswith("#")]
    wanted = case["expect"].split("|")
    for rank, i in enumerate(heads[:3], 1):
        found = next((e for e in wanted if f"{e}`" in out[i]), None)
        if found is None:
            continue
        end = heads[rank] if rank < len(heads) else len(out)
        m = re.search(r"` ([\w./-]+):(\d+)-", out[i])
        definition = f"{m.group(1)}:{m.group(2)}" if m else ""
        name = found.split(".")[-1]
        pattern = case.get("call_regex") or rf"(?<![\w]){re.escape(name)}\s*\("
        if "|" in case["expect"]:  # several accepted answers: grep the one that was found
            pattern = rf"\b{re.escape(found)}\s*\(" if "." in found else pattern
        missing = grep_files(root, pattern, definition, case.get("only_dir")) - listed_files(out[i + 1:end])
        return f"top {rank}, missing callers {sorted(missing)}" if missing else None
    return f"{case['expect']} not in top 3"


def main(root: Path, cases_file: Path) -> int:
    con = connect(root)
    cases = json.loads(cases_file.read_text(encoding="utf-8"))
    failures = 0
    for case in cases:
        for q in case["queries"]:
            why = check(con, root, case, q)
            failures += why is not None
            print(f"{'FAIL' if why else 'ok  '}  {case['name']:18} '{q}'" + (f": {why}" if why else ""))
    total = sum(len(c["queries"]) for c in cases)
    print(f"\n{total - failures}/{total} searches answer the question in one call")
    return 1 if failures else 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    sys.exit(main(Path(sys.argv[1]).resolve(), Path(sys.argv[2])))
