"""Coleta local assistida do eproc. Não confirma ciência, protocola petições ou altera processos."""
from __future__ import annotations
import csv
import hashlib
import datetime as dt
import io
import json
import os
from pathlib import Path
import re
import threading
import time
import traceback
import uuid
import zipfile
import eproc_tribunais as tribunais
from urllib.parse import urlsplit, parse_qs, urljoin

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'dados_eproc'
ENTRY = 'https://eproc1g.tjrs.jus.br/eproc/'
CNJ = re.compile(r'\b\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}\b')
# Read visible text only; keep headings and rows, never cookies or page HTML.
SNAPSHOT = r'''() => {
 const visible = e => !!e.getClientRects().length;
 const pendingId = row => {
  const ids = new Set();
  for (const a of row.querySelectorAll('a[href]')) {
   if (!visible(a)) continue;
   try {
    const u = new URL(a.href, location.href);
    const values = u.searchParams.getAll('id_peticao_pendente');
    if (u.origin === location.origin && u.pathname === '/eproc/controlador.php' &&
        u.searchParams.getAll('acao').length === 1 && u.searchParams.get('acao') === 'peticao_inicial_preparada_carregar' &&
        values.length === 1 && /^[1-9]\d{0,29}$/.test(values[0])) ids.add(values[0]);
   } catch (_) {}
  }
  return ids.size === 1 ? [...ids][0] : null;
 };
 const tables = [...document.querySelectorAll('table')].filter(visible).map(t => ({
  titulo: t.caption?.innerText || t.getAttribute('aria-label') || '',
  tabela_eventos: t.id === 'tblEventos',
  identificadores_peticoes_linhas: [...t.rows].filter(visible).map(pendingId),
  numeros_eventos_linhas: t.id === 'tblEventos' ? [...t.rows].filter(visible).map(r => /^trEvento[1-9]\d*$/.test(r.id) ? Number(r.id.replace('trEvento','')) : null) : null,
  linhas: [...t.rows].filter(visible).map(r => [...r.cells].map(c => c.innerText.trim()))
 }));
 const links = [...document.querySelectorAll('a[href]')].filter(visible).map(a => ({texto:a.innerText.trim(),url:a.href}));
 const documentos_eventos=[];
 for(const table of [...document.querySelectorAll('table')].filter(visible))for(const row of [...table.rows].filter(visible)){
  if(row.cells.length!==5||!/^\d+$/.test(row.cells[0].innerText.trim()))continue;
  for(const a of row.cells[4].querySelectorAll('a[href]'))if(visible(a))documentos_eventos.push({evento:row.cells[0].innerText.trim(),nome:a.innerText.trim(),url:a.href});
 }
 return {texto:document.body.innerText, tabelas:tables, links,documentos_eventos};
}'''


def now():
    # Fixed UTC-3 avoids missing Windows tzdata; Porto Alegre currently uses UTC-3.
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=-3))).isoformat(timespec='seconds')


def safe_cell(value):
    value = str(value)
    return "'" + value if value.lstrip().startswith(('=', '+', '-', '@')) else value


def process_links(snapshot, tribunal="TJRS"):
    result = {}
    for link in snapshot.get('links', []):
        number = CNJ.search(link['texto'])
        if (number and tribunais.valid_url(link['url'],tribunal,('processo_selecionar','processo_consultar'))
                and tribunais.from_number(number.group())==tribunal):
            result.setdefault(number.group(), link['url'])
    return result




def case_pages(pages):
    from eproc_relatorios import split_pages
    return split_pages(pages)


READ_ACTIONS = {
    'audiencia_listar':'audiencias', 'exame_listar':'pericias',
    'arvore_documento_listar':'documentos', 'alvara_eletronico_listar':'alvaras',
    'processo_conta_custas_listar':'custas', 'guias_deposito_judicial_listar':'depositos',
}


def supplement_links(snapshot, number, wanted, tribunal="TJRS"):
    digits=re.sub(r'\D','',number);out={}
    for link in snapshot.get('links',[]):
        try:url=urlsplit(link.get('url',''));port=url.port
        except ValueError:continue
        params=parse_qs(url.query)
        action=params.get('acao',[])
        if len(action)!=1 or action[0] not in READ_ACTIONS:continue
        kind=READ_ACTIONS[action[0]]
        numbers=params.get('num_processo',[])+params.get('txtNumProcesso',[])
        if (kind not in wanted or url.scheme!='https' or url.hostname!=tribunais.config(tribunal)['host']
                or url.path!='/eproc/controlador.php' or url.username or url.password or port not in (None,443)
                or not numbers or any(n!=digits for n in numbers)):continue
        out.setdefault(kind,link['url'])
    return out


def action_inventory(snapshot, number, tribunal="TJRS"):
    """Discover action names without persisting session URLs, hashes or arbitrary query data."""
    permitted=supplement_links(snapshot,number,list(READ_ACTIONS.values()),tribunal)
    found=[];seen=set()
    for link in snapshot.get('links',[]):
        try:
            url=urlsplit(link.get('url',''));action=parse_qs(url.query).get('acao',[''])[0]
        except ValueError:continue
        if not action or not re.fullmatch(r'[A-Za-z0-9_/]+',action) or action in seen:continue
        seen.add(action);kind=READ_ACTIONS.get(action)
        found.append({'acao':action,'tipo':kind or 'nao_mapeada',
                      'situacao':'consulta_disponivel' if kind in permitted else 'nao_navegada',
                      'motivo':'' if kind in permitted else 'Operação não validada como consulta deste processo.'})
    return found


