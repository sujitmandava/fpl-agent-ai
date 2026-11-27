#!/usr/bin/env bash
# Deploy the planning API to Google Cloud Run, plus a Cloud Scheduler job that
# keeps its FPL data fresh. Safe to re-run: it updates what's already there.
#
#   GCP_PROJECT=my-project deploy/cloudrun.sh
#
# Stays inside Cloud Run's free tier for a small league: scales to zero, one
# instance at most, CPU billed only while a request runs.
set -euo pipefail

PROJECT="${GCP_PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${GCP_REGION:-us-central1}"
SERVICE="${GCP_SERVICE:-fpl-api}"
JOB="${SERVICE}-refresh"
[ -n "$PROJECT" ] || { echo "Set GCP_PROJECT (or gcloud config set project …)." >&2; exit 1; }

cd "$(dirname "$0")/.."
gc() { gcloud --project "$PROJECT" --quiet "$@"; }

echo "→ Enabling APIs in $PROJECT"
gc services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com cloudscheduler.googleapis.com

# `run deploy --source` pushes the image here; creating it up front avoids a
# permission error on brand-new projects.
gc artifacts repositories describe cloud-run-source-deploy --location "$REGION" >/dev/null 2>&1 \
  || gc artifacts repositories create cloud-run-source-deploy --location "$REGION" \
       --repository-format docker --description "Cloud Run source deployments"

# Reuse the refresh token already on the service so the scheduler job keeps working.
TOKEN="$(gc run services describe "$SERVICE" --region "$REGION" --format=json 2>/dev/null \
  | python3 -c 'import json,sys
try:
    env = json.load(sys.stdin)["spec"]["template"]["spec"]["containers"][0].get("env", [])
    print(next(e["value"] for e in env if e["name"] == "FPL_REFRESH_TOKEN"))
except Exception:
    pass' || true)"
[ -n "$TOKEN" ] || TOKEN="$(openssl rand -hex 32)"

echo "→ Building and deploying $SERVICE to $REGION"
gc run deploy "$SERVICE" --source . --region "$REGION" \
  --allow-unauthenticated \
  --cpu 1 --memory 512Mi \
  --min-instances 0 --max-instances 1 --concurrency 20 --timeout 300 \
  --set-env-vars "FPL_BACKGROUND_REFRESH=0,FPL_REFRESH_TOKEN=$TOKEN"

URL="$(gc run services describe "$SERVICE" --region "$REGION" --format='value(status.url)')"

echo "→ Scheduling a data refresh every 10 minutes"
SCHED=(--location "$REGION" --schedule "*/10 * * * *" --time-zone "Etc/UTC"
       --uri "$URL/api/refresh" --http-method POST
       --attempt-deadline 300s)
HEADER="X-Refresh-Token=$TOKEN"
# `create` takes --headers; `update` only accepts --update-headers.
if gc scheduler jobs describe "$JOB" --location "$REGION" >/dev/null 2>&1; then
  gc scheduler jobs update http "$JOB" "${SCHED[@]}" --update-headers "$HEADER" --format none
else
  gc scheduler jobs create http "$JOB" "${SCHED[@]}" --headers "$HEADER" --format none
fi
gc scheduler jobs run "$JOB" --location "$REGION" >/dev/null   # warm it now

echo
echo "API: $URL"
echo "Check: curl $URL/api/health"
echo "Use it as FPL_API_URL when deploying the web app (web/: pnpm run deploy)."
