# the-company AWS for DS — arbitration decisions (session of 2026-07-27)

> Translator's note: "the-company" is a placeholder for the real client name used
> throughout the original French repository; it was not expanded here so as not to
> guess at a name that isn't in the source text.

Complement to `docs/00-programme.md`. In case of contradiction, **this file takes
precedence** (it is later and settles the gray areas of §18).

This is a **log**: entries are dated, never rewritten, and ordered in the order they
were made. The index below is for navigation.

## Index

| # | One-liner | Status |
| --- | --- | --- |
| D1 | Pairs, `teams` as a Terraform variable, TEAM_ID `^g[0-9]{2}$` | active |
| D2 / D2 bis | EC2 work machines, Ubuntu distribution (not Amazon Linux) | active |
| D3 | Code catch-up via starter tags (`j1-fin`, `j2-fin`) | active |
| D4 | AWS catch-up | partially obsolete -> D23 |
| D5 | Single region eu-west-3, never hardcoded | active |
| D6 | Presence in the Bedrock catalog doesn't mean access: probe with Converse | active |
| D7 | Deterministic naming `qc-<TEAM_ID>-...`, account suffix for S3 | active |
| D8 | SageMaker managed MLflow + `sagemaker-mlflow` mandatory | active |
| D9 | Network hardening (VPC, endpoints, internal ALB) | active |
| D10 | Verification and monitoring: `check-dayN`, `restore-dayN`, dashboard | active |
| D11 | Fixed, deterministic SECOM dataset (`features.json`) | active |
| D12 | Path-based ALB `/gNN/` -> Streamlit `--server.baseUrlPath` | active |
| D13 | Day3 reorganization (lab 6 relieved) | active |
| D14 | Bedrock model: only `mistral.mistral-large-2402-v1:0` accessible | active |
| D15 | Strands in `streaming=False`, otherwise tool use breaks | active |
| D16 | Assumed deviations of preflight from §12 | active |
| D17 | `qc/config.py` sole reader of `.env` | active |
| D18 | Frozen versions; Evidently 0.7 (presets moved) | active |
| D19 | One single application, no day1/2/3 folders | active |
| D20 | SECOM timestamps: 604 lines recovered | active |
| D21 | Isolation between groups by instance profile (deny outside prefix) | active |
| D22 | One ECS cluster per group, created in the socle | active |
| D23 | Corrections from the 07/28 cross-review | active |
| D24 | The test suite never reaches AWS | active |
| D25 | Logistic regression replaces XGBoost (SKLearn script mode) | active |
| D26 | Capture is filtered by `inferenceTime`, not file date | active |
| D27 | ECS Exec = the trainer's SSM channel, requires `ssmmessages` | active |

## D1 — Groups and TEAM_ID

- Work in **pairs** (cancels and replaces the trio recommendation from §4).
- The number of groups is **not fixed**: Terraform variable `teams` (list of
  TEAM_ID). The socle generates workstations, ALB rules, IAM roles and log groups
  via `for_each`.
- The preflight computes the SageMaker quota need as `len(teams) x margin`, never a
  hardcoded number.
- Enforced TEAM_ID format, validated by regex: `^g[0-9]{2}$` (g01, g02, ...).
- **Remove** the `qc-b03-endpoint` example from §11: it contradicts the `g01`
  format.

## D2 — Work machines

- EC2 **defined in `infra/terraform/socle/`**, applied by the trainer before the
  training. Learners only have control over `infra/terraform/team/`: they therefore
  can't destroy their own machine with Day 3's `terraform destroy`.
- **Golden AMI**: a reference workstation is built and validated, then frozen as an
  AMI. The cohort's machines start from this AMI (Docker + buildx, Python 3.11, AWS
  CLI, git, warm uv cache) -> no `dnf install` in front of 15 people on Day 1.
- **Revised on 07/28/2026 — the AMI no longer embeds the starter repo.** A repo
  clone frozen in an image goes stale on the very first commit, and the starter is
  force-pushed at every regeneration: `git pull` then fails on a rewritten history.
  Pairs clone it themselves on Day 1 (~1 MB, instant); only the uv CACHE (packages +
  interpreter) is warmed in the image, via a throwaway clone deleted before the AMI
  is created. While it remains true that no solution repo should ever get near the
  machines (D2), the note about `git checkout j1-fin` still stands: the correction
  tags arrive with the clone the pair makes.
- `make workstation-check` target: connects via SSM to each machine and checks
  docker, buildx, python, the repo clone, and `sts get-caller-identity`. To run the
  day before.
- Access via Session Manager, instance profile `qc-<TEAM_ID>-workstation-profile`,
  no static key distributed.

## D2 bis — Workstation distribution: Ubuntu, not Amazon Linux

§14 planned for Amazon Linux 2023. Trainer's decision: **Ubuntu**. The repo's
content (Python scripts, Makefile, Terraform) is entirely agnostic — only the AMI
bootstrap changes. Points to handle, none blocking:

