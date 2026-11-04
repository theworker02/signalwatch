"""v1.8 research integrity, API and catalog-regression coverage."""
import hashlib
import importlib
import json
from datetime import datetime, timezone, timedelta

import numpy as np
import pytest
from fastapi.testclient import TestClient

from signalwatch.db import Store
from signalwatch.exoplanets import process_catalog
from signalwatch.research import (build_evidence_bundle, matching_solar_observations,
                                  parse_utc, triage)
from signalwatch.radio import demo_power, analyze_file


def iso(seconds=0):
    return (datetime.now(timezone.utc)+timedelta(seconds=seconds)).isoformat()


def solar_event(id,station,offset=0,**kwargs):
    metadata={'source_station':station,'observation_timestamp_basis':'unverified_instrument_header'}
    metadata.update(kwargs)
    return {'id':id,'source':'e-Callisto solar radio','kind':'solar_radio_transient',
            'observed_at':iso(offset),'severity':'medium','metadata':metadata,'score':70}


def insert(store,source='e-Callisto solar radio',source_id='1',**kwargs):
    return store.put_event(source=source,source_id=source_id,
                           kind=kwargs.get('kind','solar_radio_transient'),
                           title=kwargs.get('title','Unverified candidate'),
                           observed_at=kwargs.get('observed_at',iso()),score=kwargs.get('score',80),
                           severity=kwargs.get('severity','medium'),
                           summary='Scientific follow-up required',metadata=kwargs.get('metadata',{}))


def test_cross_station_timing_hint_requires_distinct_sources():
    a=solar_event(1,'ALGERIA-CRAAG')
    b=solar_event(2,'GERMANY-DLR',offset=80)
    results=matching_solar_observations(a,[a,b,solar_event(3,'ALGERIA-CRAAG',100),
                                             solar_event(4,'JAPAN',500)])
    assert len(results)==1
    assert results[0]['station']=='GERMANY-DLR'
    assert results[0]['assessment']=='independent_station_timing_hint_only'
    assert results[0]['frequency_comparison']=='frequency_not_comparable'


def test_cross_station_requires_real_clock_and_frequencies():
    a=solar_event(1,'ALGERIA',frequency_axis_calibrated=True,frequency_axis_mhz=[100,110,120])
    b=solar_event(2,'GERMANY',offset=90,frequency_axis_calibrated=True,
                  frequency_axis_mhz=[150,160,170])
    assert matching_solar_observations(a,[b])==[]
    b['metadata']['frequency_axis_mhz']=[118,125]
    assert matching_solar_observations(a,[b])[0]['frequency_comparison'].startswith('frequency_ranges_overlap')
    a['metadata']['observation_timestamp_basis']='analysis_time'
    assert matching_solar_observations(a,[b])==[]
    a['metadata']['observation_timestamp_basis']='unverified_instrument_header'
    a['observed_at']='2026-Nov-04 12:00'
    assert matching_solar_observations(a,[b])==[]
    assert parse_utc('2026-11-04T12:00:00') is None


def test_cross_station_never_applies_to_seti_or_synthetic():
    a=solar_event(1,'A')
    b=solar_event(2,'B')
    a['source']='SETI radio'
    assert matching_solar_observations(a,[b])==[]
    a['source']='e-Callisto solar radio';a['severity']='test'
    assert matching_solar_observations(a,[b])==[]


def test_checksum_evidence_bundle_is_reproducible():
    event=solar_event(1,'A')
    detail=build_evidence_bundle(event,[],[],[])
    checksum=detail.pop('content_sha256')
    canonical=json.dumps(detail,sort_keys=True,separators=(',', ':'),ensure_ascii=False,allow_nan=False)
    assert checksum==hashlib.sha256(canonical.encode()).hexdigest()
    assert detail['triage']['probability_of_ETI'] is None
    assert 'solar_pointing_not_SETI' in detail['triage']['triage_issues']


def test_review_audit_trail_alerts_and_changes(tmp_path):
    db=Store(tmp_path/'research.sqlite')
    assert insert(db,source_id='1',score=82,metadata={'source_station':'A'})
    assert insert(db,source_id='2',severity='test',score=95)
    assert insert(db,source_id='3',source='SatNOGS',kind='satellite_reception',
                  severity='observation',score=90)
    events=db.event_changes(0)
    assert [e['id'] for e in events]==sorted(e['id'] for e in events)
    assert len(db.event_changes(events[-1]['id']))==0
    alert=db.alerts()
    assert len(alert)==1 and alert[0]['source_id']=='1'
    event_id=alert[0]['id']
    assert db.review_event(event_id,'investigating','Compare station timelines')
    assert db.review_event(event_id,'needs_followup','Obtain independent pointing')
    assert [h['state'] for h in db.review_history(event_id)]==['investigating','needs_followup']
    assert db.event_by_id(event_id)['review_note']=='Obtain independent pointing'
    assert db.review_event(event_id,'closed','No new activity')
    assert db.alerts()==[]


def test_catalog_initial_snapshot_and_subsequent_new_to_local_db(tmp_path):
    db=Store(tmp_path/'catalog.sqlite')
    a={'pl_name':'Test Known A b','hostname':'A','disc_year':2026,
       'discoverymethod':'Transit','disc_facility':'TESS'}
    b={'pl_name':'Test Known B b','hostname':'B','disc_year':2026,
       'discoverymethod':'Radial Velocity','disc_facility':'Ground'}
    assert process_catalog(db,[a])==(1,0)  # baseline, not a new discovery
    assert process_catalog(db,[a,b])==(2,1)  # observed first time by this local monitor
    assert process_catalog(db,[a,b])==(2,0)
    assert {v['name'] for v in db.get_exoplanets()}=={'Test Known A b','Test Known B b'}
    assert db.events_count()['total']==0


