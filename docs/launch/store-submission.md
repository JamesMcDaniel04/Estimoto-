# App Store and Google Play submission — 1.0.0 (16)

This maps each store requirement to what the source now provides and lists
the steps only the account owner can perform. Source-level items are done on
`claude/estimoto-mobile-ui-ux-7rcnv4`; nothing below claims a store review
outcome.

## What the source now provides

| Requirement | Where | Status |
| --- | --- | --- |
| In-app account deletion (App Store 5.1.1(v), Play User Data policy) | Settings → Delete account; `DELETE /v1/account` removes every customer-owned row and private file, then deletes the Supabase identity when `SUPABASE_SERVICE_ROLE_KEY` is set | Done, tested on both sides |
| Web account-deletion page (Play requirement) | Linked from the app as `PLUS_DELETE_ACCOUNT_URL`, default `https://estimoto.io/plus/delete-account` | Page must exist on estimoto.io (owner) |
| Privacy policy and terms links in the app | Welcome screen consent line and Settings → About | Done; pages must exist on estimoto.io (owner) |
| iOS privacy manifest | `ios/Runner/PrivacyInfo.xcprivacy`, registered in the Runner target | Done |
| Camera and photo usage strings | `Info.plist` | Already present |
| Export compliance | `ITSAppUsesNonExemptEncryption=false` | Already present |
| Notifications | Local only; no push entitlement, no APNs/FCM | Done |
| Android target SDK | Flutter 3.44 default, API 36 | Meets Play's 2026 target |
| Android release shrinking | `proguard-rules.pro` and `res/raw/keep.xml` keep the notification plugin and launcher icon | Done, needs one release build to confirm |
| Version | `pubspec.yaml` 1.0.0+16; `PlusBuildInfo` defaults match | Done |
| Reviewer access without an account | "Explore demo" on the welcome screen; every demo screen says it is sample data | Already present |
| Gmail restricted scope | `GMAIL_ENABLED` defaults to false; the tile says "Not available yet" | Keep disabled for launch (see below) |

## Owner steps before submitting

1. **Publish the legal pages on estimoto.io**: `/privacy`, `/terms`,
   `/support` and `/plus/delete-account`. The deletion page must tell users to
   open Settings → Delete account in the app, and offer an email address for
   requests from users who can no longer sign in. If the paths differ, pass
   `--dart-define=PLUS_PRIVACY_URL=…` (and `PLUS_TERMS_URL`,
   `PLUS_SUPPORT_URL`, `PLUS_DELETE_ACCOUNT_URL`) in `scripts/build_beta.sh`.
2. **Set `SUPABASE_SERVICE_ROLE_KEY` on the API host only.** Without it,
   account deletion removes all data but leaves the sign-in identity, and the
   API response reports `identity_deleted: null`. Never ship this key in the
   app.
3. **Run `alembic upgrade head`** (`b7e2d9c4a1f6`) and deploy the API before
   the store builds go out; the app calls the new account and mail routes.
4. **Build with `scripts/build_beta.sh`** on a machine with Xcode and the
   Android keystore. Confirm on one physical iPhone and one Android phone:
   sign in, reminder alert permission prompt, one scheduled alert firing,
   and Settings → Delete account ending the session.
5. **Keep `GMAIL_ENABLED` off for launch.** `gmail.readonly` is a Google
   restricted scope; enabling it requires Google OAuth verification and a
   CASA security assessment, which takes weeks. Google Calendar uses
   sensitive scopes and needs OAuth verification too; leave
   `GOOGLE_CALENDAR_ENABLED` off unless that verification is already granted.
   Both tiles then honestly read "Not available yet".
6. **App Store Connect**: screenshots for 6.7" and 6.5" iPhone (and iPad if
   the app stays universal), the privacy policy URL, support URL, the App
   Privacy questionnaire below, and review notes below. Submit the 1.0.0 (16)
   build from TestFlight.
7. **Google Play Console**: create the app, upload the signed AAB to
   Production or a closed track, complete Data safety (below), the content
   rating questionnaire, the privacy policy URL and the account-deletion URL,
   and declare no ads. Play requires 12 testers for 14 days on a closed track
   for personal developer accounts created after November 2023; an
   organization account skips this.

## App Privacy (App Store) and Data safety (Play) answers

Data collected and linked to the user, all for app functionality, none used
for tracking or advertising, none shared with third parties for their own
use:

| Data | Why | Shared with |
| --- | --- | --- |
| Email address | Sign-in identity, shop contact when the user shares a request | Supabase Auth (processor); a shop only when the user authorizes a request |
| Name, phone number | Profile, shop contact | A shop only when the user authorizes a request |
| ZIP code (coarse location) | Finding nearby shops | Google Places when the owner enables discovery |
| Photos | Estimate and receipt photos the user chooses | The selected shop only when the user submits an estimate |
| Vehicle details, service history, receipts, reminders (user content) | The garage itself | Nobody, unless the user opts into aggregated, de-identified insights |
| User ID | Account scoping | None |

Not collected: precise location, contacts, health, financial account data,
browsing history, device identifiers for advertising. No third-party
analytics or crash SDKs are bundled. Data is encrypted in transit (HTTPS)
and users can delete all data in-app.

## Review notes to paste

> Estimoto + is a customer companion for car care. Reviewers can tap
> "Explore demo" on the welcome screen to use the app with fictional vehicles,
> shops and timelines; no account is needed and no real shop is contacted.
> Sign-in uses an email link or 8-digit code from Supabase Auth. Account
> deletion is in Settings → Delete account. Reminder alerts are local
> notifications scheduled on the device; the app sends no push notifications.
> Google Calendar and Gmail connections are disabled in this release and show
> "Not available yet".

## Still not connected at launch

CARFAX, automated phone/SMS booking, Google Places discovery until Google
Cloud verification completes, and the Gmail and Calendar connections until
Google OAuth verification is granted. These are configuration and
partnership gates, not source work.