| Item | Amazon Linux 2023 | Ubuntu |
| --- | --- | --- |
| Default user | `ec2-user` | `ubuntu` — affects the bootstrap paths and the `docker` group |
| Python | system 3.9 | system 3.12 |
| Docker + buildx | `dnf install docker`, buildx separate | official Docker apt repo: `docker-ce` + `docker-buildx-plugin` |
| Terraform | HashiCorp yum repo | HashiCorp apt repo |
| SSM agent | preinstalled | **to verify** on the chosen Canonical AMI |

- **The system Python doesn't matter at all**: `uv` downloads and manages the
  required 3.11 interpreter (§11). That's what makes the Arch (trainer) / Ubuntu
  (workstations) gap inconsequential, and the main reason everything goes through
  `uv`.
- **Docker trap on Ubuntu**: the Ubuntu repos' `docker.io` package doesn't provide
  `buildx`. Yet §11 requires `docker buildx` and the `linux/amd64` platform, and
  preflight check 11 verifies it. The bootstrap must use Docker's official apt repo
  and install `docker-buildx-plugin`, not `docker.io`.
- **SSM agent**: to confirm on the chosen Ubuntu AMI. It's the only access to the
  machines (D2), so its absence would block everyone on Day 1 morning.
  `make workstation-check` must explicitly verify it the day before.
- **`.python-version` file** added at the repo root (value `3.11`), and `make lock`
  now compiles with `--python-version 3.11`. Without this, the lock would depend on
  the Python of whichever machine compiled it — Arch on 3.13 for the trainer, Ubuntu
  on 3.12 on the workstations — and would no longer be reproducible.

## D3 — Resuming on Day 2 / Day 3, CODE layer

- The `j1-fin`, `j2-fin` tags are **present from the start on `main`** of the
  starter repo (deliberate choice: the solution is accessible from the very first
  minute).
- Mitigation: the checks target the **real AWS state** (endpoint `InService` under
  the group's prefix, objects present in the bucket, data capture that's writing),
  not the content of the files (see D3). Copying the code without running it
  doesn't pass the check.
- Consequence: §13's criterion of "no residual solution in the git history"
  (instance C) is **cancelled**.

## D4 — [PARTIALLY OBSOLETE, see D23] Resuming on Day 2 / Day 3, AWS layer

- `make restore-day1` replays **the entirety** of Day 1: S3 upload -> training job ->
  endpoint deployment. ~15 minutes wall-clock. Same for `make restore-day2`.
- Launched in the **background** with tracking, during the Day 2 masterclass 1, so
  it doesn't eat the morning.
- Quota consequence: N pairs launching the restore at 9am = N training jobs
  simultaneously. Preflight check n°5 (training instance quota >= number of groups)
  becomes blocking at that precise moment, not just in theory.

## D5 — Region

- **eu-west-3 (Paris)**, France data residency.
- To verify in the console before any commitment:
  - list of Bedrock models activatable from eu-west-3 (access-request lead time);
  - quotas for the chosen SageMaker instance types x number of groups.
- Sizing chosen (logistic regression — and already valid for the former XGBoost —,
  ~40 features, 1567 rows -> CPU is enough): `SAGEMAKER_TRAIN_INSTANCE=ml.m5.large`,
  `SAGEMAKER_ENDPOINT_INSTANCE=ml.m5.large`. No GPU.

## D6 — Bedrock preflight fix (§12, check n°7)

- The current spec is **wrong for Europe**: it requires `BEDROCK_MODEL_ID` to appear
  in `list_foundation_models`. In the EU region, recent Claude models are invoked
  via a cross-region **inference profile** prefixed `eu.`, which appears in
  `list_inference_profiles`, not `list_foundation_models`.
- Fix: the check accepts both forms, queries `list_inference_profiles` when the ID
  starts with `eu.`, and keeps the **real `Converse` call** as the deciding
  criterion (the only check that proves actual access).

## D7 — Deterministic naming vs. derived names

- Tests **never hardcode a name**. They import `src/qc/config.py`, which is the
  single source of truth for resource names.
- Reason: two names aren't knowable when the tests are written — the bucket
  (`qc-<TEAM_ID>-data-<account suffix>`, world-wide uniqueness) and the training
  jobs / endpoint configs (UTC timestamp, uniqueness over time).

## D8 — MLflow

- **SageMaker managed MLflow**: a managed tracking server, unique for the whole
  cohort, created in the socle well ahead of the training (~20 min provisioning,
  billed hourly).
- One experiment per group, named `qc-<TEAM_ID>`. `sagemaker-mlflow:*` rights added
  to the `qc-<TEAM_ID>-lab` role. `MLFLOW_TRACKING_URI` = the tracking server's ARN.
- **Mandatory addition to `requirements.txt` (missing from the §11 stack)**: the
  `sagemaker-mlflow` package. Without this plugin, the MLflow client doesn't talk to
  the managed server and Day 3's fil-rouge lab 6 fails immediately.
- Preflight check n°14 becomes **blocking**: the SKIP planned in §12 is cancelled,
  since Day 3 depends on it.
- To confirm in the console: managed MLflow availability in eu-west-3. **Verified on
  07/28/2026 — risk lifted.** `list_mlflow_tracking_servers` responds in eu-west-3:
  managed MLflow is available there. D8 doesn't need reopening, and falling back to
  a local MLflow on the workstation is no longer necessary. Written in tranche 3
  (`infra/terraform/socle/mlflow.tf`), behind `create_mlflow = false` — the server
  is billed hourly from the moment it's created.
