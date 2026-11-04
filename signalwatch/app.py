"""ASGI app + continuous observatory polling (single-worker local deployment)."""
import asyncio
import os
import csv
from datetime import datetime, timezone
import io
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path
import httpx
from fastapi import FastAPI, Query, HTTPException, Request
from pydantic import BaseModel, Field
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from . import __version__
from .db import Store, utcnow
from .radio import scan_inbox
from .callisto_feed import download_recent, ARCHIVE_BASE, prune_processed_cache
from .sources import FEEDS, fetch_feed
from .research import matching_solar_observations, build_evidence_bundle, triage, parse_utc

ROOT=Path(__file__).resolve().parent.parent
DATA=Path(os.environ.get('SIGNALWATCH_DATA_DIR',str(ROOT/'data'))).resolve()
DATA.mkdir(parents=True,exist_ok=True)
DB=Store(DATA/'signalwatch.sqlite3')
INBOX=DATA/'inbox'
POLL_INTERVAL=max(60,int(os.environ.get('SIGNALWATCH_POLL_SECONDS','300')))
POLL_ENABLED=os.environ.get('SIGNALWATCH_BACKGROUND','1')=='1'
LOCK=asyncio.Lock()
RADIO_LOCK=asyncio.Lock()
# Source-specific minimum retry periods. JPL explicitly requests non-repetitive, cached queries.
SOURCE_INTERVALS={'NASA JPL':21600,'SatNOGS':600,'NOAA solar flares':600,'NOAA solar radio':600,'e-Callisto upload index':900,'e-Callisto raw FITS':900,'NASA Exoplanet Archive':86400}
CALLISTO_STATION=os.environ.get('SIGNALWATCH_CALLISTO_STATION','AUTO')
CALLISTO_AUTO=os.environ.get('SIGNALWATCH_CALLISTO_DOWNLOAD','1')=='1'
WRITE_TOKEN=os.environ.get('SIGNALWATCH_WRITE_TOKEN','')
_next_due={}
_failure_count={}
state={'started_at':None,'last_cycle':None,'last_cycle_results':[],'polling':False,
       'background':POLL_ENABLED,'interval_seconds':POLL_INTERVAL,'next_due':{},
       'callisto_autodownload':CALLISTO_AUTO,'callisto_station':CALLISTO_STATION}

async def poll_once():
    if LOCK.locked():return {'busy':True}
    async with LOCK:
        state['polling']=True
        try:
            now=time.monotonic()
            due=[f for f in FEEDS if _next_due.get(f[0],0)<=now]
            if CALLISTO_AUTO and _next_due.get('e-Callisto raw FITS',0)<=now:
                due.append(('e-Callisto raw FITS',ARCHIVE_BASE,None,{}))
            if not due:
                return {'sources':[], 'skipped':'Sources are within their minimum polling interval',
                        'next_due':state['next_due']}
            # Sequential polling is deliberate: NASA JPL prohibits simultaneous API calls
            # and requests conservative polling and backoff.
            results=[]
            async with httpx.AsyncClient(timeout=14.0,headers={
                'User-Agent':'Magnexis-SIGNALWATCH/1.8.1 (+https://magnexis.org; scientific public-data monitor)',
                'Accept':'application/json'},follow_redirects=False) as client:
                for feed in due:
                    if feed[0]=='e-Callisto raw FITS':
                        try:
                            result=await download_recent(client,DB,INBOX / 'callisto_auto',station=CALLISTO_STATION)
                            DB.source_status(feed[0],result['archive_url'],status='ok',
                                records_seen=result['seen'],new_events=0)
                        except Exception as exc:
                            result={'source':feed[0],'ok':False,'error':str(exc)[:250]}
                            DB.source_status(feed[0],ARCHIVE_BASE,status='error',error=str(exc)[:250])
                    else:
                        result=await fetch_feed(client,DB,feed)
                    results.append(result)
                    name=feed[0]
                    if result['ok']:
                        _failure_count[name]=0
                    else:
                        _failure_count[name]=_failure_count.get(name,0)+1
                    minimum=max(POLL_INTERVAL,SOURCE_INTERVALS.get(name,60))
                    delay=min(7*86400, minimum*2**min(_failure_count[name],5))
                    _next_due[name]=time.monotonic()+delay
                    state['next_due'][name]=round(delay)
            state.update(last_cycle=utcnow(),last_cycle_results=results)
            return {'sources':results,'last_cycle':state['last_cycle']}
        finally:
            state['polling']=False

async def scan_radio_once():
    async with RADIO_LOCK:
        results=await asyncio.to_thread(scan_inbox,DB,INBOX)
        handled=[r for r in results if not r.get('skipped')]
        await asyncio.to_thread(prune_processed_cache,DB,INBOX/'callisto_auto')
        DB.source_status('SETI radio inbox',str(INBOX),status='ok',records_seen=len(results),
                         new_events=sum(r.get('candidates',0) for r in handled))
        return handled

async def radio_forever():
    while True:
        try:
            await scan_radio_once()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            DB.source_status('SETI radio inbox',str(INBOX),status='error',error=str(exc))
        await asyncio.sleep(20)

async def poll_forever():
    while True:
        try:
            await poll_once()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            state['last_cycle_results']=[{'source':'internal','error':str(exc)}]
        await asyncio.sleep(POLL_INTERVAL)

@asynccontextmanager
async def lifespan(app):
    state['started_at']=utcnow()
    _next_due.clear(); _failure_count.clear(); state['next_due']={}
    DB.source_status('SETI radio inbox',str(INBOX),status='pending')
    tasks=[asyncio.create_task(poll_forever()),asyncio.create_task(radio_forever())] if POLL_ENABLED else []
    try:yield
    finally:
        for task in tasks: task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):await task

