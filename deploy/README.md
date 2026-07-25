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

## One-time setup

Pick an account/region (defaults below use the trading account, `us-east-1`).

```bash
export AWS_ACCOUNT_ID=703671911115
export AWS_REGION=us-east-1
```

### 1. ECR repository
```bash
aws ecr create-repository --repository-name mt4-executor --region "$AWS_REGION"
```

### 2. Secrets Manager secret (engine credentials)
One secret with JSON keys the task definition maps to env vars:
```bash
aws secretsmanager create-secret --name mt4-executor/engine --region "$AWS_REGION" \
  --secret-string '{
    "METAAPI_TOKEN":"...",
    "MT_LOGIN":"760459",
    "MT_PASSWORD":"...",
    "SUPABASE_URL":"https://asaxglwltlybcxlsiyfv.supabase.co",
    "SUPABASE_SERVICE_KEY":"sb_secret_..."
  }'
```
Use the **secret** Supabase key (`sb_secret_...`), never the publishable one.

### 3. IAM roles
- **Execution role** `mt4-executor-exec-role` - trust `ecs-tasks.amazonaws.com`;
  attach `AmazonECSTaskExecutionRolePolicy` plus a policy allowing
  `secretsmanager:GetSecretValue` on the secret above (needed to inject secrets)
  and `logs:CreateLogGroup` (task def uses `awslogs-create-group`).
- **Task role** `mt4-executor-task-role` - trust `ecs-tasks.amazonaws.com`;
  needs no AWS permissions (the engine only talks to Supabase + MetaApi over
  the internet). Kept distinct for least privilege.

### 4. Cluster + networking
```bash
aws ecs create-cluster --cluster-name trading --region "$AWS_REGION"
```
- A **subnet** with outbound internet (public subnet + `assignPublicIp=ENABLED`,
  or a private subnet + NAT gateway).
- A **security group** with **no inbound rules** and all outbound allowed.

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

0.25 vCPU / 0.5 GB ARM64 Fargate running 24/7 is roughly \$9/month plus a few
cents of ECR storage. Scale the task `cpu`/`memory` in the task def if needed.
