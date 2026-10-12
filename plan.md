# Project Plan: Natural-Language-to-Infrastructure Agent (with Deploy-and-Verify)

> Working title: **InfraPilot** (rename it whenever you like)

## 1. What this project is

A user describes the infrastructure they want in plain English. A model writes Terraform for it. The system then **proves the code works**: it validates and plans it, scans it for security problems, estimates its cost, checks it against safety rules, actually deploys it into a sandbox, runs smoke tests against the live resources, and destroys everything. Failures are fed back to the model so it can fix its own code. The user gets back verified Terraform plus a report.

**Why it's better than asking a chatbot:** a chatbot can't run anything, so it can't know whether its Terraform works. This system measures that. The headline findings are:
1. the gap between "passes `terraform plan`" and "actually works when deployed", and
2. how a small local model compares with a Bedrock model, and how much of that gap the retry loop closes.

**Cost strategy:** build and debug everything on a **local open-source model** on your laptop first (free). Only switch to Bedrock and real AWS deploys once the pipeline works.

> Note: "local model" here means **running** (inference) an existing open-source model, not training or fine-tuning one. No training is needed for this project.

### End-to-end flow

```
English request
   │
   ▼
[Generate]  Model backend (local Ollama model OR Bedrock) → Terraform files + expected behaviours
   │
   ▼
[Static checks]  terraform validate → terraform plan → Checkov scan → Infracost estimate
   │
   ▼
[Plan guard]  policy check on plan JSON (allowed resource types, cost cap, rules)
   │
   ▼
[Deploy]  terraform apply into sandbox (unique state per run, run-ID tags)
   │
   ▼
[Verify]  hand-written smoke-test probes against live resources
   │
   ▼
[Destroy]  always — even on failure or crash
   │
   ├── any failure → errors sent back to the model → retry (max 3–5 attempts)
   ▼
Output: Terraform files, design summary, security findings, cost estimate, verification report
```

---

## 2. Ground rules for using Claude Code

Claude Code types the code. **You** make every decision about how things connect.

**You do yourself**
- Architecture diagrams and design decisions (what triggers what, where state lives, what happens on failure)
- Choosing AWS services and how they connect
- Every IAM policy and security group: read it, understand it, trim it to least privilege
- The agent loop design: which tools, when it stops, retry limits
- The model backend interface design (Phase 2) — this is what makes the local → Bedrock switch painless
- The smoke-test probe *design* (what each probe checks and why)
- Debugging with logs and the AWS console before asking for help
- The first time you meet any new Terraform resource: create it by hand in the console first

**Claude Code can do**
- Writing function bodies, CLI scaffolding, boilerplate, Dockerfiles, tests
- Terraform *syntax* once you've decided which resources and settings you want
- Parsing JSON (plan output, scanner output), formatting reports

**Rules**
1. Before each phase, write a short note (5–10 lines) on what you're building and how it connects. Give that note to Claude Code as context.
2. Prompt one piece at a time ("write a function that runs `terraform plan -json` and returns parsed errors"), never "build phase 3".
3. Review every diff. If you can't explain a line, ask or delete it.
4. Reject any `"Action": "*"` or `"Resource": "*"` in IAM unless you deliberately decided it.
5. Never paste AWS keys into prompts or commit them. Use `aws configure sso` / profiles and `.gitignore` your `.env`, `*.tfstate`, and `.terraform/`.

**Interview test (check at the end of each phase):** can you whiteboard what you built and walk one request through it without looking at the code?

---

## 3. Local model setup (your laptop)

**Hardware:** ASUS G14 (2024) — RTX 4060 Laptop 8 GB VRAM, Ryzen 9 8945HS, 16 GB RAM.

| Model size | Fits? | Use it for |
|---|---|---|
| 7B–8B coder model, 4-bit (Q4) | ~5 GB, fully on GPU | **Daily development** — fast enough to iterate |
| 14B, 4-bit | ~9 GB, spills into system RAM, much slower | One-off comparison runs only |
| Larger | Not practical | — |