app=FastAPI(title='Magnexis SIGNALWATCH',version=__version__,lifespan=lifespan,
    description='Experimental near-real-time observatory. No extraterrestrial detections claimed.')
app.mount('/static',StaticFiles(directory=str(ROOT/'static')),name='static')

@app.get('/')
def index():return FileResponse(ROOT/'static'/'index.html')

@app.get('/api/status')
def status():return {'version':__version__,**state,'counts':DB.events_count()}

@app.get('/api/sources')
def sources():return DB.get_sources()

@app.get('/api/events')
def events(limit:int=Query(100,ge=1,le=500), source:str|None=None,kind:str|None=None,
           review:str|None=None):
    rows=DB.recent_events(limit,source,kind)
    return [r for r in rows if r['review_state']==review] if review else rows

@app.get('/api/events/changes')
def event_changes(after_id:int=Query(0,ge=0),limit:int=Query(100,ge=1,le=500)):
    rows=DB.event_changes(after_id,limit)
    return {'events':rows,'next_cursor':rows[-1]['id'] if rows else after_id,
            'record_type':'observations_not_confirmed_anomalies'}

@app.get('/api/alerts')
def alerts(min_score:int=Query(60,ge=0,le=100),limit:int=Query(50,ge=1,le=200)):
    return DB.alerts(limit=limit,min_score=min_score)

@app.get('/api/exoplanets')
def exoplanets(limit:int=Query(100,ge=1,le=500)):
    return {'category':'known_cataloged_objects_not_new_discoveries',
            'records':DB.get_exoplanets(limit)}

@app.get('/api/telemetry')
def telemetry():
    feeds=DB.get_sources()
    now=datetime.now(timezone.utc)
    for feed in feeds:
        last=parse_utc(feed.get('last_success'))
        age=(now-last).total_seconds() if last else None
        expected=SOURCE_INTERVALS.get(feed['name'],POLL_INTERVAL)
        feed['seconds_since_success']=round(age) if age is not None else None
        feed['stale']=age is None or age>3*expected
    return {'server_time':utcnow(),'feeds':feeds,
            'stale_count':sum(bool(f['stale']) for f in feeds),
            'source_freshness_is_not_a_live_radio_stream':True}


def get_research_record(event_id):
    event=DB.event_by_id(event_id)
    if not event:raise HTTPException(404,'Event not found')
    matches=matching_solar_observations(event,DB.solar_candidate_window())
    return event,matches

@app.get('/api/events/{event_id}')
def event_detail(event_id:int):
    event,matches=get_research_record(event_id)
    return {'event':event,'review_history':DB.review_history(event_id),
            'cross_station_timing_hints':matches,'triage':triage(event,matches)}

@app.get('/api/events/{event_id}/evidence.json')
def event_evidence(event_id:int):
    event,matches=get_research_record(event_id)
    body=build_evidence_bundle(event,DB.review_history(event_id),matches,DB.get_sources())
    return JSONResponse(body,headers={'Content-Disposition':f'attachment; filename="signalwatch-evidence-{event_id}.json"',
                                      'Cache-Control':'no-store'})

class ReviewPayload(BaseModel):
    state: str
    note: str = Field(default='',max_length=2000)

def authorize_write(request:Request):
    # Local UI only: reject browser cross-origin mutations, with optional token
    # for command-line/API automation. Internet-facing deployments need auth proxy.
    origin=request.headers.get('origin')
    if origin and origin.rstrip('/') not in {'http://127.0.0.1:8765','http://localhost:8765'}:
        raise HTTPException(403,'Cross-origin write not permitted')
    if WRITE_TOKEN and request.headers.get('x-signalwatch-token') != WRITE_TOKEN:
        raise HTTPException(401,'Write token required')

@app.patch('/api/events/{event_id}/review')
def review(event_id:int,payload:ReviewPayload,request:Request):
    authorize_write(request)
    try:
        updated=DB.review_event(event_id,payload.state,payload.note)
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from exc
    if not updated: raise HTTPException(404,'Event not found')
    return {'ok':True,'event_id':event_id,'review_state':payload.state}

@app.get('/api/events.csv')
def events_csv(source:str|None=None):
    rows=DB.recent_events(limit=500,source=source)
    output=io.StringIO()
    writer=csv.writer(output)
    writer.writerow(['id','source','kind','observed_at','discovered_at','title',
                     'score','severity','review_state','review_note','evidence_url'])
    for e in rows:
        # Prefix spreadsheet formula characters to prevent CSV formula execution.
        def safe(v):
            value=str(v or '')
            return "'"+value if value.lstrip().startswith(('=','+','-','@')) else value
        writer.writerow([safe(e.get(k)) for k in ('id','source','kind','observed_at',
           'discovered_at','title','score','severity','review_state','review_note','evidence_url')])
    return StreamingResponse(iter([output.getvalue()]),media_type='text/csv',
          headers={'Content-Disposition':'attachment; filename="signalwatch-events.csv"'})

@app.get('/api/samples')
def samples(source:str='NOAA GOES X-ray',limit:int=Query(240,ge=5,le=1000)):
    return DB.get_samples(source,limit)

@app.get('/api/radio/observations')
def radio_observations(limit:int=Query(40,ge=1,le=200)):
    return DB.get_radio_observations(limit)

@app.get('/api/radio/files')
def radio_files():return DB.get_radio_files()

@app.post('/api/poll')
async def poll(request:Request):
    authorize_write(request)
    result=await poll_once()
    result['radio']=await scan_radio_once()
    return result

@app.get('/api/health')
def health():return {'status':'ok','time':utcnow(),'version':__version__,'note':'Service is reachable; does not certify data-source freshness'}
