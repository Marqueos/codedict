# Benchmark: does codedict save tokens in Claude Code?

This document shows how we measured and what we found. The scripts are in `bench/`.

## Why the number of turns decides

In a Claude Code session, every turn re-reads the whole context. We measured 35 to 50 thousand tokens per turn: the prompt, the tools and the skills. What the tools return weighs little, 30 to 1,000 tokens.

So codedict only saves tokens when it **cuts the number of turns**. The search has to answer in one go, without the session re-checking everything with grep afterwards.

## Fair-test rules

They come from our own mistakes (see "Lessons").

1. Use two identical copies of the project. Only copy **B** has `.codedict/` and the `codedict agent-snippet` text in `CLAUDE.md`.
2. Neither copy may have Claude memory, manual notes or its own `CLAUDE.md`.
3. No file with the answers may sit inside the copies (answer keys, evaluation reports).
4. Keep the same prompt, the same allowed tools (read-only) and the same model.
5. Run 3 repetitions per task and report the median. The same task varied up to 45% between runs.
6. An answer counts as correct when it names the expected symbols and files. This check is automatic.

## How to run

```bash
# 1. Zero-token check: does the first search already answer? (seconds, no LLM)
python bench/answerability.py <project-B> <cases.json>

# 2. A/B with real Claude Code sessions (spends tokens; resumes where it stopped)
python bench/ab_test.py --a <project-A> --b <project-B> --tasks bench/tasks.example.json --reps 3
```

Run the zero-token check on every change. Run the A/B only to confirm, with few tasks.

## Results

A real private project with about 250 files in TypeScript, C# and Python. Claude Code's default model, October 2026.

### Default install (`codedict setup`): the answer arrives with the question

Here the codedict side uses what `codedict setup` installs:
- the hook, which searches the index with the user's prompt and hands the result to the AI with it;
- the instruction in `CLAUDE.md`.

So the session can answer without calling any tool. 3 runs per task on each side (medians):

| Task | Without codedict | With codedict + hook | Savings |
|---|---|---|---|
| Short search 1 | 129,319 | 41,095 (1 turn in all 3 runs) | 68% |
| Short search 2 | 223,653 | 94,248 | 58% |
| Flow 2 | 641,467 | 162,121 | 75% |
| Flow 1 | 500,132 | 213,523 | 57% |
| **Median per task** | | | **63%** |

| Measure (12 runs per side) | Without codedict | With codedict + hook | Difference |
|---|---|---|---|
| Tokens | 4,543,176 | 1,666,033 | −63% |
| Cost | US$ 5.76 | US$ 4.27 | −26% |
| Turns | 138 | 34 | −75% |
| Correct answers | 12/12 | 12/12 | = |

- **1 turn.** Short search 1 was answered in 1 turn in all 3 runs, with about 41 thousand tokens. That is below the ~85 thousand floor, because the search no longer costs a turn.
- **Flow 1: from 29% to 57%.** The question used a noun ("exclusão", Portuguese for "deletion") and the code used the verb (`Excluir...`). The search now reduces Portuguese nouns to their stem (-ção, -são, -mento: "exclusão" becomes `exclu*`, "geração" becomes `gera*`), so the C# side of the flow enters the hook context. The 3 Flow 1 runs in the table come after this fix; before it, the median was 356 thousand.
- **Flow 1 is still the most expensive task.** The flow crosses C# and TypeScript, and the session still opens a few files (4 to 6 turns).
- **The hook alone is not enough.** Without the instruction in `CLAUDE.md`, the session got the context and still re-checked everything with grep: 4 turns and 189 thousand tokens. The instruction says the context comes from a complete index, and that is what makes the session trust it. That is why `codedict setup` writes both.

### Short tasks: "where is X and who calls it" (instruction only, no hook)

10 tasks, 3 runs on each side.

| Measure | Without codedict | With codedict | Difference |
|---|---|---|---|
| Tokens | 6,357,798 | 3,108,274 | −51% |
| Median savings per task | | | 51.5% |
| Cost | US$ 9.79 | US$ 8.04 | −18% |
| Time | 522 s | 329 s | −37% |
| Turns | 147 | 72 | −51% |
| Correct answers | 30/30 | 30/30 | = |

After this main round we fixed call resolution in C#. codedict now follows inheritance, `partial class`, declared variable types and overloads. The search now shows the code of the best hit and the constants it uses.

We re-ran only the two C# tasks, which still took 3 to 5 turns, with 1 run each:

| Task | Without codedict (median of 3) | With codedict (1 run) |
|---|---|---|
| C# task 1 | 186 thousand | 88 thousand (2 turns) |
| C# task 2 | 186 thousand | 85 thousand (2 turns) |

### Flow tasks: "explain the chain from the click to the result" (instruction only, no hook)

2 tasks. The first measurement had 1 run on each side.

| Measure | Without codedict | With codedict | Difference |
|---|---|---|---|
| Tokens | 1,230,840 | 795,156 | −35% |
| Cost | US$ 1.46 | US$ 1.00 | −32% |
| Turns | 40 | 17 | −58% |
| Correct answers | 2/2 | 2/2 | = |

