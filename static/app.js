const $=s=>document.querySelector(s);
const safe=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const clock=()=>{$('#clock').textContent=new Date().toISOString().slice(11,19)+' UTC';}; clock();setInterval(clock,1000);
const fdate=s=>{if(!s)return 'Unknown time';if(/^\d{4}-[A-Za-z]{3}-\d{2}/.test(s))return s+' TDB'; const d=new Date(s);return Number.isNaN(d.valueOf())?s:d.toISOString().replace('T',' ').slice(0,16)+' UTC';};
let plotPoints=[]; let writeToken='';
async function get(url){let r=await fetch(url,{cache:'no-store'});if(!r.ok)throw Error(`${r.status} ${r.statusText}`);return r.json()}
async function refresh(){
 try{
  const [status,sources,events,samples,radio,observations,alerts,planets,telemetry]=await Promise.all([
  get('/api/status'),get('/api/sources'),get('/api/events?limit=125'+($('#filter').value?'&source='+encodeURIComponent($('#filter').value):'')),
  get('/api/samples?source=NOAA%20GOES%20X-ray&limit=360'),get('/api/radio/files'),get('/api/radio/observations?limit=16'),get('/api/alerts?min_score=60&limit=30'),get('/api/exoplanets?limit=20'),get('/api/telemetry')]);
  const n=status.counts;
  $('#m-events').textContent=n.total.toLocaleString();
  $('#m-alerts').textContent=alerts.length+(alerts.length===30?'+':'');
  $('#m-radio').textContent=n.radio_files_processed;
  $('#m-feeds').textContent=sources.filter(s=>s.status==='ok').length+' / '+(sources.length||6);
  $('#runtime').textContent=status.polling?'Polling live sources…':status.last_cycle?'Last completed '+fdate(status.last_cycle):'Waiting for first data cycle';
  renderEvents(events);renderSources(telemetry.feeds);renderSamples(samples);renderRadioObservations(observations,status,sources);renderAlerts(alerts);renderExoplanets(planets.records);
  const errors=radio.filter(r=>r.state==='error').length;
  $('#radio-status').textContent=radio.length?`${radio.filter(r=>r.state==='ok').length} processed · ${errors} errors · ${radio.reduce((n,r)=>n+r.candidate_count,0)} unverified candidate(s)`:'No local radio files have been processed.';
 }catch(e){$('#runtime').textContent='Cannot connect to local engine: '+e.message;}
}
function renderEvents(events){
 if(!events.length){$('#event-list').innerHTML='<div class="empty">No matching observations yet. This is not a synthetic event stream.</div>';return}
 const states=['new','investigating','likely_interference','needs_followup','closed'];
 $('#event-list').innerHTML=events.map(e=>`<div class="event"><div><div class="event-title">${safe(e.title)}</div><div class="event-desc">${safe(e.summary)}</div><div class="review-bar"><select class="review-state" aria-label="Review state for event ${e.id}" data-id="${e.id}">${states.map(s=>`<option ${e.review_state===s?'selected':''} value="${s}">${s.replaceAll('_',' ')}</option>`).join('')}</select><input class="review-note" aria-label="Review note for event ${e.id}" data-id="${e.id}" maxlength="2000" placeholder="Investigator note" value="${safe(e.review_note||'')}"><button class="save-review" data-id="${e.id}">Save</button><button class="inspect-event" data-id="${e.id}">Investigate</button><a href="/api/events/${e.id}/evidence.json" download="signalwatch-evidence-${e.id}.json" class="event-link">↓ Evidence JSON</a></div></div><div class="event-date">${safe(fdate(e.observed_at))}${e.evidence_url?`<a class="event-link" href="${safe(e.evidence_url)}" target="_blank" rel="noopener noreferrer">VIEW SOURCE ↗</a>`:''}</div><div><span title="Heuristic triage priority, not detection confidence" class="score ${safe(e.severity)}">${e.severity==='observation'?'LOG':Math.round(e.score)+'/100'}</span></div></div>`).join('');
}
$('#event-list').addEventListener('click',async ev=>{
 const inspect=ev.target.closest('.inspect-event'); if(inspect){await showResearch(inspect.dataset.id);return;}
 const btn=ev.target.closest('.save-review'); if(!btn)return;
 const id=btn.dataset.id;const card=btn.closest('.event'); const state=card.querySelector('.review-state').value;
 const note=card.querySelector('.review-note').value;btn.disabled=true;
 try{const r=await fetch(`/api/events/${id}/review`,{method:'PATCH',headers:{'Content-Type':'application/json',...(writeToken?{'x-signalwatch-token':writeToken}:{})},body:JSON.stringify({state,note})});
   if(r.status===401){writeToken=prompt('Enter configured SIGNALWATCH_WRITE_TOKEN (held in memory only)')||'';throw new Error('Token required. Retry save.')}if(!r.ok)throw new Error(await r.text());btn.textContent='Saved';}
 catch(e){btn.textContent='Error';console.error(e)}finally{setTimeout(()=>{btn.disabled=false;btn.textContent='Save'},1500)}
});

