# Telegram: UI shows offline / Bot not responding

## Summary

Two separate issues are involved:

1. **UI shows "Disabled" (offline)** – The `/api/telegram/config` endpoint was returning `enabled: false` because the container does not set `GLITCH_TELEGRAM_BOT_TOKEN` or `GLITCH_TELEGRAM_SECRET_NAME` in the environment (the token is loaded from Secrets Manager at startup). The API has been updated to **try DynamoDB first** (table `glitch-telegram-config`). If CONFIG exists there, the UI gets `enabled: true` and shows "Enabled" and webhook/config details.

2. **Bot not responding in chat** – Telegram sends updates to the **webhook Lambda** (`glitch-telegram-webhook`). That Lambda must exist, be reachable, and successfully invoke the AgentCore runtime. If the Lambda is missing, not registered as the webhook URL, or timing out, the bot will not reply.

---

## 1. UI shows "Disabled" or "Telegram bot not configured"

### Cause

- The API uses `_load_telegram_config_for_api()`. It now tries **DynamoDB first** (table `glitch-telegram-config`). If that succeeds, it returns `enabled: true` and the config (webhook_url, mode, policies, etc.).
- If the request to `/api/telegram/config` **fails** (e.g. timeout, 500), the UI shows `telegramError` or "Telegram bot not configured".

### Checks

1. **Confirm the request reaches the agent**  
   In CloudWatch, runtime log group `/aws/bedrock-agentcore/runtimes/Glitch-78q5TgEa8M-DEFAULT`, search for:
   - `UI API request: GET /telegram/config` or
   - `Invocation completed successfully` right after a request that had path `/api/telegram/config` (via gateway).

2. **Confirm DynamoDB has CONFIG**  
   In AWS Console → DynamoDB → Tables → `glitch-telegram-config`, check for an item with:
   - `pk` = `CONFIG`
   - `sk` = `telegram`  
   If this item is missing, the UI will get no config (and may show Enabled with defaults, or Disabled depending on path). The agent writes this when it starts and registers the webhook (DynamoDB config backend).

3. **Confirm runtime can read DynamoDB**  
   The AgentCore runtime role must have `GlitchTelegramConfigAccess` (or equivalent) allowing `dynamodb:GetItem` (and related) on `glitch-telegram-config`. If the API call fails with access denied, check IAM.

---

## 2. Bot not responding in chat

### Flow

1. User sends a message in Telegram.
2. Telegram POSTs the update to the **webhook URL** (Lambda Function URL for `glitch-telegram-webhook`).
3. The Lambda validates the webhook secret, loads config from DynamoDB, applies access rules, then **invokes the AgentCore runtime** (HTTP POST to the runtime invocations endpoint).
4. The Lambda sends the agent’s reply back to the user via the Telegram API.

If any step fails, the user gets no reply (or an error message if the Lambda sends one).

### Step 1: Confirm the webhook Lambda exists

```bash
aws lambda get-function --function-name glitch-telegram-webhook --region us-west-2
```

- If you get "ResourceNotFoundException", the Lambda was never deployed or was deleted. The **TelegramWebhookStack** (CDK) creates this Lambda; that stack is **not** currently instantiated in `infrastructure/bin/app.ts`. If you previously had it in the app and deployed it, the Lambda may still exist. If not, you need to add the stack back and deploy it (or deploy the stack from a branch/backup that still has it).

### Step 2: Get the webhook URL and confirm it’s registered with Telegram

- **Lambda Function URL** (from AWS Console → Lambda → glitch-telegram-webhook → Configuration → Function URL), or:
  ```bash
  aws lambda get-function-url-config --function-name glitch-telegram-webhook --region us-west-2
  ```
- The **agent container** registers this URL with Telegram at startup (when it has a bot token and DynamoDB config and can resolve the URL, e.g. via `get_webhook_url()` which uses `GLITCH_TELEGRAM_WEBHOOK_FUNCTION_NAME` or `get_function_url_config`). So the webhook URL in DynamoDB (`CONFIG` item, `webhook_url` attribute) should match the Lambda Function URL.
- You can also check with Telegram: call `getWebhookInfo` (e.g. `https://api.telegram.org/bot<TOKEN>/getWebhookInfo`). The `url` field should be the Lambda Function URL.

If the URL is wrong or empty, the container may have failed to register the webhook (e.g. Lambda missing, or IAM not allowing `lambda:GetFunctionUrlConfig` for the runtime role).

### Step 3: Check webhook Lambda logs

```bash
aws logs filter-log-events \
  --log-group-name "/aws/lambda/glitch-telegram-webhook" \
  --start-time $(($(date +%s) - 3600))000 \
  --region us-west-2 \
  --limit 30
```

Look for:

- **"Failed to invoke agent"** or **"timed out"** – The Lambda is receiving Telegram updates but the call to the AgentCore runtime is failing or timing out (same class of issue as the gateway timeout: increase timeout in the webhook Lambda’s HTTP call to the runtime, or fix cold start/availability).
- **Errors** (e.g. DynamoDB, Secrets Manager, Telegram API) – Fix the reported permission or configuration issue.
- **No recent events** – Telegram might not be sending updates to this URL (wrong webhook or URL not set).

### Step 4: Check runtime invocation logs

In the runtime log group, search for:

- `GLITCH_INVOKE_ENTRY` with a session that looks like `telegram:dm:...` or `telegram:group:...`

If the webhook Lambda is working but you never see these, the Lambda might be using a different runtime or the request might be failing before the container logs (e.g. timeout before response).

---

## 3. Quick checklist

| Check | Command / Location |
|-------|--------------------|
| Lambda exists | `aws lambda get-function --function-name glitch-telegram-webhook --region us-west-2` |
| Webhook URL | Lambda Console → Configuration → Function URL, or `get-function-url-config` |
| Telegram webhook set | `getWebhookInfo` with bot token (or check DynamoDB CONFIG → `webhook_url`) |
| Webhook Lambda errors | CloudWatch → Log groups → `/aws/lambda/glitch-telegram-webhook` |
| Runtime receives Telegram invocations | CloudWatch → runtime log group → filter `GLITCH_INVOKE_ENTRY` or session_id containing `telegram:` |
| DynamoDB CONFIG | DynamoDB → `glitch-telegram-config` → item `pk=CONFIG`, `sk=telegram` |
| API returns enabled | UI Telegram tab after fix: try DynamoDB first so CONFIG in DynamoDB yields `enabled: true` |

---

## 4. If the webhook Lambda is missing

The **TelegramWebhookStack** is defined in `infrastructure/lib/` as compiled JavaScript (`.js` and `.d.ts`); the TypeScript source (`.ts`) is not in the repo. That stack creates:

- Lambda `glitch-telegram-webhook` (webhook handler)
- DynamoDB table `glitch-telegram-config` (if created by this stack; your current StorageStack may instead import this table by name)
- S3 soul bucket, SSM parameters, IAM policies for the runtime, etc.

To restore the stack:

1. Re-create or restore `infrastructure/lib/telegram-webhook-stack.ts` (e.g. from the existing `.js` or from version control), then add the stack to `infrastructure/bin/app.ts` and deploy.
2. Or deploy the stack from a backup/branch that still contains the stack in the CDK app.

After deployment, ensure the agent runtime can:

- Resolve the webhook URL (e.g. `lambda:GetFunctionUrlConfig` for the webhook function).
- Be invoked by the webhook Lambda (`bedrock-agentcore:InvokeAgentRuntime` or equivalent HTTP invoke to the runtime).

Then redeploy or restart the agent so it can register the new webhook URL with Telegram at startup.
