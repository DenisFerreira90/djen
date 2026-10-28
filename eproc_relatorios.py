"""Relatórios TJRS observados nos HTML enviados; navegação somente de leitura."""
import hashlib
import json
import re
from urllib.parse import urlsplit,parse_qs
import juridico as legal
import eproc_tribunais as tribunais

ACTIONS={'relatorio_processos_prazo_a_encerrar':'prazos_a_encerrar','recursos_tribunal_agravo_listar':'agravos_distribuidos'}
HEADERS={'prazos_a_encerrar':['Número Processo','Procuradores','Data Lançamento','Data Início','Data Fim','Evento'],'agravos_distribuidos':['Processo','Número do Agravo','Data da Distribuição do Agravo']}
NEXT='a[rel="next"]:visible, a[title="Próxima Página"]:visible, a[title="Próxima página"]:visible, a[aria-label="Próxima página"]:visible, a:has(img[alt="Próxima página"]):visible'
def normalized_header(row):return [' '.join(str(x).split()) for x in row]

def valid_url(value,action,tribunal='TJRS'):
 return tribunais.valid_url(value,tribunal,(action,))

def report_rows(snapshot,kind):
 result=[];expected=None
 for table in snapshot.get('tabelas',[]):
  rows=table.get('linhas',[])
  if not rows or normalized_header(rows[0])!=HEADERS[kind]:continue
  match=re.search(r'([\d.]+)\s+registros?',table.get('titulo',''),re.I)
  if match:expected=int(match[1].replace('.',''))
  for row in rows[1:]:
   if not row:continue
   number=legal.CNJ.search(str(row[0]))
   if number:result.append({'numero':number.group(),'celulas':row})
 return result,expected

def split_pages(pages):
 result={}
 for page in pages:
  for table in page.get('tabelas',[]):
   rows=table.get('linhas',[])
   if not rows:continue
   if not (set(('Processo','Evento e Prazo','Final Prazo'))<=set(rows[0]) or normalized_header(rows[0]) in HEADERS.values()):continue
   index=rows[0].index('Processo') if 'Processo'in rows[0] else 0
   groups={}
   for row in rows[1:]:
    match=legal.CNJ.search(str(row[index])) if len(row)>index else None
    if match:groups.setdefault(match.group(),[]).append(row)
   for number,entries in groups.items():
    result.setdefault(number,[]).append({**{k:v for k,v in page.items() if k not in ('tabelas','texto')},'tabelas':[{'titulo':table.get('titulo',''),'linhas':[rows[0],*entries]}]})
 return result

def next_enabled(page):
 links=page.locator(NEXT)
 return [links.nth(i) for i in range(links.count()) if links.nth(i).get_attribute('aria-disabled')!='true' and 'disabled' not in (links.nth(i).get_attribute('class') or '').lower() and not links.nth(i).evaluate('e => !!e.closest(\'[disabled], [aria-disabled="true"], .disabled\')')]

def collect(collector,context,action,snapshot_js,pages,found,links):
 tribunal=collector.options.get('tribunal','TJRS')
 kind=ACTIONS[action];coverage={'tipo':kind,'paginas':0,'registros':0,'esperados':None,'completo':False,'motivo':'relatorio_nao_localizado'}
 url=collector.options.get('url_'+kind,'')
 if not url:
  for frame in collector.surfaces(context):
   if valid_url(frame.url,action,tribunal):url=frame.url;break
   candidates=frame.locator('a[href]').evaluate_all('(items)=>items.map(a=>a.href)')
   url=next((u for u in candidates if valid_url(u,action,tribunal)),'')
   if url:break
 if not url:
  collector.log(kind+': relatório não localizado na sessão. Não considerado coletado.');return coverage,set()
 if not valid_url(url,action,tribunal):raise ValueError('URL_RELATORIO_INVALIDA')
 page=context.new_page();priority=set();seen=set()
 try:
  page.goto(url,wait_until='domcontentloaded',timeout=60000)
  for _ in range(1000):
   collector.check();page.wait_for_timeout(350)
   if not valid_url(page.url,action,tribunal) or page.locator('input[type="password"]').count():coverage['motivo']='sessao_ou_pagina_nao_confirmada';break
   snap=page.evaluate(snapshot_js);rows,expected=report_rows(snap,kind)
   if expected is not None:coverage['esperados']=expected
   signature=hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest()
   if signature in seen:coverage['motivo']='pagina_repetida';break
   if not rows:
    coverage['completo']=coverage['esperados']==0;coverage['motivo']='vazio_confirmado' if coverage['completo'] else 'estrutura_nao_confirmada';break
   seen.add(signature)
   tables=[t for t in snap['tabelas'] if t.get('linhas') and normalized_header(t['linhas'][0])==HEADERS[kind]]
   pages.append({'texto':'','tabelas':tables,'origem_relatorio':kind,'coletado_em':legal.now()})
   numbers={r['numero'] for r in rows};priority.update(numbers)
   for number in numbers:found.setdefault(number,None)
   found.update({n:u for n,u in links(snap).items() if n in numbers})
   coverage['paginas']+=1;coverage['registros']+=len(rows)
   collector.update(relatorio_em_leitura=dict(coverage));collector.save_checkpoint([],pages)
   collector.log(f"{kind}: página {coverage['paginas']}, {coverage['registros']} / {coverage['esperados']} registros.")
   if coverage['esperados'] is not None and coverage['registros']>=coverage['esperados']:
    coverage['completo']=coverage['registros']==coverage['esperados'];coverage['motivo']='total_conferido' if coverage['completo'] else 'total_divergente';break
   available=next_enabled(page)
   if not available:coverage['motivo']='fim_sem_total_conferido';break
   old=signature;available[0].click(timeout=45000)
   changed=False
   for _ in range(120):
    collector.check();page.wait_for_timeout(250)
    try:current=page.evaluate(snapshot_js);newrows,_=report_rows(current,kind)
    except Exception:continue
    if newrows and hashlib.sha256(json.dumps(newrows,sort_keys=True).encode()).hexdigest()!=old:changed=True;break
   if not changed:coverage['motivo']='pagina_nao_mudou';break
 finally:page.close()
 return coverage,priority

def save_reports(store,db,payload,import_id):
 count=0
 for number,casepages in split_pages(payload.get('paginas_da_lista',[])).items():
  case=db.execute("SELECT id FROM records WHERE kind='processos' AND json_extract(data,'$.numero')=?",(number,)).fetchone()
  if not case:continue
  for page in casepages:
   kind=page.get('origem_relatorio')
   if kind not in HEADERS:continue
   import eproc
   value={'tipo':kind,'situacao':'listagem_coletada_requer_conferencia','texto':'Relatório de leitura; não é prazo cadastrado nem documento baixado.','estrutura':eproc.adaptive_tables(page),'tabelas':page['tabelas']}
   signature=hashlib.sha256(legal.dumps(value).encode()).hexdigest()
   count+=db.execute('INSERT OR IGNORE INTO source_complements(case_id,tipo,payload,signature,import_id) VALUES(?,?,?,?,?)',(case[0],kind,legal.dumps(value),signature,import_id)).rowcount
 return count
