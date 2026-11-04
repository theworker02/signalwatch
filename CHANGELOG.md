# Release history

## v1.8.1 — Documentation and observatory interface (2026-11-04)

- Redesigned responsive mission-control dashboard with clearer telemetry, searchable observations, and a research-first visual hierarchy.
- Added explicit opt-in synthetic preview (`?preview=1`) that never writes demonstration records or claims real detections.
- Added real Chromium browser screenshots for desktop, triage, investigation detail, and mobile layouts.
- Rebuilt README with screenshot gallery, scientific limitations, setup, architecture, and reference data attribution; added contribution and security guidance.
- Introduced reproducible preview capture and browser checks; no scientific detector claims changed in this patch.


## v1.8.0 — Research workflows and sustained monitoring (2026-11-04)

- Implemented NASA Exoplanet Archive TAP reference snapshots, explicitly separated from scientific discovery.
- Added research alerts, event change cursor, persisted review audit records, and one-click evidence JSON bundles with canonical SHA-256 checksums.
- Added cautious e-Callisto cross-station solar-radio timing hints with calibrated frequency-range gating where available; time matches do not imply physically confirmed events.
- Added web research triage view, investigator modal, source freshness, and planet reference explorer.
- Added write-token gate for mutation API endpoints, content SHA-256 for manageable SETI imports, controlled UTC-midnight spectrum retrieval, SQLite WAL and consistent CLI database backups.
- Added regression and optional FITS decoder tests; no claims of live radio validation in the isolated build environment.

**Upgrade path:** v1.8.0 follows v0.3.0 directly. Intermediate version identifiers were not individually released.

## v0.3.0 — Radio archive prototype (2026-11-04)

- Introduced e-Callisto published FITS archive ingestion and solar transient detector, distinct from the imported SETI narrowband laboratory.
- Retained NOAA, JPL and SatNOGS public metadata feeds; added basic dashboard and persisted investigator classifications.
