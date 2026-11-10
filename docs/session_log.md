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
