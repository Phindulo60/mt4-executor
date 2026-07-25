#!/usr/bin/env bash
# Build the engine image, push to ECR, and (re)deploy the Fargate service.
#
# Prereqs (one-time): see deploy/README.md - ECR repo, IAM roles, Secrets
# Manager secret "mt4-executor/engine", an ECS cluster, a subnet, and a
# security group (outbound-only) must already exist.
#
# Usage:
#   AWS_ACCOUNT_ID=123456789012 AWS_REGION=us-east-1 \
#   CLUSTER=trading SUBNET_IDS=subnet-abc SECURITY_GROUP_ID=sg-abc \
#   ./deploy/deploy.sh
set -euo pipefail

: "${AWS_ACCOUNT_ID:?set AWS_ACCOUNT_ID}"
AWS_REGION="${AWS_REGION:-us-east-1}"
ECR_REPO="${ECR_REPO:-mt4-executor}"
CLUSTER="${CLUSTER:-trading}"
SERVICE="${SERVICE:-mt4-executor-engine}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
IMAGE="${REGISTRY}/${ECR_REPO}:${IMAGE_TAG}"
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "${HERE}/.." && pwd)"

echo ">> ECR login"
aws ecr get-login-password --region "${AWS_REGION}" \
  | docker login --username AWS --password-stdin "${REGISTRY}"

echo ">> Build + push ${IMAGE} (linux/arm64)"
docker buildx build --platform linux/arm64 -t "${IMAGE}" --push "${ROOT}"

echo ">> Render + register task definition"
TMP_TASKDEF="$(mktemp)"
sed -e "s/ACCOUNT_ID/${AWS_ACCOUNT_ID}/g" -e "s/REGION/${AWS_REGION}/g" \
  "${HERE}/ecs-task-def.json" > "${TMP_TASKDEF}"
TASKDEF_ARN="$(aws ecs register-task-definition \
  --region "${AWS_REGION}" \
  --cli-input-json "file://${TMP_TASKDEF}" \
  --query 'taskDefinition.taskDefinitionArn' --output text)"
rm -f "${TMP_TASKDEF}"
echo "   registered ${TASKDEF_ARN}"

if aws ecs describe-services --region "${AWS_REGION}" --cluster "${CLUSTER}" \
     --services "${SERVICE}" --query 'services[0].status' --output text 2>/dev/null \
     | grep -q ACTIVE; then
  echo ">> Update existing service"
  aws ecs update-service --region "${AWS_REGION}" --cluster "${CLUSTER}" \
    --service "${SERVICE}" --task-definition "${TASKDEF_ARN}" \
    --force-new-deployment >/dev/null
else
  : "${SUBNET_IDS:?set SUBNET_IDS (comma-separated) to create the service}"
  : "${SECURITY_GROUP_ID:?set SECURITY_GROUP_ID to create the service}"
  echo ">> Create service (desiredCount=1, no load balancer)"
  aws ecs create-service --region "${AWS_REGION}" --cluster "${CLUSTER}" \
    --service-name "${SERVICE}" --task-definition "${TASKDEF_ARN}" \
    --desired-count 1 --launch-type FARGATE \
    --network-configuration "awsvpcConfiguration={subnets=[${SUBNET_IDS}],securityGroups=[${SECURITY_GROUP_ID}],assignPublicIp=ENABLED}" \
    >/dev/null
fi

echo ">> Done. Tail logs:"
echo "   aws logs tail /ecs/mt4-executor-engine --follow --region ${AWS_REGION}"
