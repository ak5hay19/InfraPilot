# Eval set v1: decisions and rationale

Companion to `eval/prompts.yaml` and `config/allowlist.yaml`. If you forget why something
in the eval set is the way it is, the answer should be here. Written 2026-11-13 (Phase 3).

## 1. Decisions

| # | Decision | Why |
|---|---|---|
| 1 | 30 prompts: 10 easy, 12 medium, 8 hard | A pass takes ~10–15 min (15–30 s per run), so 30 is cheap; fewer would make each difficulty level too noisy. |
| 2 | Easy = one service plus its own sub-resources. Medium = 2–3 services wired together. Hard = VPC networking, or 4+ services with IAM between them | A fixed rule stops prompts drifting between levels. |
| 3 | Plain English with every requirement stated, no Terraform resource names | Stated requirements make "correct" checkable; naming resources would hand the model the answer. |
| 4 | No SNS-only request and no "Lambda that logs each event" (the two system-prompt examples). Also no Lambda-only prompt at all | A Lambda-only prompt would measure copying EXAMPLE 2, not skill. Lambdas appear from medium up. |
| 5 | At most 4 prompts repeat a Phase 2 idea, marked `seen_in_phase2: true`: E02 (public access block), E04 (SQS DLQ), M01 (SQS triggers Lambda), H01 (VPC public subnet). Checked against the 15 real Phase 2 requests in `runs/20261112-*` (section 6); four other overlaps were replaced | These are the four known "plan-valid but wrong" traps, so they show whether anything has changed. Wording differs from Phase 2. |
| 6 | Fields: `expected_resources` (type → minimum count), `behaviours` (Phase 6 probe targets), optional `plan_checks` | Minimum counts allow harmless extras; behaviours are what really matters once deployed. |
| 7 | `expected_resources` lists the main resources and unambiguous wiring only. IAM policies are not listed; they are checked through `plan_checks` with `type: [aws_iam_role_policy, aws_iam_policy]` | Inline and managed policies are both correct, so counting either one would fail valid answers. |
| 8 | **Static-correct** = plan-valid **and** every expected minimum met **and** every `plan_check` passes | It is the best "correct" we can measure without deploying. Real behaviour waits for Phase 6. |
| 9 | `backend_error` / `internal_error`: retry once, then exclude from the denominator and report the count | One Ollama hiccup shouldn't change the denominator. |
| 10 | Two passes, temperature 0.1, no seed. Report both passes, their mean, and category agreement | Shows run-to-run variance instead of hiding it behind a seed. |
| 11 | The eval refuses a dirty tree unless `--allow-dirty`. `eval/results/` is excluded from the dirty check | Results must be traceable to a commit; result files don't change behaviour, and without the exclusion pass 2 would be refused after pass 1 writes results. |
| 12 | Harness is `infrapilot eval` in `infrapilot/evaluation/`; data in `eval/`; results committed, `runs/` not | Reuses the CLI; results are small and are the evidence. |
| 13 | Report counts and percentages ("easy 6/10 (60%)") | n is small, so a percentage alone overstates precision. |
| 14 | Every Lambda is Python | One runtime keeps prompts comparable; runtime choice is not what we're testing. |
| 15 | EventBridge (rules, targets, custom buses, Scheduler) added to the allowlist | Free, common in real requests, and Phase 7's janitor uses it anyway. |
| 16 | The set is frozen once the baseline is recorded. Changes go in as new ids or a `prompts_v2.yaml`, never edits | Otherwise Phase 4 and 5 results can't be compared with the baseline. |

## 2. How `plan_checks` work (spec for the harness)

Each check passes if **at least one** managed resource (`mode == "managed"`) whose type is in
`type` (string or list) satisfies **every** condition the check gives:

- `attrs: {path: value}` — the value at `path` in that resource's `change.after` equals `value`
  (int/float compare equal, so `100 == 100.0`; lists compare in order). A missing or unknown-at-plan value fails.
- `matches: {path: regex}` — the value at `path` is a string and `re.search(regex, value)` succeeds.
- `references: {attr, to}` — in the plan's `configuration.root_module.resources`, the
  resource's expression for `attr` (or all of its expressions if `attr` is omitted) contains a
  reference to a managed resource of type `to`. Collect `references` recursively under the
  expression. A reference to `data.<type>.<name>` is followed one level: that data source's
  own references count too (this covers `aws_iam_policy_document`).

Paths are dot-separated; a numeric part indexes a list (nested blocks are lists in plan JSON),
e.g. `rule.0.apply_server_side_encryption_by_default.0.sse_algorithm`.
Reference strings look like `aws_sqs_queue.dlq.arn` or `aws_sqs_queue.dlq[0]`; the type is
the part before the first dot.

## 3. Known limits of static-correct

Static-correct is **optimistic**: passing it doesn't prove the stack works, but failing it
almost always means it doesn't. Known gaps:

- Values built from another resource's attribute are unknown at plan time (redrive policy JSON,
  bucket and queue policy JSON). So we check the *reference* instead of the content:
  `maxReceiveCount`, IAM actions and policy conditions are not checked statically. Those are
  behaviours for Phase 6, and IAM actions are partly Phase 4 (Checkov).
- References through `locals` or variables are not followed, so they fail even when correct.
- "At least one resource" means one correct subscription out of two still passes; the expected
  counts catch missing resources but not a miswired duplicate.
