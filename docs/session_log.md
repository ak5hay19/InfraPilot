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
