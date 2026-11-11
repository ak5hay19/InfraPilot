# InfraPilot — Session Log

Rough running log. One dated entry per session, newest last.

## 2026-10-12

### Setup done
- All tools installed:
  - Terraform 1.16.5
  - AWS CLI 2.37.12
  - Python 3.12.5
  - Docker 29.5.2
  - Git 2.51.0
  - Ollama 0.30.7

### Model decision
- qwen3:8b, Q4_K_M
- Runs 100% on GPU at 8192 context
- Called with `think=false`, `stream=false`, temperature 0.1

### AWS state
- Root: MFA on, no root access keys
- IAM user `bufo19` in Admin group, MFA on
- Read-only user `infrapilot-readonly`
- Region: ap-south-1
- No Free Tier credits
- Budget alerts at $5 / $10 / $19.90, no budget actions attached

### Observed model failures (seed for notes/failures.md)
- Puts an invalid `region` argument inside `aws_s3_bucket`
- Uses the deprecated inline `versioning` block alongside the separate versioning resource
- Hardcodes a region I never asked for
- Adds unrequested extras (logging, website, commented-out blocks)
- Adds chatty explanation text

### ollama_test.py output
- tokens in: 29
- tokens out: 374
- latency: 10.18s (first call, includes model load)

### Still to do
- Whiteboard test for Phase 0
- Turn on IAM billing access from root (optional)
- Zero-spend budget (optional)
- Start Phase 1 with a 5-10 line design note

### Next
- Phase 1, console first in Mumbai

## 2026-10-18 — Phase 1 start (console first)

### Design note
Phase 1 is a learning phase. I'm building four small resources in ap-south-1 by hand first (S3 bucket, SQS queue, IAM role for Lambda, a Python Lambda that sends a message to the queue), deleting them, then rebuilding the same stack in Terraform in `learning/`. Connections: the Lambda assumes the IAM role (trust policy), the role has an inline policy allowing only sqs:SendMessage on this one queue, and the Lambda gets the queue URL from an environment variable. Terraform tracks what it built in terraform.tfstate, and destroy uses that file to know what to delete. Success: one apply builds everything, one destroy removes it.

### Console: S3 bucket (done)
- Created `infrapilot-learn-93` in ap-south-1, general purpose, global namespace
- ARN format: `arn:aws:s3:::infrapilot-learn-93` (ARNs are how IAM policies point at resources)
- ACLs disabled (bucket owner enforced); access is controlled by policies only
- Block all public access: on (all four settings)
- Versioning: off by default, keeps old copies of overwritten/deleted objects when enabled. In Terraform this is a separate `aws_s3_bucket_versioning` resource, which is where qwen3 got it wrong earlier
- Default encryption: on by default (SSE-S3). KMS options exist but cost more and add key management
- Tag added: project=infrapilot (cleanup searches in Phases 6-7 depend on tags)
- Console region had been on Stockholm earlier; switched to Mumbai

### Console: SQS queue (done)
- Created `infrapilot-learn-queue`, Standard type, ap-south-1
- URL: https://sqs.ap-south-1.amazonaws.com/448049793333/infrapilot-learn-queue
- ARN: arn:aws:sqs:ap-south-1:448049793333:infrapilot-learn-queue
- Defaults kept: visibility timeout 30s (how long a received message stays hidden from other consumers), retention 4 days, delivery delay 0, receive wait time 0, max message size 1024 KiB
- Encryption: server-side on by default (SSE-SQS, AWS-managed key)
- Access policy: default resource-based policy allowing SQS:* to my own account (principal 448049793333) on this queue only. Within one account, access is allowed if either the resource policy or the IAM policy allows it; cross-account needs both
- DLQ and redrive allow policy left disabled (will build a DLQ in Terraform later)
- Tag: project=infrapilot
- ARN format: arn:aws:sqs:<region>:<account>:<name>. The URL is what the Lambda uses to send; the ARN is what the IAM policy points at
- Cost note: S3 and SQS charge for usage, not existence; delete everything at the end of the console exercise

### Console: IAM role (done)
- Created `infrapilot-learn-lambda-role`, trusted entity AWS service: Lambda
- ARN: arn:aws:iam::448049793333:role/infrapilot-learn-lambda-role
- Trust policy: allows Principal Service lambda.amazonaws.com to sts:AssumeRole. It answers "who may become this role"; only the Lambda service can
- Permissions: only AWSLambdaBasicExecutionRole (logs:CreateLogGroup/CreateLogStream/PutLogEvents), so the role cannot yet touch SQS
- Permissions boundary: not set (will use one in Phase 6 on the sandbox deployer)
- Tag: project=infrapilot

