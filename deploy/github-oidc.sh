#!/usr/bin/env bash
# One time: Entra app + federated credentials (two subject forms) for GitHub environment "production" + Contributor on the resource group.
# Run after deploy/azure.sh (the resource group must exist). Safe to run again; needs `gh` (logged in) and `az` (logged in).
# REPO is fixed below: after a rename or transfer of the repository edit it here and rerun (the stale credential is
# reported, see ensure_credential).
set -euo pipefail
export MSYS_NO_PATHCONV=1  # Git Bash on Windows must not rewrite the scope path
RG="${RG:-rg-erechnung}"; APP_NAME="erechnung-github-deploy"; REPO="HARISPAARTAN/e-rechnung-eingang"

# GitHub presents the OIDC subject of an environment job in one of two forms, and Entra matches it exactly:
#   repo:OWNER/REPO:environment:production                   (names only)
#   repo:OWNER@OWNER_ID/REPO@REPO_ID:environment:production  (numeric ids; seen on the first real deploy, AADSTS700213)
# Both credentials are created so that a deploy works whichever form the token carries.
# The numeric ids are read first: if gh is missing or not logged in, nothing has been created in Entra yet.
IDS=$(gh api "repos/${REPO}" --jq '.owner.id, .id')
OWNER_ID=$(printf '%s\n' "$IDS" | sed -n 1p); REPO_ID=$(printf '%s\n' "$IDS" | sed -n 2p)
case "$OWNER_ID$REPO_ID" in ''|*[!0-9]*) echo "Abbruch: GitHub lieferte keine numerischen IDs fuer ${REPO} (owner='${OWNER_ID}', repo='${REPO_ID}')" >&2; exit 1 ;; esac
[ -n "$OWNER_ID" ] && [ -n "$REPO_ID" ] || { echo "Abbruch: leere GitHub-IDs fuer ${REPO}" >&2; exit 1; }
OWNER="${REPO%%/*}"; NAME="${REPO##*/}"
SUBJECT_NAMES="repo:${REPO}:environment:production"
SUBJECT_IDS="repo:${OWNER}@${OWNER_ID}/${NAME}@${REPO_ID}:environment:production"

SUB=$(az account show --query id -o tsv); TENANT=$(az account show --query tenantId -o tsv)
APP_ID=$(az ad app list --display-name "$APP_NAME" --query "[0].appId" -o tsv)
if [ -z "$APP_ID" ]; then APP_ID=$(az ad app create --display-name "$APP_NAME" --query appId -o tsv); az ad sp create --id "$APP_ID" --output none; fi
OBJ_ID=$(az ad app show --id "$APP_ID" --query id -o tsv)
SCOPE="/subscriptions/${SUB}/resourceGroups/${RG}"
CRED_FILE="deploy/.secrets/federated-credential.json"  # relative path: az.cmd on Windows cannot read Git Bash /tmp paths
mkdir -p deploy/.secrets
trap 'rm -f "$CRED_FILE"' EXIT

# $1 credential name, $2 expected subject. Creates the credential when it is absent, accepts it when the subject is
# the expected one, and stops with both values when a credential of that name has a different subject (Entra cannot
# change a subject in place, and a stale one would make deploys fail with AADSTS700213).
ensure_credential() {
  local count current
  count=$(az ad app federated-credential list --id "$OBJ_ID" --query "[?name=='${1}'] | length(@)" -o tsv)
  count=${count%$'\r'}  # az on Windows can end its output with a carriage return
  if [ "$count" = "0" ]; then
    printf '{"name":"%s","issuer":"https://token.actions.githubusercontent.com","subject":"%s","audiences":["api://AzureADTokenExchange"]}\n' \
      "$1" "$2" > "$CRED_FILE"
    az ad app federated-credential create --id "$OBJ_ID" --parameters "@${CRED_FILE}" --output none
    echo "Federated credential ${1} angelegt (${2})"
    return 0
  fi
  current=$(az ad app federated-credential list --id "$OBJ_ID" --query "[?name=='${1}'].subject | [0]" -o tsv)
  current=${current%$'\r'}
  if [ "$current" = "$2" ]; then
    echo "Federated credential ${1} existiert bereits"
    return 0
  fi
  {
    echo "Abbruch: Federated credential ${1} existiert mit einem anderen Subject."
    echo "  vorhanden: ${current}"
    echo "  erwartet:  ${2}"
    echo "  Abhilfe: az ad app federated-credential delete --id ${OBJ_ID} --federated-credential-id ${1}   und dieses Skript erneut ausfuehren"
  } >&2
  exit 1
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
