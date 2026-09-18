<#
.SYNOPSIS
    Deploys the AIFOD Daily AI News Aggregator service to Google Cloud Platform.

.DESCRIPTION
    This automation script deploys the containerized Flask application to Google Cloud Run,
    configures a dedicated IAM Service Account with invocation permissions, and schedules
    a Cloud Scheduler job to invoke the service daily at midnight in the Asia/Tokyo timezone.

.PARAMETER ProjectId
    The Google Cloud Platform project ID. If omitted, it will be loaded from the local .env file.

.PARAMETER Region
    The GCP region for Cloud Run and Cloud Scheduler deployment. Defaults to 'us-central1'.

.PARAMETER ServiceName
    The name of the Cloud Run service. Defaults to 'ai-news-aggregator-krjp'.

.PARAMETER JobName
    The name of the Cloud Scheduler job. Defaults to 'ai-news-aggregator-daily-trigger'.

.PARAMETER Schedule
    The cron expression defining the trigger frequency. Defaults to '0 0 * * *' (daily at midnight).

.PARAMETER TimeZone
    The timezone used for evaluating the schedule. Defaults to 'Asia/Tokyo'.

.EXAMPLE
    .\deployment\deploy_cloud.ps1
    Deploys using configuration loaded from the local .env file.

.EXAMPLE
    .\deployment\deploy_cloud.ps1 -ProjectId "my-gcp-project" -Region "asia-northeast1"
    Deploys to a specific project and region overriding .env defaults.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $false, HelpMessage = "GCP Project ID")]
    [string]$ProjectId,

    [Parameter(Mandatory = $false, HelpMessage = "GCP Deployment Region")]
    [string]$Region,

    [Parameter(Mandatory = $false, HelpMessage = "Cloud Run Service Name")]
    [string]$ServiceName,

    [Parameter(Mandatory = $false, HelpMessage = "Cloud Scheduler Job Name")]
    [string]$JobName,

    [Parameter(Mandatory = $false, HelpMessage = "Cron Schedule Expression")]
    [string]$Schedule,

    [Parameter(Mandatory = $false, HelpMessage = "Timezone for Schedule")]
    [string]$TimeZone
)

$ErrorActionPreference = "Stop"

# ===========================================================================
# 1. Configuration & Environment Ingestion
# ===========================================================================

# Load configuration from .env file if present
$envPath = Join-Path $PSScriptRoot "..\" | Join-Path -ChildPath ".env"
if (Test-Path $envPath) {
    Write-Host "Loading configuration from: $envPath" -ForegroundColor DarkGray
    Get-Content $envPath | ForEach-Object {
        if ($_ -match '^\s*([^#][^=]*)\s*=\s*(.*)$') {
            $name = $matches[1].Trim()
            $value = $matches[2].Trim()
            Set-Variable -Name "ENV_$name" -Value $value -Scope Script
        }
    }
}

# Resolve parameter values: Explicit CLI argument > .env file > Hardcoded default
$PROJECT_ID = if ($ProjectId) { $ProjectId } elseif ($ENV_GCP_PROJECT_ID) { $ENV_GCP_PROJECT_ID } else { $null }
$REGION = if ($Region) { $Region } elseif ($ENV_GCP_REGION) { $ENV_GCP_REGION } else { "us-central1" }
$SERVICE_NAME = if ($ServiceName) { $ServiceName } elseif ($ENV_SERVICE_NAME) { $ENV_SERVICE_NAME } else { "ai-news-aggregator-krjp" }
$JOB_NAME = if ($JobName) { $JobName } elseif ($ENV_JOB_NAME) { $ENV_JOB_NAME } else { "ai-news-aggregator-daily-trigger" }
$SCHEDULE = if ($Schedule) { $Schedule } elseif ($ENV_SCHEDULE) { $ENV_SCHEDULE } else { "0 0 * * *" }
$TIMEZONE = if ($TimeZone) { $TimeZone } elseif ($ENV_TIMEZONE) { $ENV_TIMEZONE } else { "Asia/Tokyo" }

if (-not $PROJECT_ID) {
    Write-Error "GCP_PROJECT_ID is not provided and was not found in .env. Please supply -ProjectId or configure .env."
    exit 1
}

Write-Host "Deploying AI News Aggregator to Google Cloud..." -ForegroundColor Green
Write-Host "  Project:  $PROJECT_ID"
Write-Host "  Region:   $REGION"
Write-Host "  Service:  $SERVICE_NAME"
Write-Host "  Job:      $JOB_NAME"
Write-Host "  Schedule: $SCHEDULE ($TIMEZONE)"
Write-Host ""

# ===========================================================================
# 2. Prerequisite & CLI Verification
# ===========================================================================
if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) {
    Write-Error "Google Cloud SDK (gcloud) is not installed or not available in PATH. Please install Google Cloud SDK."
    exit 1
}

# Set active project
Write-Host "[Step 1/5] Setting active project to $PROJECT_ID..." -ForegroundColor Cyan
gcloud config set project $PROJECT_ID

# ===========================================================================
# 3. Enable Required Google Cloud APIs & GCS Bucket Setup
# ===========================================================================
Write-Host "[Step 2/5] Enabling required APIs (Cloud Run, Cloud Build, Artifact Registry, Cloud Scheduler, Secret Manager, Cloud Storage)..." -ForegroundColor Cyan
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com cloudscheduler.googleapis.com secretmanager.googleapis.com storage.googleapis.com

