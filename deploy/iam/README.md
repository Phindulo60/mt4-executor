# IAM policies (reference)

These are the exact policies `deploy/setup.py` applies. Provided as standalone
files for review or manual (`aws iam`) provisioning. Replace `ACCOUNT_ID` and
`REGION` before using manually.

| File | Applied to | Purpose |
|---|---|---|
| `trust-policy.json` | both roles (`AssumeRolePolicyDocument`) | lets ECS tasks assume the role |
| `exec-role-inline-policy.json` | `mt4-executor-exec-role` (inline) | read the engine secret + write logs |

The **execution role** also gets the AWS-managed
`arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy`
(ECR image pull + base logs). The **task role** (`mt4-executor-task-role`) gets
only the trust policy and no permissions - the engine talks solely to Supabase
and MetaApi over the internet, so it needs no AWS API access.

## Manual apply (aws CLI)

```bash
export ACCOUNT_ID=703671911115 REGION=us-east-1

# Execution role
aws iam create-role --role-name mt4-executor-exec-role \
  --assume-role-policy-document file://deploy/iam/trust-policy.json
aws iam attach-role-policy --role-name mt4-executor-exec-role \
  --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy
sed -e "s/ACCOUNT_ID/$ACCOUNT_ID/g" -e "s/REGION/$REGION/g" \
  deploy/iam/exec-role-inline-policy.json > /tmp/exec-inline.json
aws iam put-role-policy --role-name mt4-executor-exec-role \
  --policy-name mt4-executor-exec-role-inline \
  --policy-document file:///tmp/exec-inline.json

# Task role (no permissions)
aws iam create-role --role-name mt4-executor-task-role \
  --assume-role-policy-document file://deploy/iam/trust-policy.json
```
