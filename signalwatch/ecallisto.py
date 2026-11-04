"""e-Callisto public *upload index* observation metadata, not raw RF samples.

The index exposes filenames of approximately 15-minute FITS observations. The
central SFTP server requires its own access arrangements; this public listing
alone does not grant access to the spectra. Never label it a live SETI feed.
"""
import re
from datetime import datetime, timezone
from pathlib import Path

INDEX_URL = 'https://soleil.i4ds.ch/solarradio/e-Callisto/sftp_directory.txt'
# Limit to instrument observations; no traversal, arbitrary links or downloads.
ENTRY = re.compile(r'^\s*(?P<size>\d{1,10})\s+(?P<uploaded>\d{4}-\d\d-\d\d\s+\d\d:\d\d:\d\d)\s+(?P<filename>[A-Za-z0-9][A-Za-z0-9_.-]{1,170}\.fit(?:\.gz)?)\s*$', re.M)
OBS_TIME = re.compile(r'_(\d{8})_(\d{6})_\d{2}\.fit(?:\.gz)?$', re.I)


def parse_index(raw_text):
    """Return normalized file arrival records, strictly rejecting bogus dates."""
    if not isinstance(raw_text, str) or 'SFTP directory listing' not in raw_text[:200]:
        raise ValueError('Unexpected e-Callisto upload-index format')
    observations = []
    for match in ENTRY.finditer(raw_text):
        name = match.group('filename')
        stamp = OBS_TIME.search(name)
        if not stamp:
            continue
        try:
            timestamp = datetime.strptime(''.join(stamp.groups()), '%Y%m%d%H%M%S').replace(tzinfo=timezone.utc)
            uploaded = datetime.strptime(match.group('uploaded'), '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
            size = int(match.group('size'))
        except (ValueError, OverflowError):
            continue
        if not 10_000 <= size <= 40_000_000:
            continue
        observations.append({'filename':name,'station':name.split('_', 1)[0],
            'observed_at':timestamp.isoformat(), 'listed_uploaded_at':uploaded.isoformat(),
            'size_bytes':size, 'origin':INDEX_URL, 'category':'solar_radio_spectrum',
            'data_availability':'metadata_only; FITS not included'})
    if not observations:
        raise ValueError('No recognized FITS entries in e-Callisto index')
    return observations


def process_ecallisto_index(store, raw_text):
    observations = parse_index(raw_text)
    return len(observations), store.put_radio_observations(observations)
