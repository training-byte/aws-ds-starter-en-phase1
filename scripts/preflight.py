#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["boto3>=1.35"]
# ///
"""
Preflight — 15 checks before creating any resource.

Non-negotiable principle (§12): no resource is created and no lab is run until
this script is green.

Output: a summary table in the console, a `preflight-report.md` report that can
be attached as-is to an access request, and an exit code of 0 if all checks are
PASS or SKIP, 1 as soon as a single one is FAIL.

All checks run even after a failure, contrary to a literal reading of §12: a
partial report has no value in front of IT. Better a complete list of missing
rights than one isolated first failure.

    uv run scripts/preflight.py               # learner mode: reads only,
                                              # no IAM write calls
    uv run scripts/preflight.py --formateur   # adds the iam:CreateRole probe,
                                              # required before `make socle-apply`

Two modes since the 07/29/2026 review (point 5): the iam:CreateRole probe is a
privileged write API — CloudTrail trace, security alerts — unsuited to a
learner machine. It's reserved for `--formateur`; the default mode relies on
IAM simulation (read) and the non-privileged probes of checks 4 through 10.

Secret hygiene: no credential value is displayed or written. Only the account
ID and the caller's ARN appear — identity, not secret.
"""

from __future__ import annotations

import functools
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Preflight must run on a BRAND-NEW machine, before the project's environment
# exists: it's a standalone PEP 723 script, so the `qc` package isn't
# installed there. Hence this addition to the import path — the only
# deviation from the repo's src/ layout, and it's deliberate: check n°13
# specifically verifies that `uv sync` works, so it can't depend on it.
sys.path.insert(0, str(ROOT / "src"))

from qc.config import ConfigError  # noqa: E402

# `config` is built lazily (PEP 562): naming it here TRIGGERS its
# construction, so an incomplete .env makes the import itself fail. Without
# this safety net, the learner gets a fifteen-line traceback on their very
# first Day 1 script — exactly when they're trying to figure out what to
# fill in. Same lesson as D17.
try:
    from qc.config import config  # noqa: E402
except ConfigError as exc:
    print(f"Incomplete configuration: {exc}", file=sys.stderr)
    print("Preflight can't check anything until .env is filled in.", file=sys.stderr)
    raise SystemExit(1) from None

REPORT = ROOT / "preflight-report.md"

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"

# Unbuffered output: some checks take several minutes (dependency
# resolution, terraform init). Without flush, output redirected to a file
# stays empty until the end — the operator thinks the script is stuck.
print = functools.partial(print, flush=True)  # noqa: A001


@dataclass
class Result:
    number: int
    name: str
    status: str
    cause: str = ""
    action: str = ""
    #: The check depends on the Terraform socle. A FAIL is normal before `make socle-apply`.
    needs_socle: bool = False
    details: list[str] = field(default_factory=list)


results: list[Result] = []


def record(
    number: int,
    name: str,
    status: str,
    cause: str = "",
    action: str = "",
    *,
    needs_socle: bool = False,
    details: list[str] | None = None,
) -> Result:
    r = Result(number, name, status, cause, action, needs_socle, details or [])
    results.append(r)
    icon = {PASS: "\u2713", FAIL: "\u2717", SKIP: "\u2013"}[status]
    suffix = "  (depends on the socle)" if needs_socle and status == FAIL else ""
    print(f"  {icon} {number:>2}. {name}{suffix}")
    if cause:
        print(f"        {cause}")
    for line in r.details:
        print(f"        {line}")
    if action and status == FAIL:
        print(f"        \u2192 {action}")
    return r


def _code(exc: Exception) -> str:
    return getattr(exc, "response", {}).get("Error", {}).get("Code", type(exc).__name__)


