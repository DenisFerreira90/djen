"""Links documentais de sessão, somente em memória e com prazo curto."""
import time,threading,re
from urllib.parse import urlsplit,parse_qs
import eproc_tribunais as courts
import juridico as legal
_cache={};_lock=threading.RLock()

def capture(number,snapshot):
 court=courts.from_number(number)
 if not court or number not in str(snapshot.get('texto','')):return
 items={}
 for row in snapshot.get('documentos_eventos',[]):
  event=str(row.get('evento',''));label=str(row.get('nome',''));url=str(row.get('url',''))
  if not event.isdigit() or not re.fullmatch('[A-Z][A-Z0-9_]*[0-9]+',label):continue
  if not courts.valid_url(url,court,('acessar_documento','documento_consultar','documento_visualizar')):continue
  params=parse_qs(urlsplit(url).query)
  nums=params.get('num_processo',[])
  if nums and any(re.sub(r'\D','',n)!=re.sub(r'\D','',number) for n in nums):continue
  items.setdefault((event,label),set()).add(url)
 now=time.monotonic()
 with _lock:
  for n in list(_cache):
   if _cache[n][0]<now:del _cache[n]
  if len(_cache)>=2000:_cache.pop(next(iter(_cache)))
  _cache[number]=(now+1800,{k:next(iter(v)) for k,v in items.items() if len(v)==1})

def available(number,event,label):
 with _lock:
  data=_cache.get(number)
  return bool(data and data[0]>time.monotonic() and (str(event),label) in data[1])

def resolve(store,actor,body):
 number=body.get('numero');event=str(body.get('evento',''));label=body.get('documento')
 if not isinstance(label,str) or not courts.from_number(number):raise legal.AppError('Documento inválido.')
 with store.lock,store.connect() as db:
  case=db.execute("SELECT id FROM records WHERE kind='processos' AND json_extract(data,'$.numero')=?",(number,)).fetchone()
  if not case:raise legal.AppError('Processo não cadastrado.',404)
  with _lock:
   data=_cache.get(number)
   url=data[1].get((event,label)) if data and data[0]>time.monotonic() else None
  if not url:raise legal.AppError('Link não disponível ou expirado. Consulte novamente o processo para capturar o endereço do documento.',409)
  store.audit(db,actor,'abrir_documento_mandado','processos',case[0],after={'evento':event,'documento':label})
 return {'url':url,'mensagem':'O eproc pode exigir autenticação ou negar um link de sessão expirado.'}
