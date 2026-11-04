# Magnexis SIGNALWATCH v0.2

An **experimental near-real-time astronomical observation monitor** and local **narrowband radio candidate detector** by Magnexis LLC. Public data is used only within its documented limits. This software does not detect extraterrestrial life, issue impact-risk predictions, or provide scientific confirmation of any signal.

## Capabilities

- Polls **NOAA GOES X-ray** measurements, solar flare reports, and planetary Kp; **NOAA solar radio flux** (heuristic outlier flagging); **NASA/JPL SBDB close-approach predictions**; **SatNOGS satellite reception metadata**. All data sources are clearly labeled.
- Source-specific minimum polling intervals: NOAA every 5–10 minutes, SatNOGS every 10 minutes, JPL every 6 hours. Sequential requests, exponential backoff on failures, and source-health status respect the JPL API's fair-use guidance.
- SETI laboratory: scan locally imported 2D power spectrograms (`.npy`, `.npz`), and bounded radio telescope `.fil`/`.h5` cutouts (optional `blimpy`). This is not a live telescope connection. Supports an explicit ON/OFF-target comparison from the CLI.
- Store unique events, radio file processing results, observations, and human review status in SQLite. Investigator notes and classification are editable from the dashboard.
- Export the latest 500 evidence events to CSV and inspect JSON API endpoints.
- Can run unattended as a single-process local service or via Docker (`restart: unless-stopped`).

## Quick start

Python **3.10+** required.

```bash
cd magnexis-signalwatch
python -m venv .venv
# Linux and macOS:
source .venv/bin/activate
# Windows PowerShell:
# .venv\\Scripts\\Activate.ps1
pip install -r requirements.txt
python run.py
```

Open <http://127.0.0.1:8765>. Windows users can run `start_windows.bat`, and Linux/macOS users `./start_linux_mac.sh`.

### Docker

```bash
docker compose up -d --build
docker compose logs -f
# Stop
# docker compose down
```

Docker's port is deliberately bound to **127.0.0.1:8765** and should **not** be internet-exposed without authentication, authorization, request throttling, CSRF controls, and a separate scheduled ingestion worker. This is not a hardened multitenant application.

## Ingestion, polling, and scientific provenance

| Source | Endpoint | What it actually describes | Minimum interval |
|---|---|---|---|
| NOAA GOES | `https://services.swpc.noaa.gov/json/goes/primary/xrays-6-hour.json` | Solar X-ray irradiance, observed | 5 min |
| NOAA solar flares | `https://services.swpc.noaa.gov/json/goes/primary/xray-flares-7-day.json` | Documented solar flares, observed | 10 min |
| NOAA Kp | `https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json` | Observed geomagnetic indices | 5 min |
| NOAA solar radio | `https://services.swpc.noaa.gov/json/solar-radio-flux.json` | Measured solar radio flux, not ETI | 10 min |
| NASA JPL CAD | `https://ssd-api.jpl.nasa.gov/cad.api` | **Predicted** close approaches of **known** objects | 6 hours |
| SatNOGS | `https://network.satnogs.org/api/observations/` | Public satellite reception metadata, not cosmic ETI | 10 min |
| Radio inbox | `data/inbox/` | Locally imported telescope observations | every 20 sec |

Network adapters may fail or change schema; errors are visible and no synthetic data is presented as real. The first cycle fetches all network sources. The **Poll now** button does not bypass minimum query spacing; it skips sources that are not due. The JSON endpoint `GET /api/status` exposes the last cycle and nominal next delay per source. `SIGNALWATCH_POLL_SECONDS` is a global lower bound (default: 300).

Solar-radio-flux outlier screening requires at least twelve valid measurements at one frequency and uses an **ad hoc robust threshold** (median + 8×MAD or 3×median). It is an **unvalidated statistical alert** about *solar radio emissions*, not a SETI classifier. If NOAA changes its JSON schema, source status shows an error.

JPL CAD reports predicted close-approach timestamps in TDB and is kept separate from UTC measurements; no threat probability is inferred. The detector may flag known natural phenomena for research awareness; their scores reflect heuristic triage priority, **not confidence or probability of an alien origin**.

## Analyze real radio data

