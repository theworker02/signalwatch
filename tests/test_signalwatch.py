import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
import numpy as np
import httpx
import pytest
from signalwatch.db import Store
from signalwatch.radio import scan_matrix, demo_power, analyze_file
from signalwatch.sources import process_xrays, process_flares, process_kp, process_jpl, process_satnogs, process_solar_radio, fetch_feed


def now(hours=0):
    return (datetime.now(timezone.utc)+timedelta(hours=hours)).isoformat().replace('+00:00','Z')


def test_synthetic_drifting_tone_detected():
    result=scan_matrix(demo_power(seed=57))
    assert result
    assert any(r['drift_bins']>3 and r['classification']=='unverified_drifting_narrowband' for r in result)
    assert all('not evidence' in r['note'] for r in result)


def test_noise_does_not_trigger():
    assert scan_matrix(demo_power(signal=False))==[]


def test_off_target_marks_likely_interference():
    p=demo_power()
    result=scan_matrix(p,off_target=p)
    assert result and result[0]['classification']=='seen_off_target_likely_RFI'


def test_radio_file_and_dedupe(tmp_path):
    store=Store(tmp_path/'events.db')
    f=tmp_path/'test_synthetic.npz'
    np.savez_compressed(f,power=demo_power())
    first=analyze_file(store,f,source_name='SYNTHETIC TEST')
    second=analyze_file(store,f,source_name='SYNTHETIC TEST')
    assert first['status']=='ok' and first['candidates']>=1
    assert second['skipped']
    rows=store.recent_events()
    assert rows and all(r['metadata']['origin']=='SYNTHETIC TEST' for r in rows)


def test_noaa_and_jpl_parsers(tmp_path):
    store=Store(tmp_path/'db.sqlite')
    xrays=[{'time_tag':now(-.5),'energy':'0.1-0.8nm','flux':0.0000021},
           {'time_tag':now(-.5),'energy':'0.05-0.4nm','flux':0.000007}]
    assert process_xrays(store,xrays)==(1,0)
    assert len(store.get_samples('NOAA GOES X-ray'))==1
    flares=[{'time_tag':now(-.4),'max_time':now(-.4),'max_class':'M2.1','satellite':18},
            {'time_tag':now(-.3),'max_time':now(-.3),'max_class':'B9.9','satellite':18}]
    assert process_flares(store,flares)==(2,1)
    assert process_flares(store,flares)[1]==0
    kp=[{'time_tag':now(-3),'Kp':6.0},{'time_tag':now(-1),'Kp':2.0}]
    assert process_kp(store,kp)==(2,1)
    jpl={'fields':['des','cd','dist','v_rel'], 'data':[['2026 AA','2026-Nov-05 10:30','0.002', '11.1'],
       ['123','2026-Nov-06 08:20','0.012','18.0']]}
    assert process_jpl(store,jpl)==(2,1)
    sat={'count':1,'results':[{'id':123,'end':now(-.1),'norad_cat_id':'25544','station_name':'station 42'}]}
    assert process_satnogs(store,sat)==(1,1)
    assert any(x['source']=='SatNOGS' and x['severity']=='observation' for x in store.recent_events())
    assert store.events_count()['total']==4


@pytest.mark.asyncio
async def test_http_ingest_mocked_endpoint(tmp_path):
    store=Store(tmp_path/'db.sqlite')
    def handler(req):
        assert req.url.host=='example.org'
        return httpx.Response(200,json=[{'time_tag':now(-1),'Kp':7.0}])
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result=await fetch_feed(client,store,('NOAA Kp','https://example.org/kp',process_kp,{}))
    assert result['ok'] and result['added']==1
    assert store.get_sources()[0]['status']=='ok'


def test_http_endpoint_without_live_network(tmp_path,monkeypatch):
    monkeypatch.setenv('SIGNALWATCH_BACKGROUND','0')
    monkeypatch.setenv('SIGNALWATCH_DATA_DIR',str(tmp_path))
    # Reload module only after disabling background networking.
    import importlib
    import signalwatch.app as appmod
    importlib.reload(appmod)
    from fastapi.testclient import TestClient
    with TestClient(appmod.app) as client:
        assert client.get('/api/health').status_code==200
        assert client.get('/').status_code==200
        assert client.get('/api/status').json()['counts']['total']==0
        assert isinstance(client.get('/api/events').json(),list)
        assert client.get('/api/sources').status_code==200


