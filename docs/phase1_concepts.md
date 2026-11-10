# Phase 1 — Terraform concepts (study notes)

Everything here comes from my own stack in `learning/` (region `ap-south-1`, prefix `infrapilot-learn`).

## 1. The stack in one picture

8 managed resources. Arrows mean "must exist before".

```
random_id.bucket_suffix ──► aws_s3_bucket.learn ──► aws_s3_bucket_public_access_block.learn

aws_sqs_queue.learn ──┬──► (data) send_to_queue ──► aws_iam_role_policy.send_to_queue ──┐
                      │                                    ▲                            │
                      │                                    │                            ▼
(data) lambda_assume_role ──► aws_iam_role.lambda ──┬──────┘                            │
                                                    └──► aws_iam_role_policy_attachment ─┤
(data) archive_file.lambda (the zip) ───────────────────────────────────────────────────┤
aws_sqs_queue.learn (its .url, for QUEUE_URL) ──────────────────────────────────────────┤
                                                                                        ▼
                                                                         aws_lambda_function.learn
```

When I invoke `infrapilot-learn-fn`:
- Lambda assumes the role (the trust policy allows it).
- `handler.py` reads `QUEUE_URL` from the environment.
- It calls `sqs.send_message` with the body `hello from infrapilot-learn-fn`.
- It returns `{"message_id": "..."}`. The message waits in `infrapilot-learn-queue`.

## 2. Concepts

**Provider**
- **What it is:** a plugin that lets Terraform talk to one service, like AWS.
- **In my stack:** `provider "aws"` in `main.tf` with `region = var.region`. Pinned `~> 6.0` (also `random`, `archive`).
- **Why it matters:** pinning stops surprise upgrades; the model's "hallucinated arguments" (Phase 2) are arguments the provider doesn't have.

**Resource**
- **What it is:** one real thing Terraform creates and manages.
- **In my stack:** `aws_sqs_queue.learn` makes the queue `infrapilot-learn-queue`. I have 8 of these.
- **Why it matters:** the Phase 4 plan guard checks resource types against an allowlist.

**Variable**
- **What it is:** an input, so values aren't hardcoded.
- **In my stack:** `variables.tf` has `region` (default `ap-south-1`) and `name_prefix` (default `infrapilot-learn`). Used as `var.name_prefix`.
- **Why it matters:** generated Terraform must use one region and not hardcode it (qwen3 got this wrong).

**Output**
- **What it is:** a value Terraform prints after apply and stores in state.
- **In my stack:** `outputs.tf` has `bucket_name`, `bucket_arn`, `queue_url`, `function_name`.
- **Why it matters:** Phase 6 probes take resource names from the Terraform outputs.

**Data source**
- **What it is:** something Terraform reads or computes. It creates nothing in AWS.
- **In my stack:** `data.aws_iam_policy_document.send_to_queue` builds policy JSON; `data.archive_file.lambda` zips `handler.py`.
- **Why it matters:** data sources appear in the plan JSON with action "read". The Phase 4 guard must skip them.

**State**
- **What it is:** a file (`terraform.tfstate`) that maps my `.tf` resources to the real AWS things.
- **In my stack:** it also holds values I never wrote, like AES256 encryption and `versioning` false (AWS defaults read back).
- **Why it matters:** lose it and Terraform forgets what it built, so it can't destroy it. Phase 7 moves state to S3.

**Plan vs apply**
- **What it is:** plan = a preview of changes; apply = actually make them.
- **In my stack:** `terraform plan "-out=plan.tfplan"` saves the plan; `terraform apply plan.tfplan` applies exactly that.
- **Why it matters:** Phases 2-4 only plan (free, read-only profile). Apply starts in Phase 6.

**Destroy**
- **What it is:** deletes everything in state, in reverse dependency order.
- **In my stack:** `terraform destroy` removed all 8 resources. The Lambda's log group survived (not in state).
- **Why it matters:** Phase 6 runs destroy in a `finally` block; Phase 7's janitor handles what's left.

**Dependency / reference**
- **What it is:** using one resource's value in another makes Terraform build them in order.
- **In my stack:** `resources = [aws_sqs_queue.learn.arn]` in `send_to_queue`, so the queue comes first. `depends_on` forces order when nothing is referenced (the Lambda and the policies).
- **Why it matters:** models often write a reference to something that doesn't exist (Phase 2 failure type).

**default_tags (tags vs tags_all)**
- **What it is:** tags set once on the provider and added to every taggable resource.
- **In my stack:** `project = "infrapilot"` in `provider "aws"`. It shows up in `tags_all`, not `tags`.
- **Why it matters:** Phases 6-7 find and clean up resources by the `project=infrapilot` tag.

## 3. IAM in two questions

**Who may become the role?** The trust policy (`assume_role_policy`):

```json
{ "Effect": "Allow",
  "Principal": { "Service": "lambda.amazonaws.com" },
  "Action": "sts:AssumeRole" }
```

**What may the role do once assumed?** The permissions policies:
- `AWSLambdaBasicExecutionRole` (managed): write CloudWatch logs.
- Inline `send-to-learn-queue`: one action, one queue.

```json
{ "Effect": "Allow",
  "Action": "sqs:SendMessage",
  "Resource": "arn:aws:sqs:ap-south-1:<account-id>:infrapilot-learn-queue" }
```

