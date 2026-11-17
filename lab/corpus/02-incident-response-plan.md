# Meridian Harbor Logistics - Security Incident Response Plan

Document ID: MHL-PLN-007
Version: 3.1
Owner: Security Operations Centre
Classification: Internal - Approved for Staff Distribution

## 1. Purpose and scope

This plan describes how Meridian Harbor Logistics detects, triages, contains, and
recovers from security incidents affecting its information systems, terminal control
networks, and the data entrusted to it by customers and carriers. It applies to every
incident irrespective of origin: external intrusion, malicious insider activity,
accidental disclosure, supplier compromise, and failures of a control that could
plausibly have led to any of these.

The plan is deliberately procedural. During an incident, people do not read reasoning;
they look for the next step and the name of the person who owns it. Explanatory material
is confined to the appendices.

## 2. Definitions

An **event** is any observable occurrence in a system or network. An **alert** is an
event that a detection rule has flagged for human attention. An **incident** is an alert
that an analyst has confirmed to involve an actual or imminent compromise of
confidentiality, integrity, or availability. A **major incident** is an incident that
meets at least one of the severity triggers in section 4.

Escalation is the act of transferring decision authority upward. Notification is the act
of informing a party who does not hold decision authority. The two are distinct and the
plan uses the words precisely.

## 3. Roles

The **duty analyst** holds first-line responsibility around the clock and is the only
role permitted to declare an incident. The **incident manager** coordinates the response
once an incident is declared and is drawn from a rota of six trained staff. The
**technical lead** is appointed by the incident manager for each incident and directs
containment and recovery work. The **communications lead** owns all internal and
external messaging. The **executive sponsor** is the Chief Information Security Officer
or, in their absence, the Chief Operating Officer.

Named deputies exist for every role. No role may be left vacant during an active
incident; if the primary holder is unreachable for fifteen minutes, the deputy assumes
the role automatically and does not wait for a handover.

## 4. Severity classification

**SEV-4 Minor.** Contained to a single endpoint or account, no sensitive data involved,
no operational impact. Handled by the duty analyst alone.

**SEV-3 Moderate.** Multiple endpoints or a single server, limited data exposure, minor
or no operational impact. Incident manager engaged.

**SEV-2 Serious.** Confirmed unauthorised access to a production system, confirmed
exposure of Tier 1 or Tier 2 records, or degradation of a terminal operation. Executive
sponsor engaged.

**SEV-1 Critical.** Any of: loss of control of a terminal operational technology
network; confirmed exfiltration of customer data; ransomware deployment on any
production system; a compromise that cannot be contained within four hours. Full
response structure activated and the Board is notified.

Severity is assessed on first information and is reassessed at every situation report.
Severity may be raised at any time by any participant; it may be lowered only by the
incident manager with the agreement of the executive sponsor.

## 5. The incident escalation path

The incident escalation path is a fixed, four-step sequence and it is followed in order
without exception. Step one: the duty analyst triages the alert and, if it is confirmed,
declares an incident and assigns an initial severity. Step two: the duty analyst pages
the on-call incident manager, who must acknowledge within fifteen minutes; if there is
no acknowledgement within fifteen minutes the page is automatically repeated to the
deputy incident manager. Step three: for any incident assessed at SEV-2 or above, the
incident manager notifies the executive sponsor, who must be reached within thirty
minutes by phone and not by message alone. Step four: for SEV-1 only, the executive
sponsor convenes the crisis management team, which includes Legal, Communications, the
Chief Operating Officer, and the regional terminal director affected, and the Board is
notified within two hours of declaration.

Each step has a hard time bound: fifteen minutes to acknowledge at step two, thirty
minutes to reach the executive sponsor at step three, and two hours to Board
notification at step four. A step that times out is not retried silently; it is recorded
in the incident log as a missed escalation and it is reviewed in the post-incident
review. Skipping a step is permitted in exactly one circumstance, which is a direct
threat to human safety; in that case the duty analyst contacts the executive sponsor
immediately and reconstructs the remaining steps afterwards.

Escalation is never blocked by uncertainty. An analyst who is unsure whether an alert is
an incident escalates it as one. The cost of a false escalation is one person's
interrupted evening; the cost of a suppressed escalation has historically been measured
in weeks of recovery work.

## 6. Containment

Containment precedes investigation. The technical lead selects a containment strategy
from the approved playbooks: network isolation of affected hosts, account suspension,
credential rotation, session revocation, or controlled shutdown of a service. Any action
that interrupts a terminal operation requires the agreement of the regional terminal
director, who is reached through the operations bridge rather than through the normal
escalation chain.

Evidence is preserved before containment where the delay is under ten minutes. Volatile
memory is captured from systems believed to hold attacker tooling. Disk images are taken
for any system that will be rebuilt. The chain of custody record is opened at the moment
the first artefact is collected and is maintained by the technical lead.

## 7. Communications

All external communication passes through the communications lead. No other person
speaks to media, customers, carriers, or regulators about an incident. Internal updates
are issued as situation reports on a fixed cadence: every thirty minutes for SEV-1,
every two hours for SEV-2, and at state change for SEV-3 and SEV-4.

Regulatory notification timelines are tracked by Legal from the moment of declaration.
The response does not wait for a notification decision, and a notification decision does
not wait for the response to conclude.

## 8. Recovery and closure

Recovery restores service from a known-good state. Systems are returned to production
only after the technical lead confirms that the initial access vector has been closed
and that monitoring for the observed attacker behaviour is in place. Partial recovery is
acceptable and is often preferable to a delayed full recovery, provided the degraded
mode is documented and communicated.

An incident is closed by the incident manager. Closure requires that containment is
confirmed, recovery is complete or an accepted degraded mode is documented, the incident
log is complete, and a post-incident review is scheduled.

## 9. Post-incident review

Every SEV-1 and SEV-2 incident receives a post-incident review within ten working days.
SEV-3 incidents receive one at the discretion of the incident manager. The review is
blameless in form and specific in output: it produces a timeline, a set of contributing
factors, and a list of actions with named owners and due dates. Actions are tracked in
the enterprise issue register and are reported to the Security Steering Group monthly
until closed.

The review explicitly examines whether the escalation path in section 5 was followed and
whether each time bound was met. Repeated misses of the same step are treated as a
process defect rather than as an individual failure.

## 10. Exercises

The plan is exercised twice a year. One exercise is a tabletop involving the full crisis
management team; the other is a technical simulation run against a non-production
environment. Exercise findings feed the same issue register as real incidents. A plan
that has not been exercised in twelve months is considered out of date regardless of its
version number.