The savings here were **lower** than on short tasks. `search` showed only one level of callers; to build the chain up to the entry point, the session went back to grep.

**After the fix.** For the top 3 hits, `search` now shows:
- `caller chain`: who calls it, up to 3 levels up;
- `calls`: what the symbol calls;
- `runs`: the `npm run X` bridge that links the C# app to the TypeScript script;
- the code of each one.

`codedict show` also accepts several names in one call. After the fix we ran 3 runs per task on each side (medians):

| Task | Without codedict | With codedict | Savings |
|---|---|---|---|
| Flow 1 | 500,132 | 266,187 | 47% |
| Flow 2 | 641,467 | 199,981 | 69% |
| **Median per task** | | | **57.8%** |

| Measure (6 runs per side) | Without codedict | With codedict | Difference |
|---|---|---|---|
| Tokens | 3,484,535 | 1,672,639 | −52% |
| Cost | US$ 4.02 | US$ 2.67 | −34% |
| Turns | 114 | 33 | −71% |
| Time | 340 s | 228 s | −33% |
| Correct answers | 6/6 | 6/6 | = |

Runs varied a lot: the codedict side ranged from 146 thousand to 403 thousand tokens on the same task.

With the same version, two short tasks stayed at 2 turns: 224 thousand → 88 thousand (61%) and 131 thousand → 85 thousand (35%). The larger `search` output did not hurt short tasks.

### Summary

| Kind of task | Token savings | How it was measured |
|---|---|---|
| Default install with hook (flows + searches) | median 63%, −63% total | 4 tasks × 3 runs |
| Flow ("explain the chain") | median 57.8% (47% and 69%), −52% total | 2 tasks × 3 runs |
| Short search ("where is X") | median 51.5%, −51% total | 10 tasks × 3 runs (main round) |

Without the hook, short searches already take the minimum possible, 2 turns. Savings hit the fixed session cost: at about 85 thousand tokens per answer, a task that costs 130 thousand without an index cannot save more than 35%. The hook breaks that floor by answering in 1 turn.

### Zero-token check

The 17 searches typed by the real sessions were run through `answerability.py`:
- Result: 17/17 answer in a single call.
- With the caller list hidden on purpose, it drops to 0/17. This shows the check catches regressions.

### Other languages: public projects (no tokens, anyone can reproduce)

To avoid relying on a private project, we ran the zero-token check on two open-source projects. The questions are in natural language, the way a person would type them, and live in `bench/public/`.

| Project | Language | Commit | Result |
|---|---|---|---|
| [psf/requests](https://github.com/psf/requests) | Python | `3c7baaa` | 3/4 answered in one search |
| [spf13/cobra](https://github.com/spf13/cobra) | Go | `adbc881` | 3/3 answered in one search |

```bash
git clone https://github.com/spf13/cobra && git -C cobra checkout adbc881
codedict index cobra
python bench/answerability.py cobra bench/public/cobra.json
```

What fails: in `requests`, the flow from `requests.get` to `HTTPAdapter.send` does not fit in one search. The session still needs one `codedict show`.

Before the generic fixes of this stage, Go scored 1/3. The fixes apply to every language:
- **Methods outside the type:** in Go, `func (c *Command) Run()` now becomes `Command.Run`. This tripled the high-confidence links (480 → 1,460).
- **Tests ranked lower:** test functions no longer take the top of the search unless the question is about tests.
- **Downward call chain** (`call chain`): for "from X to Y" questions, it follows what X calls, favoring names mentioned in the question.
- **Inflections:** "parsed" also finds `ParseFlags`, and "exclusão" finds `Excluir...`.

Nothing got worse on the private project: 22/22 searches and 100% of the answer-key calls. One answer-key search moved from 1st to 2nd place.

## Limits

- **Fixed cost.** About 37 thousand tokens per turn belong to Claude Code, not to the search. With 2 turns, a session still costs about 85 thousand tokens. On tasks that already take 3 turns without an index, the most you can save is about 33%.
- **Cost falls less than tokens (−26% vs −63% with the hook).** Writing the context to the cache, which is the fixed part, is the most expensive kind of token.
- **Automatic grading.** "Correct" means the answer names the expected symbols. A human read of a sample found no errors, but the check is not exhaustive.

## Lessons (mistakes that invalidated earlier rounds)

- **Answer files in the folder.** `gold.toml` and the evaluation report were inside the tested project, and in 8 of 20 sessions grep found the answers. The round was thrown out.
- **Memory vs. index.** Comparing a session with memory and no index against one with an index and no memory measures two things at once. That round's cost savings came almost entirely from the smaller memory.
- **Different permissions.** Allowing `codedict` only through Bash made sessions that tried PowerShell lose turns. Both sides now get the same list.
- **Command not on PATH.** In the middle of the hook round, `codedict` dropped off PATH. In 6 of 12 sessions the call returned "command not found", the session fell back to grep, and the median dropped to 52%. `codedict setup` now writes the full path of the executable when it is not on PATH. Those 6 sessions were thrown out and re-run.
- **One run is not enough.** With n = 1, run-to-run noise hid the effect of two fixes.
