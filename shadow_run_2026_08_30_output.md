# Monitoring Spirit Shadow Run — 2026-08-30

## Diagnostic Summary
- Total clusters analyzed: 500
- Clusters with silence shape: 121
- Significant silence patterns: 5
- Blocked by persistence rail: 0 (Note: this means the imbalance is not present in the MOST RECENT snapshot, correctly discarding stale imbalances. It does NOT mean the imbalance never persisted historically)
- Blocked by sourcing rail: 4
- Reached DARK verdict: 1

## Sourcing Rail Exclusions (distinct_outlets_in_loud_tier < 3)

The following 4 clusters exhibited a significant silence pattern and passed the persistence check, but were excluded by the `has_sourcing()` rail. In each case, their "loud" tier was driven by only 2 distinct outlets, which falls below the hard-coded `distinct < 3` threshold designed to guard against planted leaks.

1. **Insurers grow income by 46.7% to N1.27 billion**
   - **Category:** Economy
   - **Outlets:** 3
   - **Tier dist:** `{'pro_establishment': 0, 'institutional': 1, 'adversarial': 2}`
   - **Sourcing:** `{'distinct_outlets_in_loud_tier': 2, 'has_original_reporting_outlet': True}`
   - *Reason for exclusion:* Only 2 distinct adversarial outlets reported this. Minimum required is 3.

2. **World Population Day: Radda pledges data-driven development in Katsina**
   - **Category:** Politics
   - **Outlets:** 3
   - **Tier dist:** `{'pro_establishment': 0, 'institutional': 1, 'adversarial': 2}`
   - **Sourcing:** `{'distinct_outlets_in_loud_tier': 2, 'has_original_reporting_outlet': True}`
   - *Reason for exclusion:* Only 2 distinct adversarial outlets reported this. Minimum required is 3.

3. **My life is in danger, EFCC targeting my family, businesses – Achimugu**
   - **Category:** Judiciary
   - **Outlets:** 3
   - **Tier dist:** `{'pro_establishment': 0, 'institutional': 1, 'adversarial': 2}`
   - **Sourcing:** `{'distinct_outlets_in_loud_tier': 2, 'has_original_reporting_outlet': True}`
   - *Reason for exclusion:* Only 2 distinct adversarial outlets reported this. Minimum required is 3.

4. **How Nigerians can apply for World Bank’s 2027 Africa fellowship in US**
   - **Category:** Education
   - **Outlets:** 3
   - **Tier dist:** `{'pro_establishment': 0, 'institutional': 1, 'adversarial': 2}`
   - **Sourcing:** `{'distinct_outlets_in_loud_tier': 2, 'has_original_reporting_outlet': True}`
   - *Reason for exclusion:* Only 2 distinct adversarial outlets reported this. Minimum required is 3.

## DARK Verdicts
1. **Bagudu Seeks Stronger Partnership To Cushion Impact Of Economic Reforms On Vulnerable Nigerians**
   - **Category:** Economy
   - **Outlets:** 4
   - **Evidence:** [The silence] 4 of 4 watchdog outlets have not reported this.
