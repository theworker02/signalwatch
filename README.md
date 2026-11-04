# Magnexis SIGNALWATCH v1.8

An **experimental, continuous astronomical-data observatory** with a **dedicated narrowband SETI research laboratory**, automated **solar-radio spectrogram ingestion**, candidate triage and auditable research records. Built by **Magnexis LLC**.

> **Scientific boundary:** SIGNALWATCH does not establish extraterrestrial intelligence, discover planets, predict asteroid impacts, or scientifically confirm solar-radio bursts. It flags data patterns worth investigating. Priority scores are *not probabilities*. Source datasets have different latency and observational targets.

## What is connected

| Source | Update strategy | Classification and limitation |
|---|---|---|
| **e-Callisto public FITS spectra** | Poll published UTC-day archive about every 15 min; at most 2 small spectra/cycle, from distinct stations in AUTO mode; check previous day briefly after UTC midnight | Real radio measurements pointed at the **Sun**; broadband transient research, **not SETI**. Publication is delayed; availability varies. |
| **e-Callisto uploaded-file index** | Every ~15 min | Metadata only, **not actual signal samples**. |
| **NOAA GOES X-rays, flare events, Kp and solar radio flux** | Every ~5–10 min | Public space weather, not extraterrestrial signals. |
| **NASA/JPL close-approach predictions** | Every ~6 hours | Previously catalogued small bodies; predicted close approaches are not new discoveries or impact-risk statements. |
| **SatNOGS network** | Every ~10 min | Community satellite observation metadata, not RF spectrogram validation. |
| **NASA Exoplanet Archive** | Daily, using public TAP JSON queries | A bounded snapshot of already confirmed planets. First observation in this local database is **not** a new planet discovery. The source may experience service interruptions. |
| **SETI narrowband file watcher** | Local inbox checked every 20 seconds | `.npy`, `.npz`, and optional `blimpy` `.fil`/`.h5` observations. No continuously streaming distant-target SETI telescope is connected. |

Public sources are polled with conservative per-source rate limits and exponential backoff. The dashboard distinguishes source success, age, errors, and archive metadata from actual analyzed spectra. All data processing runs on your computer or your own server, not in ChatGPT's background.

## What's new in v1.8

- **Scientific research investigation queue** at `/api/alerts`: filters synthetic/test items, routine satellite observations and closed/interference reviews, with a minimum heuristic score.
- **Cross-station solar-radio timing hints**: compares event timestamps across distinct e-Callisto stations in a five-minute window. When both axes are calibrated, frequency ranges must overlap. A time match is never claimed to be a true frequency-coincident astrophysical event or extraterrestrial transmitter.
- **Permanent investigation audit history** with current state and previous reviewer notes, plus `/api/events/{id}` details.
- **Downloadable evidence JSON** with canonical SHA-256 digest, event metadata, source-health snapshot, review history, triage caveats and timing hints. This is an integrity checksum, not a cryptographic attestation or scientific certificate.
- **Local candidate change feed** (`/api/events/changes?after_id=0`), dashboard research modal, and separately identified known-planet catalog.
- **Operator CLI** (`doctor`, `scan`, `poll`, `alerts`, `backup`), optional write token, network-source freshness metrics, and station-archive polling across UTC midnight.
- **Content hashes** for imported radio files up to 256 MB; very large telescope files explicitly note that a full-file digest was not calculated.
- **Regression tests** for the above behavior and a conditional Astropy FITS integration test.

Versions v0.4 through v1.7 were not individually released; v1.8 is a consolidated milestone following v0.3.

## Quick start (Windows / macOS / Linux)

Python **3.10+** and an internet connection are needed for public feeds. Python package downloads and external observations may use disk space.

```bash
cd magnexis-signalwatch
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS / Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
python -m signalwatch.cli doctor
python run.py
```

Open **http://127.0.0.1:8765**. Windows also supports double-clicking `start_windows.bat`. The application binds to loopback by default.

