# Nanaimo Bylaw Tracker — GitHub, Cloudflare R2 and Worker setup

This keeps the authored website on IIS while moving runtime JSON, archived PDFs, extracted text, manifests, and collection work to Cloudflare. The R2 bucket stays private. A read-only Worker on a free `workers.dev` address serves the public files, and GitHub Actions runs the collectors.

## Final layout

```text
City of Nanaimo and eSCRIBE
          ↓
GitHub Actions collector
          ↓ authenticated S3 upload
Private Cloudflare R2 bucket
          ↓ R2 binding
Cloudflare Worker on workers.dev
          ↓ public GET / HEAD
Browser using the IIS website
```

## Values you will create

Keep these names exact because the included workflows already expect them:

| GitHub secret | Where it comes from | Purpose |
|---|---|---|
| `CLOUDFLARE_ACCOUNT_ID` | Cloudflare account overview | Used by Wrangler and the R2 S3 endpoint |
| `CLOUDFLARE_API_TOKEN` | Cloudflare account API token | Deploys the Worker only |
| `R2_ACCESS_KEY_ID` | R2 API token result | Reads and writes bucket objects |
| `R2_SECRET_ACCESS_KEY` | R2 API token result | Reads and writes bucket objects |
| `R2_BUCKET_NAME` | Your chosen bucket name | Use `nanaimo-bylaw-data` |

The Worker deployment token and R2 object credentials are separate. Do not interchange them.

## 1. Create an empty GitHub repository

1. Sign in to GitHub.
2. Select **New repository**.
3. Name it, for example, `nanaimo-bylaw-tracker`.
4. Choose **Private** unless you want the source public.
5. Do not add a README, `.gitignore`, or licence because the project already contains them.
6. Select **Create repository**.

Leave the repository empty for now. Creating Cloudflare resources and GitHub secrets before the first push prevents the automatic Worker workflow from failing on its first run.

## 2. Create the R2 bucket

1. Sign in to Cloudflare.
2. Open **Storage & databases → R2 object storage**.
3. Select **Create bucket**.
4. Enter:

```text
nanaimo-bylaw-data
```

5. Use the normal/default jurisdiction unless you specifically require an EU or FedRAMP bucket.
6. Keep public access disabled. The Worker will provide public read access without exposing the bucket directly.

The existing `cloud/worker/wrangler.jsonc` expects this exact bucket name. If you choose another name, change `bucket_name` there and use the same value for the GitHub `R2_BUCKET_NAME` secret.

## 3. Copy the Cloudflare account ID

In Cloudflare, open the account home or R2 overview and copy the **Account ID**. Save it temporarily; it becomes the GitHub secret:

```text
CLOUDFLARE_ACCOUNT_ID
```

Do not use a zone ID.

## 4. Configure your workers.dev account subdomain

Do this before the first GitHub deployment so Wrangler does not need to ask an interactive question inside GitHub Actions.

1. In Cloudflare, open **Workers & Pages**.
2. Find **Your subdomain** and select **Change** or **Set up**.
3. Choose an account subdomain, for example:

```text
yardplots
```

Your account-level address becomes:

```text
yardplots.workers.dev
```

The included Worker name is `nanaimo-bylaw-data`, so the final Worker URL will be:

```text
https://nanaimo-bylaw-data.yardplots.workers.dev
```

Use your chosen subdomain, not necessarily `yardplots`. If your Cloudflare account already has a `workers.dev` subdomain, keep the existing one.

## 5. Create the R2 object credentials

1. In **R2 object storage**, select **Manage R2 API tokens**.
2. Select **Create API token**.
3. Name it `Nanaimo collector R2 access`.
4. Choose **Object Read & Write**.
5. Choose **Apply to specific buckets only**.
6. Select only `nanaimo-bylaw-data`.
7. Create the token.
8. Immediately copy both displayed values:

```text
Access Key ID     → R2_ACCESS_KEY_ID
Secret Access Key → R2_SECRET_ACCESS_KEY
```