# ============================================================================ 1
def check_identity() -> str | None:
    try:
        ident = config.client("sts").get_caller_identity()
    except Exception as exc:  # noqa: BLE001
        record(
            1,
            "Identity",
            FAIL,
            f"sts:GetCallerIdentity fails ({_code(exc)}).",
            "Set credentials in .env, or check the instance profile.",
        )
        return None
    record(
        1,
        "Identity",
        PASS,
        details=[f"account {ident['Account']}", f"caller {ident['Arn']}"],
    )
    return ident["Arn"]


# ============================================================================ 2
def check_region() -> None:
    try:
        regions = {
            r["RegionName"]
            for r in config.client("ec2").describe_regions()["Regions"]
        }
    except Exception as exc:  # noqa: BLE001
        record(
            2,
            "Region",
            SKIP,
            f"Region list unreadable ({_code(exc)}) — needs ec2:DescribeRegions.",
        )
        return
    if config.region in regions:
        record(2, "Region", PASS, details=[f"AWS_REGION = {config.region}, enabled"])
    else:
        record(
            2,
            "Region",
            FAIL,
            f"{config.region} isn't among the account's enabled regions.",
            "Enable the region, or fix AWS_REGION in .env.",
        )


# ============================================================================ 3
REQUIRED_ACTIONS = [
    "s3:PutObject",
    "s3:GetObject",
    "s3:DeleteObject",
    "s3:ListBucket",
    "sagemaker:CreateTrainingJob",
    "sagemaker:CreateModel",
    "sagemaker:CreateEndpoint",
    "sagemaker:InvokeEndpoint",
    "bedrock:InvokeModel",
    "bedrock:Converse",
    "ecr:GetAuthorizationToken",
    "ecr:PutImage",
    "ecs:UpdateService",
    "ecs:DescribeServices",
    "elasticloadbalancing:DescribeTargetGroups",
    "logs:FilterLogEvents",
    "logs:CreateLogGroup",
    "cloudwatch:GetMetricData",
    "cloudwatch:PutMetricAlarm",
]


def _probe_iam_write(reason: str, hints: list[str] | None = None) -> None:
    """REALLY tests iam:CreateRole, without creating anything. TRAINER mode.

    The probe sends a deliberately invalid trust document. IAM authorizes
    before it validates, so:

      - AccessDenied            -> the right is missing, and the socle will fail partway through;
      - MalformedPolicyDocument -> the right is there, no role was created.

    It's the only way to know the answer without leaving a ghost role behind
    in an account shared by the whole cohort.

    07/29/2026 review, point 5: even non-mutating, this is a privileged
    WRITE API — a CloudTrail iam:CreateRole trace under the caller's name,
    security alerts on a monitored account. It's therefore only issued with
    `--formateur`, the only profile that needs iam:CreateRole (`make
    socle-apply`). The default, learner mode issues NO IAM write call at
    all.
    """
    try:
        config.client("iam").create_role(
            RoleName="qc-preflight-probe", AssumeRolePolicyDocument="{}"
        )
    except Exception as exc:  # noqa: BLE001
        code = _code(exc)
        if code == "MalformedPolicyDocument":
            record(
                3,
                "Permissions",
                PASS,
                f"iam:CreateRole authorized ({reason}, direct non-mutating probe).",
                details=hints or [],
            )
            return
        if code == "AccessDenied":
            record(
                3,
                "Permissions",
                FAIL,
                "iam:CreateRole REFUSED — the socle can't create the SageMaker roles.",
                "Ask IT for iam:CreateRole, iam:PutRolePolicy, iam:GetRole and "
                "iam:PassRole, restricted to resources named qc-*.",
                details=[
                    "Without this right, `make socle-apply` creates the buckets then fails",
                    "on the six roles. Day 1 stops at the `train` step.",
                    *(hints or []),
                ],
            )
            return
        record(3, "Permissions", SKIP, f"iam:CreateRole probe inconclusive ({code}).")
        return

    # Should never happen: an empty document isn't a valid policy.
    record(3, "Permissions", SKIP, "Unexpected iam:CreateRole probe result — a role may have been created.")


