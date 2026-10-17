# Deploy the console to Cloud Run

Private Cloud Run service in the same Google Cloud project as the API, reading
telemetry with the read-only `football-dashboard-reader` service account. It
scales to zero, so it costs nothing while unused. Nobody reaches it without
being authenticated, and the service account cannot write anywhere.

One-time setup, then deploy. Both steps need the owner's Google Cloud account.

## One-time setup

1. Copy the example environment and fill in the real values (never commit it):

   ```bash
   cp deploy/.env.deploy.example deploy/.env.deploy
   ```

   - `GCP_PROJECT_ID`: the project that runs the API.
   - `REGION`: the region the API runs in.
   - `API_SERVICE_NAME`: the Cloud Run service the console reads platform logs
     for. Staging is `football-api-staging`; the production service is planned as
     `football-api`.

2. Create the reader account and grant it exactly three read roles:

   ```bash
   bash deploy/setup_service_account.sh
   ```

   It grants `roles/logging.viewer`, `roles/cloudtrace.user` and
   `roles/errorreporting.viewer`, and nothing else. It is safe to run twice.

## Deploy

```bash
bash deploy/deploy.sh
```

The script creates the Artifact Registry repository once if it is missing, builds
the image with Cloud Build, then deploys by **digest** (not by the `latest` tag,
so a later push cannot change a running revision) with:

- `--no-allow-unauthenticated`, so the service URL is not public;
- `--service-account football-dashboard-reader@...`;
- `--min-instances 0 --max-instances 1 --cpu 1 --memory 512Mi --concurrency 20
  --timeout 60`;
- `SOURCE=gcp`, `GCP_PROJECT_ID`, `API_SERVICE_NAME` and `CACHE_TTL_SECONDS=60`.

## Open it

```bash
gcloud run services proxy football-dashboard --project <project> --region <region>
```

`gcloud run services proxy` runs a local proxy in front of the private service and
adds your identity, so an ordinary browser can open it at
<http://localhost:8080>. This is the transport boundary: the console itself has no
login page yet (see `guide/D9-owner-login.md`), so it must not be published in any
other way.

## Roll back

```bash
gcloud run revisions list --service football-dashboard --project <project> --region <region>
gcloud run services update-traffic football-dashboard \
  --project <project> --region <region> --to-revisions <revision>=100
```

## Delete everything

```bash
gcloud run services delete football-dashboard --project <project> --region <region>
gcloud artifacts repositories delete football-dashboard \
  --project <project> --location <region>
gcloud iam service-accounts delete \
  football-dashboard-reader@<project>.iam.gserviceaccount.com --project <project>
```

The Cloud Build staging bucket (`gs://<project>_cloudbuild`) can be deleted too if
nothing else uses it.

## Cost

Every page view makes a few read API calls (Cloud Logging, Cloud Trace, Error
Reporting), and loading an uncached page costs a fraction of a cent in read
operations only. Minimum instances is 0, so an idle service bills nothing for
compute, but scaling to zero does **not** guarantee a zero bill: Artifact Registry
storage, Cloud Build minutes and other project resources can still incur charges.
Check the current Google Cloud pricing pages for your region and measure your own
usage; do not rely on this note. The project carries the main repository's budget
alert; this console adds no new paid service.

The crashes page needs BigQuery access on the Firebase project, which this deploy
does not grant and does not enable — see the repository README.
