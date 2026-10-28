# Quick guide: codedict day to day

## 1. Install (once per machine)

Windows (PowerShell):

```powershell
irm https://raw.githubusercontent.com/Marqueos/codedict/main/install.ps1 | iex
```

macOS / Linux:

```bash
curl -fsSL https://raw.githubusercontent.com/Marqueos/codedict/main/install.sh | sh
```

Requires Python 3.11+. At the end, the installer prints the full path of the `codedict` command. If your terminal does not recognize `codedict`, use that path.

## 2. Turn it on for each project

In Claude Code there is nothing to do: when you open a git repository, it indexes itself and answers from the index.

For other AIs, see [INTEGRATION.md](INTEGRATION.md).

## 3. Keep it fresh

In Claude Code it is automatic: the index updates when the project opens and after each edit.

Outside it, run `codedict index .`. It is incremental and only re-reads what changed. To update on every commit, create `.git/hooks/post-commit` (no extension) with:

```sh
#!/bin/sh
codedict index . >/dev/null 2>&1 &
```

## 4. Use it actively

Agents connected over MCP use the `code_search`, `code_show` and `code_callers` tools on their own. To help them:

- Ask by intent: "where do we validate the tax ID? use codedict before opening files".
- Before changing something: "check with code_callers who uses `OrderService.Save`".
- To learn an area: "read code_module for `src/Billing/` and summarize it".

By hand, in the terminal:

| I want | Command |
|---|---|
| Project overview | `codedict overview` |
| Map of a folder | `codedict map src/Billing/` |
| Find by words | `codedict search "calculate tax"` |
| The exact code | `codedict show TaxCalculator.Calculate` |
| Who calls it / what it calls | `codedict callers X` / `codedict callees X` |
| HTTP routes | `codedict routes api/orders` |
| SQL tables and who uses them | `codedict tables Orders` |

## 5. Teach what the code does not say

If a symbol has no comment, leave a note. It shows up in searches and survives reindexing:

```bash
codedict note TaxCalculator.Calculate "Tax rule: rate depends on the state"
```

Tip: documentation comments (docstrings, `///`) become the description. The more you write, the better the search.

## 6. Docs for people

Generated with the index in `.codedict/docs/README.md` (Markdown + Mermaid diagrams; opens in VS Code or on GitHub). In another folder or in Portuguese:

```bash
codedict index . --docs-out docs/code --docs-lang pt
```

## 7. Check the quality

Copy `EVALUATION.md` to the project root and tell Claude Code: `Run EVALUATION.md`.

## 8. Common problems

| Symptom | Fix |
|---|---|
| `codedict` not found | use the full path the installer printed, or run the installer again |
| Stale results | `codedict index .` |
| A search in another language finds nothing | the code uses other words: search with the code's terms or add a `codedict note` |
| Odd index | `codedict index . --rebuild` (your notes are kept) |
| An unwanted file got indexed | add its pattern to `.codedictignore` at the root |
| New language | copy a `.toml` from `codedict/languages/` to the project's `.codedict/languages/` |