**Setup**
- Install **Ollama**. Pick the newest Qwen coder model (or similar) in the 7B size from the Ollama library.
- Set the context window to around **8k tokens**. Context uses VRAM too, and retry prompts grow with each attempt.
- Plug in and use performance mode in Armoury Crate; close GPU-heavy apps while running evals.
- Use low temperature (e.g. 0–0.2) for repeatable eval results.

**Expect from a 7B model:** more hallucinated Terraform arguments and weaker results on multi-service/VPC prompts than Bedrock. That's fine — it gives the retry loop more to fix, and the gap becomes a reported result. Don't judge the whole idea on early local results.

**Structured output:** small models are less reliable at returning JSON. Keep the output format simple (e.g. fenced code blocks per filename, or a short JSON schema), and treat "couldn't parse the output" as its own failure category that also gets retried.

---

## 4. What uses AWS (and money) in each phase

| Phase | Model | AWS used | Cost |
|---|---|---|---|
| 0 Setup | Local | Budget alerts, read-only IAM profile | Free |
| 1 Terraform basics | — | Tiny S3/SQS/Lambda/IAM exercises | ~Free (cents) |
| 2 Core loop | **Local** | Read-only API calls for `terraform plan` | Free |
| 3 Eval baseline | **Local** | Same | Free |
| 4 Guardrails + retry | **Local** | Same | Free |
| 5 Switch to Bedrock + compare | **Bedrock** | Bedrock tokens | Small |
| 6 Deploy-verify-destroy | Local for dev, Bedrock for final eval | Real sandbox deploys | Small (cents per run if cleanup works) |
| 7 Cleanup safety net | — | S3, Lambda, EventBridge | ~Free |
| 8 Cloud pipeline | Bedrock | API Gateway, SQS, ECR, Fargate, DynamoDB, CloudWatch | Small if destroyed between sessions |
| 9 Final eval + polish | Both | One full eval run | Small |

Phases 2–4 — where most of the trial-and-error happens — cost nothing.

---

## 5. Phase overview

| Phase | Name | Rough time | New things you learn |
|---|---|---|---|
| 0 | Local tooling and AWS safety | 1–2 days | Ollama, AWS CLI, IAM, billing alarms |
| 1 | Terraform fundamentals | 3–4 days | Providers, resources, variables, outputs, state, plan/apply/destroy |
| 2 | Core generation loop (local model) | 4–5 days | Model backend interface, prompt design, running Terraform from Python |
| 3 | Evaluation set and local baseline | 2–3 days | Experiment design, metrics |
| 4 | Static guardrails and retry loop (local model) | 4–5 days | Checkov, Infracost, plan JSON, policy checks, agent retry loop |
| 5 | Switch to Bedrock and compare models | 2 days | Bedrock API, IAM for Bedrock, model comparison |
| 6 | Deploy, verify, destroy (local machine) | 5–6 days | Sandbox IAM, `apply`, boto3 probes, safe teardown |
| 7 | Cleanup safety net | 3 days | S3 remote state, EventBridge, scheduled Lambda, tag sweeps |
| 8 | Move it to the cloud | 6–7 days | API Gateway, Lambda, SQS + DLQ, ECR, Fargate, DynamoDB, CloudWatch |
| 9 | Final evaluation, polish, presentation | 3–4 days | Reporting, README, demo |

**Total: about 6 weeks** at a placement-season pace.

**Safe stopping points:**
- **Checkpoint 1 — after Phase 5:** working, measured project with a local vs Bedrock comparison
- **Checkpoint 2 — after Phase 7:** real deploys, measured, safe
- **Checkpoint 3 — after Phase 9:** complete, fully on the cloud

If placements get busy, stop at a checkpoint and polish rather than leaving a phase half-done.

---

## 6. Phases in detail

### Phase 0 — Local tooling and AWS safety (1–2 days)

**Goal:** a working local toolchain, and an AWS account you can't accidentally get a big bill on.

**Local**
- Install: Ollama, Terraform, AWS CLI, Python 3.11+, Docker, Git
- Pull a 7B coder model in Ollama; send it one Terraform question from the terminal to confirm it works
- Create the GitHub repo