def check_permissions(caller_arn: str | None, formateur: bool = False) -> None:
    if not caller_arn:
        record(3, "Permissions", SKIP, "Unknown identity, check impossible.")
        return

    # simulate-principal-policy wants the ROLE's ARN, not the assumed
    # session's.
    principal = caller_arn
    if ":assumed-role/" in caller_arn:
        account = caller_arn.split(":")[4]
        role = caller_arn.split("/")[1]
        principal = f"arn:aws:iam::{account}:role/{role}"

    # The verdict rests on the REAL PROBE, never on the simulation.
    #
    # Reason, observed on 07/27/2026 across two successive sets of
    # permissions: called with no resource ARN, simulate_principal_policy
    # returns "denied" for any action covered by a policy scoped to
    # specific resources — i.e. almost all of them. The report announced
    # s3:PutObject as denied while check n°4, in the same run, was really
    # writing then deleting an object. A report that contradicts itself is
    # worthless in front of IT.
    #
    # The simulation stays useful as a hint, never as a verdict.
    hints: list[str] = []
    denied: list[str] | None = None
    try:
        resp = config.client("iam").simulate_principal_policy(
            PolicySourceArn=principal, ActionNames=REQUIRED_ACTIONS
        )
        denied = [
            r["EvalActionName"]
            for r in resp["EvaluationResults"]
            if r["EvalDecision"] != "allowed"
        ]
        if denied:
            hints = [
                f"simulation: {len(denied)}/{len(REQUIRED_ACTIONS)} actions reported as denied,",
                "to confirm via checks 4 through 10 — the simulation ignores resource-level",
                "scoping and produces false denials.",
            ]
        else:
            hints = [f"simulation: {len(REQUIRED_ACTIONS)} actions authorized"]
        reason = "simulation available"
    except Exception as exc:  # noqa: BLE001
        # Common on an SSO role. This case used to produce a SKIP, and that
        # SKIP let a role with no iam:CreateRole through: the blocker only
        # showed up in the middle of the socle's `terraform apply`, six
        # failures in a row.
        reason = f"simulation unavailable ({_code(exc)})"

    if formateur:
        _probe_iam_write(reason, hints)
        return

    # LEARNER mode (default): reads only, NO IAM write call — the
    # create_role probe is reserved for `--formateur` (see
    # _probe_iam_write). A learner has no need for iam:CreateRole anyway:
    # only `make socle-apply` creates roles, and that's a trainer action.
    # Their real rights are exercised by checks 4 through 10, via
    # non-privileged probes.
    footer = [
        "Learner mode: no IAM write probe is issued.",
        "Full check of the socle's rights: `uv run scripts/preflight.py --formateur`.",
    ]
    if denied == []:
        record(
            3,
            "Permissions",
            PASS,
            f"{reason} — the {len(REQUIRED_ACTIONS)} actions of the course are authorized.",
            details=footer,
        )
    else:
        # Simulated denials (frequent false negatives) or simulation
        # unavailable: the verdict belongs to the following checks' real
        # probes, not to a FAIL here — a report that contradicts itself is
        # worthless in front of IT.
        record(3, "Permissions", SKIP, f"{reason}.", details=[*hints, *footer])


