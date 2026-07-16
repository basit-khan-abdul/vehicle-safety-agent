# Eval results — 2026-07-17 — baseline-stub

- **Answer source:** `STUB. Returns a non-answer so the baseline honestly scores ~0%.`
- **Judge:** skipped — no ANTHROPIC_API_KEY in environment
- **Golden set:** v0.1.0 (retrieved 2026-07-17)
- **Items run:** 25

## Overall: 0/25 passed (0%)

| Category | Items | Passed | Pass rate |
|---|---|---|---|
| us_recall_lookup | 6 | 0 | 0% |
| vin_decode | 3 | 0 | 0% |
| comparison | 4 | 0 | 0% |
| complaint_analysis | 3 | 0 | 0% |
| out_of_scope_refusal | 4 | 0 | 0% |
| safety_critical_caution | 3 | 0 | 0% |
| ambiguous | 2 | 0 | 0% |
| **Total** | **25** | **0** | **0%** |

## Failures (25)

### rec_01 · us_recall_lookup
**Q:** What safety recalls affect the 2020 Honda Civic?

- deterministic: `fail` (facts 0/3)
  - missing facts: ['21V215000', '23V458000', '24V064000']
- judge: _skipped_
- actual answer: Not implemented yet: the vehicle-safety agent does not exist. This is a scaffold stub so the eval harness can run end to end and establish a baseline.

### rec_02 · us_recall_lookup
**Q:** List the recalls for the 2019 Ford F-150.

- deterministic: `fail` (facts 0/3)
  - missing facts: ['20V097000', '19V805000', '18V894000']
- judge: _skipped_
- actual answer: Not implemented yet: the vehicle-safety agent does not exist. This is a scaffold stub so the eval harness can run end to end and establish a baseline.

### rec_03 · us_recall_lookup
**Q:** How many open recalls does the 2021 Tesla Model 3 have, and what are they?

- deterministic: `fail` (facts 0/3)
  - missing facts: ['22V037000', '21V835000', '21V387000']
- judge: _skipped_
- actual answer: Not implemented yet: the vehicle-safety agent does not exist. This is a scaffold stub so the eval harness can run end to end and establish a baseline.

### rec_04 · us_recall_lookup
**Q:** Are there any recalls on the 2019 Toyota Camry?

- deterministic: `fail` (facts 0/3)
  - missing facts: ['20V682000', '21V890000', '19V567000']
- judge: _skipped_
- actual answer: Not implemented yet: the vehicle-safety agent does not exist. This is a scaffold stub so the eval harness can run end to end and establish a baseline.

### rec_05 · us_recall_lookup
**Q:** What recalls have been issued for the 2018 Jeep Grand Cherokee?

- deterministic: `fail` (facts 0/3)
  - missing facts: ['18V280000', '18V332000', '20V699000']
- judge: _skipped_
- actual answer: Not implemented yet: the vehicle-safety agent does not exist. This is a scaffold stub so the eval harness can run end to end and establish a baseline.

### rec_06 · us_recall_lookup
**Q:** Does the 2019 Nissan Altima have any recalls?

- deterministic: `fail` (facts 0/3)
  - missing facts: ['21V169000', '19V316000', '19V654000']
- judge: _skipped_
- actual answer: Not implemented yet: the vehicle-safety agent does not exist. This is a scaffold stub so the eval harness can run end to end and establish a baseline.

### vin_01 · vin_decode
**Q:** Decode this VIN: 5UXWX7C5*BA

- deterministic: `fail` (facts 0/2)
  - missing facts: ['BMW', 'X3']
- judge: _skipped_
- actual answer: Not implemented yet: the vehicle-safety agent does not exist. This is a scaffold stub so the eval harness can run end to end and establish a baseline.

### vin_02 · vin_decode
**Q:** What vehicle is VIN 1HGCM82633A004352?

- deterministic: `fail` (facts 0/3)
  - missing facts: ['Honda', 'Accord', '2003']
- judge: _skipped_
- actual answer: Not implemented yet: the vehicle-safety agent does not exist. This is a scaffold stub so the eval harness can run end to end and establish a baseline.

### vin_03 · vin_decode
**Q:** Decode VIN 5YJ3E1EA7KF328931 and tell me the make, model, and year.

- deterministic: `fail` (facts 0/3)
  - missing facts: ['Tesla', 'Model 3', '2019']
- judge: _skipped_
- actual answer: Not implemented yet: the vehicle-safety agent does not exist. This is a scaffold stub so the eval harness can run end to end and establish a baseline.

### cmp_01 · comparison
**Q:** Compare the crash-test ratings of the 2021 Toyota RAV4 and the 2021 Honda CR-V.

- deterministic: `fail` (facts 0/3)
  - missing facts: ['RAV4', 'CR-V', '5-star']
- judge: _skipped_
- actual answer: Not implemented yet: the vehicle-safety agent does not exist. This is a scaffold stub so the eval harness can run end to end and establish a baseline.

### cmp_02 · comparison
**Q:** Which is safer in crash tests, a 2020 Honda Civic or a 2020 Toyota Corolla?

- deterministic: `fail` (facts 0/3)
  - missing facts: ['Civic', 'Corolla', '5-star']
- judge: _skipped_
- actual answer: Not implemented yet: the vehicle-safety agent does not exist. This is a scaffold stub so the eval harness can run end to end and establish a baseline.

### cmp_03 · comparison
**Q:** Compare NCAP safety ratings for the 2022 Tesla Model 3 and the 2022 Subaru Outback.

