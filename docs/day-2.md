# Day 2 — From the endpoint to the app in service · the essentials

This document summarizes the essentials of the day: objective, hard points, control
commands.

## Objective of the day

```
tooled Bedrock agent -> Docker image -> push to ECR -> team Terraform module -> app behind the ALB
```

Morning: a Strands agent on Mistral Large that calls four tools (including the Day 1
endpoint). Afternoon: the containerized Streamlit application, pushed to ECR,
deployed to ECS, served by the shared ALB on `/gNN/*`.

Resuming Day 1: `make restore-day1` for the AWS state, tag `j1-fin` for the code.

## The hard points — where pairs get stuck

1. **Bedrock model**: `mistral.mistral-large-2402-v1:0` only — Nova and Anthropic
   are in the catalog but return `AccessDenied` (D14). Being in the catalog doesn't
   mean access (D6).
2. **Strands**: `BedrockModel(..., streaming=False)` is mandatory, otherwise tool use
   breaks on this model (D15).
3. **The URL prefix — Day 2's classic failure**: Streamlit must start with
   `--server.baseUrlPath=<TEAM_ID>`, otherwise a blank page behind the ALB with a
   perfectly healthy ECS task (D12). On the client side, `browser.serverAddress`
   fixes the websocket.
4. **Docker image**: build for `linux/amd64` (buildx on Mac ARM) — verifiable before
   push with `docker inspect --format '{{.Os}}/{{.Architecture}}'`. The order of the
   Dockerfile instructions determines rebuild time (dependencies before code).
5. **Two ECS roles, the distinction of the day**: `ecs-exec` starts the task (pulls
   the image, writes logs), `ecs-task` makes it work (calls the endpoint, Bedrock).
6. **Two modules, two states**: the socle (trainer) and `team/` (pair, separate
   state under `team/<TEAM_ID>/`). The team module only creates the ECS service and
   its attachment to the target group — the ALB and its routing are pre-created by
   the socle.

## Control commands

```
make check-day2                 # 8 result checks, per pair
make restore-day2               # incremental catch-up on Day3 morning
```

Code catch-up: `git checkout -b day-3 j2-fin`.

Diagnostic when the app doesn't respond, in order: is the ECS task running -> is the
health check green in the target group -> the logs at `/ecs/qc-gNN-app` -> the URL
prefix (point 3 above).

## Where the code lives

`src/qc/agent.py` (agent and tools), `app/main.py` (Streamlit), `Dockerfile`,
`infra/terraform/team/` (pair module).
