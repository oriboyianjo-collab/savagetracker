"""Content-addressed per-symbol report shards. Manifest stays small; no web requests."""
import argparse,hashlib,json,re
from pathlib import Path
try:
    from .publication import atomic,INVENTORY_SHA,validate_symbol
except ImportError:
    from publication import atomic,INVENTORY_SHA,validate_symbol

def emit(index,directory):
    if index.get('schema_version')!=1 or index.get('inventory_sha256')!=INVENTORY_SHA:raise ValueError('wrong index scope')
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    manifest={k:index[k]for k in ['schema_version','inventory_sha256','as_of']};manifest['symbols']={}
    for sym,row in index['symbols'].items():
        if not re.fullmatch(r'[A-Z0-9][A-Z0-9.\-]{0,31}',sym):raise ValueError('unsafe shard symbol')
        clean=validate_symbol(row,index['as_of'])
        shard={k:index[k]for k in ['schema_version','inventory_sha256','as_of']};shard['symbols']={sym:clean}
        raw=(json.dumps(shard,sort_keys=True,separators=(',',':'))+'\n').encode()
        if len(raw)>512000:raise ValueError('report shard exceeds mobile budget')
        h=hashlib.sha256(raw).hexdigest();name=sym+'.'+h+'.json';p=directory/name
        if p.exists():
            if p.read_bytes()!=raw:raise ValueError('immutable shard hash collision')
        else:p.write_bytes(raw)
        manifest['symbols'][sym]={'cik':row['cik'],'sha256':h}
    keep={sym+'.'+meta['sha256']+'.json' for sym,meta in manifest['symbols'].items()}
    for stale in directory.glob('*.json'):
        if stale.name not in keep:stale.unlink()
    return manifest

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--index',required=True);p.add_argument('--directory',required=True);p.add_argument('--manifest',required=True);a=p.parse_args();atomic(a.manifest,emit(json.loads(Path(a.index).read_text()),a.directory))
