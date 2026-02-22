# Known Issues and Workarounds

## VPC Configuration Validation Error

### Issue

When running `make deploy` or `agentcore deploy`, you may see:
```
Validating VPC resources...
❌ VPC mode requires both subnets and security groups
```

### Root Cause

This is a **bug in agentcore CLI v1.13.0**. The configuration in `.bedrock_agentcore.yaml` is actually correct.

Verify by checking the file:
```bash
cat .bedrock_agentcore.yaml | grep -A 6 "network_configuration:"
```

You should see:
```yaml
network_configuration:
  network_mode: VPC
  network_mode_config:
    subnet_ids:
    - subnet-xxx
    - subnet-yyy
    security_group_ids:
    - sg-xxx
```

If the subnets and security groups are populated, **your configuration is correct**.

### Solution

Just run `agentcore deploy` directly:

```bash
cd agent
agentcore deploy
```

The validation error may still appear but **deployment often succeeds anyway**. If it fails, try one more time.

### Why This Happens

The agentcore CLI has a validation bug where it reports missing VPC configuration even when it's correctly set in the YAML file. This appears to be a caching or validation logic issue in strands-agents v1.13.0.

### Alternative: Skip VPC Mode

If the issue persists, you can deploy without VPC mode first, then reconfigure:

```bash
# 1. Temporarily disable VPC
agentcore configure set network_mode NO_VPC

# 2. Deploy
agentcore deploy

# 3. Re-enable VPC (when the bug is fixed)
agentcore configure set network_mode VPC
agentcore deploy --update
```

**Note**: Without VPC mode, you won't have access to on-prem Ollama hosts.

### Report Bug

This is a known issue with strands-agents v1.13.0. The validation logic incorrectly reports missing configuration even when all fields are properly populated.
