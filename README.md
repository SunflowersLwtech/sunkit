# searchpo

OSS Radar research and Phase 1 data-prep workspace for an automated open-source and AI-tool search pipeline.

## Contents

- `oss_radar_eval.agent.final/`: evaluation report, runtime tech spec, and diagrams.
- `phase1_data_prep/`: source registry, search methods, preprocessing contract, schemas, and endpoint probe script.

## Phase 1 Focus

The first implementation boundary is the data layer:

- stable source registration;
- source-specific search methods;
- raw item and normalized candidate schemas;
- deterministic preprocessing and dedupe;
- endpoint health checks before fetcher implementation.

Run the current source reachability probe:

```bash
./phase1_data_prep/scripts/probe_sources.py
```
