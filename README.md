# Nanaimo Bylaw Tracker — V0.13.2

Independent civic-information archive for publicly available City of Nanaimo bylaws, Council records, and committee, board, commission, and panel activity.

## Deployment

Deploy authored website files to:

```text
C:\inetpub\wwwroot\sites\nanaimo
```

V0.13.2 uses cloud runtime storage in production. IIS serves HTML, CSS, JavaScript, icons, Firebase configuration, and other authored files, while Cloudflare R2 stores runtime JSON, archived PDFs, extracted text, manifests, and collection status.

`cloud-config.js` points to the deployed Worker with local fallback disabled. Preserve that deployment-specific file during ordinary IIS upgrades. `CLOUD_SETUP.md` documents the GitHub repository, R2 credential, Worker deployment, initial publish, verification, and IIS activation order.

## Collection modes

### Cloud collection — recommended

GitHub Actions restores the previous collection state from R2, runs the same collectors, verifies the result, and uploads only changed objects.

```text
.github/workflows/cloud-collect.yml
cloud/worker/
tools/cloud_sync.py
```

Worker deployment uses Node.js 24 and direct pinned Wrangler 4.114.0, avoiding the deprecated Node.js 20 runtime warning from `cloudflare/wrangler-action@v3`.

### Local emergency collection

```powershell
python .\tools\collect_bylaws.py --download-pdfs
python .\tools\collect_council.py --download --years 2026
python .\tools\deduplicate_archive.py --apply
.\tools\collect-all.cmd
.\tools\verify-council.cmd --strict
```

## Archive policy

Collectors index previous state by SHA-256. Existing PDFs are reused, missing working copies are restored, and missing text is extracted from the existing PDF. PDF bodies are requested only for new sources or when reliable remote validators indicate a change. Cloud publishing refuses duplicate content inside `archive`, skips unchanged R2 objects, and never deletes historical archive objects.

## Private account and email setup

Copy `firebase-config.example.js` to `firebase-config.js` and provide the deployment Firebase configuration. Google is the only sign-in method.

Email subscriptions are processed after cloud collection runs. The sender reads private Firestore preferences through Firebase Admin, resolves the recipient from Firebase Authentication, sends through Brevo SMTP, and records private deduplication state. See `SUBSCRIPTION_SETUP.md` for required GitHub secrets, the public-site variable, Firestore rules, test mode, dry-run mode, and production activation.

The unlinked `admin/index.html` page is restricted in the browser to `yardplots@gmail.com`. Public civic JSON and PDFs are intentionally readable through the Worker; Firebase, Brevo, R2, GitHub, and Cloudflare credentials must remain private.

## Release files

- `CLOUD_SETUP.md` — Cloudflare and GitHub setup
- `SUBSCRIPTION_SETUP.md` — Firebase and Brevo email delivery setup
- `NANAIMO_BYLAW_TRACKER_COMPACT_HANDOFF.md` — continuation rules
- `NANAIMO_BYLAW_TRACKER_V0.13.2_SUMMARY.md` — release changes