def test_catalog_invalid_rows_are_not_ingested(tmp_path):
    db=Store(tmp_path/'db.sqlite')
    with pytest.raises(ValueError):process_catalog(db,{'bad':'api error'})
    with pytest.raises(ValueError):process_catalog(db,[{'planet':'unknown'}])
    assert db.get_exoplanets()==[]


def test_api_detail_evidence_review_auth_and_alerts(tmp_path,monkeypatch):
    monkeypatch.setenv('SIGNALWATCH_DATA_DIR',str(tmp_path))
    monkeypatch.setenv('SIGNALWATCH_BACKGROUND','0')
    monkeypatch.setenv('SIGNALWATCH_WRITE_TOKEN','temporary-test-token')
    import signalwatch.app as m
    importlib.reload(m)
    insert(m.DB,source_id='a',metadata={'source_station':'ALGERIA'},score=88)
    insert(m.DB,source_id='b',metadata={'source_station':'GERMANY'},observed_at=iso(40),score=83)
    with TestClient(m.app) as client:
        events=client.get('/api/events').json()
        assert len(events)==2
        a=next(x for x in events if x['source_id']=='a')
        detail=client.get('/api/events/'+str(a['id'])).json()
        assert len(detail['cross_station_timing_hints'])==1
        assert 'cross_station_timing_not_physical_confirmation' in detail['triage']['triage_issues']
        assert len(client.get('/api/alerts').json())==2
        evidence=client.get(f"/api/events/{a['id']}/evidence.json")
        assert evidence.status_code==200
        assert evidence.json()['content_sha256']
        denied=client.patch(f"/api/events/{a['id']}/review",json={'state':'investigating'})
        assert denied.status_code==401
        allowed=client.patch(f"/api/events/{a['id']}/review",json={'state':'closed','note':'Investigated'},
                             headers={'x-signalwatch-token':'temporary-test-token'})
        assert allowed.status_code==200
        assert client.get('/api/events/'+str(a['id'])).json()['review_history'][0]['note']=='Investigated'
        assert len(client.get('/api/alerts').json())==1
        assert client.post('/api/poll').status_code==401
        assert client.get('/api/exoplanets').json()['category']=='known_cataloged_objects_not_new_discoveries'
        assert client.get('/api/events/changes?after_id=99999').json()['events']==[]
        assert client.get('/api/telemetry').json()['source_freshness_is_not_a_live_radio_stream']


def test_radio_provenance_hash_of_small_file(tmp_path):
    db=Store(tmp_path/'db.sqlite')
    p=tmp_path/'observations.npz'
    np.savez_compressed(p,power=demo_power(),
                        start_frequency_mhz=1000.0,channel_width_hz=500.0,
                        observation_start_utc=iso())
    result=analyze_file(db,p)
    assert result['status']=='ok'
    record=db.recent_events(source='SETI radio')[0]
    assert record['metadata']['file_sha256']==hashlib.sha256(p.read_bytes()).hexdigest()
    assert record['metadata']['file_sha256_note']=='full_file_digest'


def test_optional_real_fits_decoder_with_astropy(tmp_path):
    fits=pytest.importorskip('astropy.io.fits')
    from signalwatch.solar import load_callisto_fits
    p=tmp_path/'SYNTHETIC_SOLAR.fit'
    hdu=fits.PrimaryHDU(data=np.ones((64,80),dtype=np.float32))
    hdu.header['DATE-OBS']='2026-11-04'
    hdu.header['TIME-OBS']='12:00:00'
    hdu.header['CDELT1']=0.5
    fits.HDUList([hdu]).writeto(p)
    power,meta=load_callisto_fits(p)
    assert power.shape==(80,64)
    assert meta['observation_target']=='Sun'
    assert meta['integration_seconds']==0.5
    assert meta['observation_start_utc'].startswith('2026-11-04T12:00:00')

@pytest.mark.asyncio
async def test_callisto_midnight_utc_previous_day_bounded(monkeypatch,tmp_path):
    import gzip
    import httpx
    from signalwatch.callisto_feed import download_recent
    clock=datetime(2026,11,5,0,20,tzinfo=timezone.utc)
    today='JAPAN_20261105_001000_59.fit.gz'
    yesterday='ALGERIA-CRAAG_20261104_235000_59.fit.gz'
    requests=[]
    sample=gzip.compress(b'SIMPLE  = '+b' '*1024)
    def mock(request):
        path=request.url.path
        requests.append(path)
        if path.endswith('/'):
            name=today if '/05/' in path else yesterday
            html=f'<h1>Index of /2002-20yy_Callisto/</h1><a href="{name}">{name}</a>'
            return httpx.Response(200,text=html)
        return httpx.Response(200,content=sample)
    async with httpx.AsyncClient(transport=httpx.MockTransport(mock)) as client:
        result=await download_recent(client,Store(tmp_path/'db'),tmp_path/'auto',now=clock)
    assert result['seen']==2
    assert set(result['downloaded'])=={today.replace('.gz',''),yesterday.replace('.gz','')}
    assert len(requests)==4  # 2 daily listings + 2 bounded files
    assert len(result['archive_urls_checked'])==2