def test_radio_monitor_detects_outlier_and_deduplicates(tmp_path):
    store=Store(tmp_path/'events.db')
    readings=[{'time_tag':now(-((i+1)*.1)),'frequency':245,'flux':30} for i in range(19)]
    readings.append({'time_tag':now(-.05),'frequency':245,'flux':300})
    assert process_solar_radio(store,readings)==(20,1)
    assert process_solar_radio(store,readings)==(20,0)
    item=store.recent_events(source='NOAA solar radio')[0]
    assert item['kind']=='solar_radio_outlier'
    assert 'NOT a SETI' in item['summary']


def test_event_review_and_filter(tmp_path):
    store=Store(tmp_path/'events.sqlite')
    assert not store.review_event(999,'new','none')
    assert store.put_event(source='SETI radio',source_id='abc',kind='radio_candidate',title='Test',
                           observed_at=now(),score=80,severity='medium',summary='Unverified')
    e=store.recent_events()[0]
    assert e['review_state']=='new'
    assert store.review_event(e['id'],'investigating','Check ON/OFF cadence')
    reviewed=store.recent_events(kind='radio_candidate')[0]
    assert reviewed['review_state']=='investigating'
    assert reviewed['review_note']=='Check ON/OFF cadence'
    assert store.recent_events(kind='solar_flare')==[]
    with pytest.raises(ValueError):store.review_event(e['id'],'confirmed_aliens','')


def test_npz_observation_timestamp_provenance(tmp_path):
    store=Store(tmp_path/'db.sqlite')
    obs=now(-24)
    p=tmp_path/'TESS_2026.npz'
    np.savez_compressed(p,power=demo_power(),observation_start_utc=obs,
        start_frequency_mhz=1400.0,channel_width_hz=1000.0,integration_seconds=1.0)
    result=analyze_file(store,p)
    assert result['status']=='ok'
    e=store.recent_events(source='SETI radio')[0]
    assert e['observed_at']==obs
    assert e['metadata']['observation_timestamp_basis']=='instrument'
    assert e['metadata']['drift_hz_per_second']>0


def test_review_http_and_csv(tmp_path,monkeypatch):
    monkeypatch.setenv('SIGNALWATCH_BACKGROUND','0')
    monkeypatch.setenv('SIGNALWATCH_DATA_DIR',str(tmp_path))
    import importlib
    import signalwatch.app as appmod
    importlib.reload(appmod)
    appmod.DB.put_event(source='SETI radio',source_id='test',kind='radio_candidate',title='=BAD()',
                        observed_at=now(),score=50,severity='info',summary='Local test')
    from fastapi.testclient import TestClient
    with TestClient(appmod.app) as client:
        eid=client.get('/api/events').json()[0]['id']
        assert client.patch(f'/api/events/{eid}/review',json={'state':'investigating','note':'Research notes'}).status_code==200
        assert client.get('/api/events').json()[0]['review_state']=='investigating'
        assert client.patch(f'/api/events/{eid}/review',headers={'origin':'https://bad.example'},json={'state':'closed'}).status_code==403
        r=client.get('/api/events.csv')
        assert r.status_code==200 and "'=BAD()" in r.text
        assert 'Research notes' in r.text


@pytest.mark.asyncio
async def test_poller_rate_limits_and_backoff(tmp_path,monkeypatch):
    import importlib
    import signalwatch.app as appmod
    monkeypatch.setenv('SIGNALWATCH_BACKGROUND','0')
    monkeypatch.setenv('SIGNALWATCH_DATA_DIR',str(tmp_path))
    importlib.reload(appmod)
    calls=[]
    async def mocked(client,db,feed):
        calls.append(feed[0]); return {'ok':True,'source':feed[0]}
    monkeypatch.setattr(appmod,'fetch_feed',mocked)
    await appmod.poll_once()
    first=len(calls)
    await appmod.poll_once()
    assert len(calls)==first
    assert appmod._next_due['NASA JPL']>appmod._next_due['NOAA Kp']

# v0.3: live-ish e-Callisto FITS archive, separated from SETI scoring.
from signalwatch.ecallisto import parse_index, process_ecallisto_index
from signalwatch.callisto_feed import parse_archive_listing, decompress_fits, download_recent, archive_url
from signalwatch.solar import scan_solar_bursts
import gzip


def test_sftp_upload_index_is_metadata_only_and_deduped(tmp_path):
    stamp='SFTP directory listing\n===\n' + (f'  760320  2026-11-04 16:14:53  GERMANY-DLR_20261104_150000_62.fit\n')
    observations=parse_index(stamp)
    assert len(observations)==1
    assert observations[0]['category']=='solar_radio_spectrum'
    assert 'metadata_only' in observations[0]['data_availability']
    store=Store(tmp_path/'db.sqlite3')
    assert process_ecallisto_index(store,stamp)==(1,1)
    assert process_ecallisto_index(store,stamp)==(1,0)
    assert store.get_radio_observations()[0]['station']=='GERMANY-DLR'
    assert store.recent_events()==[]


