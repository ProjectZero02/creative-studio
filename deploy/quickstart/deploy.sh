#!/usr/bin/env bash
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# GenMedia Studio: one-command Cloud Run deploy for demos.
#
# Run it from the repo root in Cloud Shell (or anywhere `gcloud` is signed in):
#
#   bash deploy/quickstart/deploy.sh --project MY_PROJECT --admin-email me@company.com
#
# It is safe to re-run: every step checks before it creates.
# It sets up:
#   1. the required APIs (from deploy/scripts/apis.txt)
#   2. a runtime service account with the roles the app needs
#   3. a GCS bucket for generated media (private)
#   4. a Firestore database and the indexes the library queries need
#   5. sign-in secrets in Secret Manager (session mode only)
#   6. Cloud Run: built from source, session affinity, CPU boost,
#      a 60-minute timeout for long Veo jobs, CPU kept on while an instance
#      runs (Story Studio renders in the background), and scale to zero.
#
# Sign-in options (--auth):
#   session (default)  the app's own sign-in page and user list. The URL is
#                      reachable on the internet, but every page needs a login.
#   iap                Google sign-in through Identity-Aware Proxy. Only
#                      Google accounts you grant "IAP-secured Web App User" get in.
#
# Costs: Cloud Run scales to zero, so an idle demo costs close to nothing.
# Generation (Vertex AI), storage and Firestore are billed per use.
set -euo pipefail

PROJECT="${PROJECT_ID:-}"
REGION="us-central1"
SERVICE="genmedia-studio"
AUTH="session"
ADMIN_EMAIL=""
MIN_INSTANCES=0
MAX_INSTANCES=3
DRY_RUN=0
FIRESTORE_DB="create-studio-asset-metadata"

usage() {
  cat <<'EOF'
Usage: bash deploy/quickstart/deploy.sh --project ID [options]

  --project ID          Google Cloud project to deploy into (required)
  --region REGION       Cloud Run, bucket and Firestore region (default us-central1)
  --service NAME        Cloud Run service name (default genmedia-studio)
  --auth session|iap    How people sign in (default session)
  --admin-email EMAIL   First admin account (session mode, required on first deploy)
  --max-instances N     Upper limit on instances (default 3)
  --min-instances N     Keep N instances warm. Above 0 costs money all day (default 0)
  --dry-run             Print the commands instead of running them
  -h, --help            Show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project) PROJECT="$2"; shift 2 ;;
    --region) REGION="$2"; shift 2 ;;
    --service) SERVICE="$2"; shift 2 ;;
    --auth) AUTH="$2"; shift 2 ;;
    --admin-email) ADMIN_EMAIL="$2"; shift 2 ;;
    --max-instances) MAX_INSTANCES="$2"; shift 2 ;;
    --min-instances) MIN_INSTANCES="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 2 ;;
  esac
done

say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
run() {
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    printf '  [dry-run] %q' "$1"; shift; printf ' %q' "$@"; printf '\n'
  else
    "$@"
  fi
}

[[ -n "${PROJECT}" ]] || { echo "Missing --project" >&2; usage; exit 2; }
[[ "${AUTH}" == "session" || "${AUTH}" == "iap" ]] || { echo "--auth must be session or iap" >&2; exit 2; }
[[ -f main.py && -f deploy/scripts/apis.txt ]] || { echo "Run this from the repo root." >&2; exit 2; }
command -v gcloud >/dev/null || { echo "gcloud is not installed. Use Cloud Shell." >&2; exit 2; }

SA_NAME="genmedia-studio-run"
SA_EMAIL="${SA_NAME}@${PROJECT}.iam.gserviceaccount.com"
BUCKET="${PROJECT}-genmedia-assets"
G=(--project="${PROJECT}" --quiet)

say "Project ${PROJECT}, region ${REGION}, service ${SERVICE}, sign-in: ${AUTH}"