# ============================================================================ 4
def check_s3() -> None:
    s3 = config.client("s3")
    bucket = config.s3_bucket
    key = f"preflight/{config.team_id}-probe.txt"

    try:
        s3.head_bucket(Bucket=bucket)
    except Exception as exc:  # noqa: BLE001
        record(
            4,
            "S3",
            FAIL,
            f"Bucket {bucket} unreachable ({_code(exc)}).",
            "Apply the Terraform socle, which creates the group's bucket.",
            needs_socle=True,
        )
        return

    details = []
    try:
        s3.put_object(Bucket=bucket, Key=key, Body=b"preflight")
        s3.delete_object(Bucket=bucket, Key=key)
        details.append("write then delete: OK")
    except Exception as exc:  # noqa: BLE001
        record(
            4,
            "S3",
            FAIL,
            f"Write refused on {bucket} ({_code(exc)}).",
            "Check the group role's policy on this bucket.",
        )
        return

    try:
        s3.get_bucket_encryption(Bucket=bucket)
        details.append("encryption at rest: enabled")
    except Exception:  # noqa: BLE001
        details.append("encryption at rest: ABSENT")

    try:
        pab = s3.get_public_access_block(Bucket=bucket)["PublicAccessBlockConfiguration"]
        details.append(
            "public access block: "
            + ("full" if all(pab.values()) else "INCOMPLETE")
        )
    except Exception:  # noqa: BLE001
        details.append("public access block: NOT CONFIGURED")

    bad = [d for d in details if "ABSENT" in d or "INCOMPLETE" in d or "NOT" in d]
    record(
        4,
        "S3",
        FAIL if bad else PASS,
        f"{bucket}",
        "Fix the Terraform socle: encryption and public-access blocking are required (§14).",
        details=details,
    )


# ============================================================================ 5
def check_sagemaker_quotas() -> None:
    needed = config.teams_count
    details = []
    ok = True
    try:
        sq = config.client("service-quotas")
        paginator = sq.get_paginator("list_service_quotas")
        quotas = {
            q["QuotaName"].lower(): q["Value"]
            for page in paginator.paginate(ServiceCode="sagemaker")
            for q in page["Quotas"]
        }
    except Exception as exc:  # noqa: BLE001
        record(
            5,
            "SageMaker quotas",
            SKIP,
            f"Service Quotas unreadable ({_code(exc)}).",
            details=[f"To verify in console: {needed} simultaneous groups expected."],
        )
        return

    for instance, kind, label in (
        (config.train_instance, "training job usage", "training"),
        (config.endpoint_instance, "endpoint usage", "endpoint"),
    ):
        value = quotas.get(f"{instance} for {kind}".lower())
        if value is None:
            details.append(f"{instance} ({label}): quota not found")
            continue
        got = int(value)
        verdict = "OK" if got >= needed else "INSUFFICIENT"
        details.append(f"{instance} ({label}): {got} for {needed} groups — {verdict}")
        ok &= got >= needed

    record(
        5,
        "SageMaker quotas",
        PASS if ok else FAIL,
        f"{needed} pairs declared (TEAMS_COUNT).",
        "Request a quota increase: all groups deploy at the same time.",
        details=details,
    )


# ============================================================================ 6
def check_sagemaker_role() -> None:
    arn = config.sagemaker_role_arn
    if not arn:
        record(
            6,
            "SageMaker role",
            FAIL,
            "SAGEMAKER_ROLE_ARN not set.",
            "Ask your trainer for your group's `.env` snippet.",
            needs_socle=True,
        )
        return
    try:
        role = config.client("iam").get_role(RoleName=arn.split("/")[-1])["Role"]
    except Exception as exc:  # noqa: BLE001
        record(
            6,
            "SageMaker role",
            FAIL,
            f"Role not found or unreadable ({_code(exc)}).",
            "Check SAGEMAKER_ROLE_ARN and the iam:GetRole right.",
            needs_socle=True,
        )
        return

    doc = str(role.get("AssumeRolePolicyDocument", ""))
    trusted = "sagemaker.amazonaws.com" in doc
    record(
        6,
        "SageMaker role",
        PASS if trusted else FAIL,
        f"{role['RoleName']}",
        "The trust policy must authorize sagemaker.amazonaws.com.",
        details=["sagemaker.amazonaws.com trust: " + ("OK" if trusted else "MISSING")],
    )


