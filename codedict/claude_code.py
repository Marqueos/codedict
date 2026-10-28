"""Claude Code integration: `codedict setup` installs global hooks, `codedict hook` runs them.

- SessionStart / after Edit|Write: (re)index the git project in the background. No tokens.
- UserPromptSubmit: search the index with the prompt and hand the result to the model with the prompt,
  so a code question is answered in 1 turn instead of 2 (search call + answer).
Any other agent gets the same context with `codedict search "<question>"` (CLI) or `code_search` (MCP).
"""
import json
import re
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

from .query import relevant, search_text
from .render_ai import AGENT_SNIPPET
from .store import connect

START, END = "<!-- codedict:start -->", "<!-- codedict:end -->"

MARK = "-m codedict hook"
BUDGET = 3000  # tokens of context per prompt; the measured answers needed 1.3-1.9K
HEADER = ("codedict (code index of this repo) found this for the prompt: file:line, callers, caller chain, "
          "calls and code of the top hits. If it answers the question, answer from it: no grep, no file reads. "
          "Need more code? Pass every name to ONE call: `codedict show A B C`.")
EVENTS = {"SessionStart": None, "UserPromptSubmit": None, "PostToolUse": "Edit|Write|MultiEdit|NotebookEdit"}


def command() -> str:
    """How the agent's shell reaches codedict: the bare name when it is on PATH, else the full path.
    pip often installs scripts outside PATH; then every `codedict ...` call fails and the agent falls back to grep."""
    if shutil.which("codedict"):
        return "codedict"
    exe = shutil.which("codedict", path=sysconfig.get_path("scripts"))
    if not exe:
        return "codedict"
    p = Path(exe).as_posix()
    return f'"{p}"' if " " in p else p  # "C:/Users/Joao Silva/...": quoted, as Bash needs it


def with_command(text: str, cmd: str) -> str:
    return text.replace("`codedict ", f"`{cmd} ")


def permissions(cmd: str) -> list[str]:
    return [f"Bash({c}:*)" for c in dict.fromkeys(["codedict", cmd])] + \
           [f"PowerShell({c} *)" for c in dict.fromkeys(["codedict", cmd])]


def _git_top(cwd: str) -> Path | None:
    try:
        out = subprocess.run(["git", "-C", cwd, "rev-parse", "--show-toplevel"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return Path(out.stdout.strip()) if out.returncode == 0 and out.stdout.strip() else None


def _index_root(cwd: str) -> Path | None:
    p = Path(cwd).resolve()
    for d in (p, *p.parents):
        if (d / ".codedict" / "index.db").exists():
            return d
    return None


def _index_in_background(root: Path):
    # ponytail: two sessions saving at once may race on SQLite; the next run catches up
    flags = (subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP) if sys.platform == "win32" else 0
    subprocess.Popen([sys.executable, "-m", "codedict", "index", str(root)], cwd=root, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags,
                     start_new_session=sys.platform != "win32")


def hook(event: dict) -> str:
    """Handle one Claude Code hook event (the JSON Claude Code sends on stdin). Returns text for the model."""
    cwd = event.get("cwd") or "."
    name = event.get("hook_event_name")
    if name in ("SessionStart", "PostToolUse"):
        root = _index_root(cwd) or (_git_top(cwd) if name == "SessionStart" else None)
        if root:
            _index_in_background(root)
        return ""
    if name == "UserPromptSubmit":
        prompt = (event.get("prompt") or "").strip()
        root = _index_root(cwd)
        if not root or not prompt or prompt.startswith("/"):
            return ""
        con = connect(root)
        try:
            if not relevant(con, prompt):
                return ""
            return with_command(HEADER, command()) + "\n" + search_text(con, prompt, root=root, budget=BUDGET)
        finally:
            con.close()
    return ""


def run_hook() -> None:
    """Entry point for `codedict hook`. Never blocks the prompt: any error means no context."""
    try:
        out = hook(json.loads(sys.stdin.buffer.read().decode("utf-8") or "{}"))
    except Exception:  # noqa: BLE001 - a broken index must not break the user's prompt
        out = ""
    if out:
        sys.stdout.buffer.write(out.encode("utf-8"))


def setup(settings: Path, remove: bool = False) -> str:
    """Add (or remove) the codedict hooks and permissions in a Claude Code settings.json. Idempotent."""
    data = json.loads(settings.read_text(encoding="utf-8-sig")) if settings.exists() else {}
    if settings.exists():
        settings.with_name(settings.name + ".codedict-bak").write_text(settings.read_text(encoding="utf-8-sig"), encoding="utf-8")
    cmd = f'"{Path(sys.executable).as_posix()}" {MARK}'
    hooks = data.setdefault("hooks", {})
    for event, matcher in EVENTS.items():
        kept = [h for h in hooks.get(event, []) if MARK not in json.dumps(h)]
        if not remove:
            entry = {"hooks": [{"type": "command", "command": cmd, "timeout": 30}]}
            kept.append({"matcher": matcher, **entry} if matcher else entry)
        if kept:
            hooks[event] = kept
        else:
            hooks.pop(event, None)
    if not hooks:
        data.pop("hooks")
    cmd = command()
    allow = data.setdefault("permissions", {}).setdefault("allow", [])
    ours = re.compile(r"^(Bash|PowerShell)\(\S*codedict(\.exe)?(:\*| \*)\)$")  # also drops rules of an older install path
    allow[:] = [a for a in allow if not ours.match(a)] + ([] if remove else permissions(cmd))
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    memory = settings.parent / "CLAUDE.md"
    _memory(memory, remove, cmd)
    note = "" if remove or cmd == "codedict" else f"\n`codedict` is not on PATH; the agent will call {cmd}"
    return f"codedict {'removed from' if remove else 'installed in'} {settings} and {memory}{note}"


def _memory(path: Path, remove: bool, cmd: str = "codedict"):
    """The hook's context is trusted only with a standing instruction: keep the snippet in the global CLAUDE.md."""
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    text = re.sub(rf"\n*{re.escape(START)}.*?{re.escape(END)}\n?", "\n", text, flags=re.S).strip("\n")
    if not remove:
        text = (text + "\n\n" if text else "") + f"{START}\n{with_command(AGENT_SNIPPET, cmd).strip()}\n{END}"
    if text or path.exists():
        path.write_text(text + "\n" if text else "", encoding="utf-8")
