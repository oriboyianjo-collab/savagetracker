"""Local-only diagnostic projection. Never reads response bodies or makes requests.

Output is public-safe metadata, not raw diagnostics or source-restoration evidence.
Unknown/missing data stays unknown. The original transport state is never changed.
"""
import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit


def official_url(value):
    if not isinstance(value, str) or len(value) > 500:
        return None
    try:
        u = urlsplit(value)
        if u.scheme != 'https' or u.netloc not in {'www.sec.gov', 'data.sec.gov'} or u.query or u.fragment:
            return None
        patterns = (r'/Archives/edgar/data/\d{1,10}/\d{18}/[A-Za-z0-9][A-Za-z0-9_.-]*\.html?',
                    r'/submissions/CIK\d{10}(?:-submissions-\d+)?\.json', r'/files/company_tickers\.json')
        if any(re.fullmatch(p, u.path) for p in patterns):
            return value
    except ValueError:
        pass
    return None


def timestamp(value):
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        d = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if d.tzinfo is not None:
            return d.astimezone(timezone.utc).isoformat()
    except ValueError:
        pass
    return None


def category(record):
    status = record.get('status')
    reason = record.get('reason', '')
    if type(status) is int:
        if 300 <= status < 400:
            return 'redirect_refused'
        if status in {403, 429}:
            return 'http_' + str(status)
    # Match only prefixes written by our transport, never reproduce free text.
    if isinstance(reason, str):
        for prefix, code in [('redirect not followed;', 'redirect_refused'),
                             ('network failure;', 'network_failure'),
                             ('body safety check failed;', 'body_safety_check_failed'),
                             ('non-200 status;', 'non_200_status'),
                             ('HTTP failure;', 'http_failure')]:
            if reason.startswith(prefix):
                return code
    return 'unknown'


def project(record):
    status = record.get('status')
    return {'url': official_url(record.get('url')),
            'status': status if type(status) is int and 100 <= status <= 599 else None,
            'category': category(record),
            'timestamp': timestamp(record.get('stopped_at', record.get('ts')))}


def read_object(path):
    try:
        value = json.loads(Path(path).read_text())
        return value if isinstance(value, dict) else {}
    except (FileNotFoundError, ValueError):
        return {}


def create(state, log, control, output):
    out = Path(output)
    out.mkdir(parents=True, exist_ok=True)
    original = Path(state) / 'transport-stopped.json'
    stop = read_object(original)
    ctrl = read_object(control)
    diagnostic = {'schema_version': 1, 'source_stop_record_present': bool(stop),
                  'controller_stopped': ctrl.get('stopped') is True,
                  'access_held': ctrl.get('stopped') is True and ctrl.get('stop_code') == 'access_held',
                  'stop': project(stop) if stop else None,
                  'raw_response_retained': False}
    (out / 'stop-metadata.json').write_text(json.dumps(diagnostic, sort_keys=True, indent=2) + '\n')
    events = []
    allowed = {'cache_hit', 'http_error', 'network_error', 'response', 'stopped'}
    try:
        with Path(log).open() as fh:
            for line in fh:
                try:
                    x = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(x, dict) or x.get('component') != 'transport' or x.get('event') not in allowed:
                    continue
                rec = project(x)
                rec['event'] = x['event']
                # Successful responses are not failure categories.
                if x['event'] not in {'stopped', 'http_error', 'network_error'}:
                    rec.pop('category')
                elif x['event'] == 'network_error':
                    rec['category'] = 'network_failure'
                events.append(rec)
    except FileNotFoundError:
        pass
    (out / 'transport-events.jsonl').write_text(''.join(json.dumps(x, sort_keys=True) + '\n' for x in events))
    state_text = 'protective access stop' if diagnostic['access_held'] else 'stopped' if diagnostic['controller_stopped'] else 'not stopped'
    summary = 'Connector state: ' + state_text + '. Diagnostic category: ' + (diagnostic['stop']['category'] if stop else 'unknown (no retained stop record)') + '.'
    print(summary)
    if diagnostic['controller_stopped'] or stop:
        print('::warning title=Connector stopped::' + summary)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as fh:
            fh.write(summary + '\n')
    return diagnostic


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ['state', 'log', 'control', 'output']:
        p.add_argument('--' + name, required=True)
    a = p.parse_args()
    create(a.state, a.log, a.control, a.output)
