#!/usr/bin/env bash
# One time: Entra app + federated credential for GitHub environment "production" + Contributor on the resource group.
# Run after deploy/azure.sh (the resource group must exist). Safe to run again.
set -euo pipefail
export MSYS_NO_PATHCONV=1  # Git Bash on Windows must not rewrite the scope path
RG="${RG:-rg-erechnung}"; APP_NAME="erechnung-github-deploy"; REPO="HARISPAARTAN/e-rechnung-eingang"
SUB=$(az account show --query id -o tsv); TENANT=$(az account show --query tenantId -o tsv)
APP_ID=$(az ad app list --display-name "$APP_NAME" --query "[0].appId" -o tsv)
if [ -z "$APP_ID" ]; then APP_ID=$(az ad app create --display-name "$APP_NAME" --query appId -o tsv); az ad sp create --id "$APP_ID" --output none; fi
OBJ_ID=$(az ad app show --id "$APP_ID" --query id -o tsv)
az ad app federated-credential create --id "$OBJ_ID" --parameters "{\"name\":\"github-production\",\"issuer\":\"https://token.actions.githubusercontent.com\",\"subject\":\"repo:${REPO}:environment:production\",\"audiences\":[\"api://AzureADTokenExchange\"]}" --output none 2>/dev/null || echo "Federated credential existiert bereits"
az role assignment create --assignee "$APP_ID" --role Contributor --scope "/subscriptions/${SUB}/resourceGroups/${RG}" --output none 2>/dev/null || true
echo "GitHub secrets (Settings > Secrets and variables > Actions):"
echo "AZURE_CLIENT_ID=${APP_ID}"; echo "AZURE_TENANT_ID=${TENANT}"; echo "AZURE_SUBSCRIPTION_ID=${SUB}"
