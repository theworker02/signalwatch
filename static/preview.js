/* Clearly identified synthetic UI showcase; never persisted, downloaded or mixed with scientific evidence. */
(function () {
  const start = Date.parse('2026-11-04T18:00:00Z');
  const iso = (mins) => new Date(start + mins * 60_000).toISOString();
  const feedNames = [
    ['NOAA GOES X-ray', 'https://services.swpc.noaa.gov/'],
    ['NOAA Kp', 'https://services.swpc.noaa.gov/'],
    ['NOAA solar radio', 'https://services.swpc.noaa.gov/'],
    ['e-Callisto upload index', 'https://www.e-callisto.org/'],
    ['e-Callisto raw FITS', 'https://soleil.i4ds.ch/'],
    ['NASA JPL', 'https://ssd-api.jpl.nasa.gov/'],
    ['SatNOGS', 'https://network.satnogs.org/'],
    ['NASA Exoplanet Archive', 'https://exoplanetarchive.ipac.caltech.edu/'],
    ['SETI radio inbox', 'Local file watcher']
  ];
  const sources = feedNames.map(([name, url], idx) => ({
    name, url, status: idx < 7 ? 'ok' : 'pending',
    last_success: idx < 7 ? iso(-idx * 10) : null,
    records_seen: [120, 34, 24, 16, 2, 33, 52, 0, 0][idx],
    seconds_since_success: idx < 7 ? idx * 120 : null,
    stale: idx >= 7, last_error: null
  }));
  const events = [
    { id: 90001, source: 'e-Callisto solar radio', kind: 'solar_radio_candidate', title: 'Broadband radio intensity enhancement', summary: 'Simulated multi-channel transient near the midpoint of a test recording. Requires instrument-level follow-up.', observed_at: iso(-32), score: 83, severity:'high', review_state:'new', review_note:'', evidence_url: '' },
    { id: 90002, source: 'NOAA GOES', kind:'solar_flare', title:'Elevated X-ray flux interval', summary:'Illustrative space-weather alert; flux values are synthetic for interface demonstration.', observed_at: iso(-55), score:68, severity:'medium', review_state:'investigating', review_note:'Example review note', evidence_url:'' },
    { id: 90003, source:'SETI radio', kind:'radio_candidate', title:'Linear narrowband drift template match', summary:'Demonstration-only candidate generated from synthetic power spectrogram; not a real observation.', observed_at:iso(-91), score:79, severity:'medium', review_state:'needs_followup', review_note:'', evidence_url:'' },
    { id:90004, source:'NASA JPL', kind:'asteroid_close_approach', title:'Catalogued near-Earth object update', summary:'Example of a previously catalogued asteroid trajectory record, not an impact prediction.', observed_at:iso(-150), score:19,severity:'observation',review_state:'new',review_note:'',evidence_url:'' },
    { id:90005, source:'SatNOGS',kind:'satellite_observation',title:'Satellite reception log',summary:'Example reception metadata from a community ground station.',observed_at:iso(-195),score:12,severity:'observation',review_state:'new',review_note:'',evidence_url:'' }
  ];
  const samples = Array.from({length:110},(_,i) => ({
    observed_at: iso(-110 + i),
    metric: 2.4e-7 + 1.2e-7 * (1 + Math.sin(i * 0.16)) + (i > 47 && i < 65 ? 2.3e-6 * Math.exp(-Math.pow((i - 56) / 7, 2)) : 0) + (i>85&&i<103 ? 7e-7 * Math.exp(-Math.pow((i-93)/8,2)):0)
  }));
  const observations = [{station:'BLEIEN',observed_at:iso(-15),filename:'BLEIEN_20261104_174500_59.fit.gz',size_bytes:87234}, {station:'ALASKA',observed_at:iso(-30),filename:'ALASKA_20261104_173000_59.fit.gz',size_bytes:103442}];
  const planets = {records:[{name:'Kepler-186 f',hostname:'Kepler-186',disc_year:2014,discoverymethod:'Transit',disc_facility:'Kepler'}, {name:'TRAPPIST-1 e',hostname:'TRAPPIST-1',disc_year:2017,discoverymethod:'Transit',disc_facility:'TRAPPIST'}]};
  window.SIGNALWATCH_PREVIEW = {
    get(path) {
      const url = new URL(path,"http://127.0.0.1"); const route=url.pathname;
      if(route==='/api/status') return {version:'1.8.1',counts:{total:247, radio_files_processed:14},last_cycle:iso(0),polling:false,callisto_autodownload:true,callisto_station:'AUTO'};
      if(route==='/api/sources') return sources;
      if(route==='/api/telemetry') return {feeds:sources,stale_count:2};
      if(route==='/api/events') {const source=url.searchParams.get('source');return source?events.filter(e=>e.source===source):events;}
      if(route==='/api/samples') return samples;
      if(route==='/api/radio/files') return [{state:'ok',candidate_count:1},{state:'ok',candidate_count:0}];
      if(route==='/api/radio/observations') return observations;
      if(route==='/api/alerts') return events.filter(e=>e.score>=60);
      if(route==='/api/exoplanets') return planets;
      if(/^\/api\/events\/\d+$/.test(route)) {
        const event=events.find(e=>e.id===Number(route.split('/').pop()));
        if(!event) throw Error('Preview record not found');
        return {event,review_history:[{state:'new',note:'Preview-only illustrative note',updated_at:iso(-60)}],cross_station_timing_hints:[],triage:{triage_issues:['synthetic_preview_not_real_evidence','independent_scientific_verification_required']}};
      }
      throw Error('Unavailable in preview');
    }
  };
})();
