# Deploying the engine to ECS Fargate

The engine is an always-on, **outbound-only** process: it polls Supabase for
commands and publishes telemetry. No inbound port, so no load balancer - just a
single Fargate service with `desiredCount=1`.

```
Fargate task (engine)  --outbound-->  Supabase (commands / telemetry)
                       --outbound-->  MetaApi.cloud (MT4 account)
```

> If your local `aws` CLI is broken, run the setup + `deploy.sh` from AWS
> CloudShell or any machine with a working CLI + Docker/buildx.

## One-time setup (recommended: boto3 script)

`deploy/setup.py` provisions everything infra in one idempotent run using
boto3 - handy when the `aws` CLI is unavailable. Run it from the project venv
with credentials for the target account in your environment:

```bash
AWS_REGION=us-east-1 python deploy/setup.py           # or: .venv-ml/bin/python
```

It ensures the ECR repo, CloudWatch log group, both IAM roles (with a
least-privilege secrets/logs policy on the exec role), the ECS cluster, an
outbound-only security group, and the Secrets Manager secret
`mt4-executor/engine` (values read from `.env` - it uses the **secret**
Supabase key already there). Re-running is safe. On success it prints the exact
`deploy.sh` command with the discovered subnet + security-group IDs.

Options: `--region`, `--cluster` (default `trading`), `--vpc-id` (defaults to
the account's default VPC), `--env-file`.

<details>
<summary>Manual equivalent (aws CLI)</summary>

```bash
export AWS_ACCOUNT_ID=703671911115 AWS_REGION=us-east-1
aws ecr create-repository --repository-name mt4-executor --region "$AWS_REGION"
aws secretsmanager create-secret --name mt4-executor/engine --region "$AWS_REGION" \
  --secret-string '{"METAAPI_TOKEN":"...","MT_LOGIN":"760459","MT_PASSWORD":"...","SUPABASE_URL":"https://asaxglwltlybcxlsiyfv.supabase.co","SUPABASE_SERVICE_KEY":"sb_secret_..."}'
aws ecs create-cluster --cluster-name trading --region "$AWS_REGION"
```
- **Execution role** `mt4-executor-exec-role` (trust `ecs-tasks.amazonaws.com`):
  `AmazonECSTaskExecutionRolePolicy` + inline `secretsmanager:GetSecretValue` on
  the secret and `logs:Create*`/`PutLogEvents` on the log group.
- **Task role** `mt4-executor-task-role` (trust `ecs-tasks.amazonaws.com`): no perms.
- A **subnet** with outbound internet (public + `assignPublicIp=ENABLED`, or
  private + NAT) and a **security group** with no inbound, all outbound.
</details>

## Deploy

```bash
AWS_ACCOUNT_ID=$AWS_ACCOUNT_ID AWS_REGION=$AWS_REGION \
CLUSTER=trading SUBNET_IDS=subnet-xxxx SECURITY_GROUP_ID=sg-xxxx \
./deploy/deploy.sh
```

First run creates the service; later runs update it and force a new deployment.
`SUBNET_IDS`/`SECURITY_GROUP_ID` are only required on the first (create) run.

## Operate

```bash
# Tail logs
aws logs tail /ecs/mt4-executor-engine --follow --region "$AWS_REGION"

# Stop the engine entirely (site controls start/stop; this kills the process)
aws ecs update-service --cluster trading --service mt4-executor-engine \
  --desired-count 0 --region "$AWS_REGION"
```

The engine starts **paused** - it connects to the broker and publishes
heartbeats but runs no strategy until the site sends `start`. `flatten` and
manual buy/sell work whether running or paused.

## DEMO smoke-test before going live

Point the secret at a demo account and change the server env var, then deploy:
- In the secret: set `MT_LOGIN`/`MT_PASSWORD` to the demo account.
- In `deploy/ecs-task-def.json`: set `MT_SERVER` to the demo server
  (e.g. `TradeNation-DemoBravo`).
Verify the site shows a live heartbeat, then exercise start / manual buy /
flatten and confirm fills in the `trades` table before switching back to live.

## Cost

0.25 vCPU / 0.5 GB Fargate running 24/7 is roughly \$9/month plus a few
cents of ECR storage. Scale the task `cpu`/`memory` in the task def if needed.
