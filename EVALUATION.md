# codedict evaluation (a task for Claude Code)

Goal: measure whether the `codedict` index of this project is reliable. Run every step in order, without asking for confirmation, and deliver `EVALUATION-RESULT.md` at the root.

## Rules

1. Do not change the `codedict` code during the evaluation. Only measure and report.
2. Build the answer key (step 2) by reading the code with `grep` and direct reads. Never use `codedict search`, `callers` or `routes` to decide the right answer; that would make the test circular.
3. If you cannot verify an item, mark it `?` and leave it out of the math. Never guess.
4. Always report the `n` of each measure. Do not round up.
5. Do not print secrets (`.env`, keys, connection strings) in the result.

## Step 1: index

```bash
codedict index . --rebuild
codedict stats
```

Record: number of files, symbols per kind, calls per confidence, `parse errors`, indexing time.
Then time a reindex with no changes (expected: a few seconds):

```bash
time codedict index .
```

## Step 2: search answer key (`gold.toml`)

Create `gold.toml` with 25 real, varied cases, taken by reading the project without `codedict`:

- 15 `[[search]]` cases: a question as a developer would ask it ("where is the tax ID validated?") and the symbol that is the right answer. Mix languages if the team does, and include cases where the symbol name does not contain the question's words.
- 6 `[[calls]]` cases: `src` → `dst` pairs that really exist (check by opening the file).
- 4 `[[routes]]` cases (web projects): real method and path.

Format:

```toml
[[search]]
query = "where is tax calculated"
expect = "TaxCalculator.Calculate"

[[calls]]
src = "OrdersController.Get"
dst = "OrderService.FindOrder"

[[routes]]
method = "GET"
path = "/api/orders/{id}"
```

```bash
codedict eval gold.toml
```

Record the full output, including the `FAILURES` list.

## Step 3: call precision

For each confidence band, sample 30 links and check them one by one:

```bash
codedict audit calls -n 30 --confidence high
codedict audit calls -n 30 --confidence medium
codedict audit calls -n 30 --confidence low
```

For each item, open the calling line and the `linked` symbol. Mark `OK` if the call really goes to that symbol, `WRONG` if it goes elsewhere, `?` if you cannot tell. Precision per band = OK / (OK + WRONG).

## Step 4: missed calls

```bash
codedict audit missed -n 30
```

For each item, decide whether the call should have been linked to one of the `candidates`. Miss rate = should / total checked.

## Step 5: routes and tables (web/SQL projects)

```bash
codedict routes
codedict tables
```

Compare with reality using `grep` (`[Http*]`, `[Route]`, `MapGet/MapPost`, `@app.get`, `@page` attributes, SQL strings). Report: real routes found, real routes missed, invented routes. For tables, check 10 at random.

## Step 6: token savings (estimate)

Pick 10 small real tasks ("find where X is validated and how it is called"). For each, estimate tokens (characters / 4):

- With the index: output of `codedict search` + `codedict show` of the right symbol.
- Without the index: size of the files that would be opened whole to find the same thing.

Report the mean and the median savings.

## Step 7: real A/B test (manual, by the user)

Do not run it. Only add this empty table to the result, for the user to fill in with 10 real tasks, each done twice in Claude Code (with and without codedict):

| # | Task | Tokens without | Tokens with | Correct without | Correct with |
|---|---|---|---|---|---|

For a measured A/B with real sessions, use `bench/ab_test.py` (see [BENCHMARK.md](BENCHMARK.md)).

## Pass criteria

| Measure | Minimum |
|---|---|
| Parse errors | 0 |
| Reindex with no changes | < 5 s |
| Search recall@5 | ≥ 85% |
| `high` precision | ≥ 95% |
| `medium` precision | ≥ 85% |
| `low` precision | report only |
| Missed call rate | ≤ 20% |
| Real routes found | ≥ 95% |
| Invented routes | 0 |
| Token savings (median) | ≥ 60% |

## Deliverable: `EVALUATION-RESULT.md`

In this order:

1. A one-line verdict: `PASS`, `PASS WITH CAVEATS` or `FAIL`, with the reason.
2. A table: measure, result, `n`, minimum, pass/fail.
3. Failures: up to 10 concrete examples (file:line, what the index did, what was right), most frequent kind first.
4. Likely causes, grouped (e.g. "receiver named differently from its class", "convention-based route", "question in one language, code comments in another").
5. Suggested fixes, by impact. Propose only; do not apply.
6. The empty table from step 7.
