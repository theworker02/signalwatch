"""Experimental narrowband drifting-tone search. Scores are NOT probabilities or detections of ETI.

Input matrix: time x radio-frequency bins, representing detected POWER (not complex IQ).
For actual Breakthrough Listen .fil/.h5 recordings install requirements-radio.txt.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
from datetime import datetime, timezone, timedelta
import zipfile
import numpy as np

MAX_CELLS=4_000_000
MAX_FILE_BYTES=200*1024*1024
MAX_RADIO_FILE_BYTES=12*1024*1024*1024


def load_spectrogram(path, *, with_metadata=False):
    p=Path(path)
    ext=p.suffix.lower()
    size_limit=MAX_RADIO_FILE_BYTES if ext in ('.fil','.h5','.hdf5') else MAX_FILE_BYTES
    if p.stat().st_size > size_limit:
        raise ValueError('Radio file exceeds configured safety limit; crop it before analysis.')
    meta={'provenance':'local_import','scan_coverage':'full_matrix'}
    if ext=='.npy':
        data=np.load(p,allow_pickle=False,mmap_mode='r')
        arr=np.asarray(data)
    elif ext=='.npz':
        with zipfile.ZipFile(p) as z:
            if sum(f.file_size for f in z.infolist())>MAX_FILE_BYTES:
                raise ValueError('NPZ uncompressed content exceeds 200MB')
        with np.load(p,allow_pickle=False) as z:
            arr=np.asarray(z['power'] if 'power' in z else z[z.files[0]])
            for k in ('start_frequency_mhz','channel_width_hz','integration_seconds','observation_mjd'):
                if k in z and z[k].size==1:
                    meta[k]=float(z[k].item())
            if 'observation_start_utc' in z and z['observation_start_utc'].size==1:
                meta['observation_start_utc']=str(z['observation_start_utc'].item())
    elif ext in ('.fil','.h5','.hdf5'):
        try:
            from blimpy import Waterfall
        except ImportError as exc:
            raise RuntimeError('Install optional real-radio support: pip install -r requirements-radio.txt') from exc
        hdr=Waterfall(str(p),load_data=False)
        h=hdr.header
        # Deliberately process only a bounded frequency/time cutout from huge archives.
        # No completeness claim: this is a detector prototype, not a blind full-band SETI survey.
        nchan=int(h.get('nchans',0)); fch1=float(h.get('fch1',0)); foff=float(h.get('foff',0))
        if not nchan or not foff:
            raise ValueError('Missing radio frequency-axis metadata')
        center=fch1+foff*(nchan-1)/2
        half_width=abs(foff)*min(nchan,2048)/2
        waterfall=Waterfall(str(p),f_start=center-half_width,f_stop=center+half_width,
                            t_start=0,t_stop=192,load_data=True,max_load=0.3)
        arr=waterfall.data
        if arr is None:raise ValueError('Could not read bounded radio cutout')
        if arr.ndim==3:
            arr=arr[:,0,:]
        freqs=waterfall.get_freqs()
        meta={'provenance':'local_radio_telescope_file','scan_coverage':'central 2048 channel / first 192 time-integration cutout',
              'source_name':str(h.get('source_name','unknown')),'start_frequency_mhz':float(freqs[0]),
              'channel_width_hz':foff*1e6,'integration_seconds':float(h.get('tsamp',0)),
              'observation_mjd':float(h.get('tstart',0))}
    else:
        raise ValueError('Supported formats: .npy, .npz, .fil, .h5, .hdf5')
    if arr.ndim != 2 or min(arr.shape)<12 or arr.size>MAX_CELLS:
        raise ValueError('Need a 2D time×frequency power matrix (>=12 each axis, <=4M cells). Crop first.')
    if not np.issubdtype(arr.dtype,np.number) or np.iscomplexobj(arr):
        raise ValueError('Expected numeric real-valued power matrix, not IQ')
    x=np.asarray(arr,dtype=np.float32)
    if not np.isfinite(x).all():
        raise ValueError('Nonfinite data in radio matrix')
    if 'observation_start_utc' not in meta and meta.get('observation_mjd',0)>30000:
        # UTC approximation; the observation time scale must be confirmed from telescope metadata.
        meta['observation_start_utc']=(datetime(1858,11,17,tzinfo=timezone.utc)+
                   timedelta(days=meta['observation_mjd'])).isoformat()
        meta['observation_time_note']='MJD converted assuming UTC; verify instrument timescale'
    return (x,meta) if with_metadata else x


def scan_matrix(power, max_drift=12, max_candidates=6, off_target=None):
    """Scan linearly drifting narrowband signals in a radio power spectrogram.

    Median/MAD whitening by time row; integrate along drift templates. Strong
    zero-drift or repeated off-target peaks are RFI-like, not SETI claims.
    """
    x=np.asarray(power,dtype=np.float32)
    if x.ndim!=2 or x.shape[0]<12 or x.shape[1]<12 or x.size>MAX_CELLS:
        raise ValueError('Expected time×frequency matrix, >=12 each dimension, <=4M cells')
    if not np.isfinite(x).all():
        raise ValueError('Expected finite matrix')
    t,f=x.shape
    baseline=np.median(x,axis=1,keepdims=True)
    mad=np.median(np.abs(x-baseline),axis=1,keepdims=True)
    sigma=np.maximum(1.4826*mad,1e-6)
    z=np.clip((x-baseline)/sigma,-8,80)
    timeline=np.arange(t)
    traces=[]
    for d in range(-max_drift,max_drift+1):
        delta=np.rint(d*timeline/max(t-1,1)).astype(int)
        # True path, no wraparound. Each start channel must remain in range.
        lo=max(0,-int(delta.min()))
        hi=min(f, f-int(delta.max()))
        if lo>=hi:continue
        starts=np.arange(lo,hi)
        track=z[timeline[:,None],starts[None,:]+delta[:,None]]
        strength=np.mean(track,axis=0)
        occupancy=np.mean(track>=3.0,axis=0)
        # Strong continuous signals only, not a one-off spike.
        for k in np.flatnonzero((strength>=2.8)&(occupancy>=0.40)):
            traces.append((float(strength[k]),float(occupancy[k]),int(starts[k]),d))
    traces.sort(reverse=True)
    out=[]
    for strength,occupancy,channel,drift in traces:
        # Avoid repeatedly reporting nearby starting bins and similar paths.
        if any(abs(c['start_bin']-channel)<=3 and abs(c['drift_bins']-drift)<=4 for c in out):
            continue
        rfi_like=(abs(drift)<=1)
        # Pure heuristic 0-100 evidence-priority ranking, not confidence.
        score=min(99,int(35+7*strength+20*occupancy-(20 if rfi_like else 0)))
        out.append({'start_bin':channel,'drift_bins':drift,'mean_robust_z':round(strength,2),
                    'occupancy':round(occupancy,3),'priority_score':score,
                    'classification':'possible_stationary_RFI' if rfi_like else 'unverified_drifting_narrowband',
                    'quality_flags':['zero_or_low_drift_RFI_like'] if rfi_like else ['single_observation_unvalidated'],
                    'note':'Heuristic signal candidate; not evidence of extraterrestrial origin.'})
        if len(out)>=max_candidates:break
    if off_target is not None:
        if np.shape(off_target)!=np.shape(power):
            raise ValueError('ON/OFF comparison requires identical matrix shapes and calibrated frequency alignment')
        off=scan_matrix(off_target,max_drift=max_drift,max_candidates=30)
        for cand in out:
            if any(abs(o['start_bin']-cand['start_bin'])<=3 and abs(o['drift_bins']-cand['drift_bins'])<=3
                   for o in off):
                cand['classification']='seen_off_target_likely_RFI'
                cand['quality_flags'].append('present_in_OFF_observation')
                cand['priority_score']=max(5,cand['priority_score']-35)
    return out


def analyze_file(store,path,source_name='Local radio recording'):
    path=Path(path)
    stat=path.stat()
    signature=hashlib.sha256(f'{path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}'.encode()).hexdigest()
    if store.has_radio_file(signature):return {'file':path.name,'skipped':True}
    try:
        power,radio_metadata=load_spectrogram(path,with_metadata=True)
        candidates=scan_matrix(power)
        # Real checksum for manageable local imports, never silently call the
        # path/mtime dedup key a file-content hash. Very large telescope files
        # are bounded cutouts and remain explicitly unverified in this field.
        checksum=None
        if stat.st_size <= 256*1024*1024:
            dig=hashlib.sha256()
            with path.open('rb') as fh:
                for block in iter(lambda:fh.read(2*1024*1024),b''):
                    dig.update(block)
            checksum=dig.hexdigest()
        radio_metadata['file_sha256']=checksum
        radio_metadata['file_sha256_note']=('full_file_digest' if checksum else
                                           'omitted_for_file_exceeding_256MB')
        synthetic=('SYNTHETIC' in path.name.upper() or source_name.upper().startswith('SYNTHETIC'))
        for candidate in candidates:
            if 'start_frequency_mhz' in radio_metadata and 'channel_width_hz' in radio_metadata:
                candidate['frequency_mhz']=round(radio_metadata['start_frequency_mhz']+candidate['start_bin']*radio_metadata['channel_width_hz']/1e6,9)
                dt=radio_metadata.get('integration_seconds',0)
                if dt>0:candidate['drift_hz_per_second']=round(candidate['drift_bins']*radio_metadata['channel_width_hz']/((power.shape[0]-1)*dt),6)
            score=0 if synthetic else candidate['priority_score']
            store.put_event(source='SETI radio',source_id=f"{signature}:{candidate['start_bin']}:{candidate['drift_bins']}",
              kind='radio_candidate',title=f"{'[SYNTHETIC] '}"+f"Narrowband candidate · bin {candidate['start_bin']}" if synthetic else f"Narrowband candidate · bin {candidate['start_bin']}",
              observed_at=radio_metadata.get('observation_start_utc') or datetime.now(timezone.utc).isoformat(),
              score=score,severity='test' if synthetic else 'medium' if score>=70 else 'info',
              summary=('SYNTHETIC VALIDATION ONLY. Not an astronomical observation.' if synthetic else
               'Unverified narrowband candidate in an imported radio recording. Instrumental or terrestrial interference must be excluded.'),
              metadata=dict(candidate,filename=path.name,shape=list(power.shape),origin=source_name,
                 observation_timestamp_basis='instrument' if radio_metadata.get('observation_start_utc') else 'analysis_time',
                 **radio_metadata))
        store.record_radio_file(signature,path.name,'ok',len(candidates),f'Matrix {power.shape}')
        return {'file':path.name,'candidates':len(candidates),'status':'ok'}
    except Exception as exc:
        store.record_radio_file(signature,path.name,'error',0,str(exc))
        return {'file':path.name,'status':'error','error':str(exc)}


def scan_inbox(store,folder):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    out=[]
    # Only the operator inbox and the program-owned auto-download directory.
    auto=folder/'callisto_auto'
    candidates=list(folder.iterdir())
    if auto.is_dir() and not auto.is_symlink():candidates.extend(auto.iterdir())
    for p in sorted(candidates):
        if p.is_symlink() or not p.is_file() or p.suffix.lower() not in ('.npy','.npz','.fil','.h5','.hdf5','.fit','.fits'):
            continue
        if p.name.startswith('.'):continue
        # Avoid loading a large telescope file while another process is still writing it.
        if datetime.now(timezone.utc).timestamp()-p.stat().st_mtime < 5: continue
        if p.suffix.lower() in ('.fit','.fits'):
            from .solar import analyze_solar_fits
            out.append(analyze_solar_fits(store,p))
        else:
            out.append(analyze_file(store,p))
    return out


def demo_power(seed=57,signal=True):
    """Synthetic data for detector validation; never labeled real astronomical evidence."""
    rng=np.random.default_rng(seed)
    m=rng.normal(loc=15,scale=2,size=(96,512)).astype('float32')
    if signal:
        for ti in range(m.shape[0]):
            ch=220+int(round(9*ti/(m.shape[0]-1)))
            m[ti,ch]+=25
    return m


def main():
    ap=argparse.ArgumentParser(description='Magnexis SIGNALWATCH radio candidate scanner')
    ap.add_argument('file',nargs='?',help='2D .npy/.npz, or blimpy .fil/.h5 file')
    ap.add_argument('--demo',action='store_true',help='validate detector on a SYNTHETIC test signal')
    ap.add_argument('--off',help='optional off-target control of same frequency-bin layout')
    args=ap.parse_args()
    if not args.demo and not args.file:ap.error('provide a radio file or --demo')
    x=demo_power() if args.demo else load_spectrogram(args.file)
    off=load_spectrogram(args.off) if args.off else None
    print(json.dumps({'data_origin':'synthetic demonstration' if args.demo else args.file,
                      'matrix_shape':list(x.shape),
                      'candidates':scan_matrix(x,off_target=off)},indent=2))

if __name__=='__main__':main()
