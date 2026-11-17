# Meridian Harbor Logistics - Business Continuity and Terminal Resilience Plan

Document ID: MHL-PLN-003
Version: 5.0
Owner: Operational Resilience
Classification: Internal - Approved for Staff Distribution

## 1. Purpose

This plan sets out how Meridian Harbor Logistics continues to serve its customers when a
disruptive event removes people, premises, systems, or suppliers from normal operation.
It covers the four inland terminals, the bonded warehousing estate, the shared service
centre, and the freight platform on which all of them depend.

Continuity planning is distinct from incident response. Incident response restores a
failed system. Continuity planning keeps the business operating while the system is
still failed. Both may run at once and they are coordinated through the operations
bridge.

## 2. Critical business services

Seven services are designated critical. Gate processing and container release; customs
declaration submission; dangerous goods handling authorisation; reefer monitoring;
carrier settlement; customer booking; and workforce rostering. Each has a named service
owner, a documented manual workaround, and a recovery objective agreed with the
commercial function.

A service that is not on this list is not restored ahead of one that is, regardless of
how visible its failure may be. This ordering is decided in advance precisely because it
cannot be decided calmly during an event.

## 3. Recovery objectives

Recovery objectives are expressed as a maximum tolerable period of disruption and a
maximum tolerable data loss. Gate processing and container release must be restored
within two hours with no more than fifteen minutes of data loss. Customs declaration
submission must be restored within four hours with no more than one hour of data loss.
Dangerous goods handling authorisation must be restored within one hour with no data
loss, since the manual workaround for this service is intentionally conservative and
reduces throughput sharply. Reefer monitoring must be restored within thirty minutes
with no data loss. The remaining three services carry a twenty-four hour objective.

Objectives are tested, not asserted. An objective that has not been demonstrated in an
exercise within the last twelve months is reported to the Operational Resilience
Committee as unverified, and the service is treated as though no objective exists.

## 4. Manual workarounds

Every critical service has a workaround that functions without the freight platform.
Gate processing falls back to paper movement notes issued from a numbered pad held in
the gate office, with reconciliation into the platform once it returns. Customs
declaration submission falls back to direct submission through the authority portal by
the customs team, at reduced volume. Dangerous goods authorisation falls back to the
duty supervisor working from the printed segregation tables, which are reissued
quarterly and held in the control room.

Workarounds are rehearsed. A workaround that exists only on paper is a hypothesis.
Terminal managers run an unannounced fallback drill on one shift each quarter and record
the throughput achieved, which is the figure used in planning rather than the
theoretical capacity.

## 5. Scenarios

The plan is written against four scenarios rather than against specific causes, because
the cause matters far less to the response than the resource that has been lost.

**Loss of premises.** A terminal is unusable through fire, flood, structural failure, or
an external cordon. Traffic is diverted to the nearest terminal with capacity under the
mutual support arrangement, and customers are informed through the communications
cascade.

**Loss of systems.** The freight platform or a dependency is unavailable. Manual
workarounds are invoked by the service owner and the operations bridge is opened.

**Loss of people.** A significant proportion of a team is unavailable through illness,
industrial action, or a transport failure. Cross-trained staff are redeployed from the
skills matrix, which is maintained by each terminal manager and reviewed twice a year.

**Loss of a supplier.** A critical supplier cannot deliver. The alternate supplier named
in the supplier register is engaged, or the service is operated in degraded mode where
no alternate exists. Suppliers without an alternate are listed in the concentration risk
register and are reviewed annually by the Operational Resilience Committee.

## 6. Invocation

Any terminal director, any service owner, or the Chief Operating Officer may invoke this
plan. Invocation opens the operations bridge, notifies the continuity coordinator, and
places the relevant workarounds into effect. Invocation is deliberately easy and
deliberately logged; standing the plan down is a decision for the Chief Operating
Officer on the advice of the continuity coordinator.

Partial invocation is normal. A single service may be placed into workaround without the
rest of the plan being activated.

## 7. Communications cascade

Internal notification follows the terminal call tree, which is tested monthly and which
every supervisor holds in printed form. Customer notification is issued by the
commercial function from pre-approved templates; the templates exist so that a factual
message can be sent within thirty minutes rather than a carefully drafted one within
three hours. Carrier notification follows the agreed operational contacts in each
carrier agreement.

Where an event has both a continuity and a security dimension, all external
communication passes through the communications lead appointed under the Security
Incident Response Plan, and the templates in this plan are not used.

## 8. Dependencies

The plan records upstream dependencies for each critical service: power, connectivity,
the identity service, the records engine, the carrier interfaces, and the customs
authority portal. Single points of failure are listed explicitly rather than being
described as resilient. Where a dependency is genuinely single-sourced, the plan states
the consequence and the workaround rather than implying that the risk has been removed.

## 9. Exercising

The plan is exercised at three levels. Desktop walkthroughs are held twice a year with
the continuity coordinator and service owners. Terminal fallback drills are held
quarterly as described in section 4. A full invocation exercise, in which a terminal
operates on workarounds for a complete shift, is held once a year on a rotating basis so
that each terminal performs one every four years.

Exercise outputs are findings, not scores. Findings are tracked in the enterprise issue
register alongside incident actions and are reported to the Operational Resilience
Committee until closed.

## 10. Maintenance

The continuity coordinator reviews this plan annually and after every invocation,
whether the invocation was an exercise or a real event. Service owners confirm their
workarounds and recovery objectives as part of that review. Contact details in the call
tree are verified monthly by the terminal administrators; a call tree that has not been
verified within sixty days is treated as unusable and is rebuilt from the current
establishment list.
