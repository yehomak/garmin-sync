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

## Still open

- **Eval results aren't published yet.** The harness, the cases and the offline checks exist; the first full
  run against Claude hasn't happened. Results go here, failures first.
- Sleep times are stored in UTC, so bedtime analysis needs a timezone the data doesn't carry.