### Console: Lambda + IAM fix (done)
- Created `infrapilot-learn-fn` (Python, x86_64) using existing role infrapilot-learn-lambda-role (Custom execution role toggle)
- ARN: arn:aws:lambda:ap-south-1:448049793333:function:infrapilot-learn-fn
- Env var QUEUE_URL holds the queue URL; code reads it with os.environ and calls sqs.send_message
- Console defaulted to a Python 3.15 preview runtime; avoid preview runtimes, pin a stable one in Terraform
- First test FAILED on purpose: AccessDenied for sqs:SendMessage, "no identity-based policy allows the action". Caller shown as assumed-role/infrapilot-learn-lambda-role/infrapilot-learn-fn, i.e. trust policy worked (Lambda assumed the role via STS)
- Lesson: the queue's default resource policy names the account root, which only delegates to IAM; it does not grant the role access. The role needs its own identity policy. (Cross-account would need both sides.)
- Fix: inline policy `send-to-learn-queue` on the role: Allow sqs:SendMessage on only this queue's ARN (no wildcards)
- Retest passed, returned a message_id; message "hello from infrapilot-learn-fn" seen via SQS Send and receive messages -> Poll
- Note: Lambda auto-creates CloudWatch log group /aws/lambda/infrapilot-learn-fn; it survives function deletion and must be deleted manually

### Still to do in Phase 1
- Lambda, test the message, delete everything
- Terraform in learning/: provider, S3, variables/outputs, SQS, IAM, Lambda, default_tags
- Read terraform.tfstate, run plan -out and show -json, destroy and re-apply

## 2026-11-10 — Phase 1: Terraform S3, SQS, IAM and Lambda (steps 1-5)

### What I did
- Wrote `learning/main.tf` (terraform block, aws + random providers, provider with `default_tags`, random_id, S3 bucket, public access block) and `learning/variables.tf` (region, name_prefix)
- Ran init, plan, apply, destroy myself: 3 added, 3 destroyed, bucket seen in the console and then gone
- Added `learning/outputs.tf` (bucket_name, bucket_arn)
- Ran apply, `terraform output`, `terraform output -raw bucket_arn` and destroy with outputs.tf in place: 3 added, 3 destroyed, outputs printed after apply, bucket checked in the console
- Added `aws_sqs_queue.learn` (name from `var.name_prefix`, no random suffix, since SQS names only need to be unique per account and region); ran plan/apply/destroy, 4 added, 4 destroyed, queue seen in the console
- Added IAM: `aws_iam_role` (trust policy for lambda.amazonaws.com), AWSLambdaBasicExecutionRole attachment, inline `aws_iam_role_policy` allowing only `sqs:SendMessage` on the queue ARN; ran plan/apply/destroy, 7 added, 7 destroyed
- Added the Lambda (`archive_file` zip, python3.12, `QUEUE_URL` env var from the queue URL) plus outputs `queue_url` and `function_name`; apply built 8 resources, invoked it from the CLI, got a message_id, then destroyed all 8
- Concept notes written in docs/phase1_concepts.md
- Dropped the own-words requirement from the checklist; documentation lives in session_log.md and phase notes (deadlines tightened).

