# Patient-level data never crosses the boundary; design and report stages see aggregates only

Readers, adjudicator, workbench and estimator run inside the trust/SDE boundary on local MedGemma. Protocol design and report writing may use any model (frontier or MedGemma) because they only ever receive gateway-approved aggregates: protocol identifiers, counts, rates, intervals, taxonomy codes. The gateway is an allowlist, not a denylist, and logs every outbound payload. Consequence: the report cannot quote a note; the workbench must carry all evidence display.