# ============================================================================ 7
def check_bedrock() -> None:
    """Check fixed relative to §12 (decision D6).

    The original spec requires BEDROCK_MODEL_ID to appear in
    `list_foundation_models`. That's wrong for Europe: recent models are
    invoked via an inference profile prefixed `eu.` or `global.`, which
    only appears in `list_inference_profiles`. And above all, being in the
    catalog doesn't mean access — only the real call proves it.
    """
    model_id = config.bedrock_model_id
    if not model_id:
        record(
            7,
            "Bedrock",
            FAIL,
            "BEDROCK_MODEL_ID not set.",
            "Run `uv run scripts/discover.py` to find an enabled model.",
        )
        return

    details = []
    try:
        bedrock = config.client("bedrock")
        catalog = {
            m["modelId"] for m in bedrock.list_foundation_models()["modelSummaries"]
        }
        profiles = {
            p["inferenceProfileId"]
            for p in bedrock.list_inference_profiles()["inferenceProfileSummaries"]
        }
        where = (
            "catalog"
            if model_id in catalog
            else "inference profiles"
            if model_id in profiles
            else None
        )
        details.append(
            f"referenced in: {where}" if where else "NOT referenced (neither catalog nor profiles)"
        )
    except Exception as exc:  # noqa: BLE001
        details.append(f"listing unavailable ({_code(exc)})")

    runtime = config.client("bedrock-runtime")

    try:
        runtime.converse(
            modelId=model_id,
            messages=[{"role": "user", "content": [{"text": "OK"}]}],
            inferenceConfig={"maxTokens": 5},
        )
    except Exception as exc:  # noqa: BLE001
        record(
            7,
            "Bedrock",
            FAIL,
            f"Converse call refused on {model_id} ({_code(exc)}).",
            "Enable the model (Bedrock console -> Model access) or check the "
            "role's IAM policy. See decision D14.",
            details=details,
        )
        return

    details.append("simple Converse call: OK")

    # Tool use is the agent's ONLY hard constraint on Day 2, and a model
    # can perfectly well accept Converse while refusing tool use (decision
    # D15: exactly Mistral's case in streaming mode). A preflight that
    # stops at the simple call would go green on a model that breaks the
    # afternoon lab.
    try:
        runtime.converse(
            modelId=model_id,
            messages=[
                {
                    "role": "user",
                    "content": [{"text": "Latency of the qc-g01-endpoint endpoint?"}],
                }
            ],
            inferenceConfig={"maxTokens": 128},
            toolConfig={
                "tools": [
                    {
                        "toolSpec": {
                            "name": "get_endpoint_metrics",
                            "description": "Average latency of a SageMaker endpoint.",
                            "inputSchema": {
                                "json": {
                                    "type": "object",
                                    "properties": {"endpoint_name": {"type": "string"}},
                                    "required": ["endpoint_name"],
                                }
                            },
                        }
                    }
                ]
            },
        )
    except Exception as exc:  # noqa: BLE001
        details.append(f"tool use: REFUSED ({_code(exc)})")
        record(
            7,
            "Bedrock",
            FAIL,
            f"{model_id} accepts Converse but refuses tool use.",
            "Choose a model that supports tool use — Day 2's agent depends on it. "
            "Run `make probe` to test candidates and Strands-driven piloting.",
            details=details,
        )
        return

    details.append("tool use: OK")
    details.append(
        "reminder D15: Strands must be instantiated with streaming=False on this model"
    )
    record(7, "Bedrock", PASS, model_id, details=details)


# ============================================================================ 8
def check_ecr() -> None:
    try:
        ecr = config.client("ecr")
        ecr.get_authorization_token()
    except Exception as exc:  # noqa: BLE001
        record(
            8,
            "ECR",
            FAIL,
            f"get_authorization_token fails ({_code(exc)}).",
            "Add ecr:GetAuthorizationToken to the group's role.",
        )
        return
    try:
        ecr.describe_repositories(repositoryNames=[config.ecr_repo])
        detail = f"repo {config.ecr_repo}: exists"
    except Exception:  # noqa: BLE001
        detail = f"repo {config.ecr_repo}: absent (created by the socle)"
    record(8, "ECR", PASS, details=[detail, "authorization token: OK"])