To run continuously on a host that remains on, Docker Compose uses a persistent local `./data` directory:

```bash
docker compose up -d --build
docker compose logs -f
```

This is **not** a hosted service by default. It stops when your host is off. Docker Compose exposes the dashboard only on `127.0.0.1:8765`; the internal container port may listen on all interfaces inside Docker.

### Operator commands

```bash
python -m signalwatch.cli doctor  # Local status, no external requests
python -m signalwatch.cli poll    # One eligible public-source polling cycle
python -m signalwatch.cli scan    # Scan local files, may prune old program-owned auto-cache
python -m signalwatch.cli alerts --min-score 60
python -m signalwatch.cli backup  # Consistent snapshot in data/backups/
python -m pytest -q
```

The polling command **respects** source cooldowns within the running process; starting a new process resets in-memory cooldowns, so don't create rapid cron loops. Prefer the single always-on service. To reduce background requests:

```bash
SIGNALWATCH_CALLISTO_DOWNLOAD=0    # Stop automatic FITS downloads
SIGNALWATCH_BACKGROUND=0           # Disable all background polling / scanning
SIGNALWATCH_CALLISTO_STATION=AUTO   # Choose up to two different stations/cycle
```

Set these as shell environment variables or add them to your Compose environment.

### Access restrictions

This is a **local research prototype**, **not an authenticated internet-facing dashboard**. Keep the default loopback bind. There is browser-origin screening on mutation endpoints and an optional `SIGNALWATCH_WRITE_TOKEN` required for `PATCH /api/events/{id}/review` and `POST /api/poll`. With a token configured, the browser asks for it when needed and only holds it in page memory.

That token is not full user authentication and does not protect read-only API endpoints. Do not publish the application behind a public reverse proxy without proper authentication, HTTPS, authorization, CSRF controls and rate limits. Store secrets outside git and never commit them.

## SETI laboratory

