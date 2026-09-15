# Customer Gmail

The Plus Gmail connection is read-only and separate from the shop mail bridge.
OAuth credentials remain in Nango. A scan reads only the sender, subject,
date and Gmail's short preview of car-service mail from the last 90 days;
message bodies, attachments and recipients are never fetched or stored. The
customer files each message into service history by hand, dismisses it, or
opens it in Gmail. Nothing is ever sent, moved or deleted.

## Configuration and launch gate

The default is disabled. After independently verifying the owned Google OAuth
client, Gmail API, Nango redirect, consent audience and scope, configure:

- `GMAIL_ENABLED=true`
- `NANGO_API_KEY`, `NANGO_ENVIRONMENT=production` and
  `NANGO_ALLOWED_KEY_FINGERPRINTS` exactly as for
  [Google Calendar](google-calendar.md); the same server key serves both.
- `NANGO_GMAIL_INTEGRATION_ID=estimoto-plus-gmail`

Use Nango provider template `google-mail` with exactly:

```
https://www.googleapis.com/auth/gmail.readonly
```

Each connect attempt carries server-authored `customer_id`, `app`,
`attempt_id` and `environment` tags; reconcile requires one exact matching
connection and re-verifies its metadata. A provider 401/403/404 during a scan
marks the binding `reconnect_required`. Disconnect invalidates locally first,
deletes every scanned message, then revokes the Nango connection; a failed
revoke is retried by the background worker with backoff.

## Routes

All routes require the customer bearer token and are scoped to that customer.

| Route | Purpose |
| --- | --- |
| `GET /v1/mail/gmail/status` | `configured`, `connected`, `status`, masked-free `email_address`, `last_scan_at`, per-status `message_counts` |
| `POST /v1/mail/gmail/connect` | Starts a hosted Nango Connect session (10 per hour) |
| `POST /v1/mail/gmail/reconcile` | Verifies the attempt and records the Gmail address |
| `POST /v1/mail/gmail/scan` | Reads up to 25 unseen matching messages (6 per hour) |
| `GET /v1/mail/gmail/messages` | Stored metadata for the current connection, newest first |
| `PUT /v1/mail/gmail/messages/{id}/status` | `new`, `saved` (with an owned `knowledge_record_id`) or `dismissed` |
| `DELETE /v1/mail/gmail/connection` | Disconnects and forgets scanned mail |

Messages are categorized as `receipt`, `estimate`, `appointment` or `service`
from subject and preview keywords only. The Flutter app prefills a service
history entry from a message; the customer reviews every field before saving.
Migration `b7e2d9c4a1f6` adds `customer_gmail_connections`,
`customer_gmail_attempts` and `customer_gmail_messages`.