$BUCKET_NAME = "$PROJECT_ID-ai-news-data"
Write-Host "Ensuring Cloud Storage bucket gs://$BUCKET_NAME exists..." -ForegroundColor Cyan
$bucketCheck = gcloud storage buckets describe "gs://$BUCKET_NAME" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "Creating Cloud Storage bucket gs://$BUCKET_NAME in $REGION..."
    gcloud storage buckets create "gs://$BUCKET_NAME" --location=$REGION
} else {
    Write-Host "Cloud Storage bucket gs://$BUCKET_NAME already exists."
}

# Grant Secret Manager and Cloud Storage access to the default Cloud Run runtime service account
$PROJECT_NUMBER = gcloud projects describe $PROJECT_ID --format="value(projectNumber)"
$COMPUTE_SA = "$PROJECT_NUMBER-compute@developer.gserviceaccount.com"
Write-Host "Granting Secret Manager Secret Accessor and Storage Object User to $COMPUTE_SA..." -ForegroundColor Cyan
gcloud projects add-iam-policy-binding $PROJECT_ID --member="serviceAccount:$COMPUTE_SA" --role="roles/secretmanager.secretAccessor" --quiet
gcloud projects add-iam-policy-binding $PROJECT_ID --member="serviceAccount:$COMPUTE_SA" --role="roles/storage.objectUser" --quiet

# ===========================================================================
# 4. Deploy Application to Cloud Run
# ===========================================================================
$workspaceRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\")).Path
Write-Host "[Step 3/5] Deploying container from source ($workspaceRoot) to Cloud Run..." -ForegroundColor Cyan
Push-Location $workspaceRoot
try {
    gcloud run deploy $SERVICE_NAME `
        --source . `
        --region $REGION `
        --set-env-vars "GCP_PROJECT_ID=$PROJECT_ID,GCP_REGION=$REGION,SERVICE_NAME=$SERVICE_NAME,GCS_BUCKET_NAME=$BUCKET_NAME,GEMINI_MODEL=gemini-3.8-flash" `
        --no-allow-unauthenticated `
        --quiet
    if ($LASTEXITCODE -ne 0) {
        Write-Error "gcloud run deploy failed with exit code $LASTEXITCODE."
        exit $LASTEXITCODE
    }
} finally {
    Pop-Location
}

# Retrieve the assigned HTTPS endpoint
$SERVICE_URL = gcloud run services describe $SERVICE_NAME --region $REGION --format 'value(status.url)'
if (-not $SERVICE_URL) {
    Write-Error "Failed to retrieve the deployed service URL for $SERVICE_NAME."
    exit 1
}
Write-Host "Service deployed successfully at: $SERVICE_URL" -ForegroundColor Green


# ===========================================================================
# 5. Configure Dedicated IAM Invoker Service Account
# ===========================================================================
$SA_NAME = "ai-news-scheduler-sa"
$SA_EMAIL = "$SA_NAME@$PROJECT_ID.iam.gserviceaccount.com"

Write-Host "[Step 4/5] Setting up Service Account ($SA_EMAIL) for Cloud Scheduler..." -ForegroundColor Cyan
$existingSa = gcloud iam service-accounts list --filter="email:$SA_EMAIL" --format="value(email)"
if (-not $existingSa) {
    Write-Host "Creating service account: $SA_NAME..."
    gcloud iam service-accounts create $SA_NAME --display-name "AI News Aggregator Scheduler Invoker"
} else {
    Write-Host "Service account $SA_NAME already exists."
}

# Grant run.invoker role on the Cloud Run service to the Service Account
Write-Host "Granting roles/run.invoker to $SA_EMAIL..."
gcloud run services add-iam-policy-binding $SERVICE_NAME `
    --region $REGION `
    --member="serviceAccount:$SA_EMAIL" `
    --role="roles/run.invoker"

# ===========================================================================
# 6. Configure Cloud Scheduler Recurring HTTP Trigger
# ===========================================================================
Write-Host "[Step 5/5] Configuring Cloud Scheduler recurring trigger..." -ForegroundColor Cyan
$existingJob = gcloud scheduler jobs list --location=$REGION --filter="name:projects/$PROJECT_ID/locations/$REGION/jobs/$JOB_NAME" --format="value(name)"

if ($existingJob) {
    Write-Host "Updating existing Cloud Scheduler job ($JOB_NAME)..."
    gcloud scheduler jobs update http $JOB_NAME `
        --location=$REGION `
        --schedule="$SCHEDULE" `
        --time-zone=$TIMEZONE `
        --uri=$SERVICE_URL `
        --http-method=POST `
        --oidc-service-account-email=$SA_EMAIL
} else {
    Write-Host "Creating new Cloud Scheduler job ($JOB_NAME)..."
    gcloud scheduler jobs create http $JOB_NAME `
        --location=$REGION `
        --schedule="$SCHEDULE" `
        --time-zone=$TIMEZONE `
        --uri=$SERVICE_URL `
        --http-method=POST `
        --oidc-service-account-email=$SA_EMAIL
}

Write-Host ""
Write-Host "===========================================================================" -ForegroundColor Green
Write-Host " Deployment Complete!" -ForegroundColor Green
Write-Host " Service:   $SERVICE_URL" -ForegroundColor Green
Write-Host " Schedule:  $SCHEDULE ($TIMEZONE)" -ForegroundColor Green
Write-Host " Invoker:   $SA_EMAIL" -ForegroundColor Green
Write-Host "===========================================================================" -ForegroundColor Green
