"""Public-source adapters. All labels describe conventional phenomena, not SETI detections."""
from datetime import datetime, timedelta, timezone
from math import isfinite
import httpx
from .ecallisto import INDEX_URL, process_ecallisto_index

NOAA_XRAY = 'https://services.swpc.noaa.gov/json/goes/primary/xrays-6-hour.json'
NOAA_FLARES = 'https://services.swpc.noaa.gov/json/goes/primary/xray-flares-7-day.json'
NOAA_KP = 'https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json'
JPL_CAD = 'https://ssd-api.jpl.nasa.gov/cad.api'
SATNOGS = 'https://network.satnogs.org/api/observations/'
NOAA_RADIO = 'https://services.swpc.noaa.gov/json/solar-radio-flux.json'
LD_AU = 0.00256955529


def iso(s):
    if not s:
        return None
    # Accept ordinary ISO8601, UTC Z, naive NOAA TDB date remains unconverted.
    return str(s).replace(' ', 'T').replace('Z', '+00:00')


def recent(s, max_hours=192):
    try:
        dt = datetime.fromisoformat(iso(s))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc)-timedelta(hours=max_hours) <= dt <= datetime.now(timezone.utc)+timedelta(minutes=10)
    except (TypeError, ValueError):
        return False


def process_xrays(store, payload):
    if not isinstance(payload,list):
        raise ValueError('Unexpected NOAA X-ray schema')
    samples=[]
    for r in payload:
        if r.get('energy') not in ('0.1-0.8nm','0.1-0.8 nm'):
            continue
        try:
            v=float(r['flux']); t=r['time_tag']
            if v>0 and isfinite(v) and recent(t, 12):
                samples.append((t,v))
        except (ValueError,TypeError,KeyError):
            continue
    store.put_samples('NOAA GOES X-ray',samples,'W/m²')
    return len(samples), 0


def flare_value(clazz):
    if not clazz:
        return 0
    try:
        return 'ABCMX'.index(str(clazz)[0].upper()) * 10 + float(str(clazz)[1:])
    except (ValueError,IndexError):
        return 0


def process_flares(store, payload):
    if not isinstance(payload,list):
        raise ValueError('Unexpected NOAA flare schema')
    added=0; seen=0
    for r in payload:
        clazz=r.get('max_class') or r.get('current_class')
        when=r.get('max_time') or r.get('time_tag')
        if not recent(when) or not clazz:
            continue
        seen+=1
        level=str(clazz)[0].upper()
        if level not in ('C','M','X'):
            continue
        score={'C':35, 'M':65, 'X':90}[level]
        added+=store.put_event(source='NOAA GOES',source_id=f"{r.get('satellite')}:{when}:{clazz}",
          kind='solar_flare', title=f'{clazz} solar X-ray flare', observed_at=when,
          score=score,severity='high' if level=='X' else 'medium' if level=='M' else 'info',
          summary=f'Known solar flare classified {clazz}. A space-weather event, not an unexplained signal.',
          evidence_url='https://www.swpc.noaa.gov/products/goes-x-ray-flux',metadata=r)
    return seen, added


def process_kp(store, payload):
    if not isinstance(payload,list):
        raise ValueError('Unexpected NOAA Kp schema')
    seen=added=0; samples=[]
    for r in payload:
        try:
            when=r['time_tag']; kp=float(r['Kp'])
        except (KeyError,ValueError,TypeError):
            continue
        if not recent(when,192) or not isfinite(kp):
            continue
        seen+=1; samples.append((when,kp))
        if kp<5:
            continue
        added+=store.put_event(source='NOAA Kp',source_id=when,kind='geomagnetic_storm',
          title=f'Geomagnetic activity Kp {kp:.1f}',observed_at=when,
          score=min(99, max(55, kp*11)), severity='high' if kp>=7 else 'medium',
          summary='Elevated geomagnetic activity; expected space-weather phenomenon, not a technosignature.',
          evidence_url='https://www.swpc.noaa.gov/products/planetary-k-index',metadata=r)
    store.put_samples('NOAA Kp',samples,'Kp')
    return seen,added


def process_jpl(store, payload):
    if not isinstance(payload,dict) or not isinstance(payload.get('fields'),list):
        raise ValueError('Unexpected NASA JPL CAD schema')
    fields=payload['fields']; added=0; seen=0
    for raw in payload.get('data',[]) or []:
        r=dict(zip(fields,raw)); seen+=1
        try:
            dist=float(r['dist']); des=r['des']; when=r['cd']
        except (ValueError, TypeError, KeyError):
            continue
        lunar=dist/LD_AU
        # Highlight predicted approaches within two lunar distances only.
        if lunar>2: continue
        added+=store.put_event(source='NASA JPL',source_id=f"{des}:{when}",
          kind='close_approach',title=f'{des} · {lunar:.2f} lunar distances',
          observed_at=str(when), score=max(20,min(85,70-12*lunar)),severity='medium' if lunar<1 else 'info',
          summary='A predicted close approach of a cataloged object, not evidence of a new threat or unexplained object.',
          evidence_url=f'https://ssd.jpl.nasa.gov/tools/sbdb_lookup.html#/?sstr={str(des).replace(" ","%20")}',
          metadata=dict(r, lunar_distances=round(lunar,4)))
    return seen,added


