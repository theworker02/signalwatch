"""NASA Exoplanet Archive catalog monitor. Catalog changes are NOT discoveries by SIGNALWATCH."""
from datetime import datetime, timezone
from .db import utcnow

TAP_URL='https://exoplanetarchive.ipac.caltech.edu/TAP/sync'
# Published archive fields; bounded query; no API key required.
TAP_QUERY=("SELECT TOP 500 pl_name,hostname,disc_year,discoverymethod,disc_facility "
           "FROM ps WHERE default_flag=1 AND disc_year>=2025 ORDER BY disc_year DESC,pl_name ASC")


def process_catalog(store, rows):
    if not isinstance(rows,list):
        raise ValueError('Unexpected NASA Exoplanet Archive TAP response')
    if len(rows)>500:
        raise ValueError('Exoplanet catalog response exceeds bounded query')
    cleaned=[]
    for row in rows:
        if not isinstance(row,dict):continue
        name=str(row.get('pl_name') or '').strip()
        if not (1 <= len(name) <= 160):continue
        try:
            year=int(row.get('disc_year'))
        except (ValueError,TypeError):continue
        if not 2025<=year<=datetime.now(timezone.utc).year+1:continue
        cleaned.append({'name':name,'hostname':str(row.get('hostname') or '')[:160],
                        'disc_year':year,'discoverymethod':str(row.get('discoverymethod') or '')[:140],
                        'disc_facility':str(row.get('disc_facility') or '')[:160]})
    if rows and not cleaned:
        raise ValueError('No recognized planet entries in TAP response')
    return len(cleaned),store.store_exoplanet_catalog(cleaned)