def test_sftp_rejects_non_fit_and_unrecognized_index():
    with pytest.raises(ValueError):parse_index('<html>Nothing public</html>')
    with pytest.raises(ValueError):parse_index('SFTP directory listing\n 32 2026-11-04 15:00:00 .bash_history')


def test_archive_listing_rejects_external_paths_and_wrong_date():
    timestamp=datetime(2026,11,4,16,15,tzinfo=timezone.utc)
    html='<h1>Index of /solarradio/data/2002-20yy_Callisto/2026/11/04</h1>\n' + '\n'.join([
        '<a href="ALGERIA-CRAAG_20261104_154500_59.fit.gz">NEW</a>',
        '<a href="ALGERIA-CRAAG_20261104_153000_59.fit.gz">OLD</a>',
        '<a href="https://evil.example/file.fit.gz">NO</a>',
        '<a href="../../ALGERIA-CRAAG_20261104_153000_59.fit.gz">NO</a>',
        '<a href="GERMANY-DLR_20261104_153000_59.fit.gz">OTHER</a>',
        '<a href="ALGERIA-CRAAG_20261105_153000_59.fit.gz">WRONG</a>',
        '<a href="ALGERIA-CRAAG_20261104_200000_59.fit.gz">FUTURE</a>'
    ])
    found=parse_archive_listing(html,date='20261104',station='ALGERIA-CRAAG',clock=timestamp)
    assert found==['ALGERIA-CRAAG_20261104_154500_59.fit.gz','ALGERIA-CRAAG_20261104_153000_59.fit.gz']


def test_gzip_fits_rejects_nonfits_bombs_and_bad_magic():
    with pytest.raises(ValueError):decompress_fits(gzip.compress(b'not-a-FITS'))
    sample=b'SIMPLE  = '+b' ' * 2048
    assert decompress_fits(gzip.compress(sample))==sample
    with pytest.raises(ValueError):decompress_fits(gzip.compress(sample)*27000)


@pytest.mark.asyncio
async def test_archive_fetch_with_mock_transport_no_external_requests(tmp_path):
    clock=datetime(2026,11,4,16,15,tzinfo=timezone.utc)
    name='ALGERIA-CRAAG_20261104_154500_59.fit.gz'
    html=f'<h1>Index of /solarradio/data/2002-20yy_Callisto/2026/11/04</h1><a href="{name}">{name}</a>'
    payload=gzip.compress(b'SIMPLE  = '+b' ' * 1024)
    requested=[]
    def handler(req):
        requested.append(str(req.url))
        assert req.url.host=='soleil.i4ds.ch'
        if req.url.path.endswith('/'):return httpx.Response(200,text=html)
        if req.url.path.endswith(name):return httpx.Response(200,content=payload)
        return httpx.Response(404)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        store=Store(tmp_path/'data.sqlite')
        first=await download_recent(client,store,tmp_path/'inbox',now=clock)
        assert first['downloaded']==[name.replace('.fit.gz','.fit')]
        assert first['data_category']=='solar_radio_not_SETI'
        second=await download_recent(client,store,tmp_path/'inbox',now=clock)
        assert second['downloaded']==[]
    assert len(requested)==3
    assert (tmp_path/'inbox'/name.replace('.fit.gz','.fit')).read_bytes().startswith(b'SIMPLE  =')


def test_solar_burst_detected_not_seti():
    rng=np.random.default_rng(195)
    power=rng.normal(15,1,(120,128)).astype('float32')
    power[45:61,20:105]+=20
    # Persistent strong transmitter should vanish under per-frequency baseline.
    power[:,5]+=80
    hits=scan_solar_bursts(power)
    assert hits and hits[0]['classification']=='unverified_broadband_solar_radio_transient'
    assert hits[0]['start_sample']<=46 and hits[0]['end_sample']>=60
    assert 'not evidence of extraterrestrial' in hits[0]['note']


def test_solar_noise_or_narrowband_rfi_not_broadband_event():
    rng=np.random.default_rng(195)
    noise=rng.normal(15,1,(120,128)).astype('float32')
    assert scan_solar_bursts(noise)==[]
    noise[:,15]+=90
    noise[45:70,18]+=75
    assert scan_solar_bursts(noise)==[]


def test_on_off_rejects_misaligned_shapes():
    p=demo_power()
    with pytest.raises(ValueError,match='identical matrix shapes'):
        scan_matrix(p,off_target=p[:,:-1])