No telescope, API key, or paid service is required to work with downloaded public data. Public radio telescope observations can be obtained from [Breakthrough Listen](https://seti.berkeley.edu/opendata); archive access is separate from the live polling adapters.

Install optional radio support:

```bash
pip install -r requirements-radio.txt
python -m signalwatch.radio /path/to/observation.fil
python -m signalwatch.radio /path/to/ON.fil --off /path/to/OFF.fil
```

Or place a radio power matrix in `data/inbox/` as `.npy` or `.npz` (`power` key). A `.npz` may carry scalar metadata: `start_frequency_mhz`, `channel_width_hz`, `integration_seconds`, `observation_start_utc` or `observation_mjd`. The field `observation_start_utc` is passed through with the input file's source assertion; values created from MJD **assume UTC** and should be verified against the instrument's time scale. If no observation timestamp is provided, an event uses analysis time and metadata explicitly records `observation_timestamp_basis=analysis_time`.

**Scope of scanning:** the `.fil`/`.h5` loader intentionally analyzes only a central **2,048-channel** and first **192-time-integration** cutout (up to 4 million cells). It does not perform a full-band, full-cadence search, infer the true pointing, calibrate the instrument, model Doppler shifts, correlate independent observations, or prove technosignatures. For comprehensive blind work, use a dedicated scientific pipeline such as [turboSETI](https://github.com/UCBerkeleySETI/turbo_seti), consider terrestrial RFI and ON/OFF validation, and involve researchers.

Data safety: power matrices have size caps (200 MB for NumPy, 12 GB for optional radio telescope files); `.npz` uncompressed sizes are checked before loading, object pickles are disabled, and newly modified radio files are skipped for five seconds to reduce partial-write errors. The watcher processes local files only; it does **not** download arbitrary external radio URLs.

## Research and review workflow

In the browser, select an event's **review state** (`new`, `investigating`, `likely_interference`, `needs_followup`, `closed`) and optionally save an investigator note. These states are human labels, not automatic scientific validation. The new **Export evidence CSV** action exports the last 500 rows, including review notes and evidence URLs.

API:

- `GET /api/health`, `/api/status`, `/api/sources`
- `GET /api/events?limit=100&source=SETI%20radio&kind=radio_candidate`
- `PATCH /api/events/{event_id}/review` with JSON `{"state":"investigating","note":"Check ON/OFF cadence"}`
- `GET /api/events.csv`, `GET /api/samples?source=NOAA%20GOES%20X-ray`
- `GET /api/radio/files`, `POST /api/poll`

The review endpoint rejects non-loopback browser origin headers; the service must remain loopback-bound. Treat stored radio file paths and imported data as sensitive if you later deploy beyond localhost.

## Validation

```bash
pip install -r requirements-dev.txt
pytest -q
python -m signalwatch.radio --demo
```

The demo is **synthetic**. To populate the inbox with a clearly labeled synthetic file, run `python -m examples.make_synthetic`; its candidates are marked `SYNTHETIC` and assigned zero science priority. **Delete the test file and reset the local data store before research use.**

Automated tests cover simulated drifting tones, noise-only input, off-target RFI, provenance, feed parsers, HTTP mocked ingestion, per-source polling intervals, reviewer workflow, and CSV formula-safe export. Network verification from this build environment is unavailable; run on a machine with internet access and verify `/api/sources` shows successful real fetches before making any operational claim.

## Configuration

- `SIGNALWATCH_DATA_DIR` (default `./data`)
- `SIGNALWATCH_POLL_SECONDS` (default 300, at least 60)
- `SIGNALWATCH_BACKGROUND=0` disables background tasks for local development/tests

## Roadmap

1. A legitimate public or permissioned live radio spectrogram interface, with timestamp calibration and monitoring/usage terms.
2. Partitioned full-band .fil/.h5 scanning, ON/OFF sequence matching, Doppler drift-rate modeling, RF occupancy history, and candidate waterfall image evidence.
3. Signal clustering across independent observations and stations, scientific-quality provenance bundles, alert delivery.
4. Deployable authentication, rate limiting, audit trail, and independent worker service.

© 2026 Magnexis LLC. This software is not affiliated with or endorsed by the scientific data providers.