**AWS (all yourself, in the console)**
- Check Billing → Credits to see whether you have Free Tier credits
- Turn on MFA for the root user; stop using root after this
- Create an AWS Budget with email alerts at **$5, $10 and $20**
- Create your own admin user (or IAM Identity Center user) and a CLI profile
- Create a second, **read-only** CLI profile — this is what `terraform plan` will use in Phases 2–5
- Pick **one region** for everything
- Bedrock access can wait until Phase 5

**Done when**
- A Python script sends a prompt to Ollama and prints the reply
- `aws sts get-caller-identity` works with both profiles
- Budget alerts exist

---

### Phase 1 — Terraform fundamentals (3–4 days)

**Goal:** learn Terraform by codifying a few small resources. This phase is a learning exercise and lives in `learning/`.

**Steps**
1. **Console first.** By hand, create: an S3 bucket, an SQS queue, an IAM role, and a small Lambda that writes to the queue. Click through each settings page and note what each option does. Delete them.
2. **Now in Terraform**, one resource at a time:
   - `provider "aws"`, an S3 bucket → `terraform init`, `plan`, `apply`, `destroy`
   - Add variables (`variables.tf`) and outputs (`outputs.tf`)
   - Add the SQS queue; reference it from another resource to learn references and dependencies
   - Add the IAM role + policy + Lambda (this is where you learn IAM properly)
   - Add `default_tags` to the provider so everything gets a `project` tag
3. Open `terraform.tfstate` and read it. Understand what state is and why losing it is bad.
4. Run `terraform plan -out=plan.tfplan` then `terraform show -json plan.tfplan`. Look at the JSON — later phases parse it.
5. Destroy and re-apply everything to prove it reproduces.
6. Bonus: ask your local model to write the same Terraform and compare it with yours. You'll start spotting the mistakes it makes.

**Claude Code use:** syntax help only *after* you've tried writing each resource yourself. This is the one phase where typing it yourself matters most.

**Done when**
- You can explain: provider, resource, variable, output, state, plan vs apply, what `destroy` uses state for
- One `apply` builds all four resources and one `destroy` removes them

---

### Phase 2 — Core generation loop, local model (4–5 days)

**Goal:** English in → Terraform files out → `validate` + `plan` run automatically. Nothing is created in AWS, and generation is free.

**You design (most important decision in the project)**
- **The model backend interface**, e.g.:
  ```python
  class ModelBackend:
      def generate(self, messages: list[dict], **opts) -> ModelResponse: ...
  # ModelResponse: text, tokens_in, tokens_out, latency_s, cost_usd
  ```
  with `OllamaBackend` now and `BedrockBackend` in Phase 5. Choose the backend from config (`--backend local` / `--backend bedrock`). Nothing else in the code should know which model is running.
- The CLI, e.g. `infrapilot generate "an S3 bucket with versioning and an SQS queue with a DLQ" --backend local`
- The prompt: output format, Terraform and provider version pinning, one region, mandatory tags
- Where each run's files live: `runs/<run_id>/`