Import **authorized actual telescope observations** from [Breakthrough Listen](https://seti.berkeley.edu/opendata):

```bash
python -m pip install -r requirements-radio.txt
python -m signalwatch.radio path/to/ON.fil --off path/to/OFF.fil
```

Alternatively, place power spectrograms in `data/inbox/` (not raw complex IQ). The engine uses per-time-row median/MAD normalization, tests linear frequency-drift templates, requires persistence, flags near-zero drift as RFI-like, and optionally compares an off-target control. **ON/OFF comparison requires aligned frequency axes, observing times and telescope pointing**; same matrix shape alone is insufficient scientific validation.

For large `.fil`/`.h5` inputs, only a **central 2,048-channel × first 192-integration cutout** is analyzed; no full-band survey claim is made. `.npz` files may include `start_frequency_mhz`, `channel_width_hz`, `integration_seconds`, `observation_start_utc` or `observation_mjd` for better provenance. Local `.npy` matrices without a timestamp record the analysis time, not necessarily observation time.

```bash
python -m signalwatch.radio --demo
python -m examples.make_synthetic
```

Synthetic tests are marked `test`, have score 0, and must never appear as real discoveries. Never rename a synthetic input to disguise its provenance.

## e-Callisto radio telescope ingestion

The auto-downloader reads a bounded listing from the [published e-Callisto archive](https://soleil.i4ds.ch/solarradio/data/2002-20yy_Callisto/), validates filenames and date bounds, refuses external links, bounds compressed files to **3 MB**, uncompressed FITS to **40 MB**, and its program-owned cache to **350 MB**. It never automatically deletes manually imported recordings. Program-owned processed `.fit` files may be removed after **24 hours**; research metadata and file digest remain in SQLite. These operational limits are conservative and may exclude some valid observations.

The solar detector finds multi-channel transient enhancements using robust per-channel background subtraction. **Solar emission, terrestrial interference and receiver gain changes are not yet distinguishable solely from the detector output.** Cross-station temporal matching is a review hint, not scientific confirmation. Station positions, calibrated channel overlap, spectral shape, simultaneous ON/OFF comparison and repeat independent observations should be assessed before any external claim.

## API reference

| Method / path | Description |
|---|---|
| `GET /api/health` | App responding; **not** proof that external feeds work |
| `GET /api/status` | Version, task status, database counts |
| `GET /api/telemetry` | Feed success ages and stale flags |
| `GET /api/sources` | Source status and last errors |
| `GET /api/events?source=&kind=&review=` | Latest investigation and observation records |
| `GET /api/events/changes?after_id=` | Locally appended event records since ID |
| `GET /api/alerts?min_score=60` | Priority candidates excluding tests and closed/rejected |
| `GET /api/events/{id}` | Event, review history, cautious station timing hints |
| `GET /api/events/{id}/evidence.json` | Checksumed research bundle |
| `PATCH /api/events/{id}/review` | Review state / note, append-only audit history |
| `GET /api/events.csv` | CSV with formula-injection escaping |
| `GET /api/samples` | Recent public measurements |
| `GET /api/radio/observations` | Upload-index **metadata** only |
| `GET /api/radio/files` | Analyzed local file status |
| `GET /api/exoplanets` | Confirmed planet catalog reference snapshot |
| `POST /api/poll` | Rate-limited public-source polling and local scan |

`PATCH` review states: `new`, `investigating`, `likely_interference`, `needs_followup`, `closed`. Review details and source metadata persist in SQLite across restarts. SQLite runs in WAL journal mode for concurrent reader/writer use; use `cli backup` for a consistent evidence snapshot rather than copying an open WAL database by hand. **Note:** no digital signatures or third-party calibration certificates are supplied.

## Scientific provenance and data use

- **e-Callisto**: [Data access and publication rules](https://www.e-callisto.org/Data/data.html), FHNW/IRSOL and contributing station operators. The project asks for credit and consultation with relevant instrument PIs/operators before publication; follow the current rules for any scientific paper.
- **NOAA SWPC**: [Data service](https://www.spaceweather.gov/content/data-access) and near-real-time space-weather products.
- **NASA/JPL**: [CAD API](https://ssd-api.jpl.nasa.gov/doc/cad.html), previously catalogued objects; many close-approach times are reported in TDB, not directly UTC.
- **SatNOGS**: [Community API](https://librespacefoundation.gitlab.io/satnogs/satnogs-network/api.html); check source license and attribution.
- **NASA Exoplanet Archive**: [TAP documentation](https://exoplanetarchive.ipac.caltech.edu/docs/TAP/usingTAP.html), catalogued planet parameters. This service may be intermittently unavailable.
- **Breakthrough Listen**: [Public data archive](https://seti.berkeley.edu/opendata); archived recordings, not a continuously streaming public SETI receiver.

## Validation status and limitations

- Tests use mocked HTTP, isolated SQLite, synthetic radio matrices and an optional genuine FITS reader test using Astropy. CI installs all standard dependencies.
- **No internet-connected real FITS download and decoding was verified in this isolated build environment.** Any live/source failures are visible in the source-health panel.
- Alerts are **local dashboard/API events**, not outbound email/SMS notifications. No live SETI survey feed and no autonomous peer-reviewed anomaly confirmation pipeline are provided.
- e-Callisto solar radio time matches are based on metadata timing; not verified physical coincidences. Planet catalog polling is not a new-planet detector.

### Roadmap after v1.8

1. Run a reproducible, time-stamped end-to-end e-Callisto FITS validation on an internet-connected host; verify station metadata and frequency axes against real reference observations.
2. Integrate an expressly authorized, continuously updating distant-target SETI radio source, if made available; require telescope metadata and independent RFI controls.
3. Add robust instrument calibration, station baselines, coincidence significance, and validation by domain experts.
4. Add opt-in outbound alerts, multi-operator authentication, data governance, and reproducible scientific notebooks.

© 2026 Magnexis LLC. Unaffiliated with the data providers.
