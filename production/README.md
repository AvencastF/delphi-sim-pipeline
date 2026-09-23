# Simulation backend

The operational entry and all editable production settings live outside this
repository at `~/Ztautau/long_production/scripts/production.py` and `configs/`.
See that directory's README. There is no second submission interface here.

This directory maintains generation, container build/runtime, source freezing,
chunk claiming and event-identity audits. `campaign.py prepare` requires an
external `--site` and `--config-dir`; it copies those physics cards and detector
settings into each frozen campaign. The root controller sizes/partitions the
work and publishes successful jobs according to the shared retention policy.

Existing benchmark scripts, cards and measurements are archived outside the
active code tree. Their executed snapshots and original scratch outputs remain
unchanged. Conversion implementation is in the separate delphi-edm4hep fork.


New root campaigns use `node_runtime.py`: one container per node with a pool of
physical-core-bound workers, a shared atomic claim queue, and cached independent
stage environments. Each stage is still a separate subprocess and working
directory. `campaign.py` retains the former stage-container path for historical
standalone use; frozen executed campaigns keep their own source. Core generator,
detector and converter physics are unchanged. See the root `docs/NODE_RUNTIME.md`.
