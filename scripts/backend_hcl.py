#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["boto3>=1.35"]
# ///
"""
Regenerates `infra/terraform/socle/backend.hcl` without going through the bootstrap module.

Why this script exists: `backend.hcl` is gitignored (it carries an account
ID), and it used to be produced only by `make bootstrap-apply`, whose state
is LOCAL. On a fresh clone — a contractor trainer's machine, an admin EC2 —
the local state is absent: `bootstrap-apply` tries to recreate the bucket,
fails because it already exists, and the line that writes `backend.hcl` is
never reached. Everything else then blocks in a cascade: `socle-init`, then
`team-init` which reads the same file.

But `backend.hcl`'s five lines are entirely deterministic: the bucket name
derives from the calling account, exactly as in the bootstrap module and in
`qc.config`. No Terraform state is needed to reconstruct them.

    make backend-hcl

The script verifies that the bucket really exists. If it doesn't, that means
bootstrap was never applied on this account: it points to `make
bootstrap-apply` instead of writing a file that would point at nothing.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "infra" / "terraform" / "socle" / "backend.hcl"


def main() -> int:
    region = os.environ.get("AWS_REGION", "eu-west-3")

    try:
        account = boto3.client("sts", region_name=region).get_caller_identity()["Account"]
    except ClientError as exc:
        print(f"AWS identity unavailable: {exc}", file=sys.stderr)
        print("Check your credentials (aws sts get-caller-identity).", file=sys.stderr)
        return 1

    # Same derivation as bootstrap/main.tf and qc.config: the last six digits.
    bucket = f"qc-promo-tfstate-{account[6:12]}"

    try:
        boto3.client("s3", region_name=region).head_bucket(Bucket=bucket)
    except ClientError:
        print(f"State bucket {bucket} not found on account {account}.", file=sys.stderr)
        print("Bootstrap has never run here: make bootstrap-apply", file=sys.stderr)
        return 1

    TARGET.write_text(
        f'bucket       = "{bucket}"\n'
        'key          = "socle/terraform.tfstate"\n'
        f'region       = "{region}"\n'
        "encrypt      = true\n"
        "use_lockfile = true\n"
    )
    print(f"backend.hcl written — bucket {bucket}, region {region}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
