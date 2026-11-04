"""Conservative e-Callisto solar radio FITS analyzer.

This is NOT a SETI detector. It finds broadband solar-radio *transients*
that could also be terrestrial RFI or receiver gain changes. FITS import is
optional and is never presented as independently verified space weather.
"""
import hashlib
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

MAX_FITS_BYTES = 40 * 1024 * 1024
MAX_CELLS = 4_000_000


def load_callisto_fits(path):
    """Return time-by-frequency FITS power data and unverified instrument metadata."""
    path = Path(path)
    if path.suffix.lower() not in ('.fit', '.fits'):
        raise ValueError('Expected uncompressed .fit or .fits; decompress externally first')
    if path.stat().st_size > MAX_FITS_BYTES:
        raise ValueError('FITS exceeds 40MB safety bound')
    try:
        from astropy.io import fits
    except ImportError as exc:
        raise RuntimeError('Install FITS support: pip install -r requirements-solar.txt') from exc
    with fits.open(path, memmap=True) as hdus:
        hdu = hdus[0]
        if hdu.data is None or hdu.data.ndim != 2:
            raise ValueError('Expected a 2D primary FITS image')
        primary = np.asarray(hdu.data)
        # e-Callisto stores [frequency channels, time samples]. Do NOT silently
        # reinterpret square matrices or arbitrary FITS datasets as e-Callisto.
        if not 12 <= primary.shape[0] <= 2048 or primary.shape[1] < 24:
            raise ValueError('Unrecognized e-Callisto frequency×time dimensions')
        if primary.size > MAX_CELLS:
            raise ValueError('FITS matrix too large; crop before analysis')
        matrix = np.asarray(primary.T, dtype=np.float32).copy()
        header = hdu.header
        if not np.isfinite(matrix).all():
            raise ValueError('FITS contains invalid numeric measurements')
        info = {'provenance':'imported_e_callisto_fits', 'observation_target':'Sun',
            'instrument':str(header.get('INSTRUME','unknown'))[:120],
            'site':str(header.get('ORIGIN', 'unknown'))[:120],
            'frequency_channels':int(matrix.shape[1]),
            'time_samples':int(matrix.shape[0]),
            'frequency_axis_calibrated':False,
            'observation_time_basis':'unverified_instrument_header'}
        date=str(header.get('DATE-OBS') or header.get('DATE') or '').replace('/','-').strip()
        time=str(header.get('TIME-OBS') or '').strip()
        try:
            when=datetime.fromisoformat(date + ('T'+time if time else ''))
            if when.tzinfo is None:when=when.replace(tzinfo=timezone.utc)
            info['observation_start_utc']=when.astimezone(timezone.utc).isoformat()
        except ValueError:
            # Do not infer observation time from ingestion clock.
            info['observation_start_utc']=None
        # e-Callisto data have a nonuniform frequency axis in many recordings.
        # Only advertise actual frequencies when a length-matched FITS extension
        # explicitly provides them. Otherwise bins stay abstract.
        for ext in hdus[1:]:
            if not hasattr(ext, 'columns') or ext.data is None:
                continue
            if 'FREQUENCY' not in [n.upper() for n in (ext.columns.names or [])]:
                continue
            try:
                a=np.asarray(ext.data[ext.columns.names[[n.upper() for n in ext.columns.names].index('FREQUENCY')]],dtype=float).ravel()
                if a.size==matrix.shape[1] and np.isfinite(a).all():
                    info['frequency_axis_mhz']=[round(float(v),5) for v in a]
                    info['frequency_axis_calibrated']=True
                    break
            except (ValueError,TypeError,IndexError,KeyError):
                pass
        # File name offers a clock hint but is not independent validation.
        if info.get('observation_start_utc') is None:
            match=re.search(r'_(\d{8})_(\d{6})_\d{2}\.fits?$',path.name,re.I)
            if match:
                try:
                    info['observation_start_utc']=datetime.strptime(''.join(match.groups()),'%Y%m%d%H%M%S').replace(tzinfo=timezone.utc).isoformat()
                    info['observation_time_basis']='unverified_filename'
                except ValueError:pass
        try:
            cadence=float(header.get('CDELT1',0))
            if 0.01 <= cadence <= 120:
                info['integration_seconds']=cadence
        except (TypeError,ValueError):pass
    return matrix,info


