# Phase 2 failure notes

2026-11-12 · qwen3:8b Q4_K_M · temperature 0.1 · git `afe2bcc` (12 runs; run 11e5 recorded `1e1c778`, before the pipeline commit) · 13 runs.
**Exploration, not the baseline (Phase 3).** n=1 per request, so read these as patterns to check, not rates.
Run ids below are the 4-hex suffix of `runs/20261112-HHMMSS-xxxx`.

## Summary

| Category | Count |
|---|---|
| ok | 4 |
| validate_error | 8 |
| plan_error | 1 |
| backend_error / truncated / parse_error / provider_block_written / init_error | 0 |

ok **and** validate_clean: 3 (11e5, 857f, 6335). Only **1 of 13** (857f) actually does what was asked.

## Failure types

Counted by root cause, not by diagnostic or run (one wrong argument can print two diagnostics).

| Type | Count | Runs | Example |
|---|---|---|---|
| Hallucinated argument/attribute | 4 | 3c8f, 8ad3, e826, 5262 | `aws_sqs_queue` has no `fifo` (it is `fifo_queue`); `archive_file.output_base64` does not exist |
| Undeclared reference | 4 | bfa4, 5f69, 5262, 7346 | `data.aws_vpc.default` used, never declared |
| Plan-valid but wrong behaviour | 3 | 11e5, 7a74, 6335 | SQS "DLQ" is two unconnected queues |
| Template interpolation of an object | 2 | e826, 5f69 | `"arn:${data.aws_partition.partition}:..."` -> "string required, but have object" |
| Invalid resource type | 1 | 1c86 | `aws_sns_subscription` (real name `aws_sns_topic_subscription`) |
| Missing required argument | 1 | 5262 | `aws_dynamodb_table` without `hash_key` |
| Wrong attribute access (set indexed) | 1 | 3c8f | `...rule[0]...` -> "Cannot index a set value" |
| Plan-time provider error | 1 | 90c7 | DynamoDB `hash_key = "id"` with no `attribute` block (validate was clean) |
| Deprecation warning (passes) | 1 | 7a74 | `acl` on `aws_s3_bucket` |

Latent errors that validate did not report (hidden behind other errors): 5262 has the same partition interpolation as e826/5f69; 5f69 uses `name =` on `aws_lambda_function` (should be `function_name`); bfa4 reads `.partition` from `aws_region`, which has no such attribute. Expect more rounds of fixes than the first error list suggests.

## DynamoDB plan_error (90c7): model error, not credentials

`Error: all indexes must match a defined attribute. Unmatched indexes: ["id"]`. This is the provider's schema check at plan time. No AccessDenied or token error in `plan.log`.

## Plan-valid but wrong

Four runs reached `ok`. Only the log group is correct.

- **11e5 SQS + DLQ: wrong.** The main queue gets `redrive_allow_policy` (a setting for the *DLQ*) with an invented JSON shape, instead of `redrive_policy = jsonencode({deadLetterTargetArn = ..., maxReceiveCount = ...})`. Two queues, no wiring. Plan accepts it because the policy is an opaque string; apply may well reject it (not tested). Probe: `sqs_has_dlq`.
- **7a74 S3 block public access: wrong.** `aws_s3_bucket_public_access_block` has no flags, and all four default to false, so nothing is blocked. Also deprecated `acl` (the only reason it is not clean) and `bucket =` instead of `bucket_prefix`. Probe: `s3_not_public`. Phase 4's "reject public S3 buckets" rule could catch it statically if it checks the four flags in plan JSON.
- **857f log group: correct.** `retention_in_days = 7`, prefixed name, outputs. No probe needed; a retention probe would be new.
- **6335 VPC: partly wrong.** VPC, subnet, internet gateway, route table and a default route to the gateway, but no `aws_route_table_association`, so the subnet uses the main route table and is not public. No existing probe covers it; a "subnet routes 0.0.0.0/0 to the IGW" probe would be new. Phase 4's match review could also flag the missing association.

## Instructive excerpts

11e5, SQS DLQ (valid, wrong):
```hcl
resource "aws_sqs_queue" "main" {
  # name, visibility_timeout_seconds omitted
  redrive_allow_policy = jsonencode({
    "redrivePermission" = {
      "queue" = [aws_sqs_queue.dead_letter_queue.arn]
    }
  })
}
```

e826 / 5f69 / 5262, partition (3 of 3 Lambda runs):
```hcl
policy_arn = "arn:${data.aws_partition.partition}:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
# should be data.aws_partition.<name>.partition, or just the constant ARN
```

90c7, DynamoDB (validate clean, plan fails):
```hcl
resource "aws_dynamodb_table" "main" {
  name           = "${var.name_prefix}-table"
  billing_mode   = "PAY_PER_REQUEST"
  hash_key       = "id"
  read_capacity  = 0   # no attribute { name = "id" type = "S" } block anywhere
  write_capacity = 0
}
```

## Prompt problems vs model problems

**Caused by our prompt/runner:**
- Conflicting rules: "never hardcode an ARN" vs "you may attach AWSLambdaBasicExecutionRole". That ARN is a constant, not a resource attribute, so the model invented `data.aws_partition` in all 3 Lambda runs (2 visible failures, 1 latent). Fix: give the exact ARN.
- The Lambda rule ("archive_file with an inline `source` block") has no example; the only example is SNS. All 3 Lambda runs used `source_file = "lambda.py"` (a file that does not exist) and guessed attributes (`output_base64`).
- Nothing tells the model which VPC a security group belongs to; the runner provides no `vpc_id`. 7346 invented `data.aws_vpc.default`.

**Model problems:** invented arguments, attributes and resource types (`fifo`, `enabled`, `output_base64`, `aws_sns_subscription`); omitted required pieces (`hash_key`, DynamoDB `attribute`, route table association); ignored explicit rules (`bucket_prefix` 0 of 2 S3 runs, no deprecated args, no tags in 6335/7346 incl. an invented `Environment = "production"`); wrong semantics (DLQ, public access block); a made-up IAM action (`logs:PutLogStream` in bfa4, invisible to terraform). Lambda -> SQS (5f69) has no event source mapping and Lambda -> DynamoDB (5262) has no table permission or code, so neither would work even if it validated.

## Implications

- **Phase 3:** single-service requests plan-valid 3/6, connected-service ones 1/7. Use that as the easy/medium/hard hint, but fix the three prompt problems first, or the baseline measures our prompt. `system_prompt_sha256` in meta.json will show which prompt a result used.
- **Phase 3:** record "plan-valid" and "behaves correctly" separately; 3 of 4 plan-valid runs here were wrong. The "behaviours that should be true" list is the only thing that separates them.
- **Phase 4 retry loop:** all 8 validate errors carry a message and line, so they are easy to feed back. The plan-time error needs plan stderr trimmed and sent back too, since validate is clean there. Allow at least 3 attempts; errors hide behind each other.
- **Phase 4 plan guard:** no run hardcoded a region, but provider v6 would allow it, so the guard must reject any `region` in `resource_changes[].change.after` other than `ap-south-1`. Also check the four public-access-block flags.
- **Phase 6:** the probes cover 11e5 (`sqs_has_dlq`) and 7a74 (`s3_not_public`). VPC routing, Lambda trigger wiring, Lambda -> DynamoDB permission and invalid IAM actions have no probe yet.
