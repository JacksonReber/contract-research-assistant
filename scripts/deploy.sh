#!/usr/bin/env bash
# Deploy knowledge-assistant-demo-v3 to Databricks Apps.
# Usage: ./scripts/deploy.sh [app-name] [--profile <profile>] [--skip-build]
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'

APP_NAME="${1:-contract-research-assistant}"
PROFILE="DEFAULT"
SKIP_BUILD=false

shift || true
while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile) PROFILE="$2"; shift 2 ;;
    --skip-build) SKIP_BUILD=true; shift ;;
    -h|--help)
      echo "Usage: $0 [app-name] [--profile <profile>] [--skip-build]"
      echo "  Default app-name: contract-research-assistant"
      echo "  Default profile:  DEFAULT"
      exit 0 ;;
    *) echo -e "${RED}Unknown arg: $1${NC}"; exit 1 ;;
  esac
done

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAGING="/tmp/${APP_NAME}-deploy"
CLI="databricks --profile $PROFILE"

echo -e "${BLUE}=== Deploying ${APP_NAME} to Databricks Apps ===${NC}"
echo "  profile: $PROFILE"

# 1. Check CLI auth
if ! $CLI auth describe &> /dev/null; then
  echo -e "${RED}Not authenticated. Run: databricks auth login --profile $PROFILE${NC}"
  exit 1
fi
CURRENT_USER=$($CLI current-user me --output json 2>/dev/null | python3 -c "
import sys, json; d=json.load(sys.stdin)
print(d.get('userName', d.get('user_name', '')))
")
WORKSPACE_PATH="/Workspace/Users/${CURRENT_USER}/apps/${APP_NAME}"
echo "  user: $CURRENT_USER"
echo "  deploy path: $WORKSPACE_PATH"
echo ""

# 2. Build frontend
if [ "$SKIP_BUILD" = true ]; then
  if [ ! -d "$ROOT/client/out" ]; then
    echo -e "${RED}--skip-build set but $ROOT/client/out does not exist${NC}"
    exit 1
  fi
  echo -e "${YELLOW}[1/5] Skipping frontend build (--skip-build)${NC}"
else
  echo -e "${YELLOW}[1/5] Building frontend${NC}"
  cd "$ROOT/client"
  if [ ! -d node_modules ]; then npm install --silent; fi
  npm run build
  cd "$ROOT"
fi

# 3. Stage deployment package
echo -e "${YELLOW}[2/5] Staging deployment package at $STAGING${NC}"
rm -rf "$STAGING"
mkdir -p "$STAGING"
cp -r server "$STAGING/"
cp pyproject.toml app.yaml agent_config.yaml "$STAGING/"
[ -f uv.lock ] && cp uv.lock "$STAGING/"
mkdir -p "$STAGING/client"
cp -r client/out "$STAGING/client/"
find "$STAGING" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
find "$STAGING" -type f -name "*.pyc" -delete 2>/dev/null || true

# 4. Ensure app exists
echo -e "${YELLOW}[3/5] Ensuring app '${APP_NAME}' exists${NC}"
if ! $CLI apps get "$APP_NAME" &> /dev/null; then
  echo "  creating app..."
  $CLI apps create "$APP_NAME"
else
  echo -e "  ${GREEN}\xe2\x9c\x93${NC} app exists"
fi
SP_CLIENT_ID=$($CLI apps get "$APP_NAME" --output json | python3 -c "import sys,json; print(json.load(sys.stdin).get('service_principal_client_id', ''))")
echo "  service principal: $SP_CLIENT_ID"

# 5. Upload to workspace
echo -e "${YELLOW}[4/5] Uploading to ${WORKSPACE_PATH}${NC}"
$CLI workspace import-dir "$STAGING" "$WORKSPACE_PATH" --overwrite 2>&1 | tail -3

# 6. Deploy
echo -e "${YELLOW}[5/5] Deploying app${NC}"
DEPLOY_OUT=$($CLI apps deploy "$APP_NAME" --source-code-path "$WORKSPACE_PATH" 2>&1)
echo "$DEPLOY_OUT"

if echo "$DEPLOY_OUT" | grep -qE '"state":[[:space:]]*"SUCCEEDED"'; then
  APP_URL=$($CLI apps get "$APP_NAME" --output json | python3 -c "import sys,json;print(json.load(sys.stdin).get('url',''))")
  echo ""
  echo -e "${GREEN}=== Deployed successfully ===${NC}"
  echo -e "  URL: ${GREEN}${APP_URL}${NC}"
  echo ""
  echo "Permissions reminder:"
  echo "  - Each end user needs CAN_QUERY on the LLM serving endpoint."
  echo "  - Each end user needs USE INDEX on the VS index."
  echo "  - SP needs USE CATALOG/SCHEMA + MODIFY/SELECT on the UC trace tables."
  echo ""
  echo "Logs:  open ${APP_URL}/logz"
else
  echo ""
  echo -e "${RED}Deployment did not report SUCCEEDED. Check output above.${NC}"
  echo "Logs:  open URL above + /logz"
  exit 1
fi
