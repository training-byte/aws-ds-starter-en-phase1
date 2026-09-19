# Day 3 — Operating what's running · the essentials

This document summarizes the essentials of the day: objective, hard points,
incidents, shutdown.

## Objective of the day

```
baseline -> drift (Evidently) -> MLflow -> CloudWatch alarms -> incidents -> shut everything down
```

Day 3 adds almost nothing new: it operates on what the first two days left behind —
the endpoint's data capture, the logs, the metrics. Resuming: `make restore-day2`,
tag `j2-fin`.

## The hard points — where pairs get stuck

1. **Evidently 0.7**: the presets are in `evidently.presets` — all the code found
   online targets 0.4 and doesn't work (D18). The baseline and production columns
   must have exactly the same names.
2. **Measuring changes what's measured**: data capture also records the monitoring
   calls themselves. The proof is deterministic by counting `inferenceTime` — worth
   showing, it lands well.
3. **The baseline is a reference, not an average** — frozen at training time, not
   recalculated on production.
4. **MLflow**: `sagemaker-mlflow` is essential and missing from the program's stack
   (D8). The managed server bills hourly (`create_mlflow` in the socle).
5. **Alarms**: the combination of period x evaluation points is what separates a
   useful alarm from noise. Getting an alarm to actually go `ALARM` (breaching), not
   just on paper.

## Incidents: pairs inject them into themselves

`uv run qc chaos` breaks a random resource of the pair's without saying which one
(endpoint deleted, `sample.csv` erased, ECS service scaled to zero); the pair
diagnoses from the traces, then `uv run qc heal` repairs it and **names the
failure** — that's the self-correction. Rerunnable as many times as wanted; for the
final challenge, three `chaos` in a row. `uv run qc chaos --panne
endpoint|sample|service` forces a specific failure (demos).

Two incidents still need to be triggered by hand if you want to show them (IAM
rights required, outside the learner role):

| Incident | Trigger | What it teaches |
| --- | --- | --- |
| Blank page | redeploy without `--server.baseUrlPath` | reading the target group and logs before blaming the code |
| `AccessDenied` mid-use | right removed | tracing back from the HTTP symptom to the IAM policy |

## End of training — shutdown is an exercise

Learners shut down what they created themselves (endpoint, ECS service, team
module) — it's the last lab. The trainer checks, then destroys the socle:

```
make check-day3                 # 6 result checks, per pair
# then, once the endpoints are gone:
make socle-destroy
```

## Where the code lives

`src/qc/monitoring.py` (baseline, drift, metrics), `src/qc/chaos.py` (failures and
fixes), `infra/terraform/team/alarms.tf` (alarms lab), `scripts/check_day3.py`.