# ============================================================================ 9
def check_ecs_alb_acm() -> None:
    details, ok = [], True

    try:
        clusters = config.client("ecs").describe_clusters(clusters=[config.ecs_cluster])
        found = bool(clusters["clusters"])
        details.append(f"cluster {config.ecs_cluster}: " + ("OK" if found else "ABSENT"))
        ok &= found
    except Exception as exc:  # noqa: BLE001
        details.append(f"cluster: error ({_code(exc)})")
        ok = False

    try:
        svc = config.client("ecs").describe_services(
            cluster=config.ecs_cluster, services=[config.ecs_service]
        )
        found = bool(svc["services"])
        details.append(f"service {config.ecs_service}: " + ("OK" if found else "ABSENT"))
        ok &= found
    except Exception as exc:  # noqa: BLE001
        details.append(f"service: error ({_code(exc)})")
        ok = False

    # ACM: degraded mode chosen (§14). An empty ARN is the NORMAL value, not a gap.
    if not config.acm_cert_arn:
        details.append("ACM: not used — degraded HTTP mode assumed (§14)")
    else:
        try:
            cert = config.client("acm").describe_certificate(
                CertificateArn=config.acm_cert_arn
            )["Certificate"]
            issued = cert["Status"] == "ISSUED"
            details.append(f"ACM certificate: {cert['Status']}")
            ok &= issued
        except Exception as exc:  # noqa: BLE001
            details.append(f"ACM certificate: error ({_code(exc)})")
            ok = False

    if config.alb_dns_name:
        try:
            socket.gethostbyname(config.alb_dns_name)
            details.append(f"{config.alb_dns_name}: resolves")
        except OSError:
            details.append(f"{config.alb_dns_name}: DOES NOT RESOLVE")
            ok = False
    else:
        details.append("ALB_DNS_NAME not set")
        ok = False

    record(
        9,
        "ECS / ALB / ACM",
        PASS if ok else FAIL,
        action="Ask your trainer for your group's `.env` snippet.",
        needs_socle=True,
        details=details,
    )


# ============================================================================ 10
def check_cloudwatch() -> None:
    logs = config.client("logs")
    # The probe's name lives INSIDE the group's prefix: the workstation
    # role only allows log writes under /ecs/qc-<TEAM_ID>-*. A name outside
    # that scope (the old /preflight/<TEAM_ID>) made this check fail on
    # every learner machine even though the actually-needed rights were
    # there — observed on 08/10/2026.
    name = f"/ecs/qc-{config.team_id}-preflight-probe"
    try:
        logs.create_log_group(logGroupName=name)
        logs.delete_log_group(logGroupName=name)
    except Exception as exc:  # noqa: BLE001
        record(
            10,
            "CloudWatch Logs",
            FAIL,
            f"Creating/deleting a test group was refused ({_code(exc)}).",
            "Add logs:CreateLogGroup and logs:DeleteLogGroup to the group's role.",
        )
        return
    record(10, "CloudWatch Logs", PASS, details=["create then delete: OK"])


# ============================================================================ 11
def check_docker() -> None:
    if not shutil.which("docker"):
        record(
            11,
            "Docker",
            FAIL,
            "docker binary not found.",
            "Install Docker. On the workstations, it's provided by the golden AMI.",
        )
        return
    details = []
    try:
        subprocess.run(
            ["docker", "info"], capture_output=True, check=True, timeout=30
        )
        details.append("daemon: responding")
    except Exception:  # noqa: BLE001
        record(
            11,
            "Docker",
            FAIL,
            "The Docker daemon isn't responding.",
            "Start the Docker service.",
        )
        return
    try:
        out = subprocess.run(
            ["docker", "buildx", "ls"], capture_output=True, text=True, timeout=30
        ).stdout
        details.append("buildx: available")
        amd64 = "linux/amd64" in out
        details.append("linux/amd64 platform: " + ("supported" if amd64 else "ABSENT"))
        record(11, "Docker", PASS if amd64 else FAIL, details=details,
               action="Enable linux/amd64 emulation (§11 requires this platform).")
    except Exception:  # noqa: BLE001
        details.append("buildx: ABSENT")
        record(11, "Docker", FAIL, action="Install docker buildx.", details=details)


