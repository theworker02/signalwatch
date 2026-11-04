"""Conservative download of newly published *solar* radio spectra from public e-Callisto archive.

Never crawls external links: dates and filenames are validated and all downloads
stay on the documented host. At most two compressed FITS per 15-minute poll.
"""
import gzip
import hashlib
import io
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote

from .solar import MAX_FITS_BYTES

ARCHIVE_BASE = 'https://soleil.i4ds.ch/solarradio/data/2002-20yy_Callisto'
MAX_INDEX_BYTES = 2_000_000
MAX_COMPRESSED_BYTES = 3_000_000
MAX_DOWNLOADS = 2
MAX_CACHED_BYTES = 350 * 1024 * 1024
CACHE_RETENTION_HOURS = 24
FILENAME = re.compile(r'^(?P<station>[A-Za-z0-9][A-Za-z0-9.-]{1,100})_(?P<date>\d{8})_(?P<time>\d{6})_(?P<channel>\d{2})\.fit\.gz$')


class AnchorNames(HTMLParser):
    def __init__(self):
        super().__init__()
        self.names = []

    def handle_starttag(self, tag, attrs):
        if tag != 'a':return
        href=dict(attrs).get('href','')
        # Apache raw listing: only simple filenames, never directories/URLs.
        if href and '/' not in href and '\\' not in href and '?' not in href and '#' not in href:
            if FILENAME.fullmatch(href):self.names.append(href)


def parse_archive_listing(html, *, date, station='AUTO', clock=None):
    """Parse *daily* index and select recent samples for exactly one station."""
    if not isinstance(html,str) or not ('Index of' in html[:1000] and 'Callisto' in html[:1000]):
        raise ValueError('Unrecognized e-Callisto Apache index')
    if not re.fullmatch(r'\d{8}',date):raise ValueError('Invalid archive date')
    if station!='AUTO' and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{1,100}',station):raise ValueError('Invalid station')
    parser=AnchorNames()
    parser.feed(html)
    clock=clock or datetime.now(timezone.utc)
    found=[]
    for name in set(parser.names):
        match=FILENAME.fullmatch(name)
        if (station!='AUTO' and match.group('station')!=station) or match.group('date')!=date:continue
        try:
            observed=datetime.strptime(match.group('date')+match.group('time'),'%Y%m%d%H%M%S').replace(tzinfo=timezone.utc)
        except ValueError:continue
        # Avoid stale backlog and clock-corrupt future observations.
        if clock-timedelta(hours=8)<=observed<=clock+timedelta(minutes=5):
            found.append((observed,name))
    return [name for _,name in sorted(found,reverse=True)]


def archive_url(day):
    return f'{ARCHIVE_BASE}/{day:%Y/%m/%d}/'


def decompress_fits(payload):
    if len(payload)>MAX_COMPRESSED_BYTES or not payload.startswith(b'\x1f\x8b'):
        raise ValueError('Unexpected size or type for compressed FITS')
    with gzip.GzipFile(fileobj=io.BytesIO(payload)) as fh:
        decompressed=fh.read(MAX_FITS_BYTES+1)
    if len(decompressed)>MAX_FITS_BYTES or not decompressed.startswith(b'SIMPLE  ='):
        raise ValueError('Decompressed content not a bounded standard FITS primary header')
    return decompressed


def prune_processed_cache(store, inbox, *, now=None):
    """Delete only old *program-owned* FITS after successful analysis.

    Never touches user-imported files; keeps database evidence hashes and
    source citations. Program-owned cache is managed separately.
    """
    inbox=Path(inbox)
    if inbox.name!='callisto_auto' or inbox.is_symlink() or not inbox.is_dir():return 0
    now=now or datetime.now(timezone.utc)
    deleted=0
    for p in inbox.glob('*.fit'):
        if p.is_symlink() or now.timestamp()-p.stat().st_mtime < CACHE_RETENTION_HOURS*3600:
            continue
        if p.stat().st_size>MAX_FITS_BYTES:continue
        if store.is_radio_file_processed(hashlib.sha256(p.read_bytes()).hexdigest()):
            p.unlink();deleted+=1
    return deleted


async def download_recent(client, store, inbox, *, station='AUTO', now=None):
    """Archive polling: two small uploads max; observation data remain solar-only.

    Uses the current day's archive listing (date UTC). Typical archive latency
    varies; no promise of live streaming, availability, or scientific validity.
    """
    now=now or datetime.now(timezone.utc)
    if station!='AUTO' and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{1,100}',station):
        raise ValueError('Invalid station name')
    inbox=Path(inbox)
    inbox.mkdir(parents=True,exist_ok=True)
    cache_used=sum(p.stat().st_size for p in inbox.glob('*.fit') if p.is_file() and not p.is_symlink())
    if cache_used>=MAX_CACHED_BYTES:raise ValueError('Solar FITS cache full; clear processed files or expand disk')
    page=archive_url(now)
    response=await client.get(page,headers={'Accept':'text/html'})
    response.raise_for_status()
    if len(response.content)>MAX_INDEX_BYTES:raise ValueError('Archive index too large')
    all_names=parse_archive_listing(response.text,date=now.strftime('%Y%m%d'),station=station,clock=now)
    new=[n for n in all_names if not (inbox/n.replace('.fit.gz','.fit')).exists()]
    # Only the newest recordings; never backfill an entire station unprompted.
    # In AUTO mode, spread samples across observatories for geographic coverage
    # rather than downloading both polarizations from a single instrument.
    if station=='AUTO':
        choices=[]; selected=set()
        for name in new:
            found=FILENAME.fullmatch(name)
            site=found.group('station')
            if site in selected:continue
            choices.append(name);selected.add(site)
            if len(choices)>=MAX_DOWNLOADS:break
    else:
        choices=new[:MAX_DOWNLOADS]
    downloaded=[]
    for name in choices:
        file_url=page+quote(name,safe='')
        async with client.stream('GET',file_url,headers={'Accept':'application/octet-stream'}) as r:
            r.raise_for_status()
            compressed=bytearray()
            async for part in r.aiter_bytes():
                compressed.extend(part)
                if len(compressed)>MAX_COMPRESSED_BYTES:raise ValueError('Compressed FITS download exceeds 3MB')
        decompressed=decompress_fits(bytes(compressed))
        final=inbox/name.replace('.fit.gz','.fit')
        tmp_path=None
        try:
            with tempfile.NamedTemporaryFile(mode='wb',dir=inbox,suffix='.partial',delete=False) as fh:
                tmp_path=Path(fh.name)
                fh.write(decompressed)
            os.replace(tmp_path,final)
        finally:
            if tmp_path is not None:tmp_path.unlink(missing_ok=True)
        downloaded.append(final.name)
    return {'source':'e-Callisto raw FITS','ok':True,'seen':len(all_names),
        'added':len(downloaded),'downloaded':downloaded,'station':station,
        'archive_url':page,'data_category':'solar_radio_not_SETI'}
