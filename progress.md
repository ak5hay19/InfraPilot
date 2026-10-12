# InfraPilot — Progress Tracker

Tick boxes as you go (`- [ ]` → `- [x]`). Each phase ends with a **Done when** block — only mark the phase complete when all of those are ticked.

## Status at a glance

| Phase | Name | Status | Started | Finished |
|---|---|---|---|---|
| 0 | Local tooling and AWS safety | ⬜ Not started | | |
| 1 | Terraform fundamentals | ⬜ Not started | | |
| 2 | Core generation loop (local model) | ⬜ Not started | | |
| 3 | Evaluation set and local baseline | ⬜ Not started | | |
| 4 | Static guardrails and retry loop | ⬜ Not started | | |
| 5 | Switch to Bedrock and compare models | ⬜ Not started | | |
| 6 | Deploy, verify, destroy | ⬜ Not started | | |
| 7 | Cleanup safety net | ⬜ Not started | | |
| 8 | Move it to the cloud | ⬜ Not started | | |
| 9 | Final evaluation and polish | ⬜ Not started | | |

Status key: ⬜ Not started · 🟨 In progress · ✅ Done

---

## Before every phase
- [ ] Write a 5–10 line design note for the phase (what you're building, how it connects)
- [ ] Give that note to Claude Code as context before asking for any code

## After every phase
- [ ] Whiteboard test: explain what you built and walk one request through it without looking at the code
- [ ] Commit and push with a clear message (e.g. `phase-2: core generation loop`)
- [ ] Update the status table above

---

## Phase 0 — Local tooling and AWS safety

### Local setup
- [ ] Install Terraform
- [ ] Install AWS CLI
- [ ] Install Python 3.11+ and create a virtual environment
- [ ] Install Docker
- [ ] Install Git and create the GitHub repo
- [ ] Add `.gitignore` (`.env`, `*.tfstate*`, `.terraform/`, `runs/`, `__pycache__/`)
- [ ] Install Ollama
- [ ] Pull a 7B coder model (newest Qwen coder or similar)
- [ ] Ask it one Terraform question from the terminal
- [ ] Note model name and quantization in `config/backends.yaml`

### AWS account safety
- [ ] Check Billing → Credits for Free Tier credits (note amount and expiry: ________)
- [ ] Enable MFA on the root user
- [ ] Create AWS Budget with email alerts at $5, $10, $20
- [ ] Create your own admin user / IAM Identity Center user
- [ ] Configure admin CLI profile
- [ ] Create a **read-only** CLI profile for `terraform plan`
- [ ] Choose one region for everything (region: ________)

### Done when
- [ ] Python script sends a prompt to Ollama and prints the reply
- [ ] `aws sts get-caller-identity` works with both profiles
- [ ] Budget alerts exist and the alert email is confirmed

---

## Phase 1 — Terraform fundamentals

### Console first (by hand)
- [ ] Create an S3 bucket and explore its settings
- [ ] Create an SQS queue and explore its settings
- [ ] Create an IAM role and read its trust policy
- [ ] Create a small Lambda that sends a message to the queue
- [ ] Test the Lambda and see the message arrive
- [ ] Delete everything you created

### Terraform, one resource at a time (in `learning/`)
- [ ] Write the `provider "aws"` block with version pinning
- [ ] S3 bucket → `init`, `plan`, `apply`, `destroy`
- [ ] Add `variables.tf`
- [ ] Add `outputs.tf`
- [ ] Add the SQS queue
- [ ] Reference one resource from another (learn references/dependencies)
- [ ] Add IAM role + policy
- [ ] Add the Lambda (zip packaging)
- [ ] Add `default_tags` (`project = "infrapilot"`)

### Understanding state and plans
- [ ] Open and read `terraform.tfstate`
- [ ] Write down in your own words what state is and why losing it is bad
- [ ] Run `terraform plan -out=plan.tfplan`
- [ ] Run `terraform show -json plan.tfplan` and skim the structure
- [ ] Destroy and re-apply everything to prove it reproduces

### Bonus
- [ ] Ask the local model to write the same Terraform and note its mistakes

### Done when
- [ ] You can explain: provider, resource, variable, output, state, plan vs apply, what `destroy` uses state for
- [ ] One `apply` builds all four resources; one `destroy` removes them

---

## Phase 2 — Core generation loop (local model)

### Design (yourself)
- [ ] Design the `ModelBackend` interface and `ModelResponse` fields
- [ ] Decide the CLI shape (`infrapilot generate "..." --backend local`)
- [ ] Decide the model output format (fenced blocks per file or short JSON)
- [ ] Write the system prompt: output format, version pinning, one region, mandatory tags
- [ ] Decide the run folder layout (`runs/<run_id>/`)

### Build (Claude Code types, you review)
- [ ] `backends/base.py` — interface
- [ ] `backends/ollama.py` — calls Ollama's local API, returns tokens + latency
- [ ] `config/backends.yaml` loader with `--backend` switch
- [ ] Output parser (reply → files) with a clear parse-failure error
- [ ] Runner: write files to `runs/<run_id>/`
- [ ] Runner: `terraform init`
- [ ] Runner: `terraform validate` with captured output and exit code
- [ ] Runner: `terraform plan -out` using the **read-only** profile
- [ ] Run logger: save request, model reply, files, command outputs
- [ ] `cli.py` wiring it all together

### Explore
- [ ] Run 10+ different requests
- [ ] Record common failure types in `notes/failures.md` (parse failures, hallucinated arguments, missing references, wrong syntax)

### Done when
- [ ] One command takes a sentence and produces a folder with Terraform files and validate/plan results
- [ ] Nothing outside `backends/` knows which model is running

---

## Phase 3 — Evaluation set and local baseline

### Write the eval set (yourself)
- [ ] 10 easy prompts (single services)
- [ ] 12 medium prompts (a few connected services)
- [ ] 8 hard prompts (networking, multi-service)
- [ ] For each prompt: list expected resources
- [ ] For each prompt: list behaviours that should be true (future probe targets)
- [ ] Check every prompt only uses allowlisted, cheap resources

### Build the harness
- [ ] `eval/run_eval.py --backend local`
- [ ] Record per prompt: parse success, validate pass, plan pass, attempts, tokens in/out, latency, cost, failure category
- [ ] Save results to `eval/results/` with date, git commit, backend and model name
- [ ] Summary script that prints pass rates per difficulty level

### Run it
- [ ] Run the full eval on the local model
- [ ] Run it a second time to check results are stable (low temperature)

### Done when
- [ ] Local baseline recorded: easy ___% · medium ___% · hard ___% plan-valid

---

## Phase 4 — Static guardrails and retry loop (local model)

### Security scan
- [ ] Install Checkov (or Trivy)
- [ ] Wrapper that runs it and parses findings
- [ ] Decide which severities block a run

### Cost estimate
- [ ] Install Infracost and get the free API key
- [ ] Wrapper that runs it on the plan and returns monthly cost

### Plan guard (you design the rules)
- [ ] Write the resource-type allowlist
- [ ] Parse `terraform show -json` output
- [ ] Rule: reject non-allowlisted resource types
- [ ] Rule: reject estimated cost above the cap ($___)
- [ ] Rule: reject missing mandatory tags
- [ ] Rule: reject public S3 buckets
- [ ] Rule: reject `0.0.0.0/0` ingress on non-web ports

### Retry loop
- [ ] Design error trimming (what gets sent back, max length)
- [ ] Feed request + previous code + trimmed errors back to the model
- [ ] Stop after N attempts (N = ___); return best attempt + remaining errors
- [ ] Treat parse failures as retryable
- [ ] Log attempt count and which check failed each time

### Match review
- [ ] Second model call comparing plan resources against the request
- [ ] Flag missing or extra resources in the report

### Report
- [ ] Per-run report: files, security findings, cost estimate, match review, attempts

### Done when
- [ ] Eval re-run on local model with the retry loop
- [ ] Improvement recorded: plan-valid went from ___% → ___%

---

## Phase 5 — Switch to Bedrock and compare models

### Access and permissions
- [ ] Check which Bedrock models are available in your region
- [ ] Enable access to one cheap and one stronger model (if approval is needed)
- [ ] Write an IAM policy allowing `bedrock:InvokeModel` only for those model IDs
- [ ] Attach it to your dev profile and test one call from the CLI

### Build
- [ ] `backends/bedrock.py` behind the same interface
- [ ] Look up current pricing and set `cost_usd` calculation
- [ ] Confirm switching is just `--backend bedrock` with no other code changes

### Compare
- [ ] Full eval on the cheap Bedrock model
- [ ] Full eval on the stronger Bedrock model
- [ ] Check the Billing console to confirm actual spend matches your cost tracking

### Done when
- [ ] Comparison table filled in and saved:

| Backend | Plan-valid (no retry) | Plan-valid (with retry) | Avg attempts | Cost / prompt | Latency |
|---|---|---|---|---|---|
| Local 7B | | | | $0 | |
| Bedrock (cheap) | | | | | |
| Bedrock (strong) | | | | | |

- [ ] You can explain the quality vs cost vs latency trade-offs

### ✅ Checkpoint 1 — presentable project
- [ ] README draft with what works so far and the comparison table
- [ ] Optional: update resume with a first version of the bullets

---

## Phase 6 — Deploy, verify, destroy (from your laptop)

### Sandbox setup (by hand first, then Terraform in `infra/sandbox/`)
- [ ] Decide: same account with restrictions, or a separate sandbox account
- [ ] (If separate account) confirm it won't expire Free Tier credits
- [ ] Create `infrapilot-sandbox-deployer` role limited to allowlisted services
- [ ] Restrict the role to your one region
- [ ] Add a permissions boundary for any IAM roles it creates
- [ ] Codify the sandbox role in Terraform
- [ ] Mandatory tags on every generated resource: `project`, `run_id`, `expires_at`

### Apply and destroy
- [ ] Separate state file per run
- [ ] `terraform apply` wrapper using the sandbox role
- [ ] `terraform destroy` in a `finally` block
- [ ] Retry destroy on failure; log "NEEDS CLEANUP" with the run ID
- [ ] Test manually: deploy one simple request and destroy it

### Probe library (you design each one)
- [ ] `s3_not_public`
- [ ] `s3_versioning_on`
- [ ] `s3_encrypted`
- [ ] `sqs_send_receive`
- [ ] `sqs_has_dlq`
- [ ] `lambda_invokes`
- [ ] `dynamodb_put_get`
- [ ] `sg_no_open_ingress`
- [ ] `cloudwatch_alarm_exists`
- [ ] Model selects probes and supplies names from Terraform outputs
- [ ] Probe failures feed back into the retry loop

### Verification report
- [ ] Report shows which probes ran, passed and failed on real infra

### Evaluate
- [ ] Develop and debug using the local model
- [ ] Final deploy-and-verify eval run on Bedrock
- [ ] Tag search after every run: nothing left with `project=infrapilot`

### Done when
- [ ] Recorded: plan-valid ___% vs deploy-and-verify ___% (gap: ___ points)
- [ ] Zero leftover resources after the eval

---

## Phase 7 — Cleanup safety net

### Remote state
- [ ] Create the state S3 bucket with versioning (in Terraform)
- [ ] Store each run's state at `runs/<run_id>/terraform.tfstate`
- [ ] Confirm a different process can destroy a run from stored state

### Janitor
- [ ] Decide the TTL (___ minutes)
- [ ] Janitor Lambda: find runs past `expires_at`
- [ ] Janitor: destroy from stored state
- [ ] Janitor: fallback delete-by-tag if state is missing
- [ ] EventBridge schedule (every ___ minutes)
- [ ] Least-privilege IAM role for the janitor
- [ ] Janitor logs to CloudWatch

### Tag sweep
- [ ] Report listing `project=infrapilot` resources older than the TTL

### Done when
- [ ] Crash test: start a deploy, kill the process, janitor cleans it up within the TTL

### ✅ Checkpoint 2 — strong project
- [ ] README updated with deploy-and-verify results and the safety design

---

## Phase 8 — Move it to the cloud

### Design (yourself)
- [ ] Draw the architecture diagram
- [ ] Decide: task per job vs polling worker (and write down why)
- [ ] Decide networking: public subnet + tight SG, or VPC endpoints (no NAT Gateway)

### Container
- [ ] `docker/runner.Dockerfile` with Python, Terraform, Checkov, Infracost
- [ ] Run the container locally (optionally pointed at Ollama)
- [ ] ECR repository in Terraform; push the image

### DynamoDB
- [ ] Runs table design (keys, fields)
- [ ] Table in Terraform

### SQS
- [ ] Queue + DLQ in Terraform
- [ ] Visibility timeout longer than the longest run (___ min)
- [ ] Max receive count set

### Fargate runner
- [ ] ECS cluster and task definition in Terraform
- [ ] Runner task IAM role: queue, DynamoDB, S3, specific Bedrock models, assume sandbox role — nothing else
- [ ] Idempotency check against DynamoDB before starting a run
- [ ] Runner writes reports to S3 and status to DynamoDB

### API
- [ ] Submit Lambda (`POST /runs`)
- [ ] Status Lambda (`GET /runs/{id}`)
- [ ] API Gateway in Terraform

### Observability
- [ ] Structured JSON logs
- [ ] Custom metrics: attempts, pass rate, cost per run
- [ ] CloudWatch alarm on DLQ messages

### Done when
- [ ] `curl` submits a request and later fetches a full verification report
- [ ] Platform `destroy` removes everything; `apply` brings it back
- [ ] Platform destroyed at the end of each working session

---

## Phase 9 — Final evaluation, polish, presentation

### Final results
- [ ] Full eval through the cloud pipeline
- [ ] `eval/RESULTS.md`: local vs Bedrock table
- [ ] `eval/RESULTS.md`: baseline → retry loop → deploy-and-verify per difficulty
- [ ] Cost per run and median time
- [ ] 3–5 interesting failure case write-ups

### README
- [ ] One-paragraph pitch
- [ ] Architecture diagram
- [ ] How to run (local mode and cloud mode)
- [ ] Results summary
- [ ] Cost notes and limitations

### Presentation
- [ ] 2–3 minute demo video
- [ ] Pin the repo on GitHub
- [ ] Resume bullets with your real numbers
- [ ] Remove the RAG chatbot from the resume
- [ ] Practise a 2-minute verbal explanation of the project for interviews

### Final cleanup
- [ ] Destroy the platform and sandbox resources
- [ ] Final tag search: nothing left running
- [ ] Check the Billing console one last time

### ✅ Checkpoint 3 — complete

---

## Results log

Fill in as you go so the final write-up is easy.

| Date | Phase | Backend / model | What changed | Plan-valid | Deploy-verified | Notes |
|---|---|---|---|---|---|---|
| | | | | | | |

## Spend log

| Date | What ran | Approx cost | Running total |
|---|---|---|---|
| | | | |