### What I learned
- Apply order followed dependencies: random_id, then the bucket, then the public access block. Destroy ran in reverse
- `(known after apply)` means AWS decides the value. The bucket name was unknown at plan time because it depends on random_id
- State holds attributes I never wrote (AES256 encryption, versioning false, a grant). These are AWS defaults read back
- `tags` vs `tags_all`: the provider's `default_tags` show up in `tags_all`, not in `tags`
- random_id is removed from state on destroy, so the next apply gets a new bucket name
- Outputs show up in the plan as "Changes to Outputs" with `(known after apply)`, print at the end of apply, and can be read again with `terraform output`. `-raw` prints the bare value, which is handy for scripts and the CLI
- Destroy also removes the outputs from state ("Changes to Outputs: - bucket_arn -> null")
- Second apply produced a different bucket name (`infrapilot-learn-04c4b592` vs `07a03593` the first time), confirming the random suffix is recreated after a destroy
- Typo `terraform destory` is harmless: Terraform says "no command named" and suggests the right one
- Independent resources are created in parallel: queue and bucket were created at the same time after random_id; only the access block waited for the bucket
- SQS is slow: 25s to create, 43s to destroy (S3 ~1s). A deleted queue's name can't be reused for 60 seconds
- Terraform's provider default for `max_message_size` is 262144 (256 KiB), while the console form showed 1024 KiB. Always read the plan instead of assuming Terraform copies console defaults
- Computed values (`sqs_managed_sse_enabled = true`, `kms_data_key_reuse_period_seconds = 300`) were "(known after apply)" in the plan and show real values in state/destroy
- A reference creates a dependency: the inline policy uses `aws_sqs_queue.learn.arn`, so it was created only after the queue existed; destroy ran in reverse
- The policy data source showed "will be read during apply" because it depends on a value not known at plan time (queue ARN); the trust-policy data source had no unknowns, so it was read at plan time
- The Terraform policies match the console ones I built by hand: same trust policy, same single-action SQS permission, no wildcards
- The Lambda was created last, after the inline policy; destroy ran in reverse
- `source_code_hash` comes from the zip; a changed handler.py changes the hash and triggers an update
- `default_tags` puts project=infrapilot into `tags_all` on every taggable resource (bucket, queue, role, function), so no per-resource tags are needed
- Lambda auto-creates its CloudWatch log group on first invoke; Terraform doesn't manage it, so destroy leaves it behind and I deleted it with `aws logs delete-log-group`. Cleanup in Phases 6-7 must cover log groups
- PowerShell treats `<...>` as a reserved operator, so placeholders from instructions must be replaced, not typed
- Saved plans: `terraform apply plan.tfplan` applies exactly what was reviewed, with no yes prompt. In PowerShell the flag must be quoted: `terraform plan "-out=plan.tfplan"`
- Plan JSON has 9 entries for 8 managed resources because the data source `data.aws_iam_policy_document.send_to_queue` shows up with action "read" (it depends on a value unknown until apply). A plan guard in Phase 4 must filter on `mode == "managed"` and ignore "read" actions
- `terraform state list` shows data sources as well as resources
- The SQS poll returned my message, so the Terraform-built role, policy, Lambda and queue work end to end

### Status
- Phase 1 closed. Optional: whiteboard test before interviews; qwen3 bonus at the start of Phase 2.

### Next
- Phase 2, starting with a 5-10 line design note on the ModelBackend interface.

## 2026-11-11 — Phase 2 start

### Housekeeping
- Phase 1 close-out commit moved backends.yaml to config/ and simplified doc rules; this step added pyproject.toml, moved ollama_test.py to scripts/ (temp 0.1), extended backends.yaml, fixed the §4 wording in phase1_concepts.md

### Design note
**Design note.** Phase 2 turns one English sentence into Terraform files plus `validate`/`plan` results, with nothing created in AWS and no cost. A `ModelBackend` interface (`generate(messages) -> ModelResponse` with text, tokens, latency, cost, model, backend and stop_reason) hides which model runs; `OllamaBackend` is the only one for now, and `config/backends.yaml` plus `--backend` picks it. The model returns only `main.tf` and `outputs.tf` as fenced blocks under `### <filename>` headers. The runner owns `providers.tf` and `variables.tf` (pinned versions, `var.region`, `default_tags`), so the model never writes provider blocks; if it does, that's logged as its own failure. Each run gets `runs/<YYYYMMDD-HHMMSS-xxxx>/`, with the Terraform files in `tf/`. Steps run in order and stop at the first failure: `init` → `validate -json` → `plan -out` → `show -json`. They use `AWS_PROFILE=infrapilot-readonly` set only in the subprocess, the committed lock file and a shared plugin cache. Every run saves its request, messages, raw reply, logs and a `meta.json` with a fixed failure category (`parse_error, truncated, provider_block_written, init_error, validate_error, plan_error, ok`). Done when `infrapilot generate "..." --backend local` produces that folder, and nothing outside `backends/` knows the model.

### Build
- backends/base.py: ModelBackend ABC, frozen ModelResponse (stop_reason normalized to stop/length/other, truncated property), BackendError for infra failures.
- backends/ollama.py: POST /api/chat (stream off), wall-clock latency, done_reason -> stop_reason, all HTTP/connection errors -> BackendError.
- backends/registry.py: get_backend(name) reads config/backends.yaml (path relative to the package), maps type -> class; --backend flag wired in the CLI step.