- **Risk not covered, unlike D14.** The Bedrock model choice has a fallback scale
  and changes with one variable; managed MLflow has none. If it's not available in
  eu-west-3, Day 3's lab 6 no longer has a target and D8 must be **reopened** — this
  isn't a variable change, it moves infrastructure between the socle and the
  workstation. Fallback identified for that case: local MLflow on the workstation
  (option set aside during the initial arbitration, to be resubmitted rather than
  silently switched to).

## D9 — Network hardening

- `enable_vpc_endpoints = false`. Tasks exit via the NAT.
- Reason: at `true` as specified in §14, internet egress is removed — which breaks
  the SECOM dataset download (archive.ics.uci.edu), `pip install` and `git clone`.
  The training wouldn't get off the ground.
- The interface endpoints (ECR api/dkr, SageMaker runtime, Bedrock runtime,
  CloudWatch Logs, STS) remain **written and commented out** in the Terraform, not
  applied, and serve as a **commented demonstration on Day 2** — same treatment as
  ACM/HTTPS.
- The S3 gateway endpoint remains created (free).

## D10 — Verification and monitoring

- Learner side: `make check-day1` / `check-day2` / `check-day3`, output as a
  PASS/FAIL table per criterion with cause and corrective action — same format as
  `make preflight`, so the error vocabulary is learned only once.
- The checks target the **real AWS state** under the group's prefix, not the
  content of the files (cf. D3). They read names from `src/qc/config.py` (cf. D7).
- Each run writes its result to `s3://<cohort bucket>/checks/<TEAM_ID>/`.
- Trainer side: `make dashboard` aggregates the state of all groups in one command.
  Goal: spot a stuck pair without touring every screen.
- `pytest tests/` stays in place (§13) but becomes the underlying harness, not the
  learner-facing interface.

## D11 — Dataset determinism

- The SECOM dataset stays **downloaded at runtime** via `ucimlrepo` (§13 respected,
  no committed data).
- But the **list of ~40 selected columns is frozen** in a versioned starter file,
  and the train/test split uses a **fixed seed**. All pairs therefore get the same
  set, the same model (the logistic regression training is deterministic,
  `random_state=42`), the same Day 2 contributions, and the same Day 3 drift
  baseline — a necessary condition for deterministic checks.
- An anonymized 50-row sample is committed for the tests (already tolerated in
  §14).
- **Residual risk**: dependency on `archive.ics.uci.edu`'s availability on Day 1
  morning. Mitigation chosen: the raw dataset is pre-cached in the golden AMI, and
  a backup copy is placed in the cohort's common bucket. The code tries the source,
  then falls back to the cache.

## D12 — Application exposure and ALB routing

- **A single ALB for the whole cohort**, created in `infra/terraform/socle/` with
  its :80 listener (default action: 404 "unknown group").
- ~~The `infra/terraform/team/` module grafts its own `aws_lb_listener_rule` and its
  `aws_lb_target_group`.~~ **Amended on 07/30/2026 (technical review, point 2)**:
  the `elasticloadbalancing` write permissions required by this graft targeted the
  shared listener (`resources = ["*"]`), so one pair could delete another's rule.
  The `/<TEAM_ID>/*` rule and the `qc-<TEAM_ID>-tg` target group are now
  **pre-created by the socle** (`socle/alb_teams.tf`); the `team/` module reads the
  target group ARN from the socle's outputs and registers its ECS service there.
  The workstation role now only has `elasticloadbalancing:Describe*`. Apply
  parallelism is preserved.
- The **rule priority** must be unique per group: derive it from the TEAM_ID (e.g.
  `g01` -> 10, `g02` -> 20) — now computed in the socle.
- **Fix for a §14 conflict**: the ALB doesn't rewrite the path, so the container
  receives `GET /g01/`. Streamlit in default configuration thinks it's at the root
  and generates its static assets and websocket at `/static/...` and
  `/_stcore/stream`, which the ALB doesn't know how to route -> blank page, healthy
  task, silent logs.
- Fix adopted: the application is started with `--server.baseUrlPath=<TEAM_ID>`,
  injected from `src/qc/config.py`. The target group's health check then targets
  `/<TEAM_ID>/_stcore/health`.
- This failure mode is kept as **teaching material**: it's exactly the kind of
  incident Day 3 teaches how to diagnose.

## D13 — Day 3 reorganization (lab 6 overload)

- Finding: §8's lab 6 takes 2h10 and contains six technical tasks **plus** the oral
  demos. With N pairs x ~7 min, the orals alone eat up half the slot. The program as
  written doesn't fit.
- Decision: the **Terraform block leaves lab 6** and becomes a short, standalone lab
  placed right after masterclass 2 (modify `desired_count` / `cpu` / `memory` / log
  retention, read the `plan`, apply, verify the effect).
- Lab 6 refocuses on: injecting a drift, comparing reference and production with
  Evidently, logging to MLflow, exposing `check_data_drift()` to the agent.
- The final challenge and the oral demos keep their time slot.
- Nothing is removed from the program: only the order changes. §8 needs to be
  rewritten accordingly.