The secret access key cannot be viewed again. If it is lost, revoke the token and create another one.

## 6. Create the Worker deployment token

1. In Cloudflare, open **My Profile → API Tokens** or the account API-token page.
2. Select **Create Token**.
3. Choose the **Edit Cloudflare Workers** template.
4. Name it `Nanaimo Worker deploy`.
5. Restrict account resources to the Cloudflare account that contains the R2 bucket.
6. Create the token and copy its token value.

This value becomes:

```text
CLOUDFLARE_API_TOKEN
```

It is not the same as the R2 access key or R2 secret access key.

## 7. Add the five GitHub Actions secrets

In the empty GitHub repository:

1. Open **Settings**.
2. Open **Secrets and variables → Actions**.
3. Select **New repository secret**.
4. Add each secret individually:

```text
CLOUDFLARE_ACCOUNT_ID = your Cloudflare account ID
CLOUDFLARE_API_TOKEN = Worker deployment API token
R2_ACCESS_KEY_ID = R2 Access Key ID
R2_SECRET_ACCESS_KEY = R2 Secret Access Key
R2_BUCKET_NAME = nanaimo-bylaw-data
```

Secret names are case-sensitive. Do not add quotes around the values.

## 8. Put the project into GitHub

The files must be at the repository root, not inside another folder. After extraction, the repository should directly contain:

```text
.github/
cloud/
tools/
index.html
CLOUD_SETUP.md
```

### GitHub Desktop method

1. Extract the release ZIP.
2. Open GitHub Desktop and choose **File → Add local repository**.
3. Select the extracted project folder.
4. If prompted, create a repository in that folder.
5. Set the remote to the empty GitHub repository created earlier.
6. Commit all project files.
7. Push to the `main` branch.

### Command-line method

From the extracted project folder:

```powershell
git init
git branch -M main
git add .
git commit -m "Add Nanaimo Bylaw Tracker V0.13.1"
git remote add origin https://github.com/YOUR-GITHUB-NAME/nanaimo-bylaw-tracker.git
git push -u origin main
```

Do not commit runtime datasets, archives, downloaded PDFs, Firebase credentials, Brevo credentials, R2 credentials, databases, or logs. The included `.gitignore` excludes the normal runtime paths.

## 9. Deploy the Worker

Pushing the repository triggers **Deploy Nanaimo data Worker** because the Worker files are included in the first commit.

1. In GitHub, open **Actions**.
2. Open **Deploy Nanaimo data Worker**.
3. Confirm the run completed successfully. If no run appears, choose **Run workflow** manually.
4. Open the deploy step and find the deployment URL. It will look like:

```text
https://nanaimo-bylaw-data.YOUR-CLOUDFLARE-SUBDOMAIN.workers.dev
```

Because the account `workers.dev` subdomain was configured before this deployment, GitHub Actions can deploy non-interactively. The Worker name is already `nanaimo-bylaw-data`, so the final address is always:

```text
https://nanaimo-bylaw-data.<your-workers-dev-subdomain>.workers.dev
```

Save this complete URL. This is the final Worker URL used by `cloud-config.js`.

### Confirm the Worker itself

Open the final Worker URL in a browser. Before data is uploaded, the root should still return service information. A request for `/collection-status.json` may return `404` until the first publish.

## 10. Upload the existing IIS collection once

Run this from the current IIS project directory that contains the live `data`, `archive`, `bylaws\pdf`, and runtime Council folders:

```powershell
cd C:\inetpub\wwwroot\sites\nanaimo

$env:CLOUDFLARE_ACCOUNT_ID="YOUR_ACCOUNT_ID"
$env:R2_ACCESS_KEY_ID="YOUR_R2_ACCESS_KEY_ID"
$env:R2_SECRET_ACCESS_KEY="YOUR_R2_SECRET_ACCESS_KEY"
$env:R2_BUCKET_NAME="nanaimo-bylaw-data"

python -m pip install -r .\tools\requirements.txt
.\tools\cloud-publish.cmd
```

