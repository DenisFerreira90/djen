"""Categorias eproc observadas nos HTML enviados; navegação somente de leitura."""
import hashlib
import json
import re
from urllib.parse import urlsplit,parse_qs
import juridico as legal
import eproc_tribunais as tribunais
from eproc_paginacao import ListCoverage, signature, page_info, wait_table, wait_initial

ACTIONS={'relatorio_processos_prazo_a_encerrar':'prazos_a_encerrar','recursos_tribunal_agravo_listar':'agravos_distribuidos','citacao_intimacao_pendente_listar':'pendentes_citacao_intimacao','movimentacao_preparada_listar':'movimentacoes_preparadas','peticao_inicial_preparada_listar':'processos_pendentes_advogado','peticao_inicial_preparada_escritorio_listar':'processos_pendentes_sociedade'}
HEADERS={'prazos_a_encerrar':['Número Processo','Procuradores','Data Lançamento','Data Início','Data Fim','Evento'],'agravos_distribuidos':['Processo','Número do Agravo','Data da Distribuição do Agravo'],'pendentes_citacao_intimacao':['','Processo','Classe','Assunto','Evento e Prazo','Data envio requisição','Início Prazo','Final Prazo'],'movimentacoes_preparadas':['','Processo','Evento','Data da Criação','Preparado para','Preparado por','Data Final do Prazo','Resultado','Ações']}
INITIAL_KINDS={'processos_pendentes_advogado','processos_pendentes_sociedade'}
INITIAL_HEADER=['','Autor','Réu','Assunto','Data da Criação','Criado por','Ações']
for _kind in INITIAL_KINDS:HEADERS[_kind]=INITIAL_HEADER
NEXT='a[rel="next"]:visible, a[title="Próxima Página"]:visible, a[title="Próxima página"]:visible, a[aria-label="Próxima página"]:visible, a[aria-label="Próxima Página"]:visible, a:has(img[alt="Próxima página"]):visible'
def normalized_header(row):return [' '.join(str(x).split()) for x in row]

def open_listing_rows(pages):
 from eproc_estruturado import listing
 return listing([page for page in pages if not page.get('origem_relatorio')])

def open_page(snapshot):
 tables=[t for t in snapshot.get('tabelas',[]) if t.get('linhas') and {'Processo','Evento e Prazo','Final Prazo'}<=set(t['linhas'][0])]
 return open_listing_rows([{'tabelas':tables}]),tables


def valid_url(value,action,tribunal='TJRS'):
 return tribunais.valid_url(value,tribunal,(action,))

def report_rows(snapshot,kind):
 result=[];expected=None
 for table in snapshot.get('tabelas',[]):
  rows=table.get('linhas',[])
  if not rows or normalized_header(rows[0])!=HEADERS[kind]:continue
  match=re.search(r'([\d.]+)\s+registros?',table.get('titulo',''),re.I)
  if match:expected=int(match[1].replace('.',''))
  index=HEADERS[kind].index('Processo') if 'Processo' in HEADERS[kind] else 0
  for ri,row in enumerate(rows[1:],1):
   if not row:continue
   if kind in INITIAL_KINDS:
    ids=table.get('identificadores_peticoes_linhas') or []
    identity=ids[ri] if ri<len(ids) else None
    if len(row)==len(INITIAL_HEADER) and isinstance(identity,str) and re.fullmatch(r'[1-9]\d{0,29}',identity):
     result.append({'id_peticao_pendente':identity,'celulas':row})
    continue
   number=legal.CNJ.search(str(row[index])) if len(row)>index else None
   if number:result.append({'numero':number.group(),'celulas':row})
 return result,expected

def split_pages(pages):
 result={}
 for page in case_listing_pages(pages):
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

