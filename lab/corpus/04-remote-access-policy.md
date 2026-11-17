# Meridian Harbor Logistics - Remote Working and Privileged Access Policy

Document ID: MHL-POL-031
Version: 2.0
Owner: Information Security
Classification: Internal - Approved for Staff Distribution

## 1. Purpose

This policy sets the conditions under which staff and contractors may access company
systems from outside a company facility, and the additional conditions that apply to
privileged access regardless of location. It replaces the separate remote working
guideline and privileged access standard, which were found during the 2025 control
review to contain contradictory requirements on session duration.

## 2. Eligibility

Remote working is a working arrangement, not an entitlement, and is agreed between an
employee and their line manager against the needs of the role. Roles that require
physical presence at a terminal, in the control room, or in the bonded warehouse are not
eligible for remote working for those duties. Eligibility is reviewed when a role
changes and is withdrawn immediately where a person moves into a non-eligible role.

Contractors are eligible only where their contract explicitly permits remote delivery
and where their engaging manager has confirmed that the work does not require access to
Tier 1 regulated commercial records from an uncontrolled location.

## 3. Devices

Remote access is permitted only from a managed device. A managed device is enrolled in
the company endpoint management platform, carries full disk encryption, runs a supported
operating system version, has the endpoint detection agent installed and reporting, and
has received security updates within the last fourteen days. A device that falls out of
compliance loses access automatically and regains it when compliance is restored.

Personal devices may be used for electronic mail and calendar through the managed
container only. No other company system is reachable from a personal device. Printing
company material at home is not permitted; where a physical copy is genuinely required
it is produced at a company facility and handled under the clear desk standard.

## 4. Network access

All remote access traverses the company access gateway. Split tunnelling is disabled.
Access to a given application is granted on the basis of identity, device posture, and
the sensitivity of the application, and is re-evaluated continuously rather than only at
session establishment.

Public wireless networks may be used. The gateway assumes that every network between the
device and the company is hostile and the controls are designed accordingly; staff are
therefore not asked to assess the trustworthiness of a network themselves, which is a
judgement they are not equipped to make.

Access from a country outside the approved list requires prior approval from
Information Security, requested at least five working days in advance. Approvals are
granted for a stated period and are logged. Travel approval does not alter the device or
authentication requirements, which apply unchanged.

## 5. Authentication

Multi-factor authentication is required for every remote session without exception.
Phishing-resistant factors are mandatory for privileged accounts and for all staff in
Finance, Legal, Platform Engineering, and the Security Operations Centre. Push
notification approval is being withdrawn and will not be accepted after the end of the
current fiscal year.

Session duration for standard access is twelve hours, after which re-authentication is
required. Session duration for privileged access is four hours. These two figures
supersede any other duration published in an earlier document.

## 6. Privileged access

A privileged account is one that can alter the configuration of a production system,
read or modify Tier 1 records in bulk, grant access to others, or disable a security
control. Privileged accounts are separate from ordinary accounts; a person who requires
privilege holds two accounts and uses the ordinary one for electronic mail, browsing,
and routine work.

Privileged access is granted just in time. A user requests elevation for a stated
purpose and a stated duration, the request is approved by a second person who is not the
requester, and the elevation expires automatically. Standing privilege exists only for a
small number of break-glass accounts, which are held in the credential vault under dual
control, are monitored for any use, and are rotated after every use.

All privileged sessions are recorded. Recordings are Tier 2 operational records and are
retained accordingly. Staff are informed of this at the point of elevation and the
notice is repeated in the session banner.

## 7. Prohibited practices

The following are prohibited without exception: sharing an account or a credential with
another person; disabling or tampering with the endpoint agent; routing company traffic
through a personal anonymising service; storing company records in a personal cloud
account; and connecting an unmanaged device to a terminal operational technology network
under any circumstances, including for diagnostic purposes by a supplier engineer.

Supplier engineers requiring on-site diagnostic access use the supervised access
procedure, which provides a company-managed device and a named escort for the duration
of the work.

## 8. Monitoring

Remote access is monitored for anomalous patterns: impossible travel, unusual data
volumes, access outside an established working pattern, and use of a credential from a
device that has not previously presented it. Detections are routed to the Security
Operations Centre and are handled under the Security Incident Response Plan.

Monitoring is directed at the protection of company systems and is not used to assess
individual productivity. Access to monitoring data is itself privileged and is logged.

## 9. Responsibilities

Line managers confirm eligibility and withdraw it when circumstances change. Information
Security operates the gateway, sets device posture requirements, and administers travel
approvals. Individuals are responsible for the physical security of their device, for
not allowing household members to use it, and for reporting loss or theft within four
hours of becoming aware of it.

## 10. Breach handling

A breach of this policy is handled proportionately. A first and minor breach, such as a
device that has fallen behind on updates, is addressed by the line manager with support
from Information Security. A deliberate breach, in particular the sharing of a
credential or the connection of an unmanaged device to an operational technology
network, is referred to People Operations and may result in disciplinary action up to
and including dismissal, and in the case of a contractor the immediate termination of
the engagement.
