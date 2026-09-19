# Project targets. `make` with no argument shows this help.
#
# Scripts declare their dependencies inline (PEP 723): uv resolves them in a
# throwaway environment. No global install, no need for the AWS CLI.

.DEFAULT_GOAL := help
.PHONY: help discover probe preflight preflight-formateur bootstrap-apply socle-init \
        socle-plan socle-apply socle-destroy backend-hcl  \
        team-init team-plan team-apply team-destroy   \
          check-day1 check-day2 check-day3 \
        restore-day1 restore-day2   destroy sync test ci  lock

UV := uv run

help: ## Show this help
	@echo ""
	@echo "  the-company — AWS for Data Scientists"
	@echo ""
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "  The labs go through the qc command, not make:"
	@echo "    uv run qc          where the pair currently stands"
	@echo "    uv run qc <step>  runs that step"
	@echo ""
	@echo "  Required order: preflight green BEFORE creating any resource (§12)."
	@echo ""

# --- Diagnostics ---------------------------------------------------------------

discover: ## Probe the AWS account (creates nothing) — models, quotas, services
	@$(UV) scripts/discover.py

probe: ## Verify Bedrock model access and Strands-driven piloting
	@$(UV) scripts/probe_model.py

preflight: ## 15 mandatory checks before creating any resource (learner mode: no IAM writes)
	@$(UV) scripts/preflight.py

preflight-formateur: ## [trainer] Preflight with the iam:CreateRole probe, required before socle-apply
	@$(UV) scripts/preflight.py --formateur

# --- Socle, trainer side ----------------------------------------------------

TF_BOOTSTRAP := infra/terraform/bootstrap
TF_SOCLE     := infra/terraform/socle

bootstrap-apply: ## [trainer] Step 1 — creates the Terraform state bucket (once only)
	@# This module's state is LOCAL and gitignored: on a fresh clone, Terraform
	@# thinks the bucket doesn't exist and the apply fails on a bucket that's
	@# already taken. Bootstrap should only run once in the training's lifetime;
	@# after that it's `make backend-hcl` that regenerates the file, with no
	@# state and no apply.
	@if $(UV) scripts/backend_hcl.py 2>/dev/null; then \
	  echo "State bucket already in place — bootstrap already applied, nothing to create."; \
	  echo "Follow up with: make socle-init"; \
	else \
	  cd $(TF_BOOTSTRAP) && terraform init && terraform apply \
	    && terraform output -raw backend_config > ../socle/backend.hcl \
	    && echo "backend.hcl generated. Follow up with: make socle-init"; \
	fi

backend-hcl: ## [trainer] Regenerate socle/backend.hcl from the current account (fresh clone)
	@$(UV) scripts/backend_hcl.py

socle-init: ## [trainer] Step 2 — initializes the socle on its remote backend
	@test -f $(TF_SOCLE)/backend.hcl || $(MAKE) --no-print-directory backend-hcl
	@cd $(TF_SOCLE) && terraform init -backend-config=backend.hcl

socle-plan: ## [trainer] Shows what would be created, without creating anything
	@cd $(TF_SOCLE) && terraform plan

socle-apply: ## [trainer] Step 3 — applies the socle
	@# AMI safeguard: turning on eight machines with no golden AMI means eight
	@# full bootstraps in parallel over a single NAT gateway — a wasted quarter
	@# hour, the evening before.
	@if grep -qE '^create_workstations *= *true' $(TF_SOCLE)/terraform.tfvars 2>/dev/null \
	  && grep -qE '^workstation_ami_id *= *"" ' $(TF_SOCLE)/terraform.tfvars 2>/dev/null; then \
	  echo ""; \
	  echo "  WARNING: create_workstations = true but workstation_ami_id is empty."; \
	  echo "  The machines will start with a slow bootstrap (~10 min each)."; \
	  echo "  Build the AMI first: make ami-build  (it fills in tfvars by itself)"; \
	  echo ""; \
	fi
	@cd $(TF_SOCLE) && terraform apply


socle-destroy: ## [trainer] Destroys the socle at the end of the training
	@cd $(TF_SOCLE) && terraform destroy
	@echo "The state bucket deliberately survives (prevent_destroy)."
	@echo "Delete it by hand once the training is fully wrapped up."

# --- Team module, learner side ----------------------------------------------

TF_TEAM := infra/terraform/team

# The state bucket comes from the learner's `.env`. On the solution repo, the
# fallback to backend.hcl stays convenient for the trainer; this file is
# deliberately absent from the starter, since it depends on the training AWS
# account.
TF_STATE_BUCKET ?= $(shell sed -n 's/^bucket *= *"\(.*\)"/\1/p' $(TF_SOCLE)/backend.hcl 2>/dev/null)

TEAM_TF_VARS = -var="team_id=$(TEAM_ID)" -var="owner_email=$(OWNER_EMAIL)" -var="state_bucket=$(TF_STATE_BUCKET)"

