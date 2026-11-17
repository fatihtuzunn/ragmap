# Meridian Harbor Logistics - Data Governance and Records Retention Policy

Document ID: MHL-POL-014
Version: 4.2
Owner: Office of the Chief Data Officer
Classification: Internal - Approved for Staff Distribution

## 1. Purpose

This policy establishes how Meridian Harbor Logistics creates, classifies, stores,
protects, retains, and finally disposes of recorded information across every business
unit. It applies to structured records held in the freight management platform, to
semi-structured operational telemetry emitted by terminal equipment, and to
unstructured material such as correspondence, scanned bills of lading, and internal
reports. The policy exists so that a single, predictable rule set governs the life of a
record from the moment it is created until the moment it is irreversibly destroyed, and
so that no department invents its own private retention practice.

Meridian Harbor Logistics operates inland terminals and bonded warehousing in four
regions. Each region previously maintained separate archival conventions. The 4.0
revision of this policy consolidated those conventions; the present revision clarifies
the treatment of telemetry and model training corpora.

## 2. Scope

This policy binds all employees, contractors, secondees, and third-party processors who
handle company records in any medium. It covers primary systems of record, replicas,
backups, exports, analytics extracts, and any copy held on an endpoint device. A copy of
a record is a record. Staff may not create a parallel retention regime by moving data
into a personal drive, a spreadsheet, a messaging thread, or an unmanaged cloud bucket.

The policy does not cover physical goods held in custody, which are governed by the
Warehousing Custody Standard, nor does it cover personnel disciplinary files, which are
governed by the People Operations Records Handbook.

## 3. Record classification

Every record carries exactly one classification. The classification is assigned at
creation by the originating system or, for manually created material, by the author.

**Tier 1 - Regulated commercial records.** Customs declarations, bills of lading,
dangerous goods manifests, carrier settlement statements, and the signed contracts that
support them. These records carry statutory obligations in every jurisdiction in which
the company operates.

**Tier 2 - Operational records.** Dispatch plans, gate movements, yard assignments,
equipment maintenance logs, and the incident records produced by the Security Operations
Centre. These support internal accountability and dispute resolution.

**Tier 3 - Operational telemetry.** High-volume machine-generated signals: crane position
samples, reefer temperature readings, gate sensor events, API access logs, and
application traces. Individually these records have negligible value; in aggregate they
support capacity planning and fault diagnosis.

**Tier 4 - Transient working material.** Drafts, scratch extracts, local caches, and
interim analytical outputs that are superseded by a published result.

## 4. Retention schedule

The data retention period is set per classification tier and is enforced automatically
by the records engine. The authoritative schedule is as follows. Tier 1 regulated
commercial records are retained for ten years from the close of the customs entry to
which they relate. Tier 2 operational records are retained for seven years from the
date of the event they describe. Tier 3 operational telemetry is retained for one
hundred and eighty days in hot storage, after which it is aggregated into daily rollups
and the raw samples are deleted. Tier 4 transient working material is retained for
thirty days and is then removed without notice.

These four figures - ten years, seven years, one hundred and eighty days, and thirty
days - constitute the complete retention schedule. No business unit may extend a
retention period by local decision. Where a longer period is genuinely required, the
request is submitted to the Office of the Chief Data Officer with a written statutory or
contractual basis, and if accepted it is published as an amendment to this section
rather than kept as an informal exception.

Retention periods are measured from the event date carried on the record, not from the
date the record was ingested into a given system. A record copied into a downstream
analytics store inherits the retention clock of its source; the copy does not start a
new clock. This is the single most frequently misunderstood provision of this policy and
it is the provision most often found violated during internal audit.

## 5. Legal hold

A legal hold suspends deletion. When the General Counsel issues a hold, the records
engine marks the affected record set and the automated disposal routine skips it. A
record under hold is retained until the hold is lifted in writing, regardless of its
scheduled retention period. Staff who become aware of actual or threatened litigation,
a regulatory inquiry, or a customs investigation must notify Legal within one business
day and must not delete or alter potentially relevant material in the interim.

Holds are reviewed quarterly. A hold that has been open for more than eighteen months
without a documented reason is escalated to the Data Governance Council for a decision
to continue or release.

## 6. Disposal

Disposal is permanent and is logged. The records engine writes a disposal certificate
for every batch, recording the record identifiers, the classification tier, the
retention rule applied, the operator or schedule that triggered disposal, and a
cryptographic digest of the batch manifest. Disposal certificates are themselves Tier 2
records and are retained for seven years.

Physical media are destroyed by an approved contractor against a witnessed certificate
of destruction. Encrypted media may alternatively be disposed of by cryptographic
erasure, provided the key material is destroyed under dual control and the operation is
recorded in the key management ledger.

## 7. Backups and replicas

Backups are not an exception to the retention schedule, but they are treated as a
separate population with their own rotation. Daily backups are held for thirty-five
days, weekly backups for thirteen weeks, and annual archival snapshots for the retention
period of the highest-tier record they contain. When a record is disposed of in the
primary store, it remains recoverable from backup until the relevant rotation window
closes. This residual exposure is accepted, documented, and disclosed in the privacy
notice; it may not be used as a route to recover a record that was deliberately disposed
of.

## 8. Analytics, extracts, and model training

Analytics extracts are Tier 4 by default and expire after thirty days unless promoted.
Promotion requires a named owner, a stated purpose, and an explicit retention period
drawn from the schedule in section 4.

Where company records are used to train or tune statistical or machine learning models,
the training corpus is itself a record and is classified according to the highest tier
it contains. Derived model weights are not treated as records under this policy, but the
corpus, the preprocessing configuration, and the evaluation set are. Teams must be able
to reconstruct which records entered a given training run; where this is not possible,
the run may not be used for a production decision.

## 9. Roles and responsibilities

The Chief Data Officer owns this policy and the retention schedule. Data stewards,
appointed one per business unit, classify new record types, respond to audit findings,
and act as the first point of contact for retention questions. System owners are
accountable for ensuring that the systems they operate are registered with the records
engine and that disposal actually executes. Every employee is responsible for not
creating unmanaged copies.

## 10. Compliance and exceptions

Internal Audit tests this policy twice yearly against a sample of record types drawn
from each tier. Findings are tracked to closure in the enterprise issue register.
Exceptions are time-bound, require the written approval of the Chief Data Officer and
the relevant business unit director, and expire after twelve months unless renewed.
There is no such thing as a permanent exception to this policy.

Questions about the application of this policy are directed to the data steward of the
relevant business unit in the first instance, and to the Office of the Chief Data
Officer where the steward cannot resolve them.
