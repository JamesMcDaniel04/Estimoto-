# Customer repair history and receipts

History remains customer-reported evidence owned by the authenticated customer.
`POST /v1/knowledge/records` accepts optional integer `cost_cents` in USD
(0–100,000,000) and the additional `repair` and `modification` service types.
Omitting a cost preserves pre-existing idempotency hashes. `GET /v1/knowledge`
returns costs, currency and saved receipt metadata; files never appear as public
URLs or enter the cross-customer graph or aggregate feed.

For an already saved record:

- `POST /v1/knowledge/records/{id}/receipts`: one multipart `file`, UUID
  `Idempotency-Key`; returns `{id, filename, content_type, byte_size, created_at}`.
- `GET /v1/knowledge/records/{id}/receipts/{receipt_id}`: authenticated exact bytes,
  attachment disposition, private/no-store, nosniff, sandbox and no-referrer.
- `DELETE` on that same receipt path removes access, persists a replay tombstone,
  and deletes the private object. Deleting the history record removes its receipts
  and graph relationships together.

Limits: 10 MB/file, 10 attachments/record, 250 MB/customer; 60 new uploads and
120 validation attempts/hour. Images must decode as JPEG, PNG or WebP within
the existing bounded raster limit. PDFs must be unencrypted, flattened and at most
50 pages, without active actions or embedded files. PDF parsing runs in a separate
process with a five-second wall timeout, CPU/memory limits and bounded object traversal.
The original bytes are retained privately; these checks do not verify the invoice,
workmanship or claimed cost. The UI supports images and a bytes-only PDF viewer.

Authorization is rechecked after parsing, before reservation and before the final
write. A durable staging row and account lock protect the exact upload identity.
File writes are flushed and atomically renamed before marking saved. An uncertain
database commit never causes deletion of potentially committed bytes. Exact retries
return one receipt, changed payloads return 409, and deleted keys return 410.
Foreign or missing resources return 404. Invalid types/PDFs return 415, oversized
files/storage return 413 and a full attachment list returns 422.

The background worker expires unfinished reservations after one day and retries
failed file removals. Cleanup scans and per-customer batches are bounded at 100;
failed removals have a five-minute backoff so one unavailable path cannot starve
other customers. Deletion always revokes API access before physical cleanup.

The Repairs rollup sums only saved history costs for the selected vehicle:
maintenance = oil change/tires/brakes/battery/maintenance; repairs =
repair/diagnostics/collision/PDR; modifications = modification. Older `other`
entries retain their own bucket. Missing costs are counted separately, and active
job quotes are not added. Receipt count does not multiply a record's cost.

Vehicle valuation uses a separate bounded CarsXE request based on saved vehicle
details and customer-selected condition/state. Its provider amounts remain
separate from recorded spending. Modifications and reported care are included as
history context; no invented dollar uplift is applied to receipts.
