"""Hash-addressed small resume rows. The browser never fetches these files."""
import argparse,hashlib,json,re
from pathlib import Path
try:
    from .publication import atomic,INVENTORY_SHA
except ImportError:
    from publication import atomic,INVENTORY_SHA
try:
    from .resume_state import sanitized
except ImportError:
    from resume_state import sanitized

def dehydrate(result,directory):
    safe=sanitized(result);directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    rows=safe.pop('rows');checkpoints=safe.pop('checkpoints',{})
    manifest={**safe,'row_files':{}}
    for row in rows:
        sym=row['symbol']
        if not re.fullmatch(r'[A-Z0-9][A-Z0-9.\-]{0,31}',sym):raise ValueError('unsafe resume symbol')
        payload={'row':row}
        if sym in checkpoints:payload['checkpoint']=checkpoints[sym]
        raw=(json.dumps(payload,sort_keys=True,separators=(',',':'))+'\n').encode()
        if len(raw)>2000000:raise ValueError('resume row/checkpoint size cap exceeded')
        h=hashlib.sha256(raw).hexdigest();path=directory/(sym+'.'+h+'.json')
        if path.exists():
            if path.read_bytes()!=raw:raise ValueError('immutable resume hash mismatch')
        else:path.write_bytes(raw)
        manifest['row_files'][sym]=h
    keep={sym+'.'+h+'.json' for sym,h in manifest['row_files'].items()}
    for stale in directory.glob('*.json'):
        if stale.name not in keep:stale.unlink()
    return manifest

def hydrate(manifest,directory):
    if manifest.get('schema_version')!=1 or manifest.get('inventory_sha256')!=INVENTORY_SHA or not isinstance(manifest.get('row_files'),dict)or len(manifest['row_files'])!=6315:raise ValueError('wrong resume manifest')
    out={k:v for k,v in manifest.items()if k!='row_files'};out['rows']=[];out['checkpoints']={}
    for sym,h in manifest['row_files'].items():
        if not re.fullmatch(r'[A-Z0-9][A-Z0-9.\-]{0,31}',sym)or not re.fullmatch(r'[0-9a-f]{64}',h):raise ValueError('unsafe resume shard reference')
        raw=Path(directory,sym+'.'+h+'.json').read_bytes()
        if hashlib.sha256(raw).hexdigest()!=h:raise ValueError('resume shard hash mismatch')
        p=json.loads(raw)
        if not isinstance(p,dict)or set(p)-{'row','checkpoint'}or p['row'].get('symbol')!=sym:raise ValueError('resume shard identity mismatch')
        out['rows'].append(p['row'])
        if 'checkpoint'in p:out['checkpoints'][sym]=p['checkpoint']
    out['rows'].sort(key=lambda x:x['rank'])
    return out

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--directory',required=True);p.add_argument('--output',required=True);p.add_argument('--hydrate',action='store_true');a=p.parse_args();x=json.loads(Path(a.input).read_text());atomic(a.output,hydrate(x,a.directory)if a.hydrate else dehydrate(x,a.directory))
