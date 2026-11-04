"""Scientific triage helpers: independent observations are hints, NOT confirmations."""
from datetime import datetime, timezone
from hashlib import sha256
import json


def parse_utc(value):
    try:
        dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if dt.tzinfo is None:
            return None  # Never assume the time scale of a scientific observation.
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def station(event):
    data = event.get('metadata') or {}
    name = data.get('source_station') or data.get('site')
    if name and str(name).strip().lower() not in ('unknown', 'none', 'n/a'):
        return str(name).strip()
    return None


def matching_solar_observations(subject, candidates, window_seconds=300):
    """Find independent-station, near-simultaneous solar candidate records.

    Temporal agreement alone is not radio-frequency or scientific corroboration.
    Only compare station-qualified, non-synthetic events with instrument/file clocks.
    """
    if subject.get('source') != 'e-Callisto solar radio' or subject.get('severity') == 'test':
        return []
    origin = station(subject)
    timestamp = parse_utc(subject.get('observed_at'))
    if not origin or not timestamp:
        return []
    if subject.get('metadata', {}).get('observation_timestamp_basis') == 'analysis_time':
        return []
    matches = []
    for event in candidates:
        if (event['id'] == subject['id'] or event.get('source') != 'e-Callisto solar radio'
                or event.get('severity') == 'test'):
            continue
        partner = station(event)
        other_time = parse_utc(event.get('observed_at'))
        if not partner or partner == origin or not other_time:
            continue
        if event.get('metadata', {}).get('observation_timestamp_basis') == 'analysis_time':
            continue
        distance = abs((timestamp-other_time).total_seconds())
        if distance > window_seconds:
            continue
        a = subject.get('metadata', {}).get('frequency_axis_mhz')
        b = event.get('metadata', {}).get('frequency_axis_mhz')
        # Frequency-axis overlap can be tested only if *both* are instrument calibrated.
        if (subject.get('metadata', {}).get('frequency_axis_calibrated')
                and event.get('metadata', {}).get('frequency_axis_calibrated')
                and isinstance(a, list) and isinstance(b, list) and a and b):
            lo=max(min(a),min(b)); hi=min(max(a),max(b))
            if lo>hi:
                continue
            frequency_status = 'frequency_ranges_overlap_not_event_match'
        else:
            frequency_status = 'frequency_not_comparable'
        matches.append({'event_id':event['id'], 'station':partner,
                        'time_difference_seconds':round(distance,2),
                        'frequency_comparison':frequency_status,
                        'assessment':'independent_station_timing_hint_only'})
    return sorted(matches, key=lambda hit: hit['time_difference_seconds'])[:20]


def triage(event, related=None):
    """Return explicit caveats instead of an ETI probability or black-box confidence."""
    related=related or []
    meta=event.get('metadata') or {}
    flags=list(meta.get('quality_flags') or [])
    issues=[]
    if event.get('severity') == 'test':
        issues.append('synthetic_or_test_input')
    if event.get('kind') == 'radio_candidate':
        if meta.get('classification') in ('seen_off_target_likely_RFI','possible_stationary_RFI'):
            issues.append('terrestrial_interference_likely')
        if meta.get('observation_timestamp_basis') != 'instrument':
            issues.append('missing_verified_instrument_timestamp')
        issues.append('independent_telescope_followup_not_completed')
    elif event.get('kind') == 'solar_radio_transient':
        issues.append('solar_pointing_not_SETI')
        issues.append('terrestrial_interference_not_excluded')
        if related:
            issues.append('cross_station_timing_not_physical_confirmation')
    return {'priority_score':event.get('score',0), 'probability_of_ETI':None,
            'quality_flags':flags, 'review_state':event.get('review_state','new'),
            'triage_issues':issues,
            'independent_station_time_matches':len(related),
            'recommendation':('Investigate instrument calibration and interference; seek independent repeat observation.'
                              if event.get('kind') in ('radio_candidate','solar_radio_transient')
                              else 'Interpret using the source observatory science context.')}


def build_evidence_bundle(event, history, correlations, sources):
    """Self-checksummed, canonical JSON evidence (not a digital signature)."""
    payload={'schema':'magnexis.signalwatch.evidence.v1',
             'subject':event,
             'review_history':history,
             'independent_station_timing_hints':correlations,
             'source_health_snapshot':next((s for s in sources if s['name']==event['source']),None),
             'triage':triage(event,correlations),
             'disclaimer':'Unverified observation. Checksum is for local integrity, not third-party attestation.'}
    canonical=json.dumps(payload,sort_keys=True,separators=(',', ':'),ensure_ascii=False,allow_nan=False)
    payload['content_sha256']=sha256(canonical.encode('utf-8')).hexdigest()
    return payload
