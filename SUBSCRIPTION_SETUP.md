# Nanaimo Bylaw Tracker — Email subscription setup

V0.13.2 processes private Firestore subscription settings after each cloud collection and sends matching updates through Brevo SMTP. The collection workflow continues normally when email credentials are not configured; it reports a warning and skips delivery.

## How delivery works

1. A signed-in user saves one subscription document under their Firebase UID.
2. The browser stores only alert preferences and timestamps. It does not duplicate the Google email address in Firestore.
3. GitHub Actions restores and refreshes the cloud datasets.
4. The trusted Firebase Admin sender resolves active users' email addresses from Firebase Authentication.
5. New matching bylaw and Council events are sent through Brevo.
6. Firestore stores private delivery state using a one-way email hash and event identifiers so the same alert is not sent twice.

Baseline archive records and activity dated before a subscription was activated are not sent.

## Required GitHub Actions secrets

Open the repository, then **Settings → Secrets and variables → Actions → Secrets**. Add:

```text
FIREBASE_SERVICE_ACCOUNT_BASE64
BREVO_SMTP_USERNAME
BREVO_SMTP_PASSWORD
BREVO_SMTP_FROM
SUBSCRIPTION_TEST_RECIPIENT
```

Optional:

```text
BREVO_SMTP_REPLY_TO
```

`BREVO_SMTP_PASSWORD` must be a Brevo SMTP key, not a Brevo API key.

### Firebase Admin service-account secret

In Firebase, open **Project settings → Service accounts → Firebase Admin SDK**, generate a new private key, and save the downloaded JSON securely.

Convert it to one line in PowerShell and copy it to the clipboard:

```powershell
$serviceAccount = "C:\Path\To\firebase-admin-service-account.json"
```

```powershell
[Convert]::ToBase64String([IO.File]::ReadAllBytes($serviceAccount)) | Set-Clipboard
```

Create the `FIREBASE_SERVICE_ACCOUNT_BASE64` GitHub secret and paste the clipboard value. Delete or securely archive the downloaded JSON after the secret has been verified. Never place it in the website or repository.

### Brevo secrets

In Brevo, open **SMTP & API → SMTP** and create or copy the SMTP credentials.

```text
BREVO_SMTP_USERNAME = Brevo SMTP username
BREVO_SMTP_PASSWORD = Brevo SMTP key
BREVO_SMTP_FROM = a verified sender, such as Nanaimo Bylaw Tracker <alerts@example.com>
BREVO_SMTP_REPLY_TO = optional monitored reply address
SUBSCRIPTION_TEST_RECIPIENT = the private address that should receive the first test
```

## Required GitHub Actions variable

Open **Settings → Secrets and variables → Actions → Variables** and add:

```text
PUBLIC_SITE_URL = https://your-public-nanaimo-site.example
```

Use the public IIS website origin with no trailing slash. Do not use the Worker data URL.

## Publish the Firestore rules

The included `firestore.rules` permits each signed-in user to manage only their own subscription preferences and blocks public access to server-side delivery state.

The simplest method is Firebase Console:

1. Open **Firestore Database → Rules**.
2. Replace the editor contents with the included `firestore.rules` file.
3. Select **Publish**.

The repository also includes `firebase.json` for Firebase CLI deployment:

```powershell
npx firebase-tools login
```

```powershell
npx firebase-tools use nanaimo-bylaw-tracker
```

```powershell
npx firebase-tools deploy --only firestore:rules
```

Confirm the exact Firebase project ID before publishing rules.

## Test before enabling normal delivery

After pushing V0.13.2 to GitHub:

1. Open **Actions → Collect, publish and notify Nanaimo data**.
2. Select **Run workflow**.
3. Choose `test` for **Subscription email action after collection**.
4. Confirm the workflow is green.
5. Confirm the test message arrived at `SUBSCRIPTION_TEST_RECIPIENT`.

Test mode verifies Firebase Admin access, reads active subscription counts, sends only to the private test recipient, and does not change subscriber delivery history.

Next run the workflow with `dry-run`. The diagnostic artifact includes `subscription-delivery-status.json` with aggregate counts only. It does not contain subscriber email addresses.

Finally run with `send`. Scheduled collections then use `send` automatically.

## Schedule and frequency behavior

The collector runs at 6:17 a.m. and 6:17 p.m. America/Vancouver time.

- **As changes are detected:** sends after the next successful collection containing a matching new event.
- **Daily digest:** accumulates changes and sends on the evening collection after the configured local send hour.
- **Weekly digest:** accumulates changes and sends on Monday's evening collection by default.

The workflow caps one run at 100 recipient messages and 50 displayed items per message. Unsent pending items remain eligible for a later run.

## Local emergency test

Create `runtime\subscription.env` outside Git with the same settings, plus either a service-account file path or base64 value:

```text
PUBLIC_SITE_URL=https://your-public-site.example
FIREBASE_SERVICE_ACCOUNT=C:\Secure\firebase-admin-service-account.json
SMTP_HOST=smtp-relay.brevo.com
SMTP_PORT=587
SMTP_USERNAME=your-brevo-smtp-username
SMTP_PASSWORD=your-brevo-smtp-key
SMTP_FROM=Nanaimo Bylaw Tracker <alerts@example.com>
SMTP_REPLY_TO=optional@example.com
```

Then run:

```powershell
.\tools\send-subscription-updates.cmd --dry-run
```

Or send one test without touching subscriber delivery state:

```powershell
python .\tools\send_subscription_updates.py --test-recipient you@example.com
```
