"""Unactivated transport implementation. Public get is intentionally hard-held.
No contact identity configured or retained. No alternate endpoint, retry or runtime.
"""
import json,hashlib,time,urllib.request,urllib.error
from pathlib import Path
from pipeline import AccessHeld,sec_url,atomic,digest
class LockedSecTransport:
 def __init__(self,cache,opener=None,clock=None,sleeper=None):
  self.cache=Path(cache);self._open=opener or urllib.request.urlopen;self.clock=clock or time.monotonic;self.sleep=sleeper or time.sleep;self.last=None;self.stopped=False
 def get(self,url):
  # Not a config flag. Removing this hold needs a separately authorized code stage,
  # genuine identity, and externally grounded recovery basis, not local caller booleans.
  raise AccessHeld('SEC live acquisition held; no request sent')
 def _implementation_under_test(self,url,declared_identity):
  """Private test entry; never wired into CLI/orchestrator. Tests inject local fake opener.
  Not owner authority and not a supported live-use entry point.
  """
  if self._open is urllib.request.urlopen:raise AccessHeld('real network disabled even on internal test path')
  sec_url(url)
  if self.stopped:raise AccessHeld('transport stopped')
  if '@'not in declared_identity or 'Mozilla'in declared_identity:raise ValueError('genuine declared contact identity required')
  key=digest(url.encode());f=self.cache/(key+'.json')
  if f.exists():
   r=json.loads(f.read_text());return bytes.fromhex(r['hex']),r['evidence']
  if self.last is not None:self.sleep(max(0.,1.-(self.clock()-self.last)))
  self.last=self.clock()
  req=urllib.request.Request(url,headers={'User-Agent':declared_identity,'Accept-Encoding':'identity'})
  try:
   with self._open(req,timeout=30) as response:
    status=response.status;final=response.geturl();b=response.read(25*1024*1024+1)
  except urllib.error.HTTPError as e:
   b=e.read(4096);self.stopped=True;atomic(self.cache/'stopped.json',{'url':url,'status':e.code,'body_prefix_hash':digest(b),'body_prefix_bytes':len(b),'retry':False});raise AccessHeld('HTTP failure; stopped, no retry')
  if status!=200 or final!=url or len(b)>25*1024*1024 or any(s in b[:4096].lower()for s in [b'access denied',b'undeclared automated tool',b'request rate threshold',b'captcha']):
   self.stopped=True;raise AccessHeld('status/redirect/body safety check failed; no retry')
  ev={'url':url,'sha256':digest(b),'status':status,'source':'injected_transport_test_not_live'};atomic(f,{'hex':b.hex(),'evidence':ev});return b,ev
