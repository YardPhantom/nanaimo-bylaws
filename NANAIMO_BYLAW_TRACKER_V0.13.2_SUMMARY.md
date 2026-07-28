# Nanaimo Bylaw Tracker — V0.13.2 Release Summary

## Email subscriptions activated

V0.13.2 connects the existing account subscription controls to the cloud collection workflow and Brevo SMTP.

### Delivery pipeline

- Runs after a successful cloud collection and R2 verification.
- Supports `send`, `dry-run`, `test`, and `skip` workflow modes.
- Uses Firebase Admin to read active subscription settings and resolve the signed-in Google address.
- Sends through Brevo using an SMTP key.
- Stores private one-way-hashed delivery state to prevent duplicates.
- Produces aggregate `subscription-delivery-status.json` diagnostics without email addresses.

### Safety and correctness

- Baseline and pre-activation historical records are not emailed.
- Committee records are not mislabelled as Council alerts.
- Daily and weekly subscriptions accumulate pending matching events until due.
- Category and change-type preferences are enforced.
- Re-enabling a subscription resets its activation time.
- Old duplicated email fields are removed from Firestore subscription documents.
- A failed recipient remains eligible for a later retry because its event keys are not marked delivered.
- Run-level limits prevent accidental high-volume sends.

### Firebase and privacy

- Updated Firestore rules permit only the expected preference and timestamp fields.
- Delivery-state documents remain inaccessible to browser clients.
- Recipient addresses are resolved from Firebase Authentication at send time rather than duplicated in Firestore preferences.
- Updated Account, Subscriptions, and Privacy wording to describe active delivery accurately.

### Setup

`SUBSCRIPTION_SETUP.md` contains the required Firebase service-account, Brevo, GitHub secret, public-site variable, Firestore rule, test, dry-run, and activation steps.

## Release

- Version: **V0.13.2**
- Next code change: **V0.13.3**
- ZIP: `nanaimo-bylaw-tracker-v0.13.2.zip`
