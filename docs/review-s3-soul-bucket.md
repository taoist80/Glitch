# Code review: S3 soul bucket (TelegramWebhookStack)

Review of the S3 bucket and related IAM/SSM changes in `infrastructure/lib/telegram-webhook-stack.ts` for persistent SOUL.md and poet-soul.md.

---

## What was added

1. **GlitchSoulBucket** – S3 bucket for agent personality state:
   - `bucketName`: `glitch-agent-state-${account}-${region}` (unique per account/region)
   - `removalPolicy: RETAIN`
   - `blockPublicAccess: BlockPublicAccess.BLOCK_ALL`
   - `encryption: BucketEncryption.S3_MANAGED`

2. **SSM parameters** (runtime discovery without env vars):
   - `/glitch/soul/s3-bucket` → bucket name
   - `/glitch/soul/s3-key` → `soul.md`
   - `/glitch/soul/poet-soul-s3-key` → `poet-soul.md`

3. **IAM (AwsCustomResource)** – inline policies on the AgentCore runtime role:
   - **GlitchSoulS3Access**: `s3:GetObject`, `s3:PutObject` on `this.soulBucket.arnForObjects('*')`
   - **GlitchSoulSsmRead**: `ssm:GetParameter`, `ssm:GetParameters` on the three SSM parameter ARNs

4. **CfnOutput**: `GlitchSoulBucketName` exported.

Agent code (`soul_tools.py`, `poet_soul.py`) already supports `GLITCH_SOUL_S3_BUCKET` and SSM fallback; the stack provisions the bucket and grants the runtime role access.

---

## Correctness

- **Bucket naming**: Physical name is deterministic and unique per account/region; no collision risk.
- **Policy injection**: `cdk.Fn.sub` correctly injects `soulBucketObjectsArn` into the IAM policy JSON; `Resource: ['${SoulBucketObjectsArn}']` resolves to the bucket object ARN (`arn:aws:s3:::bucket-name/*`).
- **SSM parameter ARNs**: Used in the SSM read policy; CDK resolves them correctly.
- **AwsCustomResource**: Stable `PhysicalResourceId` per policy; onCreate/onUpdate/onDelete are consistent. onUpdate re-applies the same policy document so drift is corrected.

---

## Security

| Item | Status |
|------|--------|
| Public access | **Good** – `BlockPublicAccess.BLOCK_ALL`. |
| Encryption | **Good** – `S3_MANAGED` (SSE-S3). |
| IAM scope (S3) | **Good** – Only `s3:GetObject`, `s3:PutObject` on the bucket’s object ARN. No `s3:ListBucket` or `s3:DeleteObject`; matches read/write SOUL usage. |
| IAM scope (SSM) | **Good** – Only `ssm:GetParameter` / `GetParameters` on the three parameter ARNs. |
| Resource ARN | S3 policy uses `arnForObjects('*')` (entire bucket). Keys are effectively constrained by app logic (soul.md, poet-soul.md). Narrowing to a key prefix in IAM would require baking key names into the stack; current design is acceptable. |

---

## Optional improvements

1. **Versioning**  
   Bucket versioning is not enabled. Enabling it would allow recovery from accidental overwrites of SOUL.md. If you want simple rollback, add:
   ```ts
   versioned: true,  // optional
   ```
   (Lifecycle rules can be added later to expire old versions if needed.)

2. **Least privilege on S3 keys**  
   To restrict the role to only the two keys used by the app, you could add a second statement (or a single statement with two resources) for `arnForObjects('soul.md')` and `arnForObjects('poet-soul.md')`. That would require the stack to own key names; with keys configurable via SSM, the current single `arnForObjects('*')` is a reasonable tradeoff.

3. **CloudWatch PutMetricData**  
   The telemetry policy uses `Resource: '*'` with a condition on `cloudwatch:namespace` (Glitch/Agent). That’s a common and acceptable pattern; no change required.

---

## Operations and docs

- **Architecture.md** – Already documents S3/SSM flow, env vars, and that the runtime discovers the bucket via SSM when the stack is deployed. No update needed.
- **Runtime role** – The stack assumes the same execution role (`defaultExecutionRoleArn`) is used by the AgentCore runtime; otherwise the attached policies have no effect. Documented in Architecture.md.
- **VPC / S3 access** – The runtime (in the private subnet) must be able to reach S3 (e.g. via VPC gateway endpoint for S3 or NAT). The diagram mentions “S3 (Gateway)” in the VPC endpoints; ensure the stack that creates the VPC provides an S3 endpoint so the runtime can access the soul bucket without internet.

---

## Summary

| Area | Verdict |
|------|--------|
| Correctness | Bucket, SSM, and IAM wiring are correct. |
| Security | Block public access, encryption, and least-privilege S3/SSM are in place. |
| IAM | Scoped to GetObject/PutObject and SSM read; no broad wildcards. |
| Optional | Consider bucket versioning for SOUL.md recovery. |

No blocking issues; the S3 soul bucket implementation is sound and ready to use.
