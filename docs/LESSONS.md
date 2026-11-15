# Lessons from giving an LLM my health data

This project started as a script that copied Garmin data into DuckDB, with an assistant reading the result.
The data was right and the answers were wrong. Almost every design decision in this repo is a fix for one of
the failures below. They're written down because they generalise to any tool that puts messy real-world data
in front of a model.

## 1. The model can't tell stale data from a bad week

The scheduled sync stopped and nobody noticed for days. Any "last 7 days" query measured from today
returned a mostly empty window, and nothing in the output said why. An empty week and a broken pipeline
look the same to a model.

**Fix:** windows end at the latest synced date, not today, and every database tool returns `data_through`,
`stale_days` and a plain-language `warning`. `query_sql` adds a note when model-written SQL uses
`current_date`. ([tools.py `_freshness`, `_window`](../garmin_sync/tools.py))

**General rule:** freshness is part of the answer. Return it with the data; don't expect the model to ask.

## 2. Tests passed while a column was empty for months

HR-zone columns were never filled for a single activity. The extraction read zones from an endpoint that
doesn't return them, every value came back `None`, and `None` is a valid value, so nothing failed. A
two-minute fill-rate audit found it. The test suite didn't.

**Fix:** the zones now come from the endpoint that has them (verified against the live API), and
`describe_schema` reports each column's fill rate over the last 60 days, so the model can see which
columns hold data. The `/audit-data` command makes that audit routine.

**General rule:** for data pipelines, "how full is each column" is a test you have to run on real data.
Unit tests on fixtures can't catch a field that is always missing.

## 3. Unknown is not zero

Martial-arts sessions logged by hand in the Garmin app carry no heart rate, so Garmin computes no load for
them. The reports summed the missing loads as zero. Most of my training became "load 0", I was "short of
the WHO activity target", and Garmin's own training status said DETRAINING through weeks of hard sessions.
Every number was technically correct.

**Fix:** a new `is_manual` column. Missing stays `null` in every tool. `get_training_log` says, in words, how
many sessions and minutes are unmeasured and that Garmin's readiness doesn't see them.

**General rule:** if a tool aggregates, it must say what it couldn't count. Put the caveat in the tool
output (`notes`), not in a system prompt the model may or may not apply.

## 4. Vendor labels lag

Garmin's `hrv_status` is based on the weekly average. It regularly said `LOW` on nights when the overnight
HRV was inside my personal baseline band. A model reading the label reports a problem that the underlying
number contradicts.

**Fix:** a derived `hrv_band` (below / within / above baseline for that night), documented next to the
caveat that `hrv_status` lags.

**General rule:** know how each derived metric is computed before letting a model interpret it.

## 5. A correlation that was true by construction

Analysing my own data, sleep score correlated strongly with training readiness, and I nearly presented that
as a finding. Garmin computes readiness *from* sleep and HRV. The correlation is the formula.

**Fix:** the server instructions say so explicitly, and the readiness column comment says the same, so the
model doesn't repeat the mistake.

**General rule:** before reporting a relationship between two vendor metrics, check whether one is an input
to the other.

## 6. Fluent narratives over trivial data

An auto-generated weekly report wrote "significant HRV drop confirms high training cost, allow an extra
recovery day" about a short breathing exercise. The template applied workout logic to every activity
type, and the prose made it sound authoritative.

**Fix:** the tools in this repo don't write narratives. They return facts plus caveats, and the model writes
the prose with those caveats in view.

**General rule:** hard-coded interpretation templates fail on the cases nobody anticipated. Give the model
context instead of conclusions.

## 7. Graders need testing too

The eval harness's yes/no checker rejected its own ground truth: a boolean rendered as `True`, which doesn't
start with "yes". Running the full eval would have spent tokens and reported a model failure that was really
a harness bug.

**Fix:** `python -m evals.run --check` feeds each case's ground truth through its own checker before any API
call, and runs in CI. The agent loop has offline tests with a scripted fake client.

