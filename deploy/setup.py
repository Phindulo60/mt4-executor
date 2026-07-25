#!/usr/bin/env python3
"""One-time AWS provisioning for the mt4-executor engine on ECS Fargate.

Idempotent: safe to re-run. Uses boto3 (works even when the `aws` CLI is
broken). Provisions everything the engine needs *except* the Docker image and
the ECS service itself (those need Docker -> run deploy/deploy.sh, e.g. from
CloudShell, after this).

Creates / ensures:
  * ECR repository            (default: mt4-executor)
  * CloudWatch log group      /ecs/mt4-executor-engine
  * IAM execution role        mt4-executor-exec-role  (+ secrets/logs policy)
  * IAM task role             mt4-executor-task-role  (no perms; least priv)
  * ECS cluster               (default: trading)
  * Security group            mt4-executor-sg (no inbound, all outbound)
  * Secrets Manager secret    mt4-executor/engine (values read from .env)

Usage:
  AWS_REGION=us-east-1 .venv-ml/bin/python deploy/setup.py
  # optional: --env-file path/to/.env  --vpc-id vpc-xxxx  --cluster trading
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

try:
    from dotenv import dotenv_values
except ImportError:  # pragma: no cover
    print("python-dotenv is required (it's a project dependency). "
          "Run inside the project venv.", file=sys.stderr)
    raise

ECR_REPO = os.getenv("ECR_REPO", "mt4-executor")
LOG_GROUP = "/ecs/mt4-executor-engine"
EXEC_ROLE = "mt4-executor-exec-role"
TASK_ROLE = "mt4-executor-task-role"
SECRET_NAME = "mt4-executor/engine"
SG_NAME = "mt4-executor-sg"

IAM_DIR = Path(__file__).resolve().parent / "iam"

SECRET_KEYS = [
    "METAAPI_TOKEN",
    "MT_LOGIN",
    "MT_PASSWORD",
    "SUPABASE_URL",
    "SUPABASE_SERVICE_KEY",
]


def load_policy(name: str, **subs: str) -> dict:
    """Load a JSON policy from deploy/iam, substituting REGION/ACCOUNT_ID.

    The files in deploy/iam are the single source of truth for these policies
    (also usable for manual provisioning); this script just applies them.
    """
    text = (IAM_DIR / name).read_text()
    for key, value in subs.items():
        text = text.replace(key, value)
    return json.loads(text)


def ok(msg: str) -> None:
    print(f"  \033[32mok\033[0m  {msg}")


def info(msg: str) -> None:
    print(f"  ..  {msg}")


def ensure_ecr(ecr) -> None:
    print(">> ECR repository")
    try:
        ecr.create_repository(repositoryName=ECR_REPO,
                              imageScanningConfiguration={"scanOnPush": True})
        ok(f"created {ECR_REPO}")
    except ecr.exceptions.RepositoryAlreadyExistsException:
        ok(f"{ECR_REPO} already exists")


def ensure_log_group(logs) -> None:
    print(">> CloudWatch log group")
    try:
        logs.create_log_group(logGroupName=LOG_GROUP)
        ok(f"created {LOG_GROUP}")
    except logs.exceptions.ResourceAlreadyExistsException:
        ok(f"{LOG_GROUP} already exists")


def ensure_role(iam, name: str, inline: dict | None, managed: list[str]) -> str:
    try:
        iam.create_role(RoleName=name,
                        AssumeRolePolicyDocument=json.dumps(load_policy("trust-policy.json")),
                        Description="mt4-executor ECS role")
        ok(f"created {name}")
    except iam.exceptions.EntityAlreadyExistsException:
        ok(f"{name} already exists")
    for arn in managed:
        iam.attach_role_policy(RoleName=name, PolicyArn=arn)
    if inline:
        iam.put_role_policy(RoleName=name, PolicyName=f"{name}-inline",
                            PolicyDocument=json.dumps(inline))
    return iam.get_role(RoleName=name)["Role"]["Arn"]


def ensure_roles(iam, region: str, account: str) -> tuple[str, str]:
    print(">> IAM roles")
    exec_inline = load_policy(
        "exec-role-inline-policy.json", REGION=region, ACCOUNT_ID=account,
    )
    exec_arn = ensure_role(
        iam, EXEC_ROLE, exec_inline,
        ["arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"],
    )
    task_arn = ensure_role(iam, TASK_ROLE, None, [])
    return exec_arn, task_arn


def ensure_cluster(ecs, cluster: str) -> None:
    print(">> ECS cluster")
    ecs.create_cluster(clusterName=cluster)  # idempotent
    ok(f"{cluster} ready")


def ensure_secret(sm, env_file: Path) -> None:
    print(">> Secrets Manager secret")
    if not env_file.exists():
        info(f"{env_file} not found - skipping secret (create it manually later)")
        return
    values = dotenv_values(env_file)
    payload = {k: values.get(k) for k in SECRET_KEYS}
    missing = [k for k, v in payload.items() if not v]
    if missing:
        info(f"missing in {env_file}: {', '.join(missing)} - skipping secret")
        return
    body = json.dumps(payload)
    try:
        sm.create_secret(Name=SECRET_NAME, SecretString=body)
        ok(f"created {SECRET_NAME}")
    except sm.exceptions.ResourceExistsException:
        sm.put_secret_value(SecretId=SECRET_NAME, SecretString=body)
        ok(f"updated {SECRET_NAME} (new version)")


def ensure_sg(ec2, vpc_id: str | None) -> tuple[str, list[str]]:
    print(">> Networking (VPC / subnets / security group)")
    if not vpc_id:
        vpcs = ec2.describe_vpcs(Filters=[{"Name": "isDefault", "Values": ["true"]}])["Vpcs"]
        if not vpcs:
            info("no default VPC found - pass --vpc-id explicitly. Skipping SG.")
            return "", []
        vpc_id = vpcs[0]["VpcId"]
        ok(f"using default VPC {vpc_id}")
    else:
        ok(f"using VPC {vpc_id}")

    subnets = [s["SubnetId"] for s in ec2.describe_subnets(
        Filters=[{"Name": "vpc-id", "Values": [vpc_id]}])["Subnets"]]
    ok(f"subnets: {', '.join(subnets) or '(none)'}")

    existing = ec2.describe_security_groups(Filters=[
        {"Name": "group-name", "Values": [SG_NAME]},
        {"Name": "vpc-id", "Values": [vpc_id]}])["SecurityGroups"]
    if existing:
        sg_id = existing[0]["GroupId"]
        ok(f"{SG_NAME} already exists ({sg_id})")
    else:
        sg_id = ec2.create_security_group(
            GroupName=SG_NAME, VpcId=vpc_id,
            Description="mt4-executor engine: outbound only, no inbound")["GroupId"]
        # Default SG allows all egress and no ingress - exactly what we want.
        ok(f"created {SG_NAME} ({sg_id}) - no inbound, all outbound")
    return sg_id, subnets


def main() -> int:
    ap = argparse.ArgumentParser(description="Provision AWS infra for the engine")
    ap.add_argument("--region", default=os.getenv("AWS_REGION", "us-east-1"))
    ap.add_argument("--cluster", default=os.getenv("CLUSTER", "trading"))
    ap.add_argument("--env-file", default=str(Path(__file__).resolve().parents[1] / ".env"))
    ap.add_argument("--vpc-id", default=os.getenv("VPC_ID"))
    args = ap.parse_args()

    region = args.region
    session = boto3.Session(region_name=region)
    account = session.client("sts").get_caller_identity()["Account"]
    print(f"Account {account}  Region {region}\n")

    ensure_ecr(session.client("ecr"))
    ensure_log_group(session.client("logs"))
    exec_arn, task_arn = ensure_roles(session.client("iam"), region, account)
    ensure_cluster(session.client("ecs"), args.cluster)
    ensure_secret(session.client("secretsmanager"), Path(args.env_file))
    sg_id, subnets = ensure_sg(session.client("ec2"), args.vpc_id)

    print("\nDone. Roles:")
    print(f"  exec: {exec_arn}")
    print(f"  task: {task_arn}")
    print("\nNext (needs Docker - run from CloudShell if local Docker is unavailable):")
    subnet_arg = ",".join(subnets[:2]) if subnets else "subnet-xxxx"
    sg_arg = sg_id or "sg-xxxx"
    print(f"  AWS_ACCOUNT_ID={account} AWS_REGION={region} \\")
    print(f"  CLUSTER={args.cluster} SUBNET_IDS={subnet_arg} SECURITY_GROUP_ID={sg_arg} \\")
    print("  ./deploy/deploy.sh")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ClientError as exc:
        print(f"\nAWS error: {exc}", file=sys.stderr)
        raise SystemExit(1)
