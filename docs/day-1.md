# Day 1 — From CSV to the SageMaker endpoint · the essentials

This document summarizes the essentials of the day: objective, hard points, control
commands.

## Objective of the day

A complete chain, each link being a command from the `qc` package:

```
load -> upload -> train -> deploy -> invoke -> (check-day1) -> teardown
 local    S3     SageMaker   endpoint    predictions              shutdown
```

SECOM data, 40 fixed features (`src/qc/features.json` is authoritative), logistic
regression in SKLearn script mode. `uv run qc` with no argument shows the pair's
progress.

## The hard points — where pairs get stuck

1. **The SageMaker execution role isn't theirs.** It's the service that assumes it
   when the job starts. Classic symptom: the pair reads their bucket fine from their
   own machine, but the job fails with `AccessDenied` — two different identities.
   This is THE concept of Day 1.
2. **Job names are timestamped** (uniqueness over time) — never hardcode them. A
   lived corollary: `list_training_jobs` paginates **before** filtering on
   `NameContains`; an empty page with a `NextToken` doesn't mean "no job"
   (`qc/inference.py::latest_artifact`, dedicated regression test).
3. **The endpoint bills continuously from `deploy` onward** (~$0.134/hr on
   `ml.m5.large`). The evening `teardown` is not optional. Data capture is decided
   when the `EndpointConfig` is created, not afterward.
4. **The endpoint returns a probability, not a decision** — the threshold belongs to
   the client, not the model.
5. **Isolation between groups**: the "deliberate AccessDenied" lab (probing another
   group's bucket) must return `Refused` — otherwise the machine's instance profile
   isn't the right one.

## Control commands

```
make check-day1                 # 6 result checks, per pair, end of day
make restore-day1               # the next morning: replays only what's missing
```

Code catch-up: `git checkout -b day-2 j1-fin` on the starter.

## Where the code lives

`src/qc/secom.py` (load), `storage.py` (upload, isolation probe), `training.py`
(train), `inference.py` (deploy/invoke/teardown). The tests in `tests/` are the
assignment on the starter side: each TODO-D1-xx corresponds to a test that names it.