## PROBE RESULTS (2026-07-27, account , eu-west-3)

> **07/27 snapshot** — the full report is
> `docs/02-discovery-account-2026-07-27.md`.

- **Identity**: SSO role `AWSReservedSSO_MachineLearningSandboxAccess`. Derived
  bucket suffix: `qc-<TEAM_ID>-data-<suffix>`.
- **D5 — RESOLVED, favorably.** `ml.m5.large` quotas: **30** for training, **16**
  for endpoint. Comfortably enough for the cohort. No quota increase request
  needed. Preflight check n°5 stays written, but it won't be blocking.
- **D6 — CONFIRMED.** eu-west-3 does expose 34 inference profiles, prefixed `eu.`
  and `global.`. The fix to preflight check n°7 is therefore necessary, as
  anticipated.
- **D8 — CONFIRMED.** SageMaker managed MLflow is available in eu-west-3. No
  existing tracking server: to be created in the socle. The "local MLflow"
  fallback doesn't need reopening.
- **D14 — INVALIDATED. Only one model is actually enabled:
  `mistral.mistral-large-2402-v1:0`** (Converse call OK, tool use OK). Nova Lite,
  Nova Pro and **all** Anthropic models return `AccessDeniedException`, despite
  being in the catalog. This retroactively validates decision D6: presence in the
  catalog doesn't mean access, only the real Converse call proves it.
- ECR, ECS, ELBv2 and CloudWatch Logs: accessible.

## D15 — Strands must run in NON-streaming mode (verified)

- Finding, obtained via `scripts/probe_model.py`: Strands's Bedrock provider calls
  `ConverseStream` by default. But Mistral Large doesn't support tool use in
  streaming. Raw result, with no configuration:
  `ValidationException: This model doesn't support tool use in streaming mode`.
- Fix: instantiate `BedrockModel(model_id=..., region_name=..., streaming=False)`.
  Verified end to end — the agent calls the tool and cites the returned value.
- **Consequence on the starter**: this parameter must be **pre-filled and
  commented** in `src/qc/agent.py`, never left as a TODO. Without it, every pair
  hits an opaque ValidationException on Day 2, on a point with zero teaching
  value.
- Possible teaching use in the Day 2 masterclass: illustrates that "the model
  supports tool use" and "the model supports tool use in this call mode" are two
  distinct claims.
- Pixtral Large 25.02 (`eu.mistral.pixtral-large-2502-v1:0`), untested by the
  first probe, is also refused. Mistral Large 2402 remains the only usable model.

## D14 — Bedrock model

- Constraint: access to Anthropic models in the account isn't guaranteed. The
  choice therefore falls on what's **certainly activatable**, not the most
  capable.
- **FINAL DECISION, based on the probe: `mistral.mistral-large-2402-v1:0`.** It's
  the only model actually callable in the account (Converse OK, tool use OK). The
  initial Amazon Nova Lite hypothesis is abandoned: Nova is in the catalog but
  returns `AccessDeniedException`, like all Anthropic models.
- Note that this is a **raw modelId**, not an `eu.*` inference profile — preflight
  must therefore accept both forms (cf. D6).