# 1. APIs ---------------------------------------------------------------------
say "1/6 Turning on APIs"
mapfile -t APIS < <(grep -Ev '^\s*(#|$)' deploy/scripts/apis.txt)
[[ "${AUTH}" == "session" ]] && APIS+=("secretmanager.googleapis.com")
run gcloud services enable "${APIS[@]}" "${G[@]}"

# 2. Service account ------------------------------------------------------------
say "2/6 Runtime service account ${SA_EMAIL}"
if ! gcloud iam service-accounts describe "${SA_EMAIL}" "${G[@]}" >/dev/null 2>&1; then
  run gcloud iam service-accounts create "${SA_NAME}" --display-name="GenMedia Studio (Cloud Run)" "${G[@]}"
fi
for role in roles/aiplatform.user roles/datastore.user roles/logging.logWriter \
            roles/cloudtasks.enqueuer roles/secretmanager.secretAccessor; do
  run gcloud projects add-iam-policy-binding "${PROJECT}" \
    --member="serviceAccount:${SA_EMAIL}" --role="${role}" --condition=None --quiet >/dev/null
done
# Signed media URLs are made by the service account signing for itself.
run gcloud iam service-accounts add-iam-policy-binding "${SA_EMAIL}" \
  --member="serviceAccount:${SA_EMAIL}" --role=roles/iam.serviceAccountTokenCreator "${G[@]}" >/dev/null

# 3. Bucket ---------------------------------------------------------------------
say "3/6 Media bucket gs://${BUCKET}"
if ! gcloud storage buckets describe "gs://${BUCKET}" "${G[@]}" >/dev/null 2>&1; then
  run gcloud storage buckets create "gs://${BUCKET}" --location="${REGION}" \
    --uniform-bucket-level-access --public-access-prevention "${G[@]}"
fi
run gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" \
  --member="serviceAccount:${SA_EMAIL}" --role=roles/storage.objectAdmin "${G[@]}" >/dev/null

# 4. Firestore ------------------------------------------------------------------
say "4/6 Firestore database ${FIRESTORE_DB}"
if ! gcloud firestore databases describe --database="${FIRESTORE_DB}" "${G[@]}" >/dev/null 2>&1; then
  run gcloud firestore databases create --database="${FIRESTORE_DB}" \
    --location="${REGION}" --type=firestore-native "${G[@]}"
fi
# Composite indexes used by the library (same set as deploy/terraform).
# "already exists" errors are fine on re-runs.
for spec in \
  "field-path=mime_type,order=ascending field-path=timestamp,order=descending" \
  "field-path=media_type,order=ascending field-path=timestamp,order=descending" \
  "field-path=user_email,order=ascending field-path=timestamp,order=descending" \
  "field-path=user_email,order=ascending field-path=mime_type,order=ascending field-path=timestamp,order=descending"; do
  args=()
  for f in ${spec}; do args+=(--field-config="${f}"); done
  run gcloud firestore indexes composite create --database="${FIRESTORE_DB}" \
    --collection-group=genmedia --query-scope=COLLECTION "${args[@]}" --async "${G[@]}" \
    >/dev/null 2>&1 || true
done

# 5. Sign-in secrets --------------------------------------------------------------
ENV_VARS="PROJECT_ID=${PROJECT},LOCATION=${REGION},APP_ENV=prod"
ENV_VARS+=",GENMEDIA_BUCKET=${BUCKET},IMAGE_BUCKET=${BUCKET}/images,MEDIA_BUCKET=${BUCKET},GCS_ASSETS_BUCKET=${BUCKET}"
ENV_VARS+=",GENMEDIA_FIREBASE_DB=${FIRESTORE_DB},SERVICE_ACCOUNT_EMAIL=${SA_EMAIL},SHOW_DEV_PAGES=false"
SECRETS=""

