"""Expansão e conferência de eventos visíveis, preservando lacunas sem justificativa."""
import re
import hashlib

STATE=r'''() => ({tabela:!!document.querySelector('#tblEventos'),
 total:Number.isInteger(window.totalPaginas)?window.totalPaginas:null,
 carregadas:Number.isInteger(window.carregadas)?window.carregadas:null,
 funcao:typeof window.carregarProximaPagina==='function',
 eventos:[...document.querySelectorAll('#tblEventos tr[id^="trEvento"]')].filter(r=>!!r.getClientRects().length).map(r=>Number(r.id.replace('trEvento',''))).filter(Number.isInteger),
 eventos_ocultos:[...document.querySelectorAll('#tblEventos tr[id^="trEvento"]')].filter(r=>!r.getClientRects().length).map(r=>Number(r.id.replace('trEvento',''))).filter(Number.isInteger)})'''

def gap_intervals(events):
 result=[];previous=0
 for number in sorted(events):
  if number>previous+1:result.append((previous+1,number-1))
  previous=number
 return result

def sample_missing(intervals,limit=200):
 values=[]
 for start,end in intervals:
  values.extend(range(start,min(end+1,start+limit-len(values))))
  if len(values)>=limit:break
 return values

def coverage(state):
 events={n for n in state['eventos'] if type(n)is int and n>0};top=max(events,default=0);intervals=gap_intervals(events)
 contiguous=bool(events) and not intervals
 counter=type(state['total'])is int and type(state['carregadas'])is int and state['total']>=0 and state['carregadas']==state['total']
 return {'completo':bool(state['tabela'] and counter and contiguous),'escopo':'eventos_exibidos_na_tabela','paginacao_conferida':counter,
         'paginas_adicionais_esperadas':state['total'],'paginas_adicionais_lidas':state['carregadas'],'eventos_visiveis':len(events),'maior_evento':top,
         'sequencia_continua':contiguous,'lacunas_quantidade':sum(end-start+1 for start,end in intervals),'lacunas_intervalos':intervals,
         'eventos_numeros_hash':hashlib.sha256(','.join(map(str,sorted(events))).encode()).hexdigest(),
         'lacunas_amostra':sample_missing(intervals),'eventos_ocultos_amostra':sorted({n for n in state.get('eventos_ocultos',[]) if type(n)is int and n>0})[:200],
         'motivo':'total_e_sequencia_conferidos' if state['tabela'] and counter and contiguous else 'historico_nao_confirmado'}