- Secondary benefit: a European-sovereignty argument, appreciated by the company.
- **Open action for the trainer**: determine in the console (Bedrock's "Model
  access" page, eu-west-3) whether the refusals come from missing activation or an
  IAM restriction on the `MachineLearningSandboxAccess` SSO role. The fact that
  Nova — AWS's own model, normally the easiest to access — is also refused
  strongly leans toward an IAM restriction, i.e. an IT decision rather than a
  checkbox.
- If a better model gets unlocked before the training: switch by changing
  `BEDROCK_MODEL_ID`, plus a re-check of `src/qc/agent.py`'s template
  (SYSTEM_PROMPT).
- **The choice isn't structural**: everything goes through the Converse API and
  Strands's Bedrock provider. Changing model = changing `BEDROCK_MODEL_ID`, no
  application code line.
- Only real constraint: the model must support **tool use** via Converse.
- Consequence on `src/qc/agent.py` (SYSTEM_PROMPT): the template is written
  **constrained and explicit**, to hold up even on a lightweight model. §7 asks
  that the LLM be forced to cite tool values and that ambiguous cases be tested —
  a lightweight model resists this less well, which stays exploitable
  pedagogically but forces a more locked-down prompt.
- Preflight (check n°7) validates access via a **real Converse call**, never
  through mere presence in the catalog (cf. D6).
- To verify in the console before locking in: Bedrock's "Model access" page in
  eu-west-3 (the API doesn't reliably expose what's *activated*, only what's in
  the catalog).

## Pending information (critical path) — [OBSOLETE: since settled]

- **Training dates** and **exact headcount**. These drive the scheduling of the
  three long-lead items: Bedrock model access request, SageMaker quota increase,
  golden AMI build and validation.
- List of AWS services forbidden by the company's policies (§18, unsettled).
- Duration reserved for the final demos (§18, unsettled).

## D16 — Assumed deviations of preflight from §12

Decisions made while writing `scripts/preflight.py`.

- **All checks run, even after a failure.** §12 asks to stop dead at the first
  FAIL. A partial report has no value in front of IT: better the full list of
  missing rights than one isolated first failure. The exit code stays 1 as soon as
  one check fails, per §12.
- **Checks that depend on the socle are marked as such.** Before `make
  socle-apply`, checks 4, 6, 9 and 14 fail normally. Without this marking, a
  trainer reading a red preflight before building the socle would think there's a
  problem.
- **Check 3 (permissions) degraded to SKIP on an SSO role.**
  `iam:SimulatePrincipalPolicy` often fails on an assumed role. The script
  converts the session ARN to a role ARN, and falls back to SKIP if the call is
  still refused — the following checks test the rights actually used, which is
  more reliable than a simulation.
- **Check 9: an empty `ACM_CERT_ARN` is a PASS, not a gap.** It's the normal value
  for the degraded HTTP mode chosen in §14. Treating it as an error would produce
  a permanent false negative.
- **Check 13 delegated to `uv`.** Resolving `requirements.txt` and the imports is
  verified in a throwaway environment (`uv run --with-requirements`), which also
  validates that the file actually resolves — the check's real intent.
- **Check 14 (MLflow) made blocking**, cf. D8.
- **Check 7 (Bedrock) fixed twice.** First cf. D6: it accepts a raw modelId and an
  inference profile, and relies on the real Converse call rather than catalog
  presence. Then, it explicitly tests **tool use** with a `toolConfig`, not just
  the plain call — a model can accept Converse and refuse tool use (exactly
  Mistral's case in streaming, cf. D15). Without this second probe, a
  `BEDROCK_MODEL_ID` change would show green in the morning and break the agent in
  the Day 2 afternoon. The failure message points to `make probe`, which also
  tests Strands-driven piloting.
- **Exit contract verified**: 5 FAIL -> exit code 1.

## D17 — `src/qc/config.py`

- Single `config` object, imported everywhere. No script reads `os.environ` (§12).
- **Lazy** construction (PEP 562 `__getattr__`): importing `ROOT`, `DATA_DIR` or
  `ConfigError` doesn't build the config. With an instance built at module load,
  `uv run qc` and `uv run qc --help` used to fail on a traceback as soon as `.env`
  was incomplete — exactly when the learner is trying to figure out what to fill
  in.
- Validation at construction time, with an error message carrying the
  **corrective action**, not just the cause.
- `__repr__` redefined to never expose a credential in a trace or a log; secret
  keys are stripped from the environment dict as soon as it's loaded.
- Network calls are **deferred**: `account_id` and `account_suffix` are
  `cached_property`, so importing the config triggers no AWS call.
- Helpers carrying the decisions: `timestamped_name()` (D-temporal uniqueness),
  `streamlit_base_url_path` and `health_check_path` (D12), `mlflow_experiment`
  (D8), `tags` / `tags_list` (support for `make destroy`).
- `s3_uri()` rejects any prefix outside the list `raw/ curated/ capture/ baseline/
  reports/` — prevents a pair from writing somewhere else and failing a check over
  a typo.

## D18 — Frozen versions (`uv.lock`, 2026-07-27)

- `make lock` run: **238 packages frozen**, install and imports verified.
- Key versions: `evidently 0.7.21` / `mlflow 3.14.0` / `sagemaker-mlflow 0.5.0` /
  `strands-agents 1.50.1` / `scikit-learn 1.9.0` / `streamlit 1.60.0` /
  `boto3 1.43.56`.
- Update 07/29/2026 (D25): **170 packages frozen**. The `sagemaker` SDK, `torch`
  (which it was dragging in via sagemaker-serve), `xgboost` and `shap` drop out of
  the runtime dependencies — nothing imports them since the migration. `xgboost`
  and `shap` remain available for exploration notebooks via the `notebooks`
  group.
- Preflight check 13 now points at `uv.lock` if it exists, and warns if it's
  absent. Checking `requirements.txt` would validate a resolution that no one
  will install.
- **Evidently 0.7 trap to document in Day 3's `HINTS.md`.** The presets have moved
  module: they're in `evidently.presets`, and `evidently.metric_preset` no longer
  exists (`ModuleNotFoundError`). `DataDriftPreset` and `ClassificationPreset`
  still exist, at the new path. Consequence: **all the Evidently code found online
  targets 0.4 and won't work.** A stuck pair looking for help will run into false
  examples. Say it explicitly rather than let it be discovered.
- The `Report` API also evolved between 0.4 and 0.7: write Day 3's code against
  the frozen version, never from memory or a tutorial.

## D19 — One single application rather than numbered scripts (deviates from §13)

§13 requires a `day1/01_load_secom.py`, `day1/02_upload_s3.py`, ... layout. Chosen
instead: **a single `src/qc/` package that learners grow over three days**, driven
by a single `uv run qc <step>` command.

- **§13's underlying requirement is preserved**: strictly identical layout between
  the solution and the starter, numbered TODOs (`TODO-D1-03`), only the function
  bodies differ. Only the layout's *shape* changes.
- **A TODO benefits from living in a typed function.** `def split(dataset:
  Dataset, features: list[str]) -> Split:` tells the learner what they must
  produce and with what type. In the middle of a 255-line script, a TODO only
  says "write here."
- **Day 2 reuses Day 1 without copying.** That was the real flaw of the
  script-based structure: to retrieve the variable list or invoke the endpoint,
  Day 2 would have duplicated Day 1's code — files named `01_*.py` aren't
  importable, their name starts with a digit. The flaw would have exploded on Day
  2, not Day 1.
- **Final deliverable**: the learner leaves with a coherent application, not
  fifteen scripts. That's what they can actually take back to their company.
- **`src/` layout** (Python Packaging Authority's official recommendation): the
  package is only importable once installed, so the tests test what's actually
  shipped.
- **What replaces the visible order in the file tree**: `uv run qc` with no
  argument displays the progress table, which says *where things stand*, not just
  what exists. More useful than an `ls`, both for the learner coming back from a
  break and the trainer checking in on them.
- **Deliberately flat structure**: one module per lifecycle step (`secom`,
  `storage`, `training`, `inference`, `agent`, `monitoring`), no sub-packages. A
  module only becomes a folder if it exceeds ~300 lines or gains a second
  implementation. Splitting ahead of time is guessing.
- **Compute / display separation**: modules do no `print` at all, all display
  lives in `qc/cli.py`. Without this, Day 2's agent calling
  `qc.inference.predict()` would pick up `print` output in the middle of its
  trace.
- **Only exception**: `scripts/preflight.py` stays a standalone PEP 723 script
  with a `sys.path.insert(ROOT / "src")`. It must run on a brand-new machine, and
  its check n°13 specifically verifies that `uv sync` works — it can't depend on
  that itself.

## D20 — SECOM timestamps: 604 out of 1567 rows were being silently lost

The UCI file mixes **two** timestamp formats: `19/07/2008 11:55:00` and `1/8/2008
2:02` (no leading zero, no seconds). The fixed format `%d/%m/%Y %H:%M:%S` combined
with `errors="coerce"` was converting **38% of the dataset to `NaT`, without a
word**.

- Consequence if uncorrected: Day 3's **temporal** drift — comparing production's
  early weeks to its latest ones — would have been computed on 62% of the data,
  and chronological sorting would have scattered 604 rows randomly.
- Fixed with `format="mixed", dayfirst=True`. `dayfirst` resolves `1/8/2008`'s
  ambiguity: the dataset spans July to October 2008, so it's August 1st, never
  January 8th.
- Verified: 0 `NaT`, unchanged period (07/19/2008 -> 10/17/2008), monotonic sort.
- **Lesson to carry into Day 3's code**: `errors="coerce"` turns a noisy error
  into silent data loss. Only use it when you then check what got discarded.

## D21 — Isolation between groups doesn't exist yet (07/27/2026)

`storage.probe_isolation("g02")`, run from the trainer's workstation, **read
another group's bucket**. Verified: this isn't a tranche-1 defect, it's a feature
that simply hasn't been written yet.

The socle does scope a policy per group — but on `qc-gNN-sagemaker-exec`, the role
that **SageMaker** assumes. Nothing constrains the identity the **learner** acts
from. Yet that's the one that matters for isolation: a pair who gets the value
wrong in `S3_BUCKET` today overwrites another group's data without hitting the
slightest refusal.

- The README announced this isolation as one of the shared account's three
  pillars. That was false. Reworded as "coming — tranche 2" rather than silently
  fixed.
- To write in tranche 2: one instance profile per group, carried by the work
  machine, with a policy conditioned on the `qc-<TEAM_ID>-*` prefix.
- Until this is done, Day 1's "deliberate AccessDenied" lab **can't work**:
  there's nothing to refuse. It's a teaching prerequisite, not just a hardening
  measure.
- `probe_isolation()` now distinguishes the two situations in its message: under a
  trainer identity, a successful read is normal; from a pair's machine, it
  signals an unscoped instance profile.

**Written in tranche 2 (07/28/2026)** — `infra/terraform/socle/workstations.tf`
creates `qc-<TEAM_ID>-workstation-profile`, whose policy bounds S3, SageMaker,
ECR, ECS, the logs and Bedrock to the group's own prefix alone. Refusing to read
another bucket becomes an implicit denial: nothing authorizes it. Still to
confirm with a `probe_isolation()` run **from a work machine**, once the tranche
is applied — it's the only place where the profile applies. From the trainer's
machine, the read will still succeed.

Two limits are accepted and commented in the code:

- actions the AWS API doesn't allow scoping by resource (listing jobs, getting an
  ECR token, reading metrics) remain open in **read**;
- `elasticloadbalancing:CreateRule` targets the listener's ARN, shared by the
  whole cohort. A pair can therefore technically delete another's rule. The risk
  assumes a deliberate act and is fixed within seconds by a `team/` module
  `apply`.

## D22 — One ECS cluster per group, created in the socle (07/28/2026)

The program contradicted itself: the naming rule requires `qc-<TEAM_ID>-cluster`,
and the paragraph on state separation talks about a single cluster belonging to
the socle.

Settled in favor of prefix naming: an ECS cluster costs nothing, it's just a
logical grouping, whereas the prefix carries isolation and IAM conditions.
Clusters are therefore **per group**, and **created in the socle** so that Day
3's `terraform destroy` can't take them down.

Corollary: `FARGATE` stays the default capacity provider, `FARGATE_SPOT` is
declared but not used by default. A Spot task can be interrupted with two
minutes' notice, which would make a pair's application disappear mid-demo.

## Corrections applied to `docs/00-programme.md` (07/27/2026) — DONE

The document was **spliced** in six places: sentence endings had migrated to the
end of another section. Each fragment was reattached to its original sentence; no
word was invented or removed, only moved.

| § | Truncated sentence | Fragment found in |
| --- | --- | --- |
| 4 | "Recoverable checkpoints..." | end of §4 |
| 8 | "Day 3 deliverable: ... and reading the" | end of the Day 3 skeleton ("Terraform socle.") |
| 11 | "1) raw tool-use loop in Converse" | end of §12, after "Cleanup" |
| 13 | "the dataset is downloaded via ucimlrepo," | end of §14, after the costs |
| 14 | "...via default_tags at the" | end of the quotas paragraph ("of the provider.") |
| 14 | "bucket qc-<TEAM_ID>-tfstate created" | end of the team module ("by a bootstrap step.") |

Two **factual errors** in §3 were also corrected, each flagged in place by a
dated callout rather than silently rewritten — the document is the source of
truth for code agents, a silent correction would get lost again:

- **591 -> 590 sensor measurements.** The UCI sheet shows "591 features" because
  it counts `timestamp` as a variable, which it isn't.
- **The loading snippet didn't run.** `X = secom.data.features ; y =
  secom.data.targets` raises `AttributeError`: both are `None` for SECOM. The
  document now points to `data.original` and refers to `src/qc/secom.py`. The
  two-timestamp-format trap (D20) is documented at the same spot.

**Deliberately left uncorrected**: §13 describes a `day1/ day2/ day3/` layout that
D19 replaces with the `src/qc/` package. This isn't a writing error but a
deliberate arbitration, tracked in D19 — fixing it in the program would hide the
deviation. Same for the header ("pairs") that §4 contradicts ("trios
recommended"): that's to be settled against the real headcount, not by a
document tweak.

## D23 — Corrections from the cross-review (07/28/2026)

Three independent reviews of the repo: a code/docs/decisions consistency review,
an audit of the starter repo, a re-read of the slides against their spec. What
they found, and what was decided.

### Fixed

- **MLflow rights missing from the learner profile.** D8 requires them; the work
  machine's policy had none. Two families are needed:
  `sagemaker:*MlflowTracking*` to talk to the server, and `sagemaker-mlflow:*` for
  the MLflow API, which AWS exposes as a separate service. Granting only the
  first gives an `AccessDenied` on the first `log_metric`, in a message that
  names neither one. Tested until now from an admin identity, which was masking
  the gap.
- **`env_fragment` incomplete.** It carried neither `MLFLOW_TRACKING_URI` nor
  `TEAMS_COUNT`, even though `make env-from-tf` is presented as the only way to
  fill `.env`. `TEAMS_COUNT` is now derived from `length(var.teams)`, as D1
  required: a headcount change in Terraform now propagates to preflight's quota
  check.
- **`make restore-day2` promised by D4 and missing.** Written, modeled on
  `restore_day1`: incremental, and it starts by calling the latter since Day 2
  only stands if Day 1's endpoint responds. It does NOT apply the `team/`
  module — that's Terraform, it belongs to the pair, and replaying it for them
  would remove the one place in the course where they read a `plan`.
- **`check_day2` was rebuilding resource names** instead of reading them from
  `qc.config`, against D7 and D10. An override in `.env` would then check
  something other than what was actually deployed.
- **`make destroy` and `make slides`**, both announced by the program, errored
  out. `destroy` chains the endpoint shutdown and the destruction of the `team/`
  module; `slides` produces the PDFs via `marp-cli`.
- **Catch-up tags.** D3 announced `day1-end` / `day2-end`; the tags actually
  placed are `j1-fin` / `j2-fin`. The decision was following names that didn't
  exist.
- **Dead references** in the decisions: `shared/config.py`,
  `agent/agent_strands.py`, `app/prompts.py`, `requirements.lock`. The real files
  are `src/qc/config.py`, `src/qc/agent.py` and `uv.lock`.

### Decided, not fixed

- **D4 is superseded on `restore-day1`.** It describes a full replay taking a
  quarter hour; the script is incremental and only replays what's missing. The
  current behavior is better: the decision is marked obsolete rather than the
  code aligned to it.
- ~~**The trainer dashboard from D10 is still to be written.**~~ Written on
  07/30/2026 (technical review, point 6) — in a different form than the S3
  aggregation D10 imagined: `make dashboard` creates one CloudWatch dashboard per
  group (`scripts/dashboard.py` — endpoint invocations and 4XXs, ModelLatency in
  µs, ECS RunningTaskCount, state of the three alarms), reads it back as proof,
  and `make dashboard-destroy` cleans up. The companion Logs Insights query is in
  `scripts/logs_insights_erreurs_app.query`. The checks keep displaying without
  being written under `checks/<TEAM_ID>/`.
- **`discover.py` and `probe_model.py` read `os.environ` directly**, against the
  rule set by D17. They're standalone diagnostic scripts, runnable before
  `qc.config` has been filled in — that's exactly their role. The rule applies
  to the `qc` package, not to them.

---

## D24 — The test suite was reaching AWS without saying so (07/28/2026)

`conftest.py` replaces `config.client` with a factory of fake clients: the tests
verify the content of the calls instead of sending them. Fourteen tests were
still going over the network regardless.

`config.account_id` opens its own STS client via `boto3.Session`, outside
`config.client`. Any test whose path touches `s3_bucket` — whose name derives
from the account suffix — was therefore really calling `GetCallerIdentity`.

The flaw is invisible as long as credentials are valid. It shows up on
`ExpiredToken`, right when the resource name under test has nothing to do with
the problem anymore. It's the classic shape of a test that lies: it passes for a
reason that isn't the one it announces.

The `aws` fixture now writes a fake account ID directly into `config`'s
`__dict__` — that's where `cached_property` stores its value, writing there
amounts to caching it. Going through the dict rather than
`monkeypatch.setattr`, which reads the old value before writing, and that read
would trigger exactly the STS call. The three cached values are cleared before
and after every test, since `config` is a singleton shared by the whole
session.

Check worth rerunning after any change to `conftest.py`:

```
env -u AWS_ACCESS_KEY_ID -u AWS_SECRET_ACCESS_KEY -u AWS_SESSION_TOKEN \
  AWS_SHARED_CREDENTIALS_FILE=/dev/null AWS_CONFIG_FILE=/dev/null \
  uv run --frozen pytest tests/
```

A suite that doesn't claim to reach AWS must pass with no credentials at all.

## D25 — Logistic regression replaces XGBoost ("D-optim", 07/29/2026)

- The validated candidate from the
  `exploration-modelisation-secom-optim.ipynb` notebook becomes **the**
  fil-rouge model: median imputation -> standardization -> regularized logistic
  regression (`C=0.01`), class weight computed on the train set.
- **What decided it**: at the threshold picked the same way (F2, out-of-fold on
  the train set), defect recall of **57.7% vs 7.7%** for the XGBoost baseline,
  average precision **0.236 vs 0.180**. Temporal validation (past train -> future
  test): AP 0.308, ROC-AUC 0.759. Confirmed by a real SageMaker job on 07/29
  (2 min 09, `validation:average_precision 0.2364`, `validation:recall 0.5769`).
- **Architecture consequences**:
  - no more built-in algorithm: **script mode** on the official SKLearn
    container (`sagemaker-scikit-learn:1.2-1`, same registry account
    `659782779980`), code archive `model/code/sourcedir.tar.gz`,
    `sagemaker_program` / `sagemaker_submit_directory` contract as
    JSON-encoded values;
  - metrics go through `MetricDefinitions` (regex on the script's logs);
  - the **decision threshold is a training deliverable** (`threshold.json` in
    the artifact, 0.58 measured) — `Prediction.label()` no longer has a 0.50
    default;
  - the explanation moves from TreeSHAP to **exact linear contributions**,
    computed from the pipeline's fitted parameters (`statistics_`, `mean_`,
    `scale_`, `coef_`), never via `transform()` on the unpickled object — the
    artifact is written by the container's scikit-learn 1.2 and reread by a
    local 1.9 (07/29 incident, documented on Day 3).
- The external contract doesn't change: headerless CSV in, one score per row
  out — the data capture and Day 3 don't see the difference.

## D26 — Capture is filtered by the inference's timestamp, not the file's (07/29/2026)

- Excluding baseline-construction invocations by filtering capture files by
  their `LastModified` isn't enough: the file lands one to two minutes **after**
  `baseline.csv`, and passes the filter. Found on 07/29: 423 "production
  predictions" read of which 392 rows were the baseline itself, p = 1.0000 on
  every column — the reference compared against itself, drift invisible
  forever.
- The filter now targets **each record's** `eventMetadata.inferenceTime` (the
  moment the endpoint responded). The file date remains a pre-filter, valid
  only in one direction. A record with no readable timestamp is kept: better
  one extra row than a production silently ignored.
- Verified on real capture: 21 predictions retained out of 423, and finally
  scattered p-values (score: p = 0.4759) instead of a uniform 1.0000.

## D27 — ECS Exec opens the trainer's SSM channel, and requires `ssmmessages` (07/29/2026)

- Without a running workstation (they only exist during the training, the AMI
  being built the day before — cf. `infra/ami/README.md`), the trainer has no
  entry point into the VPC to reach the internal ALB. The pair's ECS task is
  one: the service is created with `enable_execute_command`, and the
  `AWS-StartPortForwardingSessionToRemoteHost` tunnel is set up on target
  `ecs:<cluster>_<task-id>_<runtime-id>`.
- The trap, found on 07/29: enabling Exec on the service side isn't enough. The
  `ExecuteCommandAgent` shows `RUNNING` in `describe-tasks` but every
  `start-session` fails with `TargetNotConnected` as long as the **task role**
  doesn't grant the four `ssmmessages:*` actions (control and data channels).
  The agent's status saying it started doesn't mean it managed to open its
  channel.
- Fix in the socle (`OpenTheExecSSMChannel`, `socle/iam.tf`), applied to the six
  roles. The 07/29 browser campaign (Day 2 captures) went through this tunnel.
