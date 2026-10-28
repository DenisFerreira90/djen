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
 const tables = [...document.querySelectorAll('table')].filter(visible).map(t => ({
  titulo: t.caption?.innerText || t.getAttribute('aria-label') || '',
  linhas: [...t.rows].filter(visible).map(r => [...r.cells].map(c => c.innerText.trim()))
 }));
 const links = [...document.querySelectorAll('a[href]')].filter(visible).map(a => ({texto:a.innerText.trim(),url:a.href}));
 return {texto:document.body.innerText, tabelas:tables, links};
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
        for name in ('processos.csv', 'processos.json', 'execucao.json', 'log.jsonl'):
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
            return {'ok': True, 'atual': dict(self.current) if self.current else None, 'historico': history[:100]}

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
        tribunal=options.get("tribunal","TJRS")
        tribunais.config(tribunal)
        options["tribunal"]=tribunal
        if options.get("modo")=="individual" and tribunais.from_number(options.get("numero",""))!=tribunal:
            raise ValueError("O número do processo não corresponde ao tribunal selecionado.")
        with self.lock:
            if self.thread and self.thread.is_alive():
                raise ValueError('Já existe uma coleta em andamento.')
            run = dt.datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8]
            (self.data / run).mkdir(parents=True)
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
        if getattr(self,'deadline',None) and time.monotonic()>=self.deadline:raise CollectionBudget()
        if getattr(self, 'block_status', None):
            raise RuntimeError('HTTP_' + str(self.block_status))
        if self.cancelled.is_set():
            raise InterruptedError()

    def wait_user(self, message):
        if self.options.get('automatico'):
            self.log('Coleta automática interrompida: acesso requer intervenção. Abra uma coleta manual para renovar a sessão.')
            raise RuntimeError('ACAO_HUMANA')
        self.resume.clear()
        self.update(estado='aguardando')
        self.log(message)
        while not self.resume.wait(0.5):
            self.check()
        self.check()
        self.update(estado='coletando')

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
                valid[0].click(timeout=15000)
                return True
        return False

    def find_list(self, context):
        for frame in self.surfaces(context):
            if tribunais.valid_url(frame.url,self.options.get('tribunal','TJRS'),('citacao_intimacao_prazo_aberto_listar',)):
                return frame
        return None

    def diagnostic(self, exc, stage):
        # No exception text: Playwright errors can include auth URLs or typed secrets.
        names = {'TimeoutError': 'tempo de carregamento excedido',
                 'TargetClosedError': 'janela do navegador foi fechada',
                 'Error': 'navegação ou página mudou durante a operação'}
        kind = type(exc).__name__
        location = traceback.extract_tb(exc.__traceback__)[-1] if exc.__traceback__ else None
        local = f' · linha {location.lineno}' if location and Path(location.filename).name == 'eproc.py' else ''
        return f'{stage}: {names.get(kind, "falha na operação")} ({kind}{local}).'

    def open_login(self, context):
        page = context.pages[0] if context.pages else context.new_page()
        self.log('Abrindo a entrada do eproc. A janela permanecerá aberta para o login.')
        try:
            page.goto(tribunais.entry(self.options.get('tribunal','TJRS')), wait_until='domcontentloaded', timeout=60000)
        except Exception as exc:
            self.log(self.diagnostic(exc, 'Abertura do eproc') + ' Conclua o acesso na janela aberta.')
        tribunal=self.options.get('tribunal','TJRS')
        prefix='EPROC' if tribunal=='TJRS' else 'EPROC_TJSC'
        username, password = os.environ.get(prefix+'_USUARIO'), os.environ.get(prefix+'_SENHA')
        if username and password:
            try:
                host = urlsplit(page.url).hostname or ''
                if host == tribunais.config(tribunal)['sso']:
                    u, p = page.locator('input[name="username"]'), page.locator('input[name="password"]')
                    submit = page.locator('#kc-login')
                    if u.count() == p.count() == submit.count() == 1:
                        u.fill(username, timeout=10000)
                        p.fill(password, timeout=10000)
                        submit.click(timeout=15000)
                        self.log('Formulário de login enviado. Conclua eventual autenticação adicional.')
            except Exception as exc:
                self.log(self.diagnostic(exc, 'Preenchimento do login') + ' Você pode preencher manualmente.')
        if self.options.get('automatico'):return
        self.wait_user('Faça o login na janela do eproc, sem limite de tempo. Quando chegar ao perfil ou painel, volte ao nosso sistema e clique em Continuar após login / seleção.')

    def await_listing(self, context):
        # Re-check after each explicit continuation. A premature click never ends the run.
        while True:
            self.check()
            if not any(not p.is_closed() for p in context.pages):
                raise RuntimeError('JANELA_FECHADA')
            try:
                listing = self.find_list(context)
                if listing:
                    return listing
                for frame in self.surfaces(context):
                    if urlsplit(frame.url).hostname!=tribunais.config(self.options.get('tribunal','TJRS'))['host']:continue
                    profiles = frame.locator('button[data-descricao="ADVOGADO-TITULAR"]')
                    if not profiles.count():profiles = frame.get_by_text('ADVOGADO-TITULAR', exact=True)
                    if profiles.count() == 1 and profiles.first.is_visible():
                        profiles.first.click(timeout=15000)
                        self.log('Perfil ADVOGADO-TITULAR selecionado.')
                        break
                    if profiles.count() > 1:
                        self.wait_user('Há mais de um perfil titular. Selecione a conta desejada na janela e clique em Continuar.')
                        break
                # Pump browser events: redirects and new frame/tab creation are asynchronous.
                opened = False
                for _ in range(40):
                    self.check()
                    listing = self.find_list(context)
                    if listing:
                        return listing
                    if not opened:
                        opened = self.listing(context)
                    live_pages = [p for p in context.pages if not p.is_closed()]
                    if not live_pages:
                        raise RuntimeError('JANELA_FECHADA')
                    live_pages[0].wait_for_timeout(250)
            except InterruptedError:
                raise
            except Exception as exc:
                if str(exc) == 'JANELA_FECHADA':
                    raise
                self.log(self.diagnostic(exc, 'Localização do painel/lista'))
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
        records, pages = [], []
        context = None
        outcome = 'erro'
        try:
            try:
                from playwright.sync_api import sync_playwright
            except ImportError:
                raise RuntimeError('DEPENDENCIA')
            with sync_playwright() as pw:
                context = pw.chromium.launch_persistent_context(str(self.data / tribunais.config(self.options.get('tribunal','TJRS'))['sessao']), headless=bool(self.options.get('automatico')),
                                                               accept_downloads=False)
                context.on('response', self.observe_response)
                try:
                    self.open_login(context)
                    listing = self.await_listing(context)
                    self.log('Lista localizada. Lendo páginas e preservando as linhas originais.')
                    found, seen, fingerprints = {}, set(), {}
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
                    pagination_complete = False
                    for page_index in range(1000):
                        self.check()
                        listing.locator('body').wait_for()
                        listing.page.wait_for_timeout(700)
                        snapshot = listing.evaluate(SNAPSHOT)
                        from eproc_estruturado import listing as parse_pending
                        occurrences=parse_pending([public_snapshot(snapshot)])
                        numbers=sorted({r['numero'] for r in occurrences if tribunais.from_number(r['numero'])==self.options.get('tribunal','TJRS')})
                        totals=[re.search(r'([\d.]+)\s+registros?',t.get('titulo',''),re.I) for t in snapshot.get('tabelas',[]) if t.get('linhas') and {'Processo','Evento e Prazo','Final Prazo'}<=set(t['linhas'][0])]
                        announced=next((int(m[1].replace('.','')) for m in totals if m),None)
                        if announced is not None:self.update(esperados=announced)
                        signature = hashlib.sha256(json.dumps(snapshot.get('tabelas',[]),sort_keys=True).encode()).hexdigest()
                        if not numbers or signature in seen:
                            self.log('Lista vazia ou página repetida: coleta marcada como parcial para conferência.')
                            break
                        seen.add(signature)
                        pages.append(public_snapshot(snapshot))
                        self.save_checkpoint(records, pages)
                        for number in numbers:
                            found.setdefault(number, None)
                        found.update(process_links(snapshot,self.options.get('tribunal','TJRS')))
                        from gestao import fingerprints_from_pages
                        fingerprints.update(fingerprints_from_pages([public_snapshot(snapshot)]))
                        from eproc_estruturado import listing as parse_pending
                        pending_count=len(parse_pending(pages))
                        self.update(encontrados=len(found),registros_lista=pending_count)
                        self.log(f'Página {page_index + 1}: {len(numbers)} processos; {len(found)} únicos até agora.')
                        if mode=='individual' and wanted in found:
                            self.log('Processo solicitado localizado; dispensando as outras páginas.')
                            break
                        if self.current.get('esperados') is not None and pending_count==self.current['esperados']:
                            pagination_complete=True
                            self.log('Total de registros da lista confirmado; processos repetidos representam intimações distintas.')
                            break
                        # Never guess numbered URLs or click generic arrows that could be actions.
                        from eproc_relatorios import NEXT
                        next_link = listing.locator(NEXT)
                        enabled = [next_link.nth(i) for i in range(next_link.count())
                                   if next_link.nth(i).get_attribute('aria-disabled') != 'true'
                                   and 'disabled' not in (next_link.nth(i).get_attribute('class') or '').lower()
                                   and not next_link.nth(i).evaluate("e => !!e.closest('[disabled], [aria-disabled=\"true\"], .disabled')")]
                        if not enabled:
                            expected = self.current['esperados']
                            pagination_complete = expected is not None and pending_count == expected
                            if not pagination_complete:
                                self.log('Fim da paginação não confirmado. O total precisa de conferência.')
                            break
                        old = listing.locator('body').inner_text()
                        self.log(f'Etapa: próxima página após página {page_index + 1}.')
                        self.cancelled.wait(2.0)
                        try:
                            enabled[0].click(timeout=45000)
                        except Exception as exc:
                            self.log(self.diagnostic(exc, 'Próxima página') + ' Preservando a lista e seguindo para os detalhes disponíveis; paginação não confirmada.')
                            break
                        changed = False
                        for _ in range(120):
                            self.check()
                            listing.page.wait_for_timeout(250)
                            try:next_text=listing.locator('body').inner_text()
                            except Exception:continue
                            if next_text != old:
                                changed = True
                                break
                        if not changed:
                            self.log('A página seguinte não mudou; interrompendo para evitar repetição.')
                            break
                    from gestao import fingerprints_from_pages
                    fingerprints=fingerprints_from_pages(pages)
                    pages_by_case=case_pages(pages)
                    if getattr(self,'actor',None):
                        from juridico import store
                        initial_pages=pages_by_case.get(wanted,[]) if mode=='individual' else pages
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
                    order=fila_coleta.prepare(mandate_store,found,fingerprints,mode,urgent,bool(self.options.get('descobrir_consultas'))) if getattr(self,'actor',None) else list(found)
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
                                from eproc_eventos import expand
                                history_coverage=expand(self,detail_page)
                                snapshot = detail_page.evaluate(SNAPSHOT)
                                identity=re.search(r'Nº do processo\s*('+CNJ.pattern.removeprefix(r'\b').removesuffix(r'\b')+')',snapshot['texto'])
                                if not tribunais.valid_url(detail_page.url,self.options.get('tribunal','TJRS'),('processo_selecionar','processo_consultar')) or not identity or identity.group(1)!=number or detail_page.locator('input[type="password"]').count():
                                    raise ValueError('Página não confirmada')
                                record.update(situacao='pagina_lida_requer_conferencia', detalhes=public_snapshot(snapshot))
                                record['detalhes']['cobertura_eventos']=history_coverage
                                if not history_coverage['completo']:
                                    record['situacao']='historico_parcial'
                                    self.update(historicos_pendentes=self.current.get('historicos_pendentes',0)+1)
                                    self.log(number+': histórico não confirmado; ficará pendente de nova consulta.')
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
                    outcome = 'coletado_revisar' if pagination_complete and not self.current['falhas'] and not self.current.get('historicos_pendentes') and all(c['completo'] for c in report_coverage) else 'parcial'
                    self.log('Leitura encerrada. Confira as tabelas originais; associações de partes e prazos ainda não foram validadas neste layout.')
                except InterruptedError:
                    raise
                except Exception as exc:
                    self.log(self.diagnostic(exc, 'Coleta'))
                    if any(not p.is_closed() for p in context.pages):
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
            message = ('Instale as dependências pelo INSTALAR_EPROC.bat.' if str(exc) == 'DEPENDENCIA'
                       else ('A janela do eproc foi fechada. Inicie uma nova coleta e mantenha a janela aberta.' if str(exc) == 'JANELA_FECHADA' else self.diagnostic(exc, 'Encerramento da tentativa')))
            self.log(message)
        finally:
            if self.options.get('automatico') and any('acesso requer intervenção' in x.get('mensagem','') for x in (self.current or {}).get('log',[])):outcome='requer_login'
            self.update(estado=outcome, fim=now())
            try:
                self.save_checkpoint(records, pages)
                write_exports(self.data / self.current['id'], records, pages, dict(self.current))
                if getattr(self, 'actor', None) and pages:
                    from juridico import store
                    remaining=[r for r in records if not r.get('gravado_no_sistema')]
                    final_pages=case_pages(pages).get(self.options.get('numero',''),[]) if self.options.get('modo')=='individual' else pages
                    result = store.import_corpus({'execucao': dict(self.current), 'processos': remaining, 'paginas_da_lista': final_pages}, self.actor)
                    self.log(f"Importação no sistema: {result['criados']} novos processos e {result['existentes']} existentes; dados aguardam conferência.")
                    write_exports(self.data / self.current['id'], records, pages, dict(self.current))
            except Exception:
                self.update(estado='erro_exportacao', mensagem='Não foi possível gravar a exportação. Confira espaço e permissões da pasta.')


collector = Collector()
