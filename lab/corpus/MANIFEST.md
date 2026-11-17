# Reference corpus - manifest

A fictional company: **Meridian Harbor Logistics**. No copyright risk, the
text is entirely generated, and every deployment under test is loaded with
the same five files.

| File | Title | Words | Chunks at 1000/200 |
|---|---|---|---|
| `01-data-governance-policy.md` | Data Governance and Records Retention Policy | 1310 | 11 |
| `02-incident-response-plan.md` | Security Incident Response Plan | 1276 | 11 |
| `03-vendor-integration-standard.md` | Vendor Integration and API Error Handling Standard | 1037 | 9 |
| `04-remote-access-policy.md` | Remote Working and Privileged Access Policy | 1023 | 9 |
| `05-business-continuity-plan.md` | Business Continuity and Terminal Resilience Plan | 1081 | 9 |

5727 words in total; 49 chunks at a 1000/200 setting.

The filenames and titles are deliberately recognisable. If a deployment
leaks an identifier field, you will see it as
`01-data-governance-policy.md` or as the document's title, and you will
know at a glance that it came from here rather than from the scanner's own
guesswork.

## Known facts

These are the values a scan is checked against. They are what the corpus
actually says, verified by reading it, not by asking the system under test.

| Role | Value | Where |
|---|---|---|
| in-corpus topic | the data retention period | `01`, section 4. Answer: Tier 1 **ten years**, Tier 2 **seven years**, Tier 3 **180 days**, Tier 4 **30 days**. |
| second in-corpus topic | the incident escalation path | `02`, section 5. Answer: a fixed four-step ladder; **15 min** acknowledgement, **30 min** executive, **2 h** Board. |
| off-corpus topic | the company's policy on deep sea mining | **Does not occur at all.** Neither "deep sea" nor "mining" appears in any file (verified). |
| rare literal | `ERR-7F3A-QX91` | `03`, section 6, in **exactly one place**. An error code, returned when a customs declaration is sent for a consignment whose manifest is closed. |

Verify any of it:

```bash
grep -rc "ERR-7F3A-QX91" lab/corpus/*.md        # 1, in 03 only
grep -ric "deep sea\|mining" lab/corpus/*.md    # 0 everywhere
```

Those four roles are what ragmap would otherwise have to derive from the
target itself. Supplying them with `--topic`, `--second-topic`,
`--absent-topic` and `--rare-token` turns a scan into a measurement of the
detectors alone, with corpus discovery taken out of the equation. Running
without them measures discovery too, which is the harder and more realistic
test.

## A known limitation

The facts sit where they naturally fall in the prose; they are not placed
at measured token distances from one another. That makes this corpus a
weaker instrument for chunk-boundary work than it could be: exact overlap
recovery is easiest when two known facts straddle a boundary by
construction. Rebuilding `01` and `02` with measured spacing would fix it;
the other three files would not need to change.

## Loading it into a deployment

Upload the files as they are; do not convert them. If a product insists on
PDF, keep the converted PDF beside the source under `lab/corpus/derived/`
and note which tool produced it: pagination changes where chunk boundaries
fall, and that is one of the variables a scan measures.