def scan_solar_bursts(power, *, min_fraction=0.25, min_duration=3, max_candidates=12):
    """Detect contiguous broadband enhancements after per-frequency background subtraction.

    Mask chronic occupied channels and refuse broadband single-frame spikes.
    Output is heuristic, NOT a calibrated solar burst or technosignature.
    """
    p=np.asarray(power,dtype=np.float32)
    if p.ndim!=2 or p.shape[0]<24 or p.shape[1]<24 or p.size>MAX_CELLS or not np.isfinite(p).all():
        raise ValueError('Expected finite time×frequency matrix with >=24 per axis and <=4M cells')
    med=np.median(p,axis=0,keepdims=True)
    mad=np.median(np.abs(p-med),axis=0,keepdims=True)
    # Robust floor guards silent channels and near-zero variance.
    scale=np.maximum(1.4826*mad, np.maximum(0.002*np.maximum(abs(med),1),0.15))
    z=np.clip((p-med)/scale,-10,50)
    permanently_active=(z>4.0).mean(axis=0) > 0.22
    valid=~permanently_active
    if np.count_nonzero(valid)<max(12,int(p.shape[1]*0.3)):
        return []
    occupancy=(z[:,valid]>4.0).mean(axis=1)
    # Smooth three-sample windows; require clustered evidence not an impulse.
    averaged=np.convolve(occupancy,np.ones(3)/3,mode='same')
    active=averaged >= min_fraction
    edges=np.diff(np.r_[False,active,False].astype(int))
    result=[]
    for start,end in zip(np.flatnonzero(edges==1),np.flatnonzero(edges==-1)):
        if end-start < min_duration or end-start > p.shape[0]*0.5:
            continue
        peak=float(np.max(occupancy[start:end]))
        if peak < min_fraction:
            continue
        fraction=float(np.mean(occupancy[start:end]))
        strength=float(np.percentile(z[start:end,valid],95))
        score=int(min(90, 28+45*peak+min(17,strength)))
        result.append({'start_sample':int(start),'end_sample':int(end),
                       'peak_fraction_channels':round(peak,3),
                       'mean_fraction_channels':round(fraction,3),
                       'p95_background_z':round(strength,2),
                       'priority_score':score,'classification':'unverified_broadband_solar_radio_transient',
                       'quality_flags':['single_station','receiver_gain_or_RFI_not_excluded'],
                       'note':'Solar-pointing instrument transient: not evidence of extraterrestrial intelligence.'})
    result.sort(key=lambda c:c['priority_score'],reverse=True)
    return result[:max_candidates]


def analyze_solar_fits(store,path):
    """Store events separately from SETI. Auto-ingest only local operator-provided files."""
    path=Path(path)
    if path.stat().st_size>MAX_FITS_BYTES:
        raise ValueError('FITS exceeds 40MB safety bound')
    raw=path.read_bytes()  # bounded; hash gives stable evidence identity
    if len(raw)>MAX_FITS_BYTES:
        raise ValueError('FITS exceeds 40MB safety bound')
    sha=hashlib.sha256(raw).hexdigest()
    if store.has_radio_file(sha):return {'file':path.name,'skipped':True}
    try:
        p,meta=load_callisto_fits(path)
        evidence_url='https://www.e-callisto.org/Data/data.html'
        match=re.fullmatch(r'([A-Za-z0-9][A-Za-z0-9.-]{1,100})_(\d{4})(\d{2})(\d{2})_(\d{6})_(\d{2})\.fit',path.name,re.I)
        if match and path.parent.name=='callisto_auto':
            station,year,month,day,clock,channel=match.groups()
            evidence_url=(f'https://soleil.i4ds.ch/solarradio/data/2002-20yy_Callisto/'
                          f'{year}/{month}/{day}/{path.name}.gz')
            meta['source_station']=station
            meta['source_archive_url']=evidence_url
        observations=scan_solar_bursts(p)
        fake=('SYNTHETIC' in path.name.upper())
        for c in observations:
            observed_at=meta.get('observation_start_utc')
            if observed_at and meta.get('integration_seconds'):
                observed_at=(datetime.fromisoformat(observed_at)+timedelta(seconds=c['start_sample']*meta['integration_seconds'])).isoformat()
            if not observed_at:
                observed_at=datetime.now(timezone.utc).isoformat()
            store.put_event(source='e-Callisto solar radio',source_id=f"{sha}:{c['start_sample']}",
                kind='solar_radio_transient',title=('[SYNTHETIC] ' if fake else '')+'Unverified solar radio transient',
                observed_at=observed_at,score=0 if fake else c['priority_score'],
                severity='test' if fake else 'medium',summary=('Synthetic solar radio validation only.' if fake else
                    'Broadband enhancement in a solar-pointing radio spectrograph. Solar origin, RFI and calibration are unverified; NOT SETI evidence.'),
                evidence_url=evidence_url,
                metadata={**meta,**c,'filename':path.name,'file_sha256':sha,
                    'observation_timestamp_basis':meta.get('observation_time_basis') if meta.get('observation_start_utc') else 'analysis_time'})
        store.record_radio_file(sha,path.name,'ok',len(observations),'e-Callisto solar FITS; broadband candidate scan')
        return {'file':path.name,'candidates':len(observations),'status':'ok','channel':'solar'}
    except Exception as exc:
        store.record_radio_file(sha,path.name,'error',0,str(exc))
        return {'file':path.name,'status':'error','error':str(exc),'channel':'solar'}
