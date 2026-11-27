#!/usr/bin/env bash
# Put a tested main commit on the Azure app, by hand, from Azure Cloud Shell.
#
# For when the GitHub deploy cannot sign in to Azure yet. Works from the
# Cloud Shell in the Azure mobile app or in a browser, signed in as you:
#
#   curl -fsSLo release.sh https://raw.githubusercontent.com/evanroden/msapo-generator/main/scripts/azure_release_cloud_shell.sh
#   bash release.sh            # main's newest commit
#   bash release.sh <commit>   # or one commit on main
#
# It refuses a commit whose Tests run did not pass, shows what it will do and
# changes nothing until you type yes. Then it snapshots the data share, builds
# the image in the registry the app already uses (Cloud Shell has no Docker,
# so the build runs in Azure), updates the app, waits until the new revision
# is healthy (putting the old image back if it is not) and moves the backup
# job to the same image. Last, it offers the storage check
# (scripts/host_check.py) inside the running app.
set -euo pipefail
REPO=evanroden/msapo-generator
APP=${AZURE_APP:-ca-msapo}
API=https://api.github.com/repos/$REPO

json() { python3 -c "import json,sys; d=json.load(sys.stdin); print($1)"; }

COMMIT=$(curl -fsSL "$API/commits/${1:-main}" | json "d['sha']")
STATUS=$(curl -fsSL "$API/compare/$COMMIT...main" | json "d['status']")
case "$STATUS" in ahead|identical) ;; *) echo "Stopped: $COMMIT is not on main."; exit 1 ;; esac
PASSED=$(curl -fsSL "$API/actions/workflows/tests.yml/runs?head_sha=$COMMIT&branch=main&event=push&status=success" | json "d['total_count']")
[ "$PASSED" -gt 0 ] || { echo "Stopped: Tests has not passed on $COMMIT yet. Nothing changed."; exit 1; }

RG=$(az containerapp list --query "[?name=='$APP'].resourceGroup | [0]" -o tsv)
[ -n "$RG" ] || { echo "Stopped: no app named $APP in this subscription."; exit 1; }
CURRENT=$(az containerapp show -n "$APP" -g "$RG" --query "properties.template.containers[0].image" -o tsv)
ENVID=$(az containerapp show -n "$APP" -g "$RG" --query "properties.managedEnvironmentId" -o tsv)
JOB=$(az containerapp job list -g "$RG" --query "[0].name" -o tsv)
[ -n "$JOB" ] || { echo "Stopped: no backup job found in $RG."; exit 1; }

echo "App:          $APP (group $RG)"
echo "Running now:  $CURRENT"
echo "Will deploy:  main commit ${COMMIT:0:12} (Tests passed)"
echo "Backup job:   $JOB"
read -r -p 'Type yes to snapshot the data share, build and deploy: ' OK
[ "$OK" = "yes" ] || { echo "Stopped. Nothing changed."; exit 1; }

# 1. Snapshot the app's data share first.
az containerapp env storage list -n "${ENVID##*/}" -g "$RG" \
  --query "[].properties.azureFile.[accountName,shareName]" -o tsv |
while read -r ACCT SHARE; do
  KEY=$(az storage account keys list -n "$ACCT" --query "[0].value" -o tsv)
  az storage share snapshot --account-name "$ACCT" --account-key "$KEY" --name "$SHARE" -o table
done

# 2. Build that exact commit in the registry.
REG=${CURRENT%%.azurecr.io*}
IMGREPO=${CURRENT#*.azurecr.io/}; IMGREPO=${IMGREPO%%@*}; IMGREPO=${IMGREPO%%:*}
ORIGIN=https://$(az containerapp show -n "$APP" -g "$RG" --query "properties.configuration.ingress.fqdn" -o tsv)
SHORT=${COMMIT:0:12}
WORK=$(mktemp -d)
git clone -q "https://github.com/$REPO.git" "$WORK/src"
git -C "$WORK/src" checkout -q "$COMMIT"
az acr build -r "$REG" -t "$IMGREPO:$SHORT" --timeout 3600 \
  --build-arg APP_GIT_COMMIT="$COMMIT" --build-arg PUBLIC_SITE_ORIGIN="$ORIGIN" "$WORK/src"
DIGEST=$(az acr repository show -n "$REG" --image "$IMGREPO:$SHORT" --query digest -o tsv)
IMAGE="$REG.azurecr.io/$IMGREPO@$DIGEST"

# 3. Deploy it (settings stay as they are); put the old image back if it never gets healthy.
SUFFIX="c$SHORT-$(date +%s)"
az containerapp update -n "$APP" -g "$RG" --image "$IMAGE" --revision-suffix "$SUFFIX" -o none
STATE=""
for i in $(seq 1 60); do
  STATE=$(az containerapp revision show -n "$APP" -g "$RG" --revision "$APP--$SUFFIX" \
    --query "properties.healthState" -o tsv 2>/dev/null || true)
  echo "health: ${STATE:-starting}"; [ "$STATE" = "Healthy" ] && break; sleep 15
done
if [ "$STATE" != "Healthy" ]; then
  echo "The new version did not become healthy; putting the previous image back."
  az containerapp update -n "$APP" -g "$RG" --image "$CURRENT" --revision-suffix "back-$(date +%s)" -o none
  echo "Stopped. The app runs the previous image again: $CURRENT"
  exit 1
fi

# 4. Keep the nightly backup on the same image.
az containerapp job update -n "$JOB" -g "$RG" --image "$IMAGE" -o none
echo "Done. Main commit $SHORT is live on Azure."
echo "Previous image (to go back): $CURRENT"

# 5. Optional: check storage, locks and settings inside the running app.
read -r -p 'Type check to run the storage check in the app now (anything else skips): ' CHECK
if [ "$CHECK" = "check" ]; then
  az containerapp exec -n "$APP" -g "$RG" --command "python scripts/host_check.py"
fi
