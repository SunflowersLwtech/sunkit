# V01 Evaluation Scores

## Summary

| Prompt | A (Baseline) | B (Enhanced) | Delta |
|--------|-------------|-------------|-------|
| A1 State Mgmt | 35 | 40 | **+5** |
| R1 Code Review | 35 | 38 | **+3** |
| U1 Dashboard | 36 | 38 | **+2** |
| V3 Aesthetic | 38 | 42 | **+4** |
| B1 API Design | 38 | 41 | **+3** |
| **Total** | **182** | **199** | **+17** |

**Overall delta: +9.3%** (target: +15%)

## Per-Dimension Analysis

| Dimension | A avg | B avg | Delta |
|-----------|-------|-------|-------|
| TC (Technical Correctness) | 7.8 | 7.6 | **-0.2** ⚠️ |
| DQ (Design Quality) | 6.8 | 7.6 | +0.8 |
| DR (Depth of Reasoning) | 6.8 | 8.6 | **+1.8** ★ |
| AC (Actionability) | 8.4 | 7.2 | **-1.2** ⚠️ |
| TA (Tacit Articulation) | 6.6 | 8.8 | **+2.2** ★★ |

## Key Pattern

**DR and TA improve dramatically (+1.8, +2.2), but AC regresses (-1.2).**
The skill adds depth and expert insight but displaces concrete implementation detail.

## Top Insights B Added
1. State management inversion error ("collaboration model IS the state")
2. Quality vs identity as distinct diagnostic categories
3. Deliberate exclusion as API design discipline

## V02 Focus Areas
1. Enforce "insight + implementation" rule (fix AC regression)
2. Preserve granularity under conceptual consolidation (fix TC drop in R1)
3. Calibrate framework intensity by prompt type (lighter for spec prompts)
4. Target TA-AC gap: every tacit insight must pair with concrete action
