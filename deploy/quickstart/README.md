# Deploy GenMedia Studio to Cloud Run (quickstart)

One script sets up a Google Cloud project and deploys the studio for client demos.
It is safe to re-run; each step checks before it creates anything.

## Before you start

- A Google Cloud project with billing turned on.
- You are **Owner** (or have Service Usage, IAM, Storage, Firestore, Secret Manager and Cloud Run admin rights) on it.
- Use [Cloud Shell](https://shell.cloud.google.com): `gcloud`, `openssl` and `curl` are already there.

## Deploy

```bash
git clone https://github.com/ProjectZero02/genmedia-studio.git
cd genmedia-studio
bash deploy/quickstart/deploy.sh --project YOUR_PROJECT --admin-email you@company.com
```

Add `--dry-run` first to see every command without running it.

When it finishes it prints the URL. Read the first admin password once:

```bash
gcloud secrets versions access latest --secret=genmedia-admin-password --project=YOUR_PROJECT
```

Sign in at `<URL>/login`, then add your colleagues and clients from the avatar menu, under **Users**.

## What it creates

| Thing           | Name                                                        | Why                                                                                                                                                                                   |
| --------------- | ----------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| APIs            | from `deploy/scripts/apis.txt` (+ Secret Manager)         | Vertex AI, Firestore, Storage, Cloud Run, Cloud Build                                                                                                                                 |
| Service account | `genmedia-studio-run@…`                                  | Runs the app; Vertex AI user, Firestore user, bucket object admin, log writer, signs its own media links                                                                              |
| Bucket          | `<project>-genmedia-assets` (private)                     | Generated images, videos and audio                                                                                                                                                    |
| Firestore       | database `create-studio-asset-metadata` + library indexes | Library, users, stories                                                                                                                                                               |
| Secrets         | `genmedia-session-secret`, `genmedia-admin-password`    | Sign-in cookie key and first admin password (session mode)                                                                                                                            |
| Cloud Run       | `genmedia-studio`                                         | Built from source. Session affinity, CPU boost, CPU kept on while running (Story Studio renders in the background), 60-minute timeout, 2 CPU / 4 GiB, scales to zero, max 3 instances |

## Sign-in options

- `--auth session` (default): the studio's own sign-in page and user list with admin and user roles. The URL is public, but every page needs a login. Works with any email, so it suits external clients.
- `--auth iap`: Google sign-in through Identity-Aware Proxy. Only Google accounts you grant can open it. Grant someone access:

  ```bash
  gcloud iap web add-iam-policy-binding --resource-type=cloud-run --service=genmedia-studio \
    --region=us-central1 --member=user:someone@company.com --role=roles/iap.httpsResourceAccessor
  ```

If your organisation blocks public Cloud Run services (the "Domain restricted sharing" policy), use `--auth iap`.

## Costs

An idle demo costs close to nothing: Cloud Run scales to zero. You pay per use for Vertex AI generation (Veo is the most expensive), storage and Firestore.
`--min-instances 1` removes the cold start (about 10 to 20 seconds) but bills one instance all day.

## Update or remove

- Update: pull the latest code and run the same command again.
- Remove: `gcloud run services delete genmedia-studio --region=us-central1`. The bucket, Firestore data and secrets stay until you delete them yourself.

For the full production setup (load balancer, custom domain, Terraform), see `deploy/scripts/deploy.sh` and `deploy/terraform/`.