def reconcile(base,snapshot):
 """Resolve only gaps explicitly referenced by a later cancellation event.

 A bill cancellation, a canceled hearing or an excluded party is not evidence
 that a numbered process movement was canceled. Original rows stay unchanged.
 """
 descriptions={};table_found=False
 primary=any(t.get('tabela_eventos') is True for t in snapshot.get('tabelas',[]))
 for table in snapshot.get('tabelas',[]):
  if primary and table.get('tabela_eventos') is not True:continue
  rows=table.get('linhas',[])
  if not rows or [' '.join(str(v).split()) for v in rows[0]]!=['Evento','Data/Hora','Descrição','Usuário','Documentos']:continue
  table_found=True
  ids=table.get('numeros_eventos_linhas') if table.get('tabela_eventos') is True else None
  for index,row in enumerate(rows[1:],1):
   if ids is not None and (index>=len(ids) or ids[index] is None):continue
   if len(row)>=3 and re.fullmatch(r'[1-9]\d*',str(row[0]).strip()):
    number=int(str(row[0]).strip())
    if ids is not None and ids[index]!=number:continue
    descriptions.setdefault(number,set()).add(' '.join(str(row[2]).split()))
 state={'tabela':table_found,'total':base.get('paginas_adicionais_esperadas'),'carregadas':base.get('paginas_adicionais_lidas'),'eventos':list(descriptions)}
 result=coverage(state);result['eventos_ocultos_amostra']=base.get('eventos_ocultos_amostra',[])
 result['motivo_expansao']=base.get('motivo','');result['cancelamentos_referenciados']=[]
 observed=len(descriptions)==base.get('eventos_visiveis') and max(descriptions,default=0)==base.get('maior_evento')
 if base.get('eventos_numeros_hash'):observed=observed and base['eventos_numeros_hash']==result['eventos_numeros_hash']
 result['tabela_confere_com_contagem']=observed
 justified=set()
 for source,texts in descriptions.items():
  if len(texts)!=1:continue
  description=next(iter(texts))
  if not re.match(r'^(?:Cancelada a|Cancelamento de)\s+movimenta[çc][aã]o\s+processual\s*-',description,re.I):continue
  references={int(n) for pair in re.findall(r'\(Evento\s+([1-9]\d*)\s*-|\bRefer\.\s*Evento\s+([1-9]\d*)\b',description,re.I) for n in pair if n}
  if len(references)!=1:continue
  target=next(iter(references))
  if target>=source or target in descriptions:continue
  if any(start<=target<=end for start,end in result['lacunas_intervalos']):
   justified.add(target);result['cancelamentos_referenciados'].append({'evento_cancelado':target,'evento_que_registra':source})
 result['lacunas_justificadas_por_cancelamento']=sorted(justified)
 result['lacunas_nao_justificadas_quantidade']=result['lacunas_quantidade']-len(justified)
 remaining=[]
 for start,end in result['lacunas_intervalos']:
  for n in range(start,min(end+1,start+len(justified)+200)):
   if n not in justified:remaining.append(n)
   if len(remaining)>=200:break
  if len(remaining)>=200:break
 result['lacunas_nao_justificadas_amostra']=remaining
 # More than one description may be rendered for a numbered event. Such rows
 # cannot justify a cancellation; their presence alone is not a missing page.
 result['eventos_com_descricoes_multiplas']=[n for n,texts in descriptions.items() if len(texts)>1]
 result['completo']=bool(table_found and descriptions and result['paginacao_conferida'] and observed and not result['lacunas_nao_justificadas_quantidade'])
 if base.get('falha_paginacao') or base.get('motivo') in ('sem_avanco_no_carregamento','limite_de_paginas'):
  result['completo']=False;result['motivo']=base['motivo']
 elif not observed:result['completo']=False;result['motivo']='tabela_divergente_da_contagem'
 elif not result['paginacao_conferida']:result['motivo']='paginacao_nao_confirmada'
 elif not descriptions:result['motivo']='historico_vazio_nao_confirmado'
 elif result['lacunas_nao_justificadas_quantidade']:result['motivo']='paginas_carregadas_com_lacunas_nao_justificadas'
 elif justified:
  result['motivo']='paginas_conferidas_e_cancelamentos_referenciados';result['escopo']='eventos_exibidos_e_referencias_de_cancelamento_sem_recuperar_conteudo_cancelado'
 else:result['motivo']='total_e_sequencia_conferidos'
 return result
def expand(collector,page):
 # As variáveis podem receber seus valores após o primeiro carregamento AJAX.
 stable=None;stable_count=0
 for _ in range(20):
  collector.check();state=page.evaluate(STATE)
  if state==stable:stable_count+=1
  else:stable=state;stable_count=0
  if stable_count>=3:break
  page.wait_for_timeout(250)
 for _ in range(1000):
  collector.check()
  if not state['tabela'] or state['total'] is None or state['carregadas'] is None or state['carregadas']>=state['total'] or not state['funcao']:return coverage(state)
  previous=state['carregadas'];previous_events=set(state['eventos']);total=state['total']
  collector.log('Carregando próxima página de movimentações do processo.')
  page.evaluate('() => window.carregarProximaPagina()')
  changed=False;stable=None;stable_count=0
  for _ in range(120):
   collector.check();page.wait_for_timeout(250);state=page.evaluate(STATE)
   if state['total']!=total:
    result=coverage(state);result.update(completo=False,falha_paginacao=True,motivo='total_alterado_durante_carregamento');return result
   # The counter alone does not prove that another page's rows were appended.
   if state['carregadas'] is not None and state['carregadas']>previous:
    current=set(state['eventos'])
    if previous_events < current and state==stable:stable_count+=1
    else:stable_count=0
    stable=state
    if stable_count>=2:changed=True;break
  if not changed:
   result=coverage(state);result['completo']=False;result['falha_paginacao']=True
   result['motivo']='sem_avanco_no_carregamento' if state['carregadas']==previous else 'contagem_avancou_sem_preservar_e_ampliar_eventos'
   return result
 result=coverage(state);result['completo']=False;result['motivo']='limite_de_paginas';return result
