#!/usr/bin/env python3
"""IAM lint — every `resources = ["*"]` must carry its justification, on its own line.

07/29/2026 review, point 8. Point 2 showed the cost of an unquestioned
wildcard: `elasticloadbalancing` writes on `*` let one pair delete another's
ALB rule. This lint doesn't forbid them — some AWS actions accept no
resource-level restriction at all — it requires each one to be a written
DECISION:

    resources = ["*"] // GetMetricData doesn't accept a resource-level restriction

A wildcard with no trailing comment is an error. The justification lives on
the line itself, not in prose above it: that's what makes it checkable, and
what forces it to be rewritten whenever the statement gets copy-pasted.

    uv run scripts/lint_iam.py            # part of `make ci`

Exit 0 if every wildcard is justified, 1 otherwise.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TERRAFORM = ROOT / "infra" / "terraform"

#: A resource wildcard, followed — or not — by a justification comment.
WILDCARD = re.compile(r'^\s*resources\s*=\s*\[\s*"\*"\s*\]\s*(?P<justification>//.*)?$')


def violations(root: Path = TERRAFORM) -> list[str]:
    """`resources = ["*"]` lines with no justification, as file:line."""
    unjustified: list[str] = []
    for file in sorted(root.rglob("*.tf")):
        for number, line in enumerate(
            file.read_text(encoding="utf-8").splitlines(), start=1
        ):
            match = WILDCARD.match(line)
            if match and not match.group("justification"):
                path = file.relative_to(ROOT) if file.is_relative_to(ROOT) else file
                unjustified.append(f"{path}:{number}")
    return unjustified


def main() -> int:
    found = violations()
    if found:
        print("resources = [\"*\"] with no trailing justification:\n")
        for item in found:
            print(f"  {item}")
        print(
            "\nEither restrict by ARN/prefix/condition, or write why that's"
            "\nimpossible — on the line itself: resources = [\"*\"] // <reason>"
        )
        return 1
    print("IAM lint: every resource wildcard is justified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