The one-time publisher:

- refuses to publish if duplicate PDF content remains in `archive`;
- skips objects whose stored SHA-256 already matches;
- uploads only changed objects;
- never deletes historical archive objects;
- creates `archive-manifest.json`;
- uploads `collection-status.json` last.

After it completes, verify these addresses using your final Worker URL:

```text
https://YOUR-WORKER/collection-status.json
https://YOUR-WORKER/archive-manifest.json
https://YOUR-WORKER/data/bylaws.json
```

## 11. Connect the IIS website to the Worker

Edit the root IIS file:

```text
C:\inetpub\wwwroot\sites\nanaimo\cloud-config.js
```

Set:

```javascript
window.NANAIMO_CLOUD_CONFIG = Object.freeze({
  enabled: true,
  baseUrl: "https://nanaimo-bylaw-data.YOUR-SUBDOMAIN.workers.dev",
  localFallback: true
});
```

Use the exact URL shown by the successful Worker deployment, with no trailing slash.

Keep `localFallback: true` during migration. Then verify:

- homepage counts load;
- bylaw search works;
- Council and committee pages load;
- archived PDFs open in `pdf.html`;
- `admin/index.html` shows cloud collection status;
- the admin archive check verifies a recorded cloud PDF.

Preserve the configured `cloud-config.js` when applying future site ZIP upgrades.

## 12. Run the first cloud collection

1. In GitHub, open **Actions**.
2. Select **Collect and publish Nanaimo data**.
3. Select **Run workflow → Run workflow**.
4. Wait for every step to finish successfully.
5. Open the uploaded diagnostic artifact only if a step fails or the counts look wrong.

The schedule runs at **6:17 a.m. and 6:17 p.m. America/Vancouver time**. GitHub handles daylight-saving changes because the workflow uses the IANA timezone directly.

Each collection run:

1. restores the current R2 state;
2. runs the existing bylaw and civic collectors;
3. reuses archived PDFs and extracts missing text locally in the runner;
4. downloads only new or confirmed-changed source documents;
5. verifies archive uniqueness and Council data;
6. uploads changed runtime files to R2;
7. publishes collection status last.

## 13. Remove routine runtime storage from IIS

Only after at least one successful scheduled run and a complete site check:

1. Back up the existing IIS runtime data.
2. Change `localFallback` to `false` in `cloud-config.js`.
3. Verify the site again.
4. Remove the local runtime copies only after the cloud-only test succeeds.

Normal cloud operation no longer requires these on IIS:

```text
data/*.json except authored release files
archive/
bylaws/pdf/
runtime meeting-date folders under council/
extracted text sidecars
collector progress and collection logs
```

IIS continues to serve authored HTML, CSS, JavaScript, icons, Firebase configuration, and other site files.

## Troubleshooting

### Worker workflow says authentication failed

Recheck `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN`. The Worker workflow does not use the R2 access key pair.

### Collector says an R2 variable is missing

Confirm all four collector values exist under GitHub **Actions secrets**:

```text
CLOUDFLARE_ACCOUNT_ID
R2_ACCESS_KEY_ID
R2_SECRET_ACCESS_KEY
R2_BUCKET_NAME
```

### Worker deploy says the bucket does not exist

Confirm the bucket name in all three places is identical:

```text
Cloudflare R2 bucket
cloud/worker/wrangler.jsonc
GitHub secret R2_BUCKET_NAME
```

### Worker URL returns 404 for data files

The Worker is deployed, but R2 has not been seeded. Complete the one-time IIS upload or run the cloud collector once.

### Website still loads local files

Confirm `enabled: true`, confirm the exact Worker URL, hard-refresh the browser, and make sure the deployed `cloud-config.js` was not overwritten by a later ZIP extraction.

### Emergency local mode

Set `enabled: false` in `cloud-config.js`, restore the local runtime backup, and run `tools\collect-all.cmd` as before.