def adaptive_tables(snapshot):
    """Expose all source columns, preserving duplicate/empty headers and uneven rows."""
    result=[]
    for table in snapshot.get('tabelas',[]):
        rows=table.get('linhas',[])
        if not rows:continue
        width=max((len(r) for r in rows),default=0)
        fields=[{'chave':'coluna_'+str(i+1),'rotulo':str(rows[0][i]) if i<len(rows[0]) and rows[0][i] else 'Coluna '+str(i+1)} for i in range(width)]
        result.append({'titulo':table.get('titulo',''),'campos':fields,
                       'registros':[{f['chave']:str(row[i]) if i<len(row) else '' for i,f in enumerate(fields)} for row in rows[1:]],
                       'cabecalho_inferido':True,'conferencia_pendente':True})
    return result


def public_snapshot(snapshot):
    return {k: snapshot[k] for k in ('texto', 'tabelas')}


def write_exports(folder, records, pages, status):
    folder.mkdir(parents=True, exist_ok=True)
    payload = {'execucao': status, 'processos': records, 'paginas_da_lista': pages,
               'observacao': 'Leitura das páginas visíveis. Não inclui anexos, documentos, abas fechadas ou cálculo de prazos. Campos e associações entre partes dependem da validação do layout.'}
    (folder / 'processos.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    # Long table preserves every row from every source table instead of merging deadlines.
    with (folder / 'processos.csv').open('w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f, delimiter=';')
        w.writerow(['Exportação', 'Processo', 'Origem', 'Tabela', 'Linha', 'Células (JSON)', 'Situação da leitura'])
        for record in records:
            detail = record.get('detalhes') or {}
            tables = detail.get('tabelas', [])
            for ti, table in enumerate(tables, 1):
                for ri, row in enumerate(table['linhas'], 1):
                    w.writerow([status['inicio'], record['processo'], 'Detalhes', ti, ri,
                                json.dumps([safe_cell(v) for v in row], ensure_ascii=False), record['situacao']])
            if not tables:
                w.writerow([status['inicio'], record['processo'], 'Detalhes', '', '', '', record['situacao']])
        for pi, page in enumerate(pages, 1):
            for ti, table in enumerate(page['tabelas'], 1):
                for ri, row in enumerate(table['linhas'], 1):
                    match = CNJ.search(' '.join(row))
                    if match:
                        w.writerow([status['inicio'], match.group(), f'Lista página {pi}', ti, ri,
                                    json.dumps([safe_cell(v) for v in row], ensure_ascii=False), 'Linha original'])
    (folder / 'execucao.json').write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding='utf-8')
    with zipfile.ZipFile(folder / 'exportacao.zip', 'w', zipfile.ZIP_DEFLATED) as z:
        for name in ('processos.csv', 'processos.json', 'execucao.json', 'log.jsonl', 'selecao_fila.json'):
            if (folder / name).exists():
                z.write(folder / name, name)


class CollectionBudget(InterruptedError):pass


class Collector:
    def __init__(self, data=DATA):
        self.data = Path(data)
        self.options = {}
        self.lock = threading.RLock()
        self.resume = threading.Event()
        self.cancelled = threading.Event()
        self.thread = None
        self.current = None

    def status(self):
        with self.lock:
            history = []
            if self.data.exists():
                for p in sorted(self.data.glob('*/execucao.json'), reverse=True):
                    try:
                        entry = json.loads(p.read_text(encoding='utf-8'))
                        entry['arquivo_pronto'] = (p.parent / 'exportacao.zip').exists()
                        history.append(entry)
                    except (OSError, ValueError):
                        continue
            return {'ok': True, 'em_execucao': bool(self.thread and self.thread.is_alive()), 'atual': dict(self.current) if self.current else None, 'historico': history[:100]}

    def update(self, **values):
        with self.lock:
            self.current.update(values)
            p = self.data / self.current['id'] / 'execucao.json'
            temp = p.with_suffix('.tmp')
            temp.write_text(json.dumps(self.current, ensure_ascii=False, indent=2), encoding='utf-8')
            temp.replace(p)

    def log(self, message):
        with self.lock:
            event = {'data': now(), 'mensagem': message}
            self.current['log'] = (self.current['log'] + [event])[-100:]
            with (self.data / self.current['id'] / 'log.jsonl').open('a', encoding='utf-8') as f:
                f.write(json.dumps(event, ensure_ascii=False) + '\n')
            self.update(mensagem=message)

    def start(self, actor=None, options=None):
        options=dict(options or {})
        if type(options.get('invisivel',False)) is not bool:raise ValueError('Modo invisível inválido.')
        tribunal=options.get("tribunal","TJRS")
        tribunais.config(tribunal)
        teste_sc = ((tribunal == 'TJSC' and options.get('teste_sc') is True) or (tribunal == 'TJRJ' and options.get('teste_rj') is True)) and not options.get('automatico') and not options.get('monitorar_lista')
        if not tribunais.enabled(tribunal) and not teste_sc:raise ValueError('Tribunal disponível para teste manual em Coleta eproc. Selecione o tribunal desejado.')
        options["tribunal"]=tribunal
        key=options.get('autenticador_id')
        if key is not None and (type(key) is not int or key<1):raise ValueError('Autenticador inválido.')
        if type(options.get('monitorar_lista',False))is not bool:raise ValueError('Seleção de monitoramento inválida.')
        if options.get('monitorar_lista'):options['modo']='completa'
        if options.get('monitorar_lista'):
            if not actor or actor.get('role')=='leitor':raise ValueError('Usuário sem permissão para consultar a lista.')
            import mandados
            from juridico import store
            with store.lock,store.connect() as db:
                mandados.schema(db)
                snapshot=options.get('numeros_monitorados')
                if snapshot is not None and (not isinstance(snapshot,list) or not 1<=len(snapshot)<=20000 or any(not isinstance(n,str) or not CNJ.fullmatch(n) or tribunais.from_number(n)!=tribunal for n in snapshot)):raise ValueError('Lista de consulta inválida.')
                if snapshot is None and not any(tribunais.from_number(r[0])==tribunal for r in db.execute('SELECT numero FROM mandate_watchlist')):raise ValueError('Salve uma lista com processos do tribunal selecionado.')
        if options.get("modo")=="individual" and tribunais.from_number(options.get("numero",""))!=tribunal:
            raise ValueError("O número do processo não corresponde ao tribunal selecionado.")
        with self.lock:
            if self.thread and self.thread.is_alive():
                raise ValueError('Já existe uma coleta em andamento.')
            run = dt.datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8]
            (self.data / run).mkdir(parents=True)
            self.login_steps={}
            self.report_routes={}
            self.report_panel_checked=False
            self.options = options or {}
            self.actor = actor
            self.block_status = None
            self.resume.clear()
            self.cancelled.clear()
            self.current = {'id': run, 'tribunal':tribunal, 'inicio': now(), 'fim': None, 'estado': 'iniciando',
                            'lidos': 0, 'encontrados': 0, 'relatorios':[], 'historicos_pendentes':0, 'esperados': None, 'falhas': 0, 'ignorados':0, 'modo': self.options.get('modo','incremental'), 'registros_lista':0, 'salvos_sistema':0,
                            'mensagem': 'Abrindo navegador local.', 'log': [],
                            'validacao': 'Layout interno ainda requer conferência com o eproc.'}
            self.update()
            self.thread = threading.Thread(target=self.run, daemon=True)
            self.thread.start()
            return self.status()

    def action(self, action):
        with self.lock:
            if not self.thread or not self.thread.is_alive():
                raise ValueError('Não existe coleta ativa.')
            if action == 'continuar':
                self.resume.set()
            elif action == 'cancelar':
                self.cancelled.set()
                self.resume.set()
            else:
                raise ValueError('Ação inválida.')
        return self.status()

    def observe_response(self, response):
        host = urlsplit(response.url).hostname or ''
        if host in (tribunais.config(self.options.get('tribunal','TJRS'))['host'],tribunais.config(self.options.get('tribunal','TJRS'))['sso']) and response.status in (403, 429) and response.request.resource_type in ('document', 'xhr', 'fetch'):
            self.block_status = response.status
            self.log(f"HTTP {response.status} recebido do {self.options.get('tribunal','TJRS')}. A coleta será interrompida, sem novas tentativas automáticas.")

    def save_checkpoint(self, records, pages):
        folder = self.data / self.current['id']
        tmp = folder / 'checkpoint.tmp'
        tmp.write_text(json.dumps({'execucao': dict(self.current), 'processos': records, 'paginas_da_lista': pages}, ensure_ascii=False), encoding='utf-8')
        tmp.replace(folder / 'checkpoint.json')

    def check(self):
        import time
        if getattr(self, 'block_status', None):raise RuntimeError('HTTP_' + str(self.block_status))
        if self.cancelled.is_set():raise InterruptedError()
        if getattr(self,'deadline',None) and time.monotonic()>=self.deadline:
            progress=(self.current or {}).get('lidos',0)
            if self.options.get('manter_navegador') and progress>getattr(self,'budget_last_read',0):
                self.budget_last_read=progress
                self.deadline=time.monotonic()+60*int(self.options['limite_minutos'])
                self.log('Intervalo de controle atingido. Continuando no mesmo navegador, sem reiniciar listas ou pedir OK. Checkpoint preservado.')
            else:raise CollectionBudget()

    def profile_path(self):
        return self.data / tribunais.config(self.options.get('tribunal','TJRS'))['sessao']

    def select_details(self, order, pages):
        return order

    def background(self):
        return bool(self.options.get('automatico') or self.options.get('invisivel'))

    def wait_user(self, message, context=None, on_wait=None):
        if self.background():
            self.log('Coleta em segundo plano interrompida: acesso requer intervenção. Desmarque Modo invisível e inicie uma coleta para renovar a sessão ou selecionar o perfil.')
            raise RuntimeError('ACAO_HUMANA')
        self.resume.clear()
        self.update(estado='aguardando')
        self.log(message)
        while not self.resume.wait(0.5):
            self.check()
            if context is not None:
                live=[page for page in context.pages if not page.is_closed()]
                if not live:raise RuntimeError('JANELA_FECHADA')
                live[0].wait_for_timeout(100)
            if on_wait is not None:on_wait()
        self.check()
        self.update(estado='coletando')

    def inspect_blocked(self, context):
        """Keep an already blocked visible page open for inspection; never resume collection."""
        if self.background():return
        self.resume.clear()
        self.update(estado='aguardando', bloqueio_http=self.block_status)
        self.log('Coleta parada por HTTP '+str(self.block_status)+'. A janela ficará aberta para conferir a mensagem do tribunal. Cancelar ou Encerrar diagnóstico fecha esta tentativa; não retoma a coleta.')
        # Do not call check(): the HTTP block must remain set throughout inspection.
        while not self.resume.wait(0.25):
            if self.cancelled.is_set():break
            pages=[p for p in context.pages if not p.is_closed()]
            if not pages:break
            try:pages[0].wait_for_timeout(100)
            except Exception:break

    @staticmethod
    def surfaces(context):
        return [frame for page in context.pages if not page.is_closed() for frame in page.frames if not frame.is_detached()]

    def listing(self, context):
        for frame in self.surfaces(context):
            if urlsplit(frame.url).hostname!=tribunais.config(self.options.get('tribunal','TJRS'))['host']:continue
            links = frame.locator('a[href*="acao=citacao_intimacao_prazo_aberto_listar"]')
            valid=[links.nth(i) for i in range(links.count()) if links.nth(i).is_visible() and tribunais.valid_url(urljoin(frame.url,links.nth(i).get_attribute('href') or ''),self.options.get('tribunal','TJRS'),('citacao_intimacao_prazo_aberto_listar',))]
            if valid:
                label = valid[0].inner_text().strip()
                if re.fullmatch(r'[\d.]+', label):
                    self.update(esperados=int(label.replace('.', '')))
                self.remember_reports(context)
                valid[0].click(timeout=15000)
                return True
        return False

    def remember_reports(self,context):
        from eproc_relatorios import ACTIONS
        routes=getattr(self,'report_routes',{})
        for frame in self.surfaces(context):
            if urlsplit(frame.url).hostname!=tribunais.config(self.options.get('tribunal','TJRS'))['host']:continue
            for url in frame.locator('a[href]').evaluate_all('(items)=>items.map(a=>a.href)'):
                if tribunais.valid_url(url,self.options.get('tribunal','TJRS'),ACTIONS):
                    action=parse_qs(urlsplit(url).query)['acao'][0]
                    routes[action]=url
        self.report_routes=routes

    def ready_listing(self,listing,context):
        from eproc_paginacao import wait_initial
        from eproc_relatorios import open_page
        self.log('Aguardando a tabela de prazos carregar; o endereço sozinho não confirma a lista.')
        if wait_initial(self,listing,SNAPSHOT,open_page) is not None:return listing
        self.log('A tabela de prazos não ficou pronta. Os processos anteriores permanecem salvos; não é uma lista vazia confirmada.')
        if self.background():
            self.update(estado='requer_login')
            raise RuntimeError('LISTA_NAO_CONFIRMADA')
        self.wait_user('Confira a janela: abra o painel do advogado e a lista de prazos. Depois pressione Continuar/ENTER. A tabela não foi reconhecida.',context=context)
        return None

    def find_list(self, context):
        for frame in self.surfaces(context):
            if tribunais.valid_url(frame.url,self.options.get('tribunal','TJRS'),('citacao_intimacao_prazo_aberto_listar',)):
                return frame
        return None

    def diagnostic(self, exc, stage):
        import diagnostico
        fault=diagnostico.capture(exc,'coletor',stage)
        # No exception text: Playwright errors can include auth URLs or typed secrets.
        names = {'TimeoutError': 'tempo de carregamento excedido',
                 'TargetClosedError': 'janela do navegador foi fechada',
                 'Error': 'navegação ou página mudou durante a operação'}
        kind = type(exc).__name__
        location = traceback.extract_tb(exc.__traceback__)[-1] if exc.__traceback__ else None
        local = f' · linha {location.lineno}' if location and Path(location.filename).name == 'eproc.py' else ''
        return f'{stage}: {names.get(kind, "falha na operação")} ({kind}{local}). Código: {fault["codigo"]}'

    def open_login(self, context):
        page = context.pages[0] if context.pages else context.new_page()
        self.log('Acessando o eproc em segundo plano.' if self.background() else 'Abrindo a entrada do eproc. A janela permanecerá aberta para o login.')
        try:
            page.goto(tribunais.entry(self.options.get('tribunal','TJRS')), wait_until='domcontentloaded', timeout=60000)
        except Exception as exc:
            self.log(self.diagnostic(exc, 'Abertura do eproc') + ' Conclua o acesso na janela aberta.')
        self.check()
        tribunal=self.options.get('tribunal','TJRS')
        from eproc_login import step
        step(self,context)
        if self.background():return
        confirmed=getattr(self,'login_confirmed',None)
        if callable(confirmed):
            for _ in range(120):
                self.check()
                if confirmed(context):
                    self.log('Painel autenticado reconhecido. Continuando automaticamente, sem pedir OK.')
                    return
                step(self,context)
                live=[p for p in context.pages if not p.is_closed()]
                if not live:raise RuntimeError('JANELA_FECHADA')
                live[0].wait_for_timeout(250)
        if self.options.get('monitorar_lista'):
            for frame in self.surfaces(context):
                if urlsplit(frame.url).hostname!=tribunais.config(tribunal)['host']:continue
                known=frame.locator('button[data-descricao="ADVOGADO-TITULAR"], a[href*="acao=citacao_intimacao_prazo_aberto_listar"], form[name="formPesquisaRapida"]')
                if any(known.nth(i).is_visible() for i in range(known.count())):return
        from eproc_login import select_profile
        self.wait_user('Faça o login na janela do eproc, sem limite de tempo. O perfil Advogado Titular será selecionado se for único. Ao chegar ao painel, volte e continue após login.',context=context,on_wait=lambda:select_profile(self.surfaces(context),tribunal,self.login_steps,self.log,self.log))

    def await_listing(self, context):
        # Re-check after each explicit continuation. A premature click never ends the run.
        while True:
            self.check()
            if not any(not p.is_closed() for p in context.pages):
                raise RuntimeError('JANELA_FECHADA')
            try:
                listing = self.find_list(context)
                if listing:
                    ready=self.ready_listing(listing,context)
                    if ready:return ready
                    continue
                # Pump browser events: redirects and new frame/tab creation are asynchronous.
                opened = False
                recheck = False
                for _ in range(240):
                    self.check()
                    listing = self.find_list(context)
                    if listing:
                        ready=self.ready_listing(listing,context)
                        if ready:return ready
                        recheck=True
                        break
                    from eproc_login import step
                    step(self,context)
                    if not opened:
                        opened = self.listing(context)
                    live_pages = [p for p in context.pages if not p.is_closed()]
                    if not live_pages:
                        raise RuntimeError('JANELA_FECHADA')
                    live_pages[0].wait_for_timeout(250)
                if recheck:continue
            except InterruptedError:
                raise
            except Exception as exc:
                if str(exc) in ('JANELA_FECHADA','ACAO_HUMANA','LISTA_NAO_CONFIRMADA'):
                    raise
                self.log(self.diagnostic(exc, 'Localização do painel/lista'))
            self.login_steps={}
            self.wait_user('O painel/lista ainda não foi localizado. A janela continua aberta: termine o login ou abra o painel do advogado e clique em Continuar novamente.')

    def collect_supplements(self, context, snapshot, number):
        requested=list(READ_ACTIONS.values()) if self.options.get('descobrir_consultas') else self.options.get('complementos',[])
        tribunal=self.options.get('tribunal','TJRS')
        links=supplement_links(snapshot,number,requested,tribunal)
        results=[{'tipo':'mapa_consultas','situacao':'descoberto','texto':'','tabelas':[], 'acoes':action_inventory(snapshot,number,tribunal)}]
        if not requested:return results
        extra=context.new_page()
        try:
            for kind in requested:
                self.check()
                if kind not in links:
                    results.append({'tipo':kind,'situacao':'link_nao_disponivel','texto':'','tabelas':[]})
                    self.log(f'{number}: listagem {kind} não localizada entre os links da página atual.')
                    continue
                self.log(f'{number}: consultando listagem {kind} em modo de leitura.')
                try:
                    extra.goto(links[kind],wait_until='domcontentloaded',timeout=60000)
                    self.check();extra.wait_for_timeout(700)
                    current=urlsplit(extra.url)
                    params=parse_qs(current.query)
                    current_numbers=params.get('num_processo',[])+params.get('txtNumProcesso',[])
                    if not current_numbers or any(n!=re.sub(r'\D','',number) for n in current_numbers) or not tribunais.valid_url(extra.url,tribunal,READ_ACTIONS) or params.get('acao')!=parse_qs(urlsplit(links[kind]).query).get('acao') or extra.locator('input[type="password"]').count():
                        raise ValueError('Sessão ou página não confirmada')
                    data=extra.evaluate(SNAPSHOT)
                    links.update(supplement_links(data,number,requested,tribunal))
                    results.append({'tipo':kind,'situacao':'pagina_lida_requer_conferencia','coletado_em':now(), 'acao':parse_qs(urlsplit(links[kind]).query)['acao'][0], 'estrutura':adaptive_tables(data), **public_snapshot(data)})
                except InterruptedError:raise
                except Exception as exc:
                    results.append({'tipo':kind,'situacao':'falha_na_leitura','texto':'','tabelas':[]})
                    self.log(self.diagnostic(exc,f'{number}: listagem {kind}'))
                self.cancelled.wait(2.0)
        finally:
            try:extra.close()
            except Exception:pass
        return results

    def run(self):
        import time
        self.deadline=time.monotonic()+60*int(self.options['limite_minutos']) if self.options.get('limite_minutos') else None
        self.budget_last_read=0
        records, pages = [], []
        context = None
        outcome = 'erro'
        try:
            if self.options.get('monitorar_lista'):
                import monitoramento
                from juridico import store
                self.monitor_numbers=monitoramento.begin(store,self.current['id'],self.options['tribunal'],self.options.get('numeros_monitorados'))
                self.update(encontrados=len(self.monitor_numbers))
            try:
                from playwright.sync_api import sync_playwright
            except ImportError:
                raise RuntimeError('DEPENDENCIA')
            with sync_playwright() as pw:
                context = pw.chromium.launch_persistent_context(str(self.profile_path()), headless=self.background(),
                                                               accept_downloads=False)
                context.on('response', self.observe_response)
                try:
                    self.open_login(context)
                    if self.options.get('monitorar_lista'):
                        import monitoramento
                        outcome=monitoramento.collect(self,context,records,pages)
                    else:
                        listing = self.await_listing(context)
                        self.log('Lista localizada. Lendo páginas e preservando as linhas originais.')
                        found, fingerprints = {}, {}
                        mode=self.options.get('modo','incremental')
                        wanted=self.options.get('numero','')
                        from eproc_relatorios import collect as collect_report,ACTIONS
                        report_coverage=[];deadline_priority=set()
                        for action,kind in ACTIONS.items():
                            if not self.options.get('incluir_'+kind,kind=='prazos_a_encerrar') or mode=='individual':continue
                            self.log('Etapa: relatório '+kind+'.')
                            try:
                                coverage,report_numbers=collect_report(self,context,action,SNAPSHOT,pages,found,lambda snap:process_links(snap,self.options.get('tribunal','TJRS')))
                                if kind=='prazos_a_encerrar':deadline_priority.update(report_numbers)
                            except (InterruptedError,CollectionBudget):raise
                            except Exception as exc:
                                self.check()
                                coverage={'tipo':kind,'completo':False,'motivo':'falha_na_leitura'}
                                self.log(self.diagnostic(exc,'Relatório '+kind))
                            report_coverage.append(coverage);self.update(relatorios=report_coverage)
                        self.log('Etapa: lista de prazos abertos.')
                        from eproc_paginacao import ListCoverage, signature as page_signature, page_info, wait_table
                        from eproc_relatorios import open_page, next_enabled
                        list_coverage = ListCoverage(self.current.get('esperados'))
                        pagination_complete = False
                        for page_index in range(1000):
                            self.check()
                            listing.locator('body').wait_for()
                            listing.page.wait_for_timeout(700)
                            if not tribunais.valid_url(listing.url,self.options.get('tribunal','TJRS'),('citacao_intimacao_prazo_aberto_listar',)):
                                list_coverage.stop('sessao_ou_pagina_nao_confirmada');break
                            snapshot = listing.evaluate(SNAPSHOT)
                            occurrences, listing_tables = open_page(snapshot)
                            numbers=sorted({r['numero'] for r in occurrences if tribunais.from_number(r['numero'])==self.options.get('tribunal','TJRS')})
                            if any(tribunais.from_number(r['numero'])!=self.options.get('tribunal','TJRS') for r in occurrences):
                                list_coverage.stop('numero_tribunal_divergente');break
                            if not list_coverage.accept(occurrences, listing_tables):
                                self.log('Paginação não confirmada: '+list_coverage.reason+'.');break
                            self.update(esperados=list_coverage.expected,paginacao_lista=list_coverage.export())
                            pages.append(public_snapshot(snapshot))
                            self.save_checkpoint(records, pages)
                            for number in numbers:
                                found.setdefault(number, None)
                            found.update(process_links(snapshot,self.options.get('tribunal','TJRS')))
                            from gestao import fingerprints_from_pages
                            fingerprints.update(fingerprints_from_pages([public_snapshot(snapshot)]))
                            from eproc_estruturado import listing as parse_pending
                            from eproc_relatorios import open_listing_rows
                            pending_count=len(open_listing_rows(pages))
                            self.update(encontrados=len(found),registros_lista=pending_count)
                            self.log(f'Página {page_index + 1}: {len(numbers)} processos; {len(found)} únicos até agora.')
                            if mode=='individual' and wanted in found:
                                self.log('Processo solicitado localizado; dispensando as outras páginas.')
                                break
                            if list_coverage.complete:
                                self.log('Total e intervalos disponíveis da lista conferidos; processos repetidos representam intimações distintas.')
                                break
                            enabled = next_enabled(listing)
                            if not enabled:
                                list_coverage.stop('fim_sem_total_conferido')
                                self.log('Fim da paginação não confirmado. O total precisa de conferência.')
                                break
                            old = (page_signature(occurrences),tuple(sorted(page_info(listing_tables)[1])))
                            self.log(f'Etapa: próxima página após página {page_index + 1}.')
                            self.cancelled.wait(2.0)
                            try:
                                enabled[0].click(timeout=45000)
                            except Exception as exc:
                                list_coverage.stop('falha_ao_abrir_proxima_pagina')
                                self.log(self.diagnostic(exc, 'Próxima página') + ' Preservando a lista; paginação não confirmada.')
                                break
                            if wait_table(self,listing,SNAPSHOT,open_page,old) is None:
                                list_coverage.stop('pagina_nao_mudou')
                                self.log('A tabela seguinte não mudou; interrompendo para evitar repetição.')
                                break
                        else:list_coverage.stop('limite_de_paginas')
                        pagination_complete = list_coverage.complete
                        self.update(paginacao_lista=list_coverage.export())
                        self.log(f'Lista de prazos: {list_coverage.rows}/{list_coverage.expected} registros; {list_coverage.pages} páginas; motivo: {list_coverage.reason}.')
                        from gestao import fingerprints_from_pages
                        fingerprints=fingerprints_from_pages(pages)
                        pages_by_case=case_pages(pages)
                        if getattr(self,'actor',None):
                            from juridico import store
                            from eproc_relatorios import case_listing_pages
                            initial_pages=pages_by_case.get(wanted,[]) if mode=='individual' else case_listing_pages(pages)
                            if initial_pages:
                                basic=store.import_corpus({'execucao':{'id':self.current['id']+':lista','fim':now()},'processos':[],'paginas_da_lista':initial_pages},self.actor)
                                self.log(f'Lista gravada no sistema: {basic["total"]} processos com dados básicos disponíveis antes dos detalhes.')
                        self.log('Etapa: leitura de detalhes dos processos.')
                        detail_page = context.new_page()
                        import mandados
                        from juridico import store as mandate_store
                        watch=mandados.status(mandate_store)
                        urgent=set(watch['numeros']) if watch['estado'].get('somente_lista')=='1' else set()
                        urgent.update(deadline_priority)
                        self.log(f'Prioridade de acompanhamento: {len(urgent)} processos; só os encontrados na lista atual do eproc poderão ser consultados.')
                        import fila_coleta
                        selection={}
                        attempted=set(self.options.get('tentados_rodada',[]))
                        candidates={number:url for number,url in found.items() if number not in attempted}
                        order=fila_coleta.prepare(mandate_store,candidates,fingerprints,mode,urgent,bool(self.options.get('descobrir_consultas')),selection=selection) if getattr(self,'actor',None) else list(candidates)
                        if selection:
                            selection['ja_tentados_rodada']=len(found)-len(candidates)
                            summary={k:v for k,v in selection.items() if k!='processos'}
                            self.update(selecao_fila=summary)
                            folder=self.data/self.current['id']
                            temp=folder/'selecao_fila.tmp'
                            temp.write_text(json.dumps(selection,ensure_ascii=False,indent=2),encoding='utf-8')
                            temp.replace(folder/'selecao_fila.json')
                            self.log('Seleção da fila: '+str(selection['total_encontrados'])+' encontrados; '+str(selection['selecionados'])+' selecionados; '+str(selection['dispensados_incremental'])+' dispensados pelo incremental; '+str(selection['aguardando_retentativa'])+' aguardando nova tentativa; '+str(selection['fora_da_fila'])+' fora da fila.')
                        order=self.select_details(order,pages)
                        self.log(f'Fila persistente: {len(order)} processos elegíveis nesta rodada.')
                        for number in order:
                            self.check()
                            url=found[number]
                            if mode=='individual' and number!=wanted:continue
                            if getattr(self,'actor',None):
                                from gestao import sync_plan
                                from juridico import store
                                should_read,reason=sync_plan(store,number,fingerprints.get(number,''),mode)
                                if fila_coleta.pending(store,number):
                                    should_read=True;reason='Pendência da fila persistente.'
                                if number in urgent:
                                    should_read=True;reason='Reconsulta prioritária da lista de acompanhamento.'
                                if not should_read:
                                    self.update(ignorados=self.current.get('ignorados',0)+1)
                                    self.log(f'{number}: dispensado — {reason}.')
                                    continue
                                self.log(f'{number}: {reason}.')
                            self.check()
                            if getattr(self,'actor',None):fila_coleta.claim(store,number)
                            record = {'gravado_no_sistema':False, 'processo': number, 'situacao': 'sem_link_de_detalhes', 'detalhes': None}
                            if url:
                                try:
                                    self.log(f'Etapa: detalhes do processo {number}.')
                                    detail_page.goto(url, wait_until='domcontentloaded', timeout=60000)
                                    self.check()
                                    detail_page.wait_for_timeout(700)
                                    from eproc_eventos import expand,reconcile
                                    history_coverage=expand(self,detail_page)
                                    snapshot = detail_page.evaluate(SNAPSHOT)
                                    history_coverage=reconcile(history_coverage,snapshot)
                                    import mandados_documentos
                                    mandados_documentos.capture(number,snapshot)
                                    identity=re.search(r'Nº do processo\s*('+CNJ.pattern.removeprefix(r'\b').removesuffix(r'\b')+')',snapshot['texto'])
                                    if not tribunais.valid_url(detail_page.url,self.options.get('tribunal','TJRS'),('processo_selecionar','processo_consultar')) or not identity or identity.group(1)!=number or detail_page.locator('input[type="password"]').count():
                                        raise ValueError('Página não confirmada')
                                    record.update(situacao='pagina_lida_requer_conferencia', detalhes=public_snapshot(snapshot))
                                    record['detalhes']['cobertura_eventos']=history_coverage
                                    from coleta_evidencias import save_tables
                                    save_tables(DATA / self.current['id'],number,snapshot,history_coverage,
                                                sistema='eproc',tribunal=self.options.get('tribunal','TJRS'),coletado_em=now())
                                    if not history_coverage['completo']:
                                        record['situacao']='historico_parcial'
                                        self.update(historicos_pendentes=self.current.get('historicos_pendentes',0)+1)
                                        self.log(number+': histórico pendente — '+history_coverage['motivo']+'; lacunas não justificadas: '+str(history_coverage['lacunas_nao_justificadas_amostra'])+'.')
                                    elif history_coverage.get('lacunas_justificadas_por_cancelamento'):
                                        self.log(number+': páginas conferidas; numeração ausente justificada por referências explícitas de cancelamento: '+str(history_coverage['lacunas_justificadas_por_cancelamento'])+'. Conteúdo cancelado não recuperado.')
                                    record['detalhes']['complementos']=self.collect_supplements(context,snapshot,number)
                                except InterruptedError:raise
                                except Exception:
                                    record['situacao'] = 'pagina_lida_complementos_pendentes' if record.get('detalhes') else 'falha_na_leitura'
                            records.append(record)
                            self.update(lidos=len(records), falhas=sum(r['detalhes'] is None for r in records))
                            self.log(f"Processo {number}: {record['situacao']} ({len(records)}/{len(found)}).")
                            self.save_checkpoint(records, pages)
                            if getattr(self,'actor',None) and record.get('detalhes'):
                                try:
                                    from juridico import store
                                    store.import_corpus({'execucao':{'id':self.current['id']+':processo:'+re.sub(r'\D','',number),'fim':now()},'processos':[record],'paginas_da_lista':pages_by_case.get(number,[])},self.actor)
                                    record['gravado_no_sistema']=True
                                    self.update(salvos_sistema=self.current.get('salvos_sistema',0)+1)
                                except Exception as exc:
                                    self.log(self.diagnostic(exc,'Gravação do processo no sistema')+' A origem está no checkpoint para reimportação.')
                            if getattr(self,'actor',None):
                                from gestao import sync_save
                                from juridico import store
                                sync_save(store,number,fingerprints.get(number,''),record,self.current['id'])
                                fila_coleta.finish(store,number,record)
                            self.cancelled.wait(2.0)
                        if mode=='individual' and wanted not in found:self.log('Processo solicitado não apareceu nas listas consultadas. Não foram abertos outros processos.')
                        outcome = 'coletado_revisar' if pagination_complete and not self.current['falhas'] and not self.options.get('falhas_anteriores',0) and not self.current.get('historicos_pendentes') and not self.options.get('historicos_anteriores',0) and all(c['completo'] for c in report_coverage) else 'parcial'
                        self.log('Leitura encerrada. Confira as tabelas originais; associações de partes e prazos ainda não foram validadas neste layout.')
                except InterruptedError:
                    raise
                except Exception as exc:
                    self.log(self.diagnostic(exc, 'Coleta'))
                    if self.block_status and not self.background() and any(not p.is_closed() for p in context.pages):
                        self.inspect_blocked(context)
                    elif not self.background() and not self.block_status and any(not p.is_closed() for p in context.pages):
                        self.wait_user('A coleta encontrou uma falha. A janela permanece aberta para você conferir. Clique em Cancelar para salvar os dados parciais, ou em Continuar para encerrar esta tentativa.')
                    raise
                finally:
                    try:
                        context.close()
                    except Exception:
                        pass
        except CollectionBudget:
            outcome='pausado_orcamento'
            self.log('Orçamento desta rodada atingido. A fila preserva os pendentes para a próxima execução.')
        except InterruptedError:
            outcome = 'cancelado'
            self.log('Cancelado pelo usuário. Os registros já lidos serão exportados.')
        except Exception as exc:
            if str(exc) in ('ACAO_HUMANA','LISTA_NAO_CONFIRMADA'):outcome='requer_login'
            if str(exc) in ('HTTP_403','HTTP_429'):
                outcome='bloqueado_http'
                self.log('Acesso recusado pelo tribunal (HTTP '+str(self.block_status)+'). Coleta interrompida antes de prosseguir. Confira o acesso pelo portal oficial; não haverá nova tentativa automática.')
            message = ('Instale as dependências pelo INSTALAR_EPROC.bat.' if str(exc) == 'DEPENDENCIA'
                       else ('A janela do eproc foi fechada. Inicie uma nova coleta e mantenha a janela aberta.' if str(exc) == 'JANELA_FECHADA' else self.diagnostic(exc, 'Encerramento da tentativa')))
            if str(exc) in ('DEPENDENCIA','JANELA_FECHADA'):message+=' '+self.diagnostic(exc,'Encerramento da tentativa')
            self.log(message)
        finally:
            if self.background() and any('acesso requer intervenção' in x.get('mensagem','') for x in (self.current or {}).get('log',[])):outcome='requer_login'
            previous_history=self.options.get('historicos_anteriores',0)
            previous_failures=self.options.get('falhas_anteriores',0)
            if outcome=='coletado_revisar' and (previous_history or previous_failures):outcome='parcial'
            self.update(estado=outcome, fim=now(),
                        tentados_rodada=len(set(self.options.get('tentados_rodada',[]))|{r['processo'] for r in records}),
                        historicos_pendentes_rodada=previous_history+self.current.get('historicos_pendentes',0),
                        falhas_rodada=previous_failures+self.current.get('falhas',0))
            if self.options.get('monitorar_lista') and getattr(self,'actor',None):
                import monitoramento
                from juridico import store
                monitoramento.finish(store,self.current['id'],outcome)
            try:
                self.save_checkpoint(records, pages)
                write_exports(self.data / self.current['id'], records, pages, dict(self.current))
                if getattr(self, 'actor', None) and pages:
                    from juridico import store
                    remaining=[r for r in records if not r.get('gravado_no_sistema')]
                    from eproc_relatorios import case_listing_pages
                    final_pages=case_pages(pages).get(self.options.get('numero',''),[]) if self.options.get('modo')=='individual' else case_listing_pages(pages)
                    if final_pages or remaining:
                        result = store.import_corpus({'execucao': dict(self.current), 'processos': remaining, 'paginas_da_lista': final_pages}, self.actor)
                        self.log(f"Importação no sistema: {result['criados']} novos processos e {result['existentes']} existentes; dados aguardam conferência.")
                    write_exports(self.data / self.current['id'], records, pages, dict(self.current))
            except Exception:
                self.update(estado='erro_exportacao', mensagem='Não foi possível gravar a exportação. Confira espaço e permissões da pasta.')
                if self.options.get('monitorar_lista') and getattr(self,'actor',None):
                    import monitoramento
                    from juridico import store
                    monitoramento.finish(store,self.current['id'],'erro_exportacao')


collector = Collector()