**Claude Code builds**
- `OllamaBackend` (calls Ollama's local HTTP API)
- Output parser that turns the model's reply into files, with a clear error when parsing fails
- A runner module that writes files and executes `terraform init`, `validate`, `plan -out` as subprocesses using the **read-only** AWS profile
- A run logger saving the request, generated files, model reply, and command outputs to `runs/<run_id>/`

**Done when**
- One command takes a sentence and produces a folder with Terraform files and validate/plan results
- You've read the output for 10+ requests and noted common failure types (parse failures, hallucinated arguments, missing references, wrong provider syntax)

---

### Phase 3 — Evaluation set and local baseline (2–3 days)

**Goal:** a fixed test set so every later change is measured, not guessed.

**You do (design work, keep it yours)**
- Write **30 prompts** in `eval/prompts.yaml` across three difficulty levels:
  - *Easy (10):* single services — "S3 bucket with versioning and encryption"
  - *Medium (12):* a few connected services — "Lambda triggered by SQS, writing to DynamoDB"
  - *Hard (8):* networking and multi-service — "VPC with public and private subnets, a Lambda in the private subnet that can reach DynamoDB through a VPC endpoint"
- For each prompt, note expected resources and behaviours that should be true (these become probe targets in Phase 6)
- Keep prompts to cheap, fast resources (see the allowlist in section 8)

**Claude Code builds**
- `eval/run_eval.py --backend local`: runs every prompt, saves results with date, git commit hash, model name and backend

**Metrics per run**
- parse success, validate pass, plan pass, attempts used, tokens in/out, latency, cost (0 for local), failure category

**Done when**
- You have a **local baseline** table: plan-valid rate per difficulty level

---

### Phase 4 — Static guardrails and retry loop, local model (4–5 days)

**Goal:** catch problems before anything is deployed, and let the model fix its own mistakes — all still free.

**Components**
1. **Security scan:** Checkov (or Trivy) on the generated code. Decide which severities block a run.
2. **Cost estimate:** Infracost on the plan (needs a free Infracost API key, not AWS). Cost comes from pricing data, never from the model guessing.
3. **Plan guard:** a Python check on `terraform show -json` output that rejects:
   - resource types not on your allowlist
   - estimated monthly cost above a cap (e.g. $5)
   - missing mandatory tags, public S3 buckets, `0.0.0.0/0` ingress on non-web ports
4. **Retry loop:** any failure → send the model the original request, its previous code, and the *trimmed* error output → new attempt. Stop after 3–5 attempts and return the best attempt with remaining errors. Trimming matters more on the local model because of the 8k context window.
5. **Match review:** a second model call compares the final plan's resource list against the request and flags anything missing or extra.

**You design:** the allowlist, blocking rules, how errors are trimmed, the stop condition.

**Claude Code builds:** scanner/Infracost wrappers, plan JSON parser, the loop, report formatting.

**Done when**
- Re-run the eval on the local model and compare with the Phase 3 baseline (e.g. "plan-valid rate went from 35% to 70% with the retry loop")
- Each run outputs a report: files, security findings, cost estimate, match review

---

### Phase 5 — Switch to Bedrock and compare models (2 days)

**Goal:** add the Bedrock backend and get your first comparison result. This is the first phase that spends money, and only on tokens.

**Steps**
- In the Bedrock console, enable access to one cheap model and one stronger model if access approval is required (check which models your region offers)
- Create an IAM policy that allows `bedrock:InvokeModel` **only** for those model IDs; attach it to your dev profile
- Build `BedrockBackend` behind the same interface (Claude Code types it; you check the IAM and the token/cost accounting)
- Check current Bedrock pricing for your chosen models and set `cost_usd` from it
- Run the full eval with `--backend bedrock` on the cheap model, then once on the stronger model

**Result table to save in `eval/results/`**

| Backend | Plan-valid (no retry) | Plan-valid (with retry) | Avg attempts | Cost per prompt | Latency |
|---|---|---|---|---|---|
| Local 7B | | | | $0 | |
| Bedrock (cheap) | | | | | |
| Bedrock (strong) | | | | | |

**Done when**
- The table is filled in and you can explain the trade-offs (quality vs cost vs latency)

**✅ Checkpoint 1: a complete, presentable project if you stop here.**

---

### Phase 6 — Deploy, verify, destroy, from your laptop (5–6 days)

**Goal:** actually deploy generated infra into a sandbox, test it, and tear it down.

**Cost tip:** use the **local model** while building and debugging this phase. Switch to Bedrock only for the final deploy-and-verify eval run. (Optional: test your apply/destroy code against LocalStack first, but use real AWS for the actual numbers, since LocalStack doesn't always behave like AWS.)

**Sandbox setup (by hand first, then codify in Terraform)**
- A dedicated IAM role `infrapilot-sandbox-deployer` that:
  - can only create allowlisted resource types
  - is restricted to your one region
  - has a **permissions boundary** so any IAM roles it creates can't exceed its own powers
- Every generated resource gets tags: `project=infrapilot`, `run_id=<id>`, `expires_at=<timestamp>`
- Decide: same account with these restrictions, or a separate sandbox account. (Joining an AWS Organization expires Free Tier credits immediately — check before doing that.)

**Probe library (you design each probe; Claude Code can type them)** in `infrapilot/probes/`, using boto3:
- `s3_not_public` — public access block enabled
- `s3_versioning_on` / `s3_encrypted`
- `sqs_send_receive` — send, receive, delete a message
- `sqs_has_dlq` — redrive policy points at a real queue
- `lambda_invokes` — invoke the function, check for no error
- `dynamodb_put_get` — write and read a test item
- `sg_no_open_ingress` — no unexpected `0.0.0.0/0` rules
- `cloudwatch_alarm_exists`

The model **selects** which probes apply and supplies resource names from Terraform outputs. It does not write probes — otherwise it grades its own homework.

**Teardown rules (critical)**
- `terraform destroy` runs in a `finally` block — always
- If destroy fails, retry, then log the run ID loudly as "NEEDS CLEANUP"
- Each run has its own state file so destroy only touches that run

**Done when**
- Run the eval with deploy-and-verify on (Bedrock for the final run). Record the **deploy-and-verify pass rate** next to the plan-valid rate.
- After every eval run, a tag search (Tag Editor / Resource Groups, filter `project=infrapilot`) shows nothing left behind

---

### Phase 7 — Cleanup safety net (3 days)

**Goal:** even if your laptop dies mid-run, nothing keeps billing you.

**Components**
1. **Remote state in S3:** each run's state at `s3://<state-bucket>/runs/<run_id>/terraform.tfstate`, versioning on. Now any process can destroy a run.
2. **Janitor Lambda** on an **EventBridge schedule** (e.g. every 15 minutes):
   - finds runs whose `expires_at` tag is in the past
   - destroys using stored state, or deletes resources directly by tag if state is missing
3. **Tag sweep report:** lists any `project=infrapilot` resource older than the TTL.

**You design:** the TTL, how the janitor finds runs, what happens if state is missing.

**Done when**
- Tested on purpose: start a deploy, kill the process mid-run, confirm the janitor cleans it up within the TTL

**✅ Checkpoint 2: strong project — real deploys, measured, safe.**

---

### Phase 8 — Move it to the cloud (6–7 days)

**Goal:** the whole pipeline runs on AWS behind an API, defined entirely in Terraform. The cloud version uses the **Bedrock backend** (the local model stays your dev tool).

**Architecture (draw it yourself before writing anything)**
```
Client ──► API Gateway ──► Submit Lambda ──► SQS queue ──► Fargate runner task
                               │                (+ DLQ)          │
                               ▼                                 ├─► Bedrock
                           DynamoDB  ◄───── status updates ──────┤
                          (run records)                          ├─► sandbox deploy/verify/destroy
                               ▲                                 ▼
Client ──► API Gateway ──► Status Lambda                    S3 (artifacts, reports, state)
                                                            CloudWatch (logs, metrics)
```

**Order (one service at a time, console first, then Terraform)**
1. **ECR + Docker:** containerise the runner (Python + Terraform + Checkov + Infracost). Run the container locally first — you can even point it at Ollama on your laptop to test it for free.
2. **DynamoDB:** a runs table (run_id, status, timestamps, metrics, S3 report link)
3. **SQS + DLQ:** visibility timeout longer than the longest run; set max receive count
4. **Fargate task:** pulls a job, runs the full flow, writes results to S3 and DynamoDB
   - Decide and justify: launch a task per job, or run a small polling worker
   - **Avoid a NAT Gateway:** public subnet with a tight security group and public IP, or VPC endpoints. A NAT Gateway bills by the hour even when idle.
5. **API Gateway + Lambdas:** `POST /runs` (submit), `GET /runs/{id}` (status + report link)
6. **CloudWatch:** structured logs, custom metrics (attempts, pass rate, cost per run), one alarm on DLQ messages

**Watch for**
- Idempotency: SQS can deliver a message twice, so check DynamoDB status before starting a run
- The runner's IAM role needs: read the queue, write DynamoDB/S3, call Bedrock (specific models only), assume the sandbox deployer role. Nothing more.

**Done when**
- `curl` to the API submits a request and later returns a full verification report
- `terraform destroy` removes the whole platform cleanly, and `apply` brings it back
- Destroy the platform at the end of each working session

---

### Phase 9 — Final evaluation, polish, presentation (3–4 days)

**Steps**
- Run the full eval one final time through the cloud pipeline
- Write `eval/RESULTS.md`:
  - local vs Bedrock comparison (Phase 5 table)
  - baseline → retry loop → deploy-and-verify, per difficulty level
  - cost per run, median time
- Write up 3–5 interesting failure cases (e.g. "plan passed, but the Lambda couldn't read the queue because of a missing IAM permission")
- README: one-paragraph pitch, architecture diagram, how to run (including local mode), results, cost notes, limitations
- Record a 2–3 minute demo video
- Draft resume bullets from your real numbers, for example:
  - *Built an agent that converts natural-language infra requests into Terraform with automated validation, security scanning, cost estimation and a self-correcting retry loop, raising plan-valid rate from X% to Y% on a 30-prompt benchmark.*
  - *Benchmarked a local 7B open-source model against AWS Bedrock models on quality, latency and cost through a pluggable model backend.*
  - *Added sandboxed deploy-and-verify with hand-written smoke-test probes and TTL-based cleanup, revealing a Z-point gap between plan-valid and deploy-verified code.*
  - *Deployed as an event-driven pipeline (API Gateway, SQS, Fargate, DynamoDB, S3, CloudWatch), fully defined in Terraform.*
- Remove the old RAG project from your resume

**✅ Checkpoint 3: complete.**

---

## 7. Repo structure

```
infrapilot/
├── README.md
├── plan.md
├── config/
│   └── backends.yaml         # local (Ollama model, context size) / bedrock (model IDs, region)
├── learning/                 # Phase 1 Terraform exercises
├── infrapilot/
│   ├── cli.py
│   ├── backends/             # base interface, ollama.py, bedrock.py
│   ├── generator/            # prompts, output parsing
│   ├── runner/               # terraform init/validate/plan/apply/destroy
│   ├── checks/               # checkov, infracost, plan guard, match review
│   ├── probes/               # smoke-test probes (boto3)
│   ├── loop.py               # retry loop / orchestration
│   └── report.py
├── eval/
│   ├── prompts.yaml
│   ├── run_eval.py
│   ├── results/              # dated results, tagged by backend + model
│   └── RESULTS.md
├── infra/                    # Terraform for the platform itself
│   ├── sandbox/              # deployer role, permissions boundary, state bucket
│   ├── janitor/              # EventBridge + cleanup Lambda
│   └── platform/             # API Gateway, Lambdas, SQS, ECR, Fargate, DynamoDB
├── docker/
│   └── runner.Dockerfile
└── runs/                     # local run outputs (gitignored)
```

---

## 8. Cost and safety guardrails

**Starting allowlist (cheap and fast to create/destroy)**
S3, SQS, SNS, DynamoDB (on-demand), Lambda, IAM roles/policies, CloudWatch log groups/alarms, VPC/subnets/route tables/security groups, VPC gateway endpoints, API Gateway.

**Blocked at first** (slow to provision, bill hourly, or both)
NAT Gateway, RDS/Aurora, load balancers, EKS, ElastiCache, OpenSearch, anything larger than a micro/small EC2 instance. Unblock individually later as a deliberate, capped experiment.

**Habits**
- Default to `--backend local` during development; use Bedrock for comparison and final eval runs
- End every AWS session with a tag search for `project=infrapilot`
- Destroy the platform when you're not working on it in Phases 8–9
- Keep the per-run cost cap in the plan guard
- Check current pricing pages for Bedrock, Fargate and anything you unblock — prices change

**Expected spend:** Phases 0–4 are essentially free. Total project spend should be small (roughly tens of dollars at most) if cleanup works and the blocked list is respected. This is an estimate — your budget alerts are the real safety net.

---

## 9. Later / stretch ideas (not in scope now)
- Auth: Cognito login, per-user isolation, STS-scoped per-run credentials, per-user quotas
- A small web UI showing the report and plan diff
- Fine-tune the local model on your own failure/fix pairs from the eval logs and measure the improvement
- Unblock RDS or ALB with strict caps and longer-running probes
- Publish the benchmark prompts and results as a standalone dataset
