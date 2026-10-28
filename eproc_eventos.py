"""Expansão incremental da tabela de eventos pelo carregador observado do tribunal."""
STATE=r'''() => ({tabela:!!document.querySelector('#tblEventos'),
 total:Number.isInteger(window.totalPaginas)?window.totalPaginas:null,
 carregadas:Number.isInteger(window.carregadas)?window.carregadas:null,
 funcao:typeof window.carregarProximaPagina==='function',
 eventos:[...document.querySelectorAll('#tblEventos tr[id^="trEvento"]')].filter(r=>!!r.getClientRects().length).map(r=>Number(r.id.replace('trEvento',''))).filter(Number.isFinite)})'''
def coverage(state):
 events=set(state['eventos']);top=max(events,default=0);contiguous=bool(events) and events==set(range(1,top+1))
 counter=state['total'] is not None and state['carregadas'] is not None and state['carregadas']>=state['total']
 return {'completo':bool(state['tabela'] and counter and contiguous),'paginas_adicionais_esperadas':state['total'],'paginas_adicionais_lidas':state['carregadas'],'eventos_visiveis':len(events),'maior_evento':top,'sequencia_continua':contiguous,'motivo':'total_e_sequencia_conferidos' if state['tabela'] and counter and contiguous else 'historico_nao_confirmado'}
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
  previous=state['carregadas'];collector.log('Carregando próxima página de movimentações do processo.')
  page.evaluate('() => window.carregarProximaPagina()')
  changed=False
  for _ in range(120):
   collector.check();page.wait_for_timeout(250);state=page.evaluate(STATE)
   if state['carregadas'] is not None and state['carregadas']>previous:changed=True;break
  if not changed:
   result=coverage(state);result['completo']=False;result['motivo']='sem_avanco_no_carregamento';return result
 result=coverage(state);result['completo']=False;result['motivo']='limite_de_paginas';return result