def recover_panel_routes(collector,context,wanted):
 """Reopen only a current, observed panel link when the list lacks categories."""
 if getattr(collector,'report_panel_checked',False) is True:return ''
 panel_actions=('painel_adv_listar','painel_advogado_listar')
 tribunal=collector.options.get('tribunal','TJRS');panel_url=''
 for frame in collector.surfaces(context):
  if tribunais.valid_url(frame.url,tribunal,panel_actions):
   panel_url=frame.url;break
  for url in frame.locator('a[href]').evaluate_all('(items)=>items.map(a=>a.href)'):
   if tribunais.valid_url(url,tribunal,panel_actions):panel_url=url;break
  if panel_url:break
 collector.report_panel_checked=True
 if not panel_url:return ''
 collector.log('Recuperando os links atuais das categorias pelo Painel do Advogado, na mesma sessão.')
 page=context.new_page()
 try:
  page.goto(panel_url,wait_until='domcontentloaded',timeout=60000)
  for _ in range(240):
   collector.check();page.wait_for_timeout(250)
   if not tribunais.valid_url(page.url,tribunal,panel_actions):continue
   routes=getattr(collector,'report_routes',{})
   if not isinstance(routes,dict):routes={}
   for url in page.locator('a[href]').evaluate_all('(items)=>items.map(a=>a.href)'):
    if tribunais.valid_url(url,tribunal,ACTIONS):
     action=parse_qs(urlsplit(url).query)['acao'][0];routes[action]=url
   collector.report_routes=routes
   if wanted in routes:return routes[wanted]
 finally:page.close()
 return ''


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
 if not url:url=getattr(collector,'report_routes',{}).get(action,'')
 if not isinstance(url,str):url=''
 if not url:url=recover_panel_routes(collector,context,action)
 if not url:
  collector.log(kind+': relatório não localizado na sessão. Não considerado coletado.');return coverage,set()
 if not valid_url(url,action,tribunal):raise ValueError('URL_RELATORIO_INVALIDA')
 if kind not in HEADERS:
  coverage['motivo']='layout_nao_validado'
  collector.log(kind+': categoria localizada; falta o HTML da lista para validar o layout. Não considerada coletada.')
  return coverage,set()
 page=context.new_page();priority=set();tracker=ListCoverage()
 def extract(snap):
  rows,_=report_rows(snap,kind)
  return rows,[t for t in snap.get("tabelas",[]) if t.get("linhas") and normalized_header(t["linhas"][0])==HEADERS[kind]]
 try:
  page.goto(url,wait_until='domcontentloaded',timeout=60000)
  ready=wait_initial(collector,page,snapshot_js,extract)
  if ready is None:
   tracker.stop('tabela_nao_carregada_ou_layout_nao_confirmado');coverage.update(tracker.export());return coverage,priority
  for _ in range(1000):
   collector.check();page.wait_for_timeout(350)
   if not valid_url(page.url,action,tribunal) or page.locator('input[type="password"]').count():tracker.stop('sessao_ou_pagina_nao_confirmada');break
   snap=page.evaluate(snapshot_js);rows,tables=extract(snap)
   if not tracker.accept(rows,tables):break
   numbers={r['numero'] for r in rows if r.get('numero')}
   if any(tribunais.from_number(n)!=tribunal for n in numbers):tracker.stop('numero_tribunal_divergente');break
   pages.append({'texto':'','tabelas':tables,'origem_relatorio':kind,'tribunal':tribunal,'coletado_em':legal.now()})
   priority.update(numbers)
   for number in numbers:found.setdefault(number,None)
   found.update({n:u for n,u in links(snap).items() if n in numbers})
   coverage.update(tracker.export());coverage['processos_distintos']=len(priority)
   if kind in INITIAL_KINDS:coverage.update(escopo='peticoes_iniciais_preparadas_sem_numero_cnj',peticoes_distintas=len({r['id_peticao_pendente'] for p in pages if p.get('origem_relatorio')==kind for r in report_rows(p,kind)[0]}))
   collector.update(relatorio_em_leitura=dict(coverage));collector.save_checkpoint([],pages)
   collector.log(f"{kind}: página {coverage['paginas']}, {coverage['registros']} / {coverage['esperados']} registros.")
   if tracker.complete:break
   available=next_enabled(page)
   if not available:tracker.stop('fim_sem_total_conferido');break
   old=(signature(rows),tuple(sorted(page_info(tables)[1])))
   available[0].click(timeout=45000)
   if wait_table(collector,page,snapshot_js,extract,old) is None:
    tracker.stop('pagina_nao_mudou');break
  else:tracker.stop('limite_de_paginas')
  coverage.update(tracker.export())
 finally:page.close()
 return coverage,priority