**The AccessDenied lesson (console).** My first test failed: "no identity-based policy allows the action".
- The queue's default policy names my account root. That only *delegates* to IAM; it doesn't grant the role anything.
- The role needed its own identity policy. Within one account, resource policy OR identity policy is enough. Across accounts you need both.
- The error showed `assumed-role/infrapilot-learn-lambda-role/...`, so the trust policy had worked.

## 4. What happened on apply and destroy

Order comes from the dependency graph. Steps on the same line can run in parallel, and their exact interleaving varies.

**Apply**
1. Plan time: read `archive_file` (zip) and `lambda_assume_role`. They have no unknowns.
2. `random_id`, `aws_sqs_queue` and `aws_iam_role` have no dependencies, so they start at once. In my runs the queue and bucket were created at the same time.
3. Then the bucket (needs `random_id`) and the policy attachment (needs the role). `send_to_queue` data is read once the queue ARN exists. SQS takes about 25s, S3 about 1s.
4. Then the public access block (needs the bucket) and the inline policy (needs the role and the queue ARN).
5. Last, the Lambda: it needs the role, zip and queue URL, and `depends_on` makes it wait for both policies.

**Destroy**: the reverse. Lambda first, then the policies, access block, role, bucket, queue (about 43s), and `random_id` at the end. Nothing is deleted before the things that depend on it.

## 5. Lessons / gotchas I hit

- **`max_message_size`:** Terraform's default is 262144 (256 KiB); the console showed 1024 KiB. Read the plan, don't assume.
- **`(known after apply)`:** AWS decides the value. The bucket name was unknown at plan time because of `random_id`.
- **Plan JSON: 9 entries for 8 resources.** The extra one is the data source `send_to_queue` with action "read". The Phase 4 guard must filter `mode == "managed"` and ignore "read".
- **Log group left behind:** Lambda creates `/aws/lambda/infrapilot-learn-fn` on first invoke. Terraform doesn't manage it, so destroy leaves it. I deleted it with the CLI. Phases 6-7 cleanup must cover log groups.
- **`random_id` regenerates after destroy:** next apply = new bucket name (`...-04c4b592` vs `...-07a03593`).
- **PowerShell:** quote the flag, `"-out=plan.tfplan"`. Never type `<...>` placeholders; PowerShell reads `<` as an operator.
- **Runtime:** the console defaulted to a Python 3.15 preview. I pinned stable `python3.12`.
- **SQS name reuse:** a deleted queue's name can't be reused for 60 seconds.
- **qwen3's earlier mistakes:** invalid `region` inside `aws_s3_bucket`; the deprecated inline `versioning` block next to the separate versioning resource; a hardcoded region I never asked for; unrequested extras (logging, website, commented-out blocks).

## 6. Commands cheat sheet

```
terraform init                      # download providers, write the lock file
terraform fmt                       # tidy formatting
terraform validate                  # check syntax and references (no AWS calls)
terraform plan                      # preview changes
terraform plan "-out=plan.tfplan"   # save the plan (quote it in PowerShell)
terraform show -json plan.tfplan    # plan as JSON (Phase 4 parses this)
terraform apply                     # build it (asks yes)
terraform apply plan.tfplan         # apply exactly the saved plan (no prompt)
terraform state list                # everything in state, data sources too
terraform state show aws_sqs_queue.learn
terraform output                    # all outputs
terraform output -raw queue_url     # bare value, no quotes
terraform destroy                   # delete everything in state
```

AWS CLI checks (PowerShell):

```
aws lambda invoke --function-name infrapilot-learn-fn --region ap-south-1 out.json
aws sqs receive-message --queue-url (terraform output -raw queue_url) --region ap-south-1
aws logs delete-log-group --log-group-name /aws/lambda/infrapilot-learn-fn --region ap-south-1
```

## 7. 60-second whiteboard script

"My `.tf` files describe 8 resources. On `terraform apply`, Terraform reads the files, builds a dependency graph from the references, and compares it to state. Things with no dependencies start first: the random suffix, the queue and the IAM role. The bucket waits for the suffix; the access block waits for the bucket. The inline policy uses the queue's ARN, so it waits for the queue and the role. That policy allows only `sqs:SendMessage` on that one queue. The Lambda goes last: it needs the role, the zip, and the queue URL for its `QUEUE_URL` variable, and `depends_on` makes it wait for both policies. When I invoke it, Lambda assumes the role, the code sends a message to the queue, and returns the message ID. State records what was built, so `destroy` can remove it in reverse."

## 8. Self-check questions

1. Why does the bucket name have a random suffix, but the queue name doesn't?
   *S3 names are global across all AWS accounts; SQS names only need to be unique in one account and region.*
2. What does "(known after apply)" mean?
   *AWS decides that value, so Terraform can't know it until the resource exists.*
3. What is a data source, and does it create anything?
   *Something Terraform reads or computes; it creates nothing in AWS.*
4. Why did the inline policy wait for the queue?
   *It uses `aws_sqs_queue.learn.arn`, a reference, which creates a dependency.*
5. Why does the Lambda need `depends_on` when other resources don't?
   *It never reads the policies' values, so Terraform wouldn't order it after them on its own.*
6. What does state hold, and what happens if I lose it?
   *The map from my `.tf` resources to real AWS objects; without it Terraform can't manage or destroy what it built.*
7. Trust policy vs permissions policy?
   *Trust = who may become the role (`lambda.amazonaws.com`); permissions = what the role may do (`sqs:SendMessage` on one queue).*
8. Why does a plan guard have to filter on `mode == "managed"`?
   *Data sources show up in the plan JSON with action "read"; they aren't resources being created.*
