# Magnexis SIGNALWATCH v0.3

**Experimental continuously polling astronomical observatory and unverified radio anomaly research tool.** Developed under Magnexis LLC. All candidate classifications require human review and scientific follow-up. There are **no claims of extraterrestrial detection**.

## What is genuinely connected?

| Feed | Cadence / what it is | Scientifically appropriate use |
|---|---|---|
| **e-Callisto public FITS archive** | Programmatically checks current UTC day every ~15 minutes and downloads **at most two recently published compressed solar radio spectrograms** from [FHNW's public archive](https://soleil.i4ds.ch/solarradio/data/2002-20yy_Callisto/) per cycle | Broadband solar-radio transient screening, not SETI. FITS observations can be delayed; archive isn't an instantaneous RF stream. |
| **e-Callisto public upload index** | Checks a public SFTP directory *text listing* every 15 minutes. Indexed filenames are **metadata only**, not received spectra. | Provides audit trail of newly submitted station data. |
| **NOAA GOES X-ray, X-ray flares, Kp, solar radio flux** | Near-real-time published JSON polled every 5–10 minutes | Space weather, known solar/geomagnetic activity; separate from technosignature detection. |
| **NASA JPL CAD** | Cached, predicted close approaches; once every 6 hours | Known-object predictions, **not discoveries or impact probabilities**. |
| **SatNOGS** | Published community spacecraft reception metadata; every 10 minutes | Reception records only, no ETI claims. |
| **SETI laboratory** | Watches *local* `.npy`, `.npz`, `.fil` or `.h5` file inputs every 20 seconds | Narrowband frequency-drift candidates in user-imported telescope observations, with optional ON/OFF comparisons; **no public continuously streaming extraterrestrial-target telescope is integrated**. |

The e-Callisto FITS archive was publicly verified on **November 4, 2026** to contain files for that date. **We could not fetch a real FITS file from this isolated development environment**, so the v0.3 downloader has been tested with realistic mocked HTTP responses, and the broadband classifier on synthetic observations. The installation's source-health panel will show genuine fetch errors rather than manufactured results.

### Install and run

Python **3.10+** required. The main requirements now include `astropy` to read real FITS radio telescope files; `blimpy` for optional Breakthrough Listen `.fil`/`.h5` is separate.

```bash
cd magnexis-signalwatch
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python run.py
```

Visit <http://127.0.0.1:8765>. Windows: double-click `start_windows.bat`; Linux/macOS: `./start_linux_mac.sh`. To run unattended on a machine that stays on:

```bash
docker compose up -d --build
docker compose logs -f
```

Docker stays bound to **127.0.0.1**. Do not expose it directly to the internet: the research UI and write API have no login, remote auth, rate limiting or full CSRF protection. One server worker only.

### Solar-radio spectrum download and screening

Default configuration:

```bash
SIGNALWATCH_CALLISTO_DOWNLOAD=1
SIGNALWATCH_CALLISTO_STATION=AUTO
```

`AUTO` selects the latest eligible spectra from up to **two different observing stations** in the current UTC day's public archive, not more than two downloads per 15 minutes. Switch to an exact archive station name (e.g., `ALGERIA-CRAAG`) to inspect only one station. Set `SIGNALWATCH_CALLISTO_DOWNLOAD=0` to disable autonomous downloads while retaining the metadata index.

Only public, fixed-host HTTPS URLs are requested. The engine validates archive filename format, UTC date, and recent observation time; does not follow arbitrary HTML links; limits compressed data to **3 MB/file** and decompressed FITS data to **40 MB/file**; refuses overlarge listings; and rejects invalid FITS magic. Recent files are stored in `data/inbox/callisto_auto/`, then reviewed via the optional Astropy FITS decoder and broadband detector. Only previously **successfully processed** program-owned files older than **24 hours** are automatically deleted. If the auto-download cache reaches **350 MB** the downloader pauses with a visible error until space is available. User-imported recordings are never deleted.

Each FITS recording is classified as **solar-radio only**. The heuristic scans 2D time×frequency data for sustained broadband enhancements, performs per-frequency robust background subtraction, ignores chronically occupied channels, and rejects single-time-step spikes. Solar transients are **not a SETI technosignature**; RFI, receiver gain changes, and solar physics must still be differentiated. Candidate records include raw-file SHA-256, instrument timestamp where available, station/source metadata, bin/time ranges, quality flags and a human review state.

An additional `GET /api/radio/observations` endpoint shows recent **upload-index metadata** separately from downloaded raw FITS. Never confuse an indexed file with an inspected signal or a confirmed event.

### SETI narrowband laboratory

Download authorized telescope observations from [Breakthrough Listen](https://seti.berkeley.edu/opendata). For real `.fil`/`.h5` recordings, install:

```bash
python -m pip install -r requirements-radio.txt
python -m signalwatch.radio path/to/ON.fil --off path/to/OFF.fil
```

Or place a 2D power matrix (`.npy`/`.npz`) or `.fil`/`.h5` recording in `data/inbox/`. The SETI detector searches for persistent drifting narrowband traces and applies an **RFI-like** classification for low drift, as well as a heuristic off-target comparison if provided. ON/OFF matrix shapes must match; *actual frequency alignment, pointing, matched timestamps and independent telescope validation remain the operator's responsibility*. The `.fil`/`.h5` reader uses **only the central 2,048 frequency channels and first 192 time integrations** rather than the whole archive. Results are **candidates**, not confidence scores or evidence of an extraterrestrial transmitter.

`python -m signalwatch.radio --demo` validates the algorithms with synthetic tones. `python -m examples.make_synthetic` generates explicitly labeled, zero-priority synthetic data; remove synthetic test files from the inbox before interpreting actual research.

### Scientific provenance and attribution

- **e-Callisto**: Public archive by participating observatories / FHNW / IRSOL, [data portal and instructions](https://www.e-callisto.org/Data/data.html). They request credit and special advance consultation for publication; consult the source's current rules and observing teams before publishing results based on their data. The source describes typical 15-minute data submissions; appearance may lag.
- **NOAA SWPC**: [public data service](https://www.spaceweather.gov/content/data-access), near-real-time space-weather measurements and reports.
- **NASA/JPL**: [CAD API](https://ssd-api.jpl.nasa.gov/doc/cad.html), predicted known-body close approaches; timestamps in the CAD feed are TDB, not UTC.
- **SatNOGS**: [public REST API](https://librespacefoundation.gitlab.io/satnogs/satnogs-network/api.html), CC BY-SA observation data.
- **Breakthrough Listen**: Public archive is not an authenticated always-on live telescope stream.

No unexplained signal should be announced as astronomical discovery without provenance, analysis of terrestrial/interference hypotheses, independent ON/OFF or repeat observations, and review by relevant researchers.

### API & review workflow

- `GET /api/health`, `/api/status`, `/api/sources`
- `GET /api/radio/observations?limit=40` — recently indexed solar FITS **metadata only**
- `GET /api/radio/files` — results of local FITS/SETI scanning
- `GET /api/events?limit=100&source=e-Callisto%20solar%20radio`
- `GET /api/samples?source=NOAA%20GOES%20X-ray`
- `PATCH /api/events/{id}/review` — `new`, `investigating`, `likely_interference`, `needs_followup`, `closed`
- `GET /api/events.csv` — latest events, CSV formula-sanitized
- `POST /api/poll` — observes per-source minimum polling intervals, does not force repeated public queries.

A source can show `ok` (feed fetched successfully) despite zero new records. Inspect observation timestamps to assess freshness. Tests use mock endpoints/synthetic signals and **never insert fake discoveries as real data**.

### Tests

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

20 tests validate feed parsers, duplicate handling, controlled HTTP archive download with mocked responses, compressed-file safety, narrowband signal detection, broadband solar transients, stationary interference suppression, ON/OFF shape validation, review endpoints and polling/backoff. Tests are local; they are not proof the production telescope connection is live.

### Roadmap

1. Verify live archive download, instrument metadata and FITS decoding on an internet-connected host; publish reproducible sample spectrum provenance.
2. Add legitimate streaming astronomy datasets with observed station/source coordinates, frequency axes, and calibrated timestamps; obtain source permission where needed.
3. Improve RF occupancy persistence, same-event checks at independent observatories, telescope ON/OFF sequences and signal validation, with manual review.
4. Add alerting and scientific evidence bundles, authentication and separate workers for remote deployment.

© 2026 Magnexis LLC. Unaffiliated with the source organizations.