def process_satnogs(store,payload):
    if isinstance(payload,dict):
        rows=payload.get('results',[])
    elif isinstance(payload,list):
        rows=payload
    else: raise ValueError('Unexpected SatNOGS observation schema')
    if not isinstance(rows,list):raise ValueError('Unexpected SatNOGS results')
    seen=added=0
    for r in rows[:80]:
        obs_id=r.get('id'); when=r.get('end') or r.get('start')
        if obs_id is None or not recent(when,48):continue
        seen+=1
        # Every satellite pass is normal; store as a non-alert observation for RF evidence.
        added+=store.put_event(source='SatNOGS',source_id=str(obs_id),kind='satellite_reception',
          title=f"Satellite reception · NORAD {r.get('norad_cat_id') or 'unknown'}",
          observed_at=when,score=0,severity='observation',
          summary=f"Ground station {r.get('station_name') or r.get('ground_station') or 'unknown'} received a satellite observation. Not a SETI candidate.",
          evidence_url=f'https://network.satnogs.org/observations/{obs_id}/',
          metadata={'observation_id':obs_id,'ground_station':r.get('station_name'),'norad_cat_id':r.get('norad_cat_id'),
          'transmitter_mode':r.get('transmitter_mode'),'status':r.get('status'),'waterfall':r.get('waterfall')})
    return seen,added


def process_solar_radio(store, payload):
    """Record actual solar RF activity, with conservative per-frequency outlier screening.

    This is ordinary solar emission, NOT a SETI technosignature signal. The NOAA
    JSON structure may evolve; fail explicitly instead of fabricating measurements.
    """
    from statistics import median
    if not isinstance(payload,list):
        raise ValueError('Unexpected NOAA solar radio schema')
    by_freq={}; count=0; added=0
    for record in payload:
        if not isinstance(record,dict):continue
        ts=next((record.get(k) for k in ('time_tag','time','timestamp','observed_at') if record.get(k)),None)
        freq=record.get('frequency',record.get('frequency_mhz'))
        val=next((record.get(k) for k in ('flux','observed_flux','flux_sfu','value') if record.get(k) is not None),None)
        try:
            frequency=float(str(freq).replace('MHz','').strip())
            flux=float(val)
            if not 10<=frequency<=20000 or not isfinite(flux) or flux<=0 or not recent(ts,168):continue
        except (ValueError,TypeError):continue
        by_freq.setdefault(frequency,[]).append((ts,flux))
        count+=1
    if not count and payload:
        raise ValueError('NOAA solar radio response contained no recent recognized measurements')
    for frequency, rows in by_freq.items():
        series=f'NOAA solar radio {frequency:g} MHz'
        store.put_samples(series,rows,'solar flux units (sfu)')
        if len(rows)<12:continue
        values=[x[1] for x in rows]
        base=median(values)
        mad=median(abs(v-base) for v in values)
        cutoff=base+max(8*1.4826*mad,base*2)
        for timestamp, flux in rows:
            if flux<cutoff:continue
            added+=store.put_event(source='NOAA solar radio',source_id=f'{frequency}:{timestamp}',
               kind='solar_radio_outlier',title=f'Solar radio flux spike · {frequency:g} MHz',
               observed_at=timestamp,score=55,severity='medium',
               summary='Statistical outlier in solar-radio measurements. Natural solar activity or measurement interference; NOT a SETI candidate.',
               evidence_url=NOAA_RADIO,
               metadata={'frequency_mhz':frequency,'flux_sfu':flux,'baseline_sfu':base,'threshold_sfu':cutoff,
                         'detector':'median+8*MAD, minimum 3x baseline, >=12 samples'})
    return count,added


FEEDS = [
 ('NOAA GOES X-ray',NOAA_XRAY,process_xrays,{}),
 ('NOAA solar flares',NOAA_FLARES,process_flares,{}),
 ('NOAA Kp',NOAA_KP,process_kp,{}),
 ('NOAA solar radio',NOAA_RADIO,process_solar_radio,{}),
 ('e-Callisto upload index',INDEX_URL,process_ecallisto_index,{}),
 ('NASA JPL',JPL_CAD,process_jpl,{'params':{'date-min':'now','date-max':'+30','dist-max':'5LD','limit':'300'}}),
 ('SatNOGS',SATNOGS,process_satnogs,{'params':{'page':1}}),
]


async def fetch_feed(client: httpx.AsyncClient, store, feed):
    name,url,parser,options=feed
    try:
        response=await client.get(url,**options)
        response.raise_for_status()
        if len(response.content)>6_000_000:
            raise ValueError('Feed exceeded 6MB safety limit')
        seen,added=parser(store,response.text if parser is process_ecallisto_index else response.json())
        store.source_status(name,url,status='ok',records_seen=seen,
                            new_events=0 if parser is process_ecallisto_index else added)
        return {'source':name,'ok':True,'seen':seen,'added':added}
    except Exception as exc:
        store.source_status(name,url,status='error',error=f'{type(exc).__name__}: {str(exc)[:220]}')
        return {'source':name,'ok':False,'error':str(exc)[:220]}