def case_listing_pages(pages):
 return [p for p in pages if p.get('origem_relatorio') not in INITIAL_KINDS]

def initial_entries(pages):
 result=[]
 for page in pages:
  kind=page.get('origem_relatorio')
  if kind not in INITIAL_KINDS:continue
  for row in report_rows(page,kind)[0]:
   cells=row['celulas']
   result.append({'id_peticao_pendente':row['id_peticao_pendente'],'categoria':kind,
    'autor':cells[1],'reu':cells[2],'assunto':cells[3],'data_criacao':cells[4],
    'criado_por':cells[5],'escopo':'peticao_inicial_preparada_sem_numero_cnj'})
 return result

def save_initials(store,pages,tribunal,run_id):
 """Store immutable observations; same ID in two lists remains one identity."""
 if any(p.get('origem_relatorio') in INITIAL_KINDS and p.get('tribunal') not in (None,tribunal) for p in pages):raise ValueError('Origem das petições não corresponde ao tribunal da coleta.')
 entries=initial_entries(pages)
 if not entries:return 0
 with store.lock,store.connect() as db:
  db.execute('CREATE TABLE IF NOT EXISTS source_initial_preparations(id INTEGER PRIMARY KEY,tribunal TEXT NOT NULL,peticao_id TEXT NOT NULL,categoria TEXT NOT NULL,payload TEXT NOT NULL,signature TEXT NOT NULL,execucao TEXT NOT NULL,coletado_em TEXT NOT NULL,UNIQUE(tribunal,peticao_id,categoria,signature))')
  saved=0
  for entry in entries:
   raw=legal.dumps(entry);digest=hashlib.sha256(raw.encode()).hexdigest()
   saved+=db.execute('INSERT OR IGNORE INTO source_initial_preparations(tribunal,peticao_id,categoria,payload,signature,execucao,coletado_em) VALUES(?,?,?,?,?,?,?)',(tribunal,entry['id_peticao_pendente'],entry['categoria'],raw,digest,run_id,legal.now())).rowcount
 return saved


def prepared_entries(pages):
 """Keep preparation metadata separate from filed events and official deadlines."""
 result=[]
 for page in pages:
  if page.get('origem_relatorio')!='movimentacoes_preparadas':continue
  rows,_=report_rows(page,'movimentacoes_preparadas')
  for row in rows:
   cells=row['celulas']
   if len(cells)!=len(HEADERS['movimentacoes_preparadas']):continue
   result.append({'numero':row['numero'],'tribunal':page.get('tribunal') or tribunais.from_number(row['numero']),'evento':cells[2],'data_criacao':cells[3],
    'preparado_para':cells[4],'preparado_por':cells[5],
    'data_final_prazo_origem':cells[6],'resultado':cells[7],
    'escopo':'lista_de_movimentacoes_preparadas_sem_confirmacao_de_protocolo'})
 return result


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
   if kind=='movimentacoes_preparadas':value['registros_preparados']=prepared_entries([page])
   signature=hashlib.sha256(legal.dumps(value).encode()).hexdigest()
   count+=db.execute('INSERT OR IGNORE INTO source_complements(case_id,tipo,payload,signature,import_id) VALUES(?,?,?,?,?)',(case[0],kind,legal.dumps(value),signature,import_id)).rowcount
 return count
