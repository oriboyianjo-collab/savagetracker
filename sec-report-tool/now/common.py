"""NOW-only local helpers. No network or ISRG imports."""
import copy
import hashlib
import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit


def digest(b): return hashlib.sha256(b).hexdigest()


def atomic(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(value,sort_keys=True,indent=2)+'\n')
    os.replace(tmp,path)


def sec_url(u):
    p=urlsplit(u)
    if p.scheme!='https' or p.username or p.password or p.query or p.fragment or p.port not in {None,443}:
        raise ValueError('official SEC HTTPS URL required')
    submissions=p.hostname=='data.sec.gov' and re.fullmatch(r'/submissions/CIK0001373715(?:-submissions-\d+)?\.json',p.path)
    document=p.hostname=='www.sec.gov' and re.fullmatch(r'/Archives/edgar/data/1373715/0001373715\d{8}/[A-Za-z0-9_.-]+\.html?',p.path)
    if not (submissions or document): raise ValueError('wrong NOW issuer/route')
    return u


class AccessHeld(RuntimeError): pass


def body_excerpt(raw,limit=400):
    if not raw:return ''
    return ' '.join(re.sub(r'<[^>]+>',' ',raw[:4096].decode('utf-8','replace')).split())[:limit]