function renderSources(sources){
 if(!sources.length){$('#source-list').innerHTML='<div class="card empty">Sources have not started polling.</div>';return}
 $('#source-list').innerHTML=sources.map(s=>`<div class="card source-card"><div style="display:flex;justify-content:space-between;gap:10px"><div class="source-title">${safe(s.name)}</div><span class="status-pill ${safe(s.status)}">${safe(s.status).toUpperCase()}</span></div><div class="source-desc">${safe(s.url)}</div><div class="source-meta"><span>LAST SUCCESS: ${safe(s.last_success?fdate(s.last_success):'NONE')}</span><span>${s.records_seen} RECORDS · ${s.stale?'STALE/UNKNOWN':(s.seconds_since_success??'?')+'s OLD'}</span></div>${s.last_error?`<div class="error-detail">${safe(s.last_error)}</div>`:''}</div>`).join('');
}
function renderRadioObservations(observations,status,sources){
 const archive=sources.find(s=>s.name==='e-Callisto raw FITS');
 const index=sources.find(s=>s.name==='e-Callisto upload index');
 const downloading=status.callisto_autodownload?'Automatic FITS downloads ON':'Automatic FITS downloads OFF';
 $('#callisto-status').textContent=`${downloading} · Station: ${status.callisto_station||'unconfigured'} · Archive status: ${archive?.status||'pending'} · Upload index: ${index?.status||'pending'}`;
 if(!observations.length){$('#radio-observation-list').innerHTML='<div class="empty">No indexed station observations yet.</div>';return;}
 $('#radio-observation-list').innerHTML=observations.map(o=>`<div class="radio-observation"><strong>${safe(o.station)}</strong><span>${safe(fdate(o.observed_at))}</span><small>${safe(o.filename)} · ${Math.round((o.size_bytes||0)/1024)} KB · metadata only</small></div>`).join('');
}
function renderSamples(samples){
 plotPoints=samples.filter(s=>Number.isFinite(s.metric) && s.metric>0);
 $('#sample-count').textContent=plotPoints.length+' DATA POINTS';
 $('#chart-empty').style.display=plotPoints.length?'none':'flex';
 if(plotPoints.length){let last=plotPoints[plotPoints.length-1];$('#flux').textContent=last.metric.toExponential(2)+' W/m²';$('#flux-at').textContent=fdate(last.observed_at)}
 drawChart();
}
function drawChart(){
 const canvas=$('#chart'),rect=canvas.getBoundingClientRect(),dpr=window.devicePixelRatio||1;
 canvas.width=Math.max(100,Math.round(rect.width*dpr));canvas.height=Math.max(100,Math.round(rect.height*dpr));
 const c=canvas.getContext('2d');c.scale(dpr,dpr);let w=rect.width,h=rect.height,p={l:55,r:15,t:18,b:25};
 c.clearRect(0,0,w,h);c.font='10px monospace';
 const min=-8,max=-3; // log10 W/m²; GOES flare-scale range
 for(let i=0;i<=5;i++){let y=p.t+(h-p.t-p.b)*(i/5);c.strokeStyle='#26404b';c.setLineDash([4,5]);c.beginPath();c.moveTo(p.l,y);c.lineTo(w-p.r,y);c.stroke();c.setLineDash([]);c.fillStyle='#71929d';c.fillText('1e'+(-3-i),5,y+4)}
 if(plotPoints.length<2)return;
 c.beginPath();plotPoints.forEach((s,i)=>{let x=p.l+i/(plotPoints.length-1)*(w-p.l-p.r);let v=Math.log10(Math.max(s.metric,1e-9));let y=p.t+(max-v)/(max-min)*(h-p.t-p.b);y=Math.max(p.t,Math.min(h-p.b,y));i?c.lineTo(x,y):c.moveTo(x,y)});
 c.strokeStyle='#57e6c5';c.lineWidth=1.8;c.shadowColor='#33ecbb';c.shadowBlur=6;c.stroke();c.shadowBlur=0;
 c.fillStyle='#7893a0';c.fillText(fdate(plotPoints[0].observed_at).slice(5,16),p.l,h-5);let end=fdate(plotPoints[plotPoints.length-1].observed_at).slice(5,16);c.fillText(end,Math.max(p.l,w-p.r-110),h-5);
}
$('#poll').addEventListener('click',async()=>{$('#poll').disabled=true;$('#runtime').textContent='Requesting source refresh…';try{const r=await fetch('/api/poll',{method:'POST',headers:writeToken?{'x-signalwatch-token':writeToken}:{}});if(r.status===401){writeToken=prompt('Enter configured SIGNALWATCH_WRITE_TOKEN (held in memory only)')||'';throw Error('Token required. Retry refresh.')}if(!r.ok)throw Error(r.status+' '+r.statusText);await refresh()}catch(e){$('#runtime').textContent='Refresh failed: '+e.message}finally{$('#poll').disabled=false}});
function renderAlerts(rows){
 $('#alert-list').innerHTML=rows.length?rows.map(e=>`<div class="triage-row"><div><b>${safe(e.title)}</b><div class="helper">${safe(e.source)} · ${safe(fdate(e.observed_at))} · ${safe(e.review_state)}</div></div><div class="triage-actions"><span class="score ${safe(e.severity)}">${Math.round(e.score)}/100</span><button class="inspect-event" data-id="${e.id}">Investigate</button></div></div>`).join(''):'<div class="empty">No currently flagged observations above threshold. This does not mean a live SETI stream has been scanned.</div>';
}
$('#alert-list').addEventListener('click',async ev=>{const btn=ev.target.closest('.inspect-event');if(btn)await showResearch(btn.dataset.id)});
function renderExoplanets(rows){
 $('#exoplanet-list').innerHTML=rows.length?rows.map(e=>`<div class="radio-observation"><strong>${safe(e.name)}</strong><span>${safe(e.hostname)} · ${safe(e.disc_year)}</span><small>${safe(e.discoverymethod)} · ${safe(e.disc_facility)}</small></div>`).join(''):'<div class="empty">Catalog unavailable until the first successful NASA TAP fetch.</div>';
}
async function showResearch(id){
 try{
  const d=await get('/api/events/'+encodeURIComponent(id));
  const ev=d.event, flags=d.triage.triage_issues||[];
  $('#research-detail').innerHTML=`<h2>${safe(ev.title)}</h2><p>${safe(ev.summary)}</p><div class="research-grid"><div><label>Source</label><b>${safe(ev.source)}</b></div><div><label>Observed</label><b>${safe(fdate(ev.observed_at))}</b></div><div><label>Review</label><b>${safe(ev.review_state)}</b></div><div><label>Priority, not probability</label><b>${safe(ev.score)}/100</b></div></div><h3>Scientific caveats</h3><ul>${flags.map(f=>`<li>${safe(f.replaceAll('_',' '))}</li>`).join('')}</ul><h3>Other solar observing stations</h3>${d.cross_station_timing_hints.length?d.cross_station_timing_hints.map(h=>`<p>${safe(h.station)} · ${safe(h.time_difference_seconds)}s separation · ${safe(h.frequency_comparison)}</p>`).join(''):'<p>No independent station timing hints yet, or event is not a solar recording.</p>'}<h3>Review history</h3>${d.review_history.length?d.review_history.map(h=>`<p><b>${safe(h.state)}</b> · ${safe(h.updated_at)} · ${safe(h.note)}</p>`).join(''):'<p>No investigator reviews yet.</p>'}<a href="/api/events/${ev.id}/evidence.json" download>↓ Export self-checksummed evidence JSON</a><p class="helper">An anomaly is not a confirmed discovery. Confirm the instrument and exclude interference.</p>`;
  $('#research-modal').showModal();
 }catch(e){console.error(e)}
}
$('#close-research').addEventListener('click',()=>$('#research-modal').close());
$('#filter').addEventListener('change',refresh);window.addEventListener('resize',drawChart);
refresh();setInterval(refresh,15000);