ensure_secret() {  # name, value-producing command
  local name="$1"
  if ! gcloud secrets describe "${name}" "${G[@]}" >/dev/null 2>&1; then
    if [[ "${DRY_RUN}" -eq 1 ]]; then
      echo "  [dry-run] create secret ${name}"
    else
      "${@:2}" | gcloud secrets create "${name}" --data-file=- --replication-policy=automatic "${G[@]}" >/dev/null
      echo "  created secret ${name}"
    fi
  fi
}
random_secret() { openssl rand -base64 48 | tr -d '\n'; }

if [[ "${AUTH}" == "session" ]]; then
  say "5/6 Sign-in secrets (Secret Manager)"
  ensure_secret genmedia-session-secret random_secret
  if ! gcloud secrets describe genmedia-admin-password "${G[@]}" >/dev/null 2>&1; then
    [[ -n "${ADMIN_EMAIL}" ]] || { echo "First deploy in session mode needs --admin-email" >&2; exit 2; }
    ensure_secret genmedia-admin-password random_secret
    echo "  First admin password is in Secret Manager. Read it once with:"
    echo "    gcloud secrets versions access latest --secret=genmedia-admin-password --project=${PROJECT}"
  fi
  ENV_VARS+=",AUTH_MODE=session,REQUIRE_AUTHENTICATED_USER=true"
  [[ -n "${ADMIN_EMAIL}" ]] && ENV_VARS+=",BOOTSTRAP_ADMIN_EMAIL=${ADMIN_EMAIL}"
  SECRETS="SESSION_SECRET=genmedia-session-secret:latest,BOOTSTRAP_ADMIN_PASSWORD=genmedia-admin-password:latest"
else
  say "5/6 Sign-in: Identity-Aware Proxy (no app secrets needed)"
  # The app checks the IAP-signed header against this audience
  # (Cloud Run with IAP turned on directly, no load balancer).
  PROJECT_NUMBER="$(gcloud projects describe "${PROJECT}" --format='value(projectNumber)')"
  ENV_VARS+=",AUTH_MODE=iap,REQUIRE_AUTHENTICATED_USER=true"
  ENV_VARS+=",IAP_JWT_AUDIENCE=/projects/${PROJECT_NUMBER}/locations/${REGION}/services/${SERVICE}"
fi

# 6. Cloud Run --------------------------------------------------------------------
say "6/6 Building and deploying to Cloud Run (takes 5-10 minutes)"
DEPLOY=(gcloud run deploy "${SERVICE}" --source=. --region="${REGION}"
  --service-account="${SA_EMAIL}"
  --session-affinity --cpu-boost --timeout=3600
  --no-cpu-throttling
  --cpu=2 --memory=4Gi --concurrency=40
  --min-instances="${MIN_INSTANCES}" --max-instances="${MAX_INSTANCES}"
  --set-env-vars="${ENV_VARS}" "${G[@]}")
[[ -n "${SECRETS}" ]] && DEPLOY+=(--set-secrets="${SECRETS}")
if [[ "${AUTH}" == "iap" ]]; then
  # --iap is on the beta track in some gcloud versions.
  DEPLOY=(gcloud beta "${DEPLOY[@]:1}" --no-allow-unauthenticated --iap)
else
  DEPLOY+=(--allow-unauthenticated)
fi
run "${DEPLOY[@]}"

if [[ "${DRY_RUN}" -eq 0 ]]; then
  URL="$(gcloud run services describe "${SERVICE}" --region="${REGION}" "${G[@]}" --format='value(status.url)')"
  say "Done: ${URL}"
  code="$(curl -s -o /dev/null -m 20 -w '%{http_code}' "${URL}/healthz" || echo 000)"
  echo "  /healthz returned ${code}"
  if [[ "${AUTH}" == "iap" ]]; then
    echo "  Give people access:"
    echo "    gcloud iap web add-iam-policy-binding --resource-type=cloud-run --service=${SERVICE} \\"
    echo "      --region=${REGION} --member=user:someone@company.com --role=roles/iap.httpsResourceAccessor --project=${PROJECT}"
  else
    echo "  Sign in at ${URL}/login as ${ADMIN_EMAIL:-your admin} and add users under Users."
  fi
fi