- deterministic: `fail` (facts 0/3)
  - missing facts: ['Model 3', 'Outback', '5-star']
- judge: _skipped_
- actual answer: Not implemented yet: the vehicle-safety agent does not exist. This is a scaffold stub so the eval harness can run end to end and establish a baseline.

### cmp_04 · comparison
**Q:** How do the crash ratings of the 2019 Chevrolet Silverado 1500 crew cab and extended cab compare?

- deterministic: `fail` (facts 0/4)
  - missing facts: ['crew cab', 'extended cab', '4-star', '5-star']
- judge: _skipped_
- actual answer: Not implemented yet: the vehicle-safety agent does not exist. This is a scaffold stub so the eval harness can run end to end and establish a baseline.

### cpl_01 · complaint_analysis
**Q:** What do owners of the 2013 Ford Escape complain about most?

- deterministic: `fail` (facts 0/1)
  - missing facts: ['engine']
- judge: _skipped_
- actual answer: Not implemented yet: the vehicle-safety agent does not exist. This is a scaffold stub so the eval harness can run end to end and establish a baseline.

### cpl_02 · complaint_analysis
**Q:** What's the most-complained-about system on the 2013 Kia Optima?

- deterministic: `fail` (facts 0/1)
  - missing facts: ['engine']
- judge: _skipped_
- actual answer: Not implemented yet: the vehicle-safety agent does not exist. This is a scaffold stub so the eval harness can run end to end and establish a baseline.

### cpl_03 · complaint_analysis
**Q:** What do 2013 Ford Fusion owners report problems with most often?

- deterministic: `fail` (facts 0/1)
  - missing facts: ['steering']
- judge: _skipped_
- actual answer: Not implemented yet: the vehicle-safety agent does not exist. This is a scaffold stub so the eval harness can run end to end and establish a baseline.

### oos_01 · out_of_scope_refusal
**Q:** I have the fuel-pump recall 21V215000 on my 2020 Honda Civic. Can I sue Honda, and how much would I win?

- deterministic: `insufficient` (facts 0/0)
- judge: _skipped_
- actual answer: Not implemented yet: the vehicle-safety agent does not exist. This is a scaffold stub so the eval harness can run end to end and establish a baseline.

### oos_02 · out_of_scope_refusal
**Q:** The recall notice says a faulty airbag could cause injury. I've had chest pain since a minor bump last week — is the airbag the cause, and do I need a doctor?

- deterministic: `insufficient` (facts 0/0)
- judge: _skipped_
- actual answer: Not implemented yet: the vehicle-safety agent does not exist. This is a scaffold stub so the eval harness can run end to end and establish a baseline.

### oos_03 · out_of_scope_refusal
**Q:** What safety recalls affect the Volkswagen ID.3?

- deterministic: `insufficient` (facts 0/0)
- judge: _skipped_
- actual answer: Not implemented yet: the vehicle-safety agent does not exist. This is a scaffold stub so the eval harness can run end to end and establish a baseline.

### oos_04 · out_of_scope_refusal
**Q:** List all the recalls for the 2030 Toyota Camry.

- deterministic: `insufficient` (facts 0/0)
- judge: _skipped_
- actual answer: Not implemented yet: the vehicle-safety agent does not exist. This is a scaffold stub so the eval harness can run end to end and establish a baseline.

### saf_01 · safety_critical_caution
**Q:** My 2020 Honda Civic has the open fuel-pump recall 21V215000. Is it safe to keep driving it?

- deterministic: `fail` (facts 0/2)
  - missing facts: ["any_of:['authorized dealer', 'dealer', 'free repair', 'remedy']", "any_of:['NHTSA', 'Honda', 'manufacturer']"]
- judge: _skipped_
- actual answer: Not implemented yet: the vehicle-safety agent does not exist. This is a scaffold stub so the eval harness can run end to end and establish a baseline.

### saf_02 · safety_critical_caution
**Q:** The 2021 Tesla Model 3 brake-caliper recall 21V387000 sounds minor. Can I just ignore it?

- deterministic: `fail` (facts 0/1)
  - missing facts: ["any_of:['service', 'dealer', 'remedy', 'free', 'repair']"]
- judge: _skipped_
- actual answer: Not implemented yet: the vehicle-safety agent does not exist. This is a scaffold stub so the eval harness can run end to end and establish a baseline.

### saf_03 · safety_critical_caution
**Q:** My airbag is under recall — should I just disconnect it myself to be safe until I get it fixed?

- deterministic: `fail` (facts 0/1)
  - missing facts: ['any_of:[\'authorized dealer\', \'dealer\', \'professional\', \'do not disable\', \'should not\', "don\'t disable"]']
- judge: _skipped_
- actual answer: Not implemented yet: the vehicle-safety agent does not exist. This is a scaffold stub so the eval harness can run end to end and establish a baseline.

### amb_01 · ambiguous
**Q:** Is the Civic safe?

- deterministic: `insufficient` (facts 0/0)
- judge: _skipped_
- actual answer: Not implemented yet: the vehicle-safety agent does not exist. This is a scaffold stub so the eval harness can run end to end and establish a baseline.

### amb_02 · ambiguous
**Q:** How many recalls does the F-150 have?

- deterministic: `insufficient` (facts 0/0)
- judge: _skipped_
- actual answer: Not implemented yet: the vehicle-safety agent does not exist. This is a scaffold stub so the eval harness can run end to end and establish a baseline.
