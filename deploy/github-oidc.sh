#!/usr/bin/env bash
# One time: Entra app + federated credentials (two subject forms) for GitHub environment "production" + Contributor on the resource group.
# Run after deploy/azure.sh (the resource group must exist). Safe to run again.
set -euo pipefail
export MSYS_NO_PATHCONV=1  # Git Bash on Windows must not rewrite the scope path
RG="${RG:-rg-erechnung}"; APP_NAME="erechnung-github-deploy"; REPO="HARISPAARTAN/e-rechnung-eingang"
SUB=$(az account show --query id -o tsv); TENANT=$(az account show --query tenantId -o tsv)
APP_ID=$(az ad app list --display-name "$APP_NAME" --query "[0].appId" -o tsv)
if [ -z "$APP_ID" ]; then APP_ID=$(az ad app create --display-name "$APP_NAME" --query appId -o tsv); az ad sp create --id "$APP_ID" --output none; fi
OBJ_ID=$(az ad app show --id "$APP_ID" --query id -o tsv)
SCOPE="/subscriptions/${SUB}/resourceGroups/${RG}"
CRED_FILE="deploy/.secrets/federated-credential.json"  # relative path: az.cmd on Windows cannot read Git Bash /tmp paths
mkdir -p deploy/.secrets
trap 'rm -f "$CRED_FILE"' EXIT
# GitHub presents the OIDC subject of an environment job in one of two forms, and Entra matches it exactly:
#   repo:OWNER/REPO:environment:production                   (names only)
#   repo:OWNER@OWNER_ID/REPO@REPO_ID:environment:production  (numeric ids; seen on the first real deploy, AADSTS700213)
# Both credentials are created so that a deploy works whichever form the token carries.
OWNER_ID=$(gh api "repos/${REPO}" --jq '.owner.id'); REPO_ID=$(gh api "repos/${REPO}" --jq '.id')
OWNER="${REPO%%/*}"; NAME="${REPO##*/}"
SUBJECT_NAMES="repo:${REPO}:environment:production"
SUBJECT_IDS="repo:${OWNER}@${OWNER_ID}/${NAME}@${REPO_ID}:environment:production"
ensure_credential() {  # $1 credential name, $2 subject; creates only what is missing, any other error stops the script
  printf '{"name":"%s","issuer":"https://token.actions.githubusercontent.com","subject":"%s","audiences":["api://AzureADTokenExchange"]}
'     "$1" "$2" > "$CRED_FILE"
  local existing
  existing=$(az ad app federated-credential list --id "$OBJ_ID" --query "[?name=='${1}'] | length(@)" -o tsv)
  if [ "$existing" = "0" ]; then
    az ad app federated-credential create --id "$OBJ_ID" --parameters "@${CRED_FILE}" --output none
    echo "Federated credential ${1} angelegt (${2})"
  else
    echo "Federated credential ${1} existiert bereits"
  fi
}
ensure_credential "github-production" "$SUBJECT_NAMES"
ensure_credential "github-production-ids" "$SUBJECT_IDS"
EXISTING_ROLE=$(az role assignment list --assignee "$APP_ID" --role Contributor --scope "$SCOPE" --query "length(@)" -o tsv)
if [ "$EXISTING_ROLE" = "0" ]; then
  az role assignment create --assignee "$APP_ID" --role Contributor --scope "$SCOPE" --output none
  echo "Rolle Contributor auf ${RG} vergeben"
else
  echo "Rolle Contributor auf ${RG} existiert bereits"
fi
echo "GitHub secrets (Settings > Secrets and variables > Actions):"
echo "AZURE_CLIENT_ID=${APP_ID}"; echo "AZURE_TENANT_ID=${TENANT}"; echo "AZURE_SUBSCRIPTION_ID=${SUB}"
