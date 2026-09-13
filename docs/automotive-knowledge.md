# Automotive knowledge and customer scheduling

## Shipping foundation

Estimoto + stores customer-owned vehicles, shops, scheduling requests and
service history in PostgreSQL. The existing Estimoto CRM remains authoritative
for shop jobs, technicians, estimates and confirmed repair events. Explicit
bridge IDs connect those workflows; contact details and VINs do not establish
ownership or merge accounts.

The customer graph projects service records into typed vehicle, service, shop,
part and parts-supplier entities. Source-linked edges record which service was
reported for a vehicle, where it was performed and where its parts came from.
Each edge retains the source record, customer scope, evidence type and time.
Customer-entered history is `customer_reported`; it is never silently promoted
to a verified invoice, completed repair, OEM recommendation or shop endorsement.

Estibot's local GraphRAG path starts from the authenticated customer's selected
vehicle, traverses its service relationships, ranks relevant source records,
and gives the bounded answer model at most six evidence records. A deterministic
source summary remains available when the model fails. Retrieval filters every
hop by customer before constructing context. Contact fields, VIN, insurance and
free-text history notes are excluded from model evidence. The model has no
action tools, and the API retains source references in its answer.

The graph is rebuildable from operational records. Deleting history erases its
edges and orphaned nodes in the same transaction, with a content-free deletion
receipt preventing a delayed retry from restoring the record. Personal history
works without contributing to broader insights.

## Customer-authorized scheduling

My shops is a private address book, separate from the public Estimoto provider
directory. Adding a business does not publish its listing, imply its endorsement,
or enable it to view the customer's other records.

An outreach draft freezes the recipient, service description, selected vehicle,
shared contact information and proposed appointment slots. The customer reviews
and authorizes that exact draft. An outbox and stable provider idempotency key
protect retries. Email acceptance is distinct from inbox delivery and appointment
confirmation. A shop can confirm an offered slot using a scoped expiring link;
viewing the link does not change anything. Phone-only entries offer a call action.
Autonomous phone calls, SMS and arbitrary calendar booking are not implemented.

## Useful, permissioned industry signals

Optional aggregate participation defaults off. Revocation takes effect on the
next query; raw customer records are never copied into a global report store.
The consent preference and its changes retain the disclosed policy version.

The bridge insights API exposes only coarse service types, request types and
normalized parts-supplier categories. Each category requires at least ten
distinct consenting, non-demo customers. Counts are rounded down to multiples of
five. Repeated records from one customer do not inflate that threshold. Arbitrary
supplier/shop names, location filters, contacts, VIN, insurance, notes and individual
records are excluded. Sparse data produces an empty result instead of a synthetic
market conclusion. These are contributed usage signals, not representative
industry statistics.

Original Estimoto already has a shop-scoped Neo4j/Aura knowledge projection for
documents, repair jobs, operations, technicians and related workflow evidence.
Customer-private facts are not exported wholesale into that index. A future
cross-source projection must preserve source ownership, explicit sharing purpose,
consent revocation, correction/deletion propagation and the difference between a
requested repair, a customer report and a shop-confirmed outcome.

## Growth path

The next data sources are verified repair outcomes, part identifiers and invoices,
supplier availability, opt-in technician specialties and measured customer
satisfaction. Integrate them through versioned source events, deterministic entity
resolution and correction/retraction events. Do not infer a customer's shop from
an email domain or assume a parts source mentioned in chat is a completed purchase.

The current implementation is a custom typed local GraphRAG pipeline. Microsoft's
GraphRAG package, community detection, corpus-wide LLM summaries and model training
are not deployed. The retained entities, relationships and source references fit
its documented [bring-your-own-graph approach](https://microsoft.github.io/graphrag/index/byog/)
when the corpus is large enough to justify that indexing cost. Evaluate retrieval
quality, source attribution and tenant isolation before enabling such a projection.

Product usefulness, source quality, permitted reuse and measured adoption will
determine the value of this dataset. No acquisition or third-party interest is
assumed or promised.
