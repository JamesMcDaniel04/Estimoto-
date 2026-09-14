# Receipt totals

On a newly saved receipt, the private service extracts text from PDFs with
Poppler and uses Tesseract OCR for photos or scanned PDFs of up to three pages.
No receipt is sent to Google Places, OpenAI, or another extraction provider.
The original upload remains private and unchanged. The amount result is stored
on `knowledge_receipts.total_extraction`; no extracted transcript is retained.

A clear USD grand/invoice total takes precedence over a plain total. Subtotal,
labor, parts, taxes and a zero paid balance do not replace the grand total.
Duplicate printed totals are collapsed. Conflicting totals, other explicit
currencies, unreadable/oversized text and low OCR confidence require review.
The value is integer cents and respects the existing recorded-cost limits.

When the history entry has no cost, a confident total fills it in the same
transaction that saves the receipt metadata. Existing costs, including zero,
are retained. Replaying an upload does not parse or add the amount again, and
a second attachment never automatically adds another charge to that entry.
Deleting a receipt preserves the independently editable recorded cost.

`POST .../receipts/{id}/parse-total` reads an existing owned receipt with a
bounded per-customer rate; file bytes and hash are checked before parsing.
`POST .../receipts/{id}/apply-total` requires `expected_cost_cents` and rejects a
concurrent edit with 409. Replaying an already applied amount is safe. The UI
offers review, Read receipt total, and Edit recorded cost, and updates the
visible record and cost summary after a successful upload.

The parser has one process slot, a 15-second wall deadline, CPU/address-space/
file-size bounds, a private temporary directory cleaned by the parent, and no
provider secrets in its environment. Timeout/failure preserves the successful
upload and permits retry/manual entry. The Docker image and backend CI install
the required English OCR and PDF tools. Demo uploads remain local and explicitly
offer manual costs; server extraction requires signing in.
