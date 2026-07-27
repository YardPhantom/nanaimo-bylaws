# Nanaimo Bylaw Tracker — V0.13.1

Independent civic-information archive for publicly available City of Nanaimo bylaws, Council records, and committee, board, commission, and panel activity.

## Deployment

Deploy authored website files to:

```text
C:\inetpub\wwwroot\sites\nanaimo
```

V0.13.1 adds optional cloud runtime storage. IIS can serve only HTML, CSS, JavaScript, icons, Firebase configuration, and other authored files, while Cloudflare R2 stores runtime JSON, archived PDFs, extracted text, manifests, and collection status.

Cloud mode is disabled until `cloud-config.js` contains the deployed Worker URL. `CLOUD_SETUP.md` now provides the exact GitHub repository, R2 credential, Worker deployment, initial publish, verification, and IIS activation order.

## Collection modes

### Cloud collection — recommended

GitHub Actions restores the previous collection state from R2, runs the same collectors, verifies the result, and uploads only changed objects.

```text
.github/workflows/cloud-collect.yml
cloud/worker/
tools/cloud_sync.py
```

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

## Private account setup

Copy `firebase-config.example.js` to `firebase-config.js` and provide the deployment Firebase configuration. Google is the only sign-in method.

The unlinked `admin/index.html` page is restricted in the browser to `yardplots@gmail.com`. Public civic JSON and PDFs are intentionally readable through the Worker; Firebase, Brevo, R2, GitHub, and Cloudflare credentials must remain private.

## Release files

- `CLOUD_SETUP.md` — Cloudflare and GitHub setup
- `NANAIMO_BYLAW_TRACKER_COMPACT_HANDOFF.md` — continuation rules
- `NANAIMO_BYLAW_TRACKER_V0.13.1_SUMMARY.md` — release changes
