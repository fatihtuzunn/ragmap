# Meridian Harbor Logistics - Vendor Integration and API Error Handling Standard

Document ID: MHL-STD-022
Version: 2.5
Owner: Platform Engineering
Classification: Internal - Approved for Staff and Approved Suppliers

## 1. Purpose

This standard defines how external parties integrate with the Meridian Harbor Logistics
freight platform, what guarantees the platform offers them, and how errors are
represented so that both sides can diagnose a failure without a telephone call. It is
written for supplier engineering teams as much as for internal ones, and an approved
supplier may be given this document in full.

## 2. Integration patterns

Three patterns are supported and no others are offered.

**Synchronous REST.** The caller issues an HTTPS request to the regional gateway and
receives a response within the published timeout. Used for lookups, bookings, and
status queries.

**Asynchronous webhook.** The platform posts an event to a supplier-registered endpoint.
Used for movement notifications, customs status changes, and settlement events.
Delivery is at-least-once; consumers must be idempotent.

**Batch file exchange.** Fixed-format files are exchanged over SFTP on a schedule. This
pattern is maintained for legacy carrier systems and is not offered to new integrations.

Direct database access is not an integration pattern. Requests for it are declined
without escalation.

## 3. Authentication

Every integration authenticates with a client credential issued by the platform identity
service. Credentials are scoped to a single supplier, a single environment, and an
explicit list of permitted operations. Credentials expire after three hundred and
sixty-five days and must be rotated before expiry; the platform issues reminders at
sixty, thirty, and seven days.

Shared credentials are prohibited. Where a supplier operates multiple systems, each
system receives its own credential so that a compromise can be isolated and revoked
without interrupting the remainder of the integration.

Mutual TLS is required for the webhook pattern in both directions. Certificate pinning
is supported but not mandated; suppliers who pin must subscribe to the certificate
rotation notice list.

## 4. Rate limits and fair use

The default rate limit is six hundred requests per minute per credential, measured in a
sliding window. Burst capacity of twice the limit is available for up to ten seconds.
Exceeding the limit returns a throttling response with a retry hint; it does not result
in credential suspension unless the behaviour persists across multiple days after
contact.

Bulk retrieval of the movement history is not permitted through the synchronous REST
pattern. Suppliers requiring history use the batch export, which is produced nightly.

## 5. Error representation

All errors share one envelope. The envelope carries a machine-readable code, a
human-readable message intended for an engineer rather than an end user, a correlation
identifier, and an optional retry hint. The envelope never carries a stack trace, a
framework name, an internal hostname, or a database identifier; suppliers who observe
any of these in a production response should report it as a defect.

Error codes are grouped by first character. Codes beginning with A are authentication
and authorisation failures. Codes beginning with V are validation failures and indicate
that the request was understood but malformed. Codes beginning with R are resource
failures: a referenced booking, container, or consignment does not exist or is not
visible to the caller. Codes beginning with T are transient and the caller should retry
with backoff. Codes beginning with E are internal errors and the caller should not
retry the same request without contacting support.

The complete code catalogue is published in the developer portal and is versioned
alongside this standard. Codes are never reused and never redefined; a code that is
withdrawn is marked deprecated and continues to be documented.

## 6. Correlation identifiers

Every response carries a correlation identifier in both the envelope and a response
header. The identifier is the only thing a supplier needs in order to open a support
case, and support staff are trained to ask for it first. Identifiers are retained in the
platform trace store under the Tier 3 telemetry schedule.

One code in the catalogue is worth singling out because it is the most frequently
misdiagnosed. The code ERR-7F3A-QX91 is returned when a customs declaration is submitted
against a consignment whose manifest has already been closed by the carrier. It is an
R-class resource failure, not a validation failure, and it is not transient: retrying
the submission will return the same result indefinitely. The correct remedy is to
request a manifest reopen from the carrier through the commercial channel and to
resubmit the declaration afterwards. Supplier teams routinely implement an exponential
backoff retry against this code, which produces no result other than additional load,
and it is the single most common cause of a supplier exceeding the rate limit described
in section 4.

## 7. Idempotency

Write operations accept an idempotency key supplied by the caller. The platform stores
the key and the resulting response for twenty-four hours. A repeated request carrying
the same key returns the stored response without re-executing the operation. Callers who
omit the key accept the risk of duplicate side effects and the platform offers no
reconciliation service for duplicates created in this way.

## 8. Versioning and deprecation

The API is versioned in the path. A major version is supported for twenty-four months
after its successor is released. Deprecation notices are issued through the developer
portal, the certificate rotation notice list, and a response header carrying the sunset
date. Breaking changes are never introduced into an existing major version; additive
changes are, and consumers must tolerate unknown fields.

## 9. Environments

Three environments are offered: sandbox, staging, and production. Sandbox carries
synthetic data and is reset weekly. Staging mirrors the production schema and carries
masked data; access requires an approved data handling agreement. Production
credentials never function in the lower environments and the reverse is also true.

## 10. Support and escalation

Integration defects are raised through the supplier support portal with the correlation
identifier attached. The platform targets a first response within four business hours
for standard severity and within one hour where a production integration is wholly
unavailable. Security concerns, including any suspected credential compromise, bypass
the portal and go directly to the Security Operations Centre under the Security Incident
Response Plan, which takes precedence over this standard in any conflict.