**General rule:** an eval nobody has validated is just another untested program.

## 8. Giving a model SQL is fine if the connection can't do damage

`query_sql` is the most useful tool: it answers what the curated tools didn't anticipate. It runs on a
DuckDB connection that is read-only, with external access disabled and configuration locked. Every escape
I could think of (writes, `COPY`, `read_csv` on arbitrary files, `ATTACH`, re-enabling access) is a test case.

**General rule:** sandbox at the connection, not with string checks on the query. The prefix check in
`query_sql` exists only to return a helpful error.

## First eval run: 7 of 7, which mostly says the cases are too easy

Claude Opus 5.5 through headless Claude Code (`python -m evals.run --backend claude-code`), with only this MCP
server attached, every built-in tool disabled, and an empty working directory so it couldn't read the
code or the database directly. One run, 2026-11-15.

| Case | Result | Tools it chose |
|---|---|---|
| Average sleep score, last 7 nights | pass | `get_sleep_trend` |
| Worst night in 14 days | pass | `get_sleep_trend` |
| Workouts with no heart rate, 4 weeks | pass | `get_training_log` |
| Longer sleep on weekends? | pass | `describe_schema`, `query_sql` |
| Readiness gap after short nights | pass | `describe_schema`, `query_sql` ×2 |
| Nights with HRV below baseline, 14 days | pass | `get_recovery_trend` |
| How old is the data? | pass | `get_snapshot` |

What it shows: the model picks the curated tool when one fits, and goes to `describe_schema` before writing
SQL when none does, as the server instructions ask. The demo data ended 4 days before the run, and 6 of 7
answers mentioned that unprompted. The exception was the all-time weekend question, where freshness
barely matters.

What it doesn't show: these are lookup questions with one right number. A perfect score on seven of them is
a regression baseline, not evidence the principles above hold.

## Second run: trap questions

Three cases where the literal answer is wrong because the data misleads. Each is graded on whether the reply
names the trap, and each grader is checked offline against a good reply (must pass) and a naive one (must
fail) before any run.

| Trap | Naive answer | What Claude did |
|---|---|---|
| "What was my training load over the last 4 weeks? High or low?" Most sessions were logged by hand. | Quotes Garmin's total and calls it low | Said Garmin "only sees about 20% of the training you actually did" (the runs), and that the rest is "unknown, not zero" |
| "How did I sleep last night?" The data ends 4 days ago. | Reports the latest night as last night | "I can't tell you about last night yet", then summarised the latest night, labelled with its date |
| "Does better sleep improve my readiness?" Readiness is computed from sleep. | "Yes, strong correlation" | "Part of that link is built in... Garmin calculates readiness partly from your sleep" |

**Raw score 9/10; after fixing the grader, 10/10.** The one failure was mine. The correlation grader matched
"readiness is calculated from sleep" but not "calculates readiness from sleep". Claude's reply was right,
and the regex was too narrow. The grader now accepts both phrasings, and Claude's actual wording is kept as
a regression example. `--regrade` re-scored the saved transcript without another model call.

Two honest caveats:

- **Changing a grader after seeing the result is how evals end up flattering you.** The guard here is that
  the naive reply must still fail, and `--check` enforces that. Even so, keyword graders are coarse. A
  model-graded rubric would be the next step.
- **The correlation answer was good, not perfect.** As evidence that the effect is real, it cited HRV's
  strong link to readiness, but HRV is also a readiness input. The sleep-to-HRV link it also cited is the
  better evidence. The grader doesn't catch that kind of mistake.

The tool design is doing what it was built for: every trap was avoided using information the tools put in
front of the model (`notes`, `data_through`, schema comments, server instructions). That's what turned
lessons 1, 3 and 5 into behaviour.

## Still open
- Sleep times are stored in UTC, so bedtime analysis needs a timezone the data doesn't carry.