# ============================================================================ 12
def check_terraform() -> None:
    if not shutil.which("terraform"):
        record(
            12,
            "Terraform",
            FAIL,
            "terraform binary not found.",
            "Install Terraform >= 1.6.",
        )
        return
    try:
        out = subprocess.run(
            ["terraform", "version", "-json"],
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout
        import json

        version = json.loads(out)["terraform_version"]
    except Exception:  # noqa: BLE001
        record(12, "Terraform", FAIL, "Version unreadable.", "Check the installation.")
        return

    major, minor = (int(x) for x in version.split(".")[:2])
    ok = (major, minor) >= (1, 6)
    details = [f"version {version}"]

    tfdir = ROOT / "infra" / "terraform"
    if not tfdir.exists():
        details.append("infra/terraform/ absent — socle not yet written")
        record(12, "Terraform", PASS if ok else FAIL,
               action="Terraform >= 1.6 is required.", details=details)
        return

    try:
        subprocess.run(
            ["terraform", "init", "-backend=false"],
            cwd=tfdir, capture_output=True, check=True, timeout=180,
        )
        details.append("terraform init: OK")
    except Exception:  # noqa: BLE001
        details.append("terraform init: FAILED")
        ok = False

    record(12, "Terraform", PASS if ok else FAIL,
           action="Terraform >= 1.6 and a valid init are required.", details=details)


# ============================================================================ 13
def check_python() -> None:
    details = [f"interpreter {sys.version_info.major}.{sys.version_info.minor}"]

    lock = ROOT / "uv.lock"
    if not lock.exists():
        record(13, "Python", FAIL, "uv.lock absent.",
               "Run `make lock`. Without a lock, two pairs can install two "
               "different resolutions.", details=details)
        return
    if not shutil.which("uv"):
        record(13, "Python", SKIP, "uv not found, environment untested.",
               details=details)
        return

    # `--frozen` fails if uv.lock no longer matches pyproject.toml: this
    # validates both the lock's consistency AND that everything imports
    # together.
    imports = "import boto3, strands, evidently, mlflow, sagemaker_mlflow, streamlit"
    try:
        subprocess.run(
            ["uv", "run", "--frozen", "python", "-c", imports],
            cwd=ROOT, capture_output=True, check=True, timeout=900,
        )
        details.append("uv.lock consistent with pyproject.toml, imports OK")
        record(13, "Python", PASS, details=details)
    except subprocess.CalledProcessError as exc:
        tail = (exc.stderr or b"").decode(errors="replace").strip().splitlines()[-3:]
        details.extend(tail)
        record(13, "Python", FAIL, "Lock out of sync or import failed.",
               "Run `make lock` then rerun preflight.", details=details)
    except subprocess.TimeoutExpired:
        record(13, "Python", SKIP, "Install taking too long (>15 min).", details=details)


# ============================================================================ 14
def check_mlflow() -> None:
    """Check made BLOCKING by decision D8.

    §12 planned a SKIP if MLFLOW_TRACKING_URI was empty. That's no longer
    tenable: Day 3's fil-rouge lab 6 logs its Evidently reports to MLflow.
    A green preflight with no MLflow would mean half a day of lab with no
    target.
    """
    uri = config.mlflow_tracking_uri
    if not uri:
        record(
            14,
            "MLflow",
            FAIL,
            "MLFLOW_TRACKING_URI not set.",
            "Ask your trainer for the `.env` snippet updated after the tracking server was created.",
            needs_socle=True,
        )
        return
    try:
        sm = config.client("sagemaker")
        name = uri.split("/")[-1]
        info = sm.describe_mlflow_tracking_server(TrackingServerName=name)
        status = info["TrackingServerStatus"]
        ok = status == "Created"
        record(
            14,
            "MLflow",
            PASS if ok else FAIL,
            f"tracking server {name}",
            "Wait for provisioning to finish, or recreate the server.",
            details=[f"status: {status}", f"group's experiment: {config.mlflow_experiment}"],
        )
    except Exception as exc:  # noqa: BLE001
        record(
            14,
            "MLflow",
            FAIL,
            f"Tracking server unreachable ({_code(exc)}).",
            "Check MLFLOW_TRACKING_URI and the sagemaker-mlflow right on the role.",
            needs_socle=True,
        )


# ============================================================================ 15
def check_costs() -> None:
    record(
        15,
        "Costs and tags",
        PASS,
        "A reminder, not a blocking check.",
        details=[
            f"{config.endpoint_instance} endpoint: billed as long as it runs — "
            "turn it off every evening",
            "Fargate service and NAT gateway: billed continuously",
            "MLflow tracking server: billed hourly",
            "tags applied: " + ", ".join(f"{k}={v}" for k, v in config.tags.items()),
            "`make destroy` relies on these tags — without them, nothing gets cleaned up",
        ],
    )


# ============================================================================
def write_report() -> None:
    lines = [
        "# Preflight report",
        "",
        f"- Region: `{config.region}`",
        f"- Group: `{config.team_id}`",
        f"- Bedrock model: `{config.bedrock_model_id or '(not set)'}`",
        "",
        "This report can be attached as-is to an access request.",
        "",
        "| # | Check | Status | Cause |",
        "| --- | --- | --- | --- |",
    ]
    for r in results:
        lines.append(f"| {r.number} | {r.name} | **{r.status}** | {r.cause or '\u2014'} |")

    failures = [r for r in results if r.status == FAIL]
    if failures:
        lines += ["", "## Failures and corrective actions", ""]
        for r in failures:
            lines.append(f"### {r.number}. {r.name}")
            lines.append("")
            if r.cause:
                lines.append(f"- Cause: {r.cause}")
            for d in r.details:
                lines.append(f"- {d}")
            if r.action:
                lines.append(f"- **Action**: {r.action}")
            if r.needs_socle:
                lines.append(
                    "- This check depends on the Terraform socle. A failure is **normal** "
                    "until `make socle-apply` has been run."
                )
            lines.append("")

    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="15 checks before creating any resource."
    )
    parser.add_argument(
        "--formateur",
        action="store_true",
        help="enables the iam:CreateRole write probe (needed for `make"
        " socle-apply`). By default — learner mode — no IAM write call"
        " is issued.",
    )
    options = parser.parse_args(argv)

    print()
    print("=" * 72)
    mode = "trainer" if options.formateur else "learner"
    print(
        f"  Preflight ({mode}) — {config.project} — group {config.team_id} — {config.region}"
    )
    print("=" * 72)
    print()

    caller = check_identity()
    check_region()
    check_permissions(caller, formateur=options.formateur)
    check_s3()
    check_sagemaker_quotas()
    check_sagemaker_role()
    check_bedrock()
    check_ecr()
    check_ecs_alb_acm()
    check_cloudwatch()
    check_docker()
    check_terraform()
    check_python()
    check_mlflow()
    check_costs()

    write_report()

    failures = [r for r in results if r.status == FAIL]
    socle_only = [r for r in failures if r.needs_socle]

    print()
    print("=" * 72)
    counts = {s: sum(1 for r in results if r.status == s) for s in (PASS, FAIL, SKIP)}
    print(f"  {counts[PASS]} PASS \u00b7 {counts[FAIL]} FAIL \u00b7 {counts[SKIP]} SKIP")
    if failures:
        print()
        print("  Failures: " + ", ".join(f"{r.number}. {r.name}" for r in failures))
        if len(socle_only) == len(failures):
            print()
            print("  All these failures depend on the Terraform socle, not yet applied.")
            print("  That's the expected behavior at this stage.")
    print(f"  Report written to {REPORT.name}")
    print("=" * 72)
    print()

    return 1 if failures else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ConfigError as exc:
        print(f"\nInvalid configuration.\n\n{exc}\n", file=sys.stderr)
        sys.exit(1)
