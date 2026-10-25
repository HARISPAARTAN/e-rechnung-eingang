#!/usr/bin/env bash
# Usage: deploy/azure.sh v0.2.0   (after `az login`; creates rg-erechnung in germanywestcentral)
# Run from the repository root. Safe to run again: the key file and the resources are reused.
set -euo pipefail
export MSYS_NO_PATHCONV=1  # Git Bash on Windows must not rewrite arguments that start with a slash
TAG="${1:?image tag, e.g. v0.2.0}"
RG="${RG:-rg-erechnung}"; LOC="${LOC:-germanywestcentral}"; IMAGE="ghcr.io/harispaartan/e-rechnung-eingang:${TAG}"
KEYFILE="deploy/.secrets/ere_api_key"
SECRETPARAMS="deploy/.secrets/secure.parameters.json"
umask 077  # key and parameter files are readable by the owner only
mkdir -p deploy/.secrets
if [ ! -s "$KEYFILE" ]; then openssl rand -hex 32 > "$KEYFILE"; echo "API-Schlüssel erzeugt in $KEYFILE (nicht teilen)"; fi
# The key goes to Azure through a git-ignored parameter file, not through the command line.
trap 'rm -f "$SECRETPARAMS"' EXIT
printf '{"$schema":"https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#","contentVersion":"1.0.0.0","parameters":{"apiKey":{"value":"%s"}}}\n' \
  "$(tr -d '\r\n' < "$KEYFILE")" > "$SECRETPARAMS"
az group create --name "$RG" --location "$LOC" --output none
az deployment group create --name "erechnung-$(date +%Y%m%d%H%M%S)" --resource-group "$RG" \
  --template-file deploy/containerapp.bicep --parameters @deploy/containerapp.parameters.json \
  --parameters @"$SECRETPARAMS" --parameters image="$IMAGE" --output none
FQDN=$(az containerapp show --name ca-erechnung --resource-group "$RG" --query properties.configuration.ingress.fqdn -o tsv)
echo "URL: https://${FQDN}"
echo "Test: curl -s https://${FQDN}/health"
