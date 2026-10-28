"""A/B token benchmark: Claude Code headless sessions with and without codedict.

Fair-test rules (see BENCHMARK.md):
  - A and B are two copies of the same code; only B has `.codedict/` and the codedict snippet in CLAUDE.md.
  - Neither copy has Claude memory, notes, or files that contain the answers.
  - Same prompt, same tool allowlist, same model on both sides; several repetitions per task.

Usage:
  python bench/ab_test.py --a ../proj-without --b ../proj-with --tasks bench/tasks.example.json --reps 3 --out bench/runs

Each run is saved as <out>/<task>-<side>-r<rep>.json (the `claude -p --output-format json` result).
Re-running skips finished runs and retries failed ones (e.g. after a usage limit).
"""
import argparse
import json
import shutil
import statistics
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# Read-only tools for both sides. `codedict` is allowed on both; side A has no index and no snippet.
from codedict.claude_code import command, permissions

ALLOWED = ["Read", "Grep", "Glob", "Bash(grep:*)", "Bash(rg:*)", "Bash(cat:*)", "Bash(head:*)", "Bash(sed:*)",
           "Bash(ls:*)", "Bash(find:*)", *permissions(command()), "PowerShell(Get-Content *)",
           "PowerShell(Select-String *)", "PowerShell(Get-ChildItem *)"]
DENIED = ["Write", "Edit", "NotebookEdit"]


def run_session(claude: str, prompt: str, cwd: Path, out: Path) -> dict:
    if out.exists():
        old = json.loads(out.read_text(encoding="utf-8-sig"))
        if not old.get("is_error"):
            return old
    cmd = [claude, "-p", prompt, "--output-format", "json", "--disallowedTools", *DENIED, "--allowedTools", *ALLOWED]
    res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8")
    try:
        data = json.loads(res.stdout)
    except json.JSONDecodeError:
        data = {"is_error": True, "result": (res.stdout + res.stderr)[-500:]}
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return data


def tokens(d: dict) -> int:
    u = d.get("usage") or {}
    return sum(u.get(k, 0) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens",
                                     "output_tokens"))


def correct(d: dict, expect: list[str]) -> bool:
    text = d.get("result") or ""
    return all(e in text for e in expect)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--a", required=True, type=Path, help="baseline copy (no codedict)")
    ap.add_argument("--b", required=True, type=Path, help="copy with .codedict/ and the CLAUDE.md snippet")
    ap.add_argument("--tasks", required=True, type=Path)
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--out", type=Path, default=Path("bench/runs"))
    ap.add_argument("--sides", default="AB", help="run only these sides; the other is read from --out (e.g. B after a codedict change)")
    args = ap.parse_args()

    claude = shutil.which("claude")
    if not claude:
        sys.exit("claude CLI not found on PATH")
    if (args.a / ".codedict").exists() or not (args.b / ".codedict").exists():
        sys.exit("--a must NOT have .codedict/, --b must have it (run `codedict index .` in --b)")
    tasks = json.loads(args.tasks.read_text(encoding="utf-8-sig"))
    args.out.mkdir(parents=True, exist_ok=True)
    sides = {"A": args.a.resolve(), "B": args.b.resolve()}

    results = {}  # (task id, side) -> list of run dicts
    with ThreadPoolExecutor(max_workers=2) as pool:  # A and B of the same task run side by side
        for rep in range(1, args.reps + 1):
            for t in tasks:
                futs = {s: pool.submit(run_session, claude, t["prompt"], d, args.out / f"{t['id']}-{s}-r{rep}.json")
                        for s, d in sides.items() if s in args.sides}
                for s in sides:
                    saved = args.out / f"{t['id']}-{s}-r{rep}.json"
                    data = futs[s].result() if s in futs else (
                        json.loads(saved.read_text(encoding="utf-8-sig")) if saved.exists() else {"is_error": True})
                    results.setdefault((t["id"], s), []).append(data)
                print(f"rep {rep} task {t['id']} done", flush=True)

    rows, savings, totals = [], [], {"A": [0, 0.0, 0, 0, 0], "B": [0, 0.0, 0, 0, 0]}
    for t in tasks:
        med = {}
        for s in sides:
            ok_runs = [d for d in results[(t["id"], s)] if not d.get("is_error")]
            med[s] = statistics.median(tokens(d) for d in ok_runs) if ok_runs else None
            tot = totals[s]
            tot[0] += sum(tokens(d) for d in ok_runs)
            tot[1] += sum(d.get("total_cost_usd", 0) for d in ok_runs)
            tot[2] += sum(d.get("num_turns", 0) for d in ok_runs)
            tot[3] += sum(correct(d, t["expect"]) for d in ok_runs)
            tot[4] += len(ok_runs)
        save = 1 - med["B"] / med["A"] if med["A"] and med["B"] else None
        if save is not None:
            savings.append(save)
        fmt = lambda v: f"{int(v):,}" if v else "-"
        rows.append(f"| {t['id']} | {fmt(med['A'])} | {fmt(med['B'])} | " + (f"{save:.0%}" if save is not None else "-") + " |")

    print("\n| task | median tokens A (no codedict) | median tokens B (codedict) | saving |\n|---|---|---|---|")
    print("\n".join(rows))
    for s, (tok, usd, turns, ok, n) in totals.items():
        print(f"{s}: runs {n} | tokens {tok:,} | cost US$ {usd:.2f} | turns {turns} | correct {ok}/{n}")
    if savings:
        print(f"median per-task saving: {statistics.median(savings):.1%} (n={len(savings)} tasks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