team-init: ## Initializes the pair's module — usage: make team-init TEAM_ID=g01
	@test -n "$(TEAM_ID)" || (echo "Usage: make team-init TEAM_ID=g01"; exit 1)
	@test -n "$(TF_STATE_BUCKET)" \
	  || (echo "State bucket not found — set TF_STATE_BUCKET in .env, or (trainer): make backend-hcl"; exit 1)
	@cd $(TF_TEAM) && terraform init \
	  -backend-config="bucket=$(TF_STATE_BUCKET)" \
	  -backend-config="key=team/$(TEAM_ID)/terraform.tfstate" \
	  -backend-config="region=$${AWS_REGION:-eu-west-3}" \
	  -backend-config="encrypt=true" \
	  -backend-config="use_lockfile=true"

team-plan: ## Shows what the pair would create — make team-plan TEAM_ID=g01
	@test -n "$(TEAM_ID)" || (echo "Usage: make team-plan TEAM_ID=g01"; exit 1)
	@test -n "$(OWNER_EMAIL)" || (echo "OWNER_EMAIL missing — set it in .env then: set -a; . ./.env; set +a"; exit 1)
	@test -n "$(TF_STATE_BUCKET)" || (echo "TF_STATE_BUCKET missing — ask your trainer for your group's .env snippet then reload .env"; exit 1)
	@cd $(TF_TEAM) && terraform plan $(TEAM_TF_VARS)

team-apply: ## Deploys the pair's application — make team-apply TEAM_ID=g01
	@test -n "$(TEAM_ID)" || (echo "Usage: make team-apply TEAM_ID=g01"; exit 1)
	@test -n "$(OWNER_EMAIL)" || (echo "OWNER_EMAIL missing — set it in .env then: set -a; . ./.env; set +a"; exit 1)
	@test -n "$(TF_STATE_BUCKET)" || (echo "TF_STATE_BUCKET missing — ask your trainer for your group's .env snippet then reload .env"; exit 1)
	@cd $(TF_TEAM) && terraform apply $(TEAM_TF_VARS)

team-destroy: ## Removes the pair's resources, never the socle
	@test -n "$(TEAM_ID)" || (echo "Usage: make team-destroy TEAM_ID=g01"; exit 1)
	@test -n "$(OWNER_EMAIL)" || (echo "OWNER_EMAIL missing — set it in .env then: set -a; . ./.env; set +a"; exit 1)
	@test -n "$(TF_STATE_BUCKET)" || (echo "TF_STATE_BUCKET missing — ask your trainer for your group's .env snippet then reload .env"; exit 1)
	@cd $(TF_TEAM) && terraform destroy $(TEAM_TF_VARS)




# --- Verification, learner side ---------------------------------------------

check-day1: ## Verifies the expected AWS state at the end of Day 1
	@$(UV) scripts/check_day1.py

check-day2: ## Verifies the expected AWS state at the end of Day 2
	@$(UV) scripts/check_day2.py

check-day3: ## Verifies the expected AWS state at the end of Day 3
	@$(UV) scripts/check_day3.py



# --- Catch-up ------------------------------------------------------------------

restore-day1: ## Replays what's missing from Day 1: S3, training, endpoint (~15 min)
	@$(UV) scripts/restore_day1.py $(ARGS)

restore-day2: ## Replays what's missing from Day 2: Day1, image, push to ECR (~10 min)
	@$(UV) scripts/restore_day2.py $(ARGS)

# --- Misc -------------------------------------------------------------------

sync: ## Installs the environment from uv.lock
	@uv sync --frozen

test: ## Runs the test suite
	@$(UV) --frozen pytest tests/

ci: ## Everything CI checks: fmt, validate (bootstrap/socle/team), IAM lint, tests
	@terraform fmt -check -recursive infra/terraform
	@# Throwaway TF_DATA_DIR: a local `terraform init` may have configured the S3
	@# backend under .terraform/, and reading it back would require credentials —
	@# irrelevant here.
	@for module in bootstrap socle team; do \
		donnees=$$(mktemp -d); \
		echo "terraform validate — $$module"; \
		(cd infra/terraform/$$module \
			&& TF_DATA_DIR=$$donnees terraform init -backend=false -input=false > /dev/null \
			&& TF_DATA_DIR=$$donnees terraform validate) || exit 1; \
		rm -rf $$donnees; \
	done
	@$(UV) scripts/lint_iam.py
	@$(UV) --frozen pytest tests/

lock: ## Freezes the dependencies (uv.lock) and regenerates requirements.txt
	@uv lock
	@# requirements.txt is a GENERATED ARTIFACT, kept for the traceability
	@# required by §13. The source of truth is pyproject.toml.
	@uv export --no-hashes --no-dev --format requirements-txt -o requirements.txt -q
	@echo "Checking imports..."
	@$(UV) --frozen python -c \
	  "import boto3, strands, evidently, mlflow, sagemaker_mlflow, streamlit"
	@echo "OK — $$(grep -c '^[a-zA-Z0-9]' requirements.txt) packages frozen."

destroy: ## Removes what the labs bill for — endpoint then ECS service
	@test -n "$(TEAM_ID)" || (echo "Usage: make destroy TEAM_ID=g01"; exit 1)
	@$(UV) qc teardown
	@cd $(TF_TEAM) && terraform destroy -var="team_id=$(TEAM_ID)"
	@echo ""
	@echo "The ECR image and S3 artifact remain: they cost almost nothing and let"
	@echo "you redeploy without rebuilding. make socle-destroy takes them down too."
