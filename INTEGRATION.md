# Using codedict with your codebase and your AI

codedict does not depend on any AI. It reads your code once, stores a local index (SQLite) and answers questions about the code: where something is, who calls it, the path from one call to another, and the code itself. It is the retrieval step of a RAG, but exact, and it costs no tokens to build.

The same index produces two dictionaries:

| For | Where | What it has |
|---|---|---|
| The AI | `.codedict/ai/` + `codedict search` | A compact map of the project and ready answers per question |
| People | `.codedict/docs/README.md` | A Markdown manual with Mermaid diagrams: modules, routes, tables and who calls whom |

The index lives in `.codedict/`. That folder ships with its own `.gitignore`, so git ignores it without touching your project's `.gitignore`.

## 1. Install (one line, once per machine)

Windows (PowerShell):

```powershell
irm https://raw.githubusercontent.com/Marqueos/codedict/main/install.ps1 | iex
```

macOS / Linux:

```bash
curl -fsSL https://raw.githubusercontent.com/Marqueos/codedict/main/install.sh | sh
```

The installer:
- checks for Python 3.11+;
- creates its own folder in `~/.codedict`, with no admin rights and no PATH changes;
- installs codedict there;
- turns codedict on in Claude Code (step 2).

To update, run the same line again.

Manual install, if you prefer: `pip install git+https://github.com/Marqueos/codedict`, then `python -m codedict setup`.

## 2. Claude Code: on by default

The installer already does this step. After a manual install, run `python -m codedict setup`. It applies to every project. The command writes three hooks to the global Claude Code settings (`~/.claude/settings.json`) and a short instruction to the global memory (`~/.claude/CLAUDE.md`).

| When | What happens | Token cost |
|---|---|---|
| A session opens in a git repository | Indexes the project in the background (only what changed) | Zero |
| After each AI edit | Updates the index in the background | Zero |
| You send a prompt | If the prompt is about the code, the index answer goes to the AI with it | ~1,500 to 2,000 per code question; zero otherwise |

If `codedict` is not on PATH, `setup` writes the full path of the executable into the instruction and the permissions, so the AI does not waste turns on "command not found".

Prompts that are not about code ("thanks", "commit this") get nothing. Prompts that start with `/` get nothing either.

To undo everything: `~/.codedict/venv/bin/python -m codedict setup --remove` (Windows: `~\.codedict\venv\Scripts\python.exe -m codedict setup --remove`), then delete the `~/.codedict` folder. Your other settings and notes stay intact, and the previous file is kept as `settings.json.codedict-bak`.

## 3. Other AIs with tool access (Cursor, Codex, Gemini CLI, OpenCode, Windsurf)

All of them accept MCP servers. First install the MCP extra into the codedict folder:

```bash
~/.codedict/venv/bin/python -m pip install "codedict[mcp] @ git+https://github.com/Marqueos/codedict"
```

Then register codedict, pointing at the project. The installer prints the full path of the `codedict` command at the end; use it if `codedict` is not on PATH:

```json
{
  "mcpServers": {
    "codedict": { "command": "codedict", "args": ["--root", "/path/to/project", "mcp"] }
  }
}
```

The file name changes from tool to tool (`.cursor/mcp.json`, `~/.codex/config.toml`, `~/.gemini/settings.json`…). The content is always this command.

Then put the instruction in the rules file the tool reads. Codex, Cursor and OpenCode read `AGENTS.md`:

```bash
codedict index .
codedict agent-snippet >> AGENTS.md
```

Without hooks, keep the index fresh with a git hook:

```bash
# .git/hooks/post-commit
codedict index . >/dev/null 2>&1 &
```

## 4. Any model, including local ones (RAG mode)

For any LLM, even a local model behind Ollama or LiteLLM with no tool support: fetch the context and put it in the prompt.

```bash
codedict search "where is the discount calculated?" --budget 2000
```

`--budget` caps the output in tokens, so it fits models with a small context. Python example with any OpenAI-compatible API:

```python
import subprocess
from openai import OpenAI

question = "Where is the discount calculated, and who calls it?"
context = subprocess.run(["codedict", "--root", "/path/to/project", "search", question, "--budget", "2000"],
                         capture_output=True, text=True).stdout

client = OpenAI(base_url="http://localhost:11434/v1", api_key="local")  # Ollama, LiteLLM, OpenAI...
answer = client.chat.completions.create(model="qwen2.5-coder", messages=[
    {"role": "system", "content": "Answer only from the code index context."},
    {"role": "user", "content": f"{context}\n\nQuestion: {question}"},
])
print(answer.choices[0].message.content)
```

As a library, with no subprocess:

```python
from pathlib import Path
from codedict.store import connect
from codedict.query import search_text

root = Path("/path/to/project")
context = search_text(connect(root), "where is the discount calculated?", root=root, budget=2000)
```

## 5. Languages

Python, JavaScript, TypeScript/TSX, C#, Java, Go, SQL and Razor work out of the box. For another language, copy a `.toml` from `codedict/languages/` to the project's `.codedict/languages/` and adjust:

- `[kinds]`: which grammar nodes are classes, functions and methods. Grammars come from `tree-sitter-language-pack`, which has more than 160 languages.
- `[calls]`: which node is a call.
- `[types]`: how the language declares a variable's type, for example `repo: OrderRepo`. This links `repo.save()` to the right class.
- `[methods]`: only when methods live outside the type, as in Go (`func (c *Command) Run()`).

## 6. Check that it works on your project, with no tokens

```bash
python bench/answerability.py <project> <cases.json>
```

The script runs your questions and tells you whether the first search already returns the answer and every call site grep would find. See the examples in `bench/public/` and the full method in [BENCHMARK.md](BENCHMARK.md).