- `rule.0` / `ttl.0` assume the first block is the right one.
- Absence can't be checked (no internet gateway in H02, no `0.0.0.0/0` route on a private
  subnet). Those are behaviours only.
- M10's alarm isn't checked for the function dimension, because a correct answer may use a
  plain name string instead of a reference.
- H06 `failures_to_queue` has no `attr`, so any reference from the function to the queue passes.
- M06 accepts only `rate(15 minutes)` or `cron(0/15 * * * ? *)`.
- E07 checks the index name only, not its key: provider 6.x offers more than one way
  to declare a GSI key, so a key check could fail a correct answer.

## 4. Allowlist (`config/allowlist.yaml`)

Starts from plan.md §8, plus EventBridge (decision 15), S3 CORS configuration and same-account VPC peering (both free; needed by E01 and H04). Everything on it costs nothing while
idle, apart from CloudWatch alarms ($0.10 per alarm-month, prorated).
Excluded on purpose: NAT gateways and interface VPC endpoints (bill hourly), KMS customer keys
($1/month each and a 7-day minimum deletion window, which makes cleanup awkward), Secrets
Manager, EC2, RDS, load balancers. VPC endpoints are allowed as Gateway type only; Phase 4's
guard must reject any other `vpc_endpoint_type` and `PROVISIONED` DynamoDB.
Phase 6 note: H02's Lambda-in-VPC network interfaces can take 20+ minutes to release on destroy.

## 5. What each prompt probes

| Id | Trap or skill |
|---|---|
| E01 | Ownership controls and CORS as separate resources (inline blocks are deprecated) |
| E02 | Public access block flags default to false (Phase 2 run 7a74) |
| E03 | Lifecycle rule shape: status, filter, expiration block |
| E04 | `redrive_policy` vs `redrive_allow_policy` (Phase 2 run 11e5) |
| E05 | Exact attribute names and units (`delay_seconds`, bytes for `max_message_size`, `sqs_managed_sse_enabled`) |
| E06 | Exact attribute names, values in seconds |
| E07 | An `attribute` block for every key, including the GSI's (Phase 2 run 90c7) |
| E08 | Nested `ttl` and `point_in_time_recovery` blocks |
| E09 | Metric filter wired to the log group |
| E10 | Bucket policy referencing the bucket ARN, `aws:SecureTransport` condition |
| M01 | Event source mapping (missing after Step 3.0) and a role scoped to the queue |
| M02 | Environment variable plus send permission (the Phase 1 stack) |
| M03 | Queue policy for S3 and the notification; S3 checks the policy at apply time |
| M04 | S3 → SNS notification plus a topic policy for S3; S3 checks the policy at apply time |
| M05 | `aws_lambda_permission` for S3 |
| M06 | Schedule syntax and the permission for events.amazonaws.com |
| M07 | Alarm dimension pointing at the queue, alarm action at the topic |
| M08 | Read-only least privilege and a Lambda trust policy without a function |
| M09 | Stream settings plus the `starting_position` that stream sources require |
| M10 | Log group name convention `/aws/lambda/<function name>` |
| M11 | Subscription plus permission for SNS |
| M12 | Two buckets and the logging target |
| H01 | Route table association (Phase 2 run 6335) |
| H02 | VPC Lambda: VPC access policy, security group, endpoint on the route table |
| H03 | Four subnets across two AZs; tempts a `data.aws_availability_zones` lookup, which the prompt rules forbid |
| H04 | VPC peering: both VPC references, routes on both sides via the peering connection |
| H05 | HTTP API pieces, `$default` stage, permission for API Gateway |
| H06 | Async on-failure destination (or DLQ) plus two scoped permissions |
| H07 | Two DLQ pairs, raw delivery, two queue policies |
| H08 | Longest chain: custom bus → rule → queue policy → queue → mapping → Lambda → table |

## 6. Overlap with Phase 2 (checked 2026-11-13)

The 15 Phase 2 requests (`runs/20261112-*/request.txt`) against this set:

| Phase 2 run | Request | Outcome |
|---|---|---|
| 11e5 | SQS queue with a DLQ | Kept as E04, marked seen |
| 7a74 | S3 bucket that blocks all public access | Kept as E02, marked seen |
| 5f69, 36eb | Lambda triggered by an SQS queue | Kept as M01, marked seen |
| 6335 | VPC with one public subnet, IGW, route table | Kept as H01, marked seen |
| 3c8f | S3 bucket with versioning and SSE | Draft E01 was the same request → replaced (ownership + CORS) |
| 7346 | Security group, HTTPS from anywhere, SSH from a CIDR | Draft H04 was the same request → replaced (VPC peering) |
| 8ad3 | An SQS FIFO queue | Draft E05 had the same trap → replaced (delay, size, SSE) |
| 1c86 | SNS topic with an SQS queue subscribed | Draft M04 had the same trap → replaced (S3 → SNS) |
| 90c7, 5262, e826, bfa4, 857f, f7ca | DynamoDB table, Lambda → DynamoDB, Lambda hello, Lambda role, log groups | Only appear as one part of larger prompts (E07–E09, M08–M10, H02, H05, H06, H08); not counted as repeats |

Side effect: with the security-group prompt gone, H02 is the only prompt with a security
group, so Phase 4's open-ingress rule is tested by unit tests rather than by the eval set.
