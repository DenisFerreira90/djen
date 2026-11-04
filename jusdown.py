"""Public HTTP reachability, independent from authenticated judicial collection."""
import contextlib
from html.parser import HTMLParser
import hashlib
import re
import unicodedata
import concurrent.futures
import datetime as dt
import ipaddress
import json
from pathlib import Path
import socket
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = Path(__file__).resolve().parent
TZ = dt.timezone(dt.timedelta(hours=-3))
CERT_CNJ = 'https://www.cnj.jus.br/tecnologia-da-informacao-e-comunicacao/justica-4-0/relatorios-de-indisponibilidade/'
NOTICE_SC = 'https://www.tjsc.jus.br/web/processo-eletronico-eproc'
from jusdown_catalogo import CATALOG, COURTS, BY_ID, COURT_IDS


def now():return dt.datetime.now(TZ).isoformat(timespec='seconds')


def validate_url(url):
    p=urllib.parse.urlsplit(url)
    host=(p.hostname or '').lower()
    if p.scheme!='https' or not host.endswith('.jus.br') or p.username or p.password or p.port not in (None,443):
        raise ValueError('Destino fora dos domínios judiciais HTTPS.')
    addresses=socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError('Destino de rede não público.')
    return url


class JudicialRedirect(urllib.request.HTTPRedirectHandler):
    max_redirections=4
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        validate_url(newurl)
        return super().redirect_request(req,fp,code,msg,headers,newurl)


class NoticeLinks(HTMLParser):
    def __init__(self,base):
        super().__init__();self.base=base;self.current=None;self.found=[]
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='a' and attrs.get('href'):self.current=[urllib.parse.urljoin(self.base,attrs['href']),attrs.get('title','')]
    def handle_data(self,data):
        if self.current:self.current[1]+=' '+data
    def handle_endtag(self,tag):
        if tag!='a' or not self.current:return
        url,title=self.current;self.current=None
        title=' '.join(title.split())[:300]
        plain=''.join(c for c in unicodedata.normalize('NFKD',title.lower()) if not unicodedata.combining(c))
        p=urllib.parse.urlsplit(url)
        if (p.scheme=='https' and (p.hostname or '').endswith('.jus.br') and not p.username and not p.password
                and not re.search(r'(?:hash|key|token|session|nonce|state)=',p.query,re.I)
                and re.search(r'manutenc|indisponibil|interrup|instabil',plain) and len(self.found)<12):
            self.found.append({'url':url,'titulo':title})

def notice_links(html,base):
    parser=NoticeLinks(base)
    parser.feed(html)
    return parser.found


class PublicContent(HTMLParser):
    def __init__(self,base):
        super().__init__();self.base=base;self.anchor=None;self.anchors=[];self.cell=None;self.row=None;self.rows=[];self.ignore=0
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag in ('script','style'):self.ignore+=1
        if tag=='a' and attrs.get('href'):self.anchor=[urllib.parse.urljoin(self.base,attrs['href']),attrs.get('title','')]
        if tag=='tr':self.row=[]
        if tag in ('td','th') and self.row is not None:self.cell=''
    def handle_data(self,text):
        if self.ignore:return
        if self.anchor is not None:self.anchor[1]+=' '+text
        if self.cell is not None:self.cell+=' '+text
    def handle_endtag(self,tag):
        if tag in ('script','style'):self.ignore=max(0,self.ignore-1)
        if tag=='a' and self.anchor:
            self.anchors.append(self.anchor);self.anchor=None
        if tag in ('td','th') and self.cell is not None:
            if self.row is not None:self.row.append(' '.join(self.cell.split()))
            self.cell=None
        if tag=='tr' and self.row is not None:self.rows.append(self.row);self.row=None

def public_content(html,base):
    parser=PublicContent(base);parser.feed(html)
    result=[];seen=set()
    def add(url,title):
        title=' '.join(title.split())[:1600]
        key=(url,title)
        if key not in seen and len(result)<60:
            seen.add(key);result.append({'url':url,'titulo':title})
    for row in parser.rows:
        if len(row)>=3 and any(re.search(r'\b\d{2}[./-]\d{2}[./-]\d{4}\b',cell) for cell in row):
            add(base,' | '.join(row))
    for url,title in parser.anchors:
        p=urllib.parse.urlsplit(url)
        plain=''.join(c for c in unicodedata.normalize('NFKD',title.lower()) if not unicodedata.combining(c))
        if (p.scheme=='https' and (p.hostname or '').endswith('.jus.br') and not p.username and not p.password
            and not re.search(r'(?:hash|key|token|session|nonce|state)=',p.query,re.I)
            and len(title.strip())>=24 and re.search(r'manutenc|indisponibil|atualiz|versao|comunicad|instabil|migrac|implant|suspens|prazos|novidade|lanca',plain)):
            add(url,title)
    return result

def probe(item):
    start=time.monotonic()
    result={'id':item['id'],'verificado_em':now(),'http':None,'estado':'sem_resposta','detalhe':''}
    try:
        validate_url(item['url'])
        opener=urllib.request.build_opener(JudicialRedirect())
        request=urllib.request.Request(item['url'],headers={'User-Agent':'ConectaAdv-JUSDOWN/44 (public availability check)'})
        with opener.open(request,timeout=8) as response:
            code=response.status
            content=response.read(131072).decode('utf-8',errors='replace')
            result['avisos']=notice_links(content,response.geturl())
            result['conteudos']=public_content(content,response.geturl())
        result.update(http=code,estado='respondeu' if 200<=code<400 else 'erro_http',detalhe='O endereço público respondeu; autenticação e consultas não foram testadas.')
        title=re.search(r'<title[^>]*>(.*?)</title>',content,re.I|re.S)
        title=title.group(1).lower() if title else ''
        plain=''.join(c for c in unicodedata.normalize('NFKD',title) if not unicodedata.combining(c))
        if re.search(r'manutenc|indisponivel|unavailable|maintenance',plain):
            result.update(estado='pagina_manutencao',detalhe='Página exibiu aviso de manutenção/indisponibilidade. Confira a fonte e a abrangência.')
        elif re.search(r'just a moment|access denied|captcha',plain):
            result.update(estado='acesso_restrito',detalhe='Página de bloqueio ou desafio de acesso; disponibilidade não confirmada.')

    except urllib.error.HTTPError as exc:
        result.update(http=exc.code,estado='acesso_restrito' if exc.code in (401,403,429) else 'erro_http',detalhe='Acesso restrito ou limite de requisições.' if exc.code in (401,403,429) else 'Resposta HTTP de erro no endereço consultado.')
    except ValueError:
        result.update(estado='destino_nao_verificado',detalhe='Redirecionamento ou destino fora da política de verificação.')
    except (OSError,urllib.error.URLError,TimeoutError):
        result['detalhe']='Não respondeu a partir deste computador. Pode ser rede local, DNS ou serviço remoto.'
    except Exception:
        result['detalhe']='Falha na verificação técnica. Consulte o endereço oficial.'
    result['latencia_ms']=round((time.monotonic()-start)*1000)
    return result


def iso(value):
    parsed=dt.datetime.fromisoformat(value)
    if parsed.tzinfo is None:raise ValueError('Data sem fuso horário.')
    return parsed


def color(result,previous=None,network_uncertain=False):
    previous=previous or {}
    failed=result['estado'] in ('sem_resposta','erro_http') and (result.get('http') is None or result['http']>=500)
    consecutive=previous.get('falhas_seguidas',0)+1 if failed else 0
    recovered=previous.get('sucessos_seguidos',0)+1 if result['estado']=='respondeu' else 0
    value='cinza'
    if result['estado']=='respondeu':
        value='amarelo' if result.get('latencia_ms',0)>3000 or (previous.get('cor') in ('vermelho','amarelo') and recovered<2) else 'verde'
    elif failed:value='vermelho' if consecutive>=2 and not network_uncertain else 'amarelo'
    elif result['estado'] in ('erro_http','pagina_manutencao'):value='amarelo'
    return {**result,'cor':value,'falhas_seguidas':consecutive,'sucessos_seguidos':recovered,'rede_incerta':network_uncertain}


def public_url(value):
    url=str(value).strip()
    p=urllib.parse.urlsplit(url)
    if (p.scheme!='https' or not (p.hostname or '').endswith('.jus.br') or p.username or p.password or p.port not in (None,443) or p.query or p.fragment):
        raise ValueError('Use URL pública HTTPS .jus.br, sem parâmetros, hash ou dados de sessão.')
    return urllib.parse.urlunsplit(('https',p.netloc.lower(),p.path or '/','',''))


SLOTS=('08:00','12:30')
def reading_stale(checked,current):
    due=[current.replace(hour=int(t[:2]),minute=int(t[3:]),second=0,microsecond=0) for t in SLOTS]
    latest=max((d for d in due if d<=current),default=(current-dt.timedelta(days=1)).replace(hour=12,minute=30,second=0,microsecond=0))
    return checked<latest and (current-latest).total_seconds()>900


class Monitor:
    def __init__(self,path=None,check=probe):
        self.path=Path(path) if path else BASE/'dados_jusdown'/'jusdown.sqlite3'
        self.check=check
        self.lock=threading.Lock()
        self.busy=False
        self.last={}
        self.started=False
        self.stop_event=threading.Event()
        self.error=None

    @contextlib.contextmanager
    def db(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        conn=sqlite3.connect(self.path,timeout=10)
        conn.execute('CREATE TABLE IF NOT EXISTS portal_catalog (id TEXT PRIMARY KEY, data TEXT NOT NULL, removed INTEGER NOT NULL DEFAULT 0)')
        for seed in CATALOG:conn.execute('INSERT OR IGNORE INTO portal_catalog(id,data) VALUES (?,?)',(seed['id'],json.dumps(seed,ensure_ascii=False)))
        conn.execute('CREATE TABLE IF NOT EXISTS daily_runs (slot TEXT PRIMARY KEY, data TEXT NOT NULL)')
        conn.execute('CREATE TABLE IF NOT EXISTS page_seen (id TEXT PRIMARY KEY, data TEXT NOT NULL)')
        conn.execute('CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY, enabled INTEGER NOT NULL)')
        conn.execute('INSERT OR IGNORE INTO settings VALUES (1,1)')
        conn.execute('CREATE TABLE IF NOT EXISTS checks (id TEXT PRIMARY KEY, data TEXT NOT NULL)')
        conn.execute('CREATE TABLE IF NOT EXISTS history (id TEXT NOT NULL, at TEXT NOT NULL, state TEXT NOT NULL, http INTEGER)')
        conn.execute('CREATE TABLE IF NOT EXISTS courtsettings (id TEXT PRIMARY KEY, enabled INTEGER NOT NULL, data TEXT NOT NULL)')
        conn.execute('CREATE TABLE IF NOT EXISTS endpoints (id TEXT PRIMARY KEY, data TEXT NOT NULL)')
        conn.execute('CREATE TABLE IF NOT EXISTS notices (id TEXT PRIMARY KEY, tribunal TEXT NOT NULL, data TEXT NOT NULL, reviewed INTEGER DEFAULT 0)')
        conn.execute('CREATE TABLE IF NOT EXISTS notes (id INTEGER PRIMARY KEY, data TEXT NOT NULL)')
        conn.execute('CREATE TABLE IF NOT EXISTS alerts (id INTEGER PRIMARY KEY, target TEXT NOT NULL, at TEXT NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL, acknowledged INTEGER DEFAULT 0)')
        conn.commit()
        try:
            with conn:yield conn
        finally:conn.close()

    def catalog(self):
        with self.db() as c:
            overrides={k:json.loads(v) for k,v in c.execute('SELECT id,data FROM endpoints')}
            rows=[json.loads(v) for v, in c.execute('SELECT data FROM portal_catalog WHERE removed=0 ORDER BY id')]
        return [{**item,**overrides.get(item['id'],{})} for item in rows]

    def courts(self):
        return list({r['tribunal']:{**r,'id':r['tribunal']} for r in self.catalog()}.values())

    def court_settings(self):
        with self.db() as c:return {key:bool(enabled) for key,enabled in c.execute('SELECT id,enabled FROM courtsettings')}

    def set_court(self,court,enabled,actor):
        if actor.get('role')!='administrador':raise ValueError('Controle restrito ao administrador.')
        if court not in {c['id'] for c in self.courts()} or not isinstance(enabled,bool):raise ValueError('Informe um tribunal e sua ativação.')
        # Serialize changes with requests so an inactive court cannot be newly queued.
        with self.lock:
            if self.busy:raise ValueError('Aguarde a rodada atual terminar antes de alterar a ativação do tribunal.')
            with self.db() as c:
                c.execute('INSERT OR REPLACE INTO courtsettings VALUES (?,?,?)',(court,int(enabled),json.dumps({'alterado_por':actor['id'],'alterado_em':now()})))
        return {'tribunal':court,'ativo':enabled}

    def status(self,actor=None):
        with self.db() as c:
            enabled=bool(c.execute('SELECT enabled FROM settings WHERE id=1').fetchone()[0])
            results={k:json.loads(v) for k,v in c.execute('SELECT id,data FROM checks')}
            notices=[dict(json.loads(raw),id=key,conferido=bool(reviewed)) for key,raw,reviewed in c.execute('SELECT id,data,reviewed FROM notices ORDER BY rowid DESC LIMIT 200')]
            notes=[dict(json.loads(data),id=key) for key,data in c.execute('SELECT id,data FROM notes ORDER BY id DESC')]
            alerts=[dict(id=r[0],alvo=r[1],data=r[2],tipo=r[3],texto=r[4],reconhecido=bool(r[5])) for r in c.execute('SELECT id,target,at,kind,text,acknowledged FROM alerts ORDER BY id DESC LIMIT 200')]
        settings=self.court_settings()
        admin=actor is None or actor.get('role')=='administrador'
        courts=self.courts()
        visible={c['id'] for c in courts if admin or settings.get(c['id'],True)}
        items=[]
        for item in self.catalog():
            if item['tribunal'] not in visible:continue
            result=results.get(item['id'],{})
            if result.get('url_consultada')!=item.get('url'):result={}
            row={**item,**result,'ativo':settings.get(item['tribunal'],True)}
            row.setdefault('estado','nao_verificado' if item['url'] else 'endpoint_pendente')
            row.setdefault('cor','cinza')
            if row.get('verificado_em'):
                try:
                    if reading_stale(iso(row['verificado_em']),dt.datetime.now(TZ)):
                        row.update(cor='cinza',desatualizado=True)
                except (ValueError,TypeError):row.update(cor='cinza',desatualizado=True)
            row['manutencoes']=[]
            for note in notes:
                if note.get('arquivado') or note['tribunal']!=item['tribunal'] or (note.get('alvo') and note['alvo']!=item['id']):continue
                current=dt.datetime.now(TZ)
                active=(not note.get('inicio') or iso(note['inicio'])<=current) and (not note.get('fim') or iso(note['fim'])>=current)
                note={**note,'situacao':'encerrada' if note.get('fim') and iso(note['fim'])<current else 'em_andamento' if active else 'programada'}
                row['manutencoes'].append(note)
                if note['tipo']=='manutencao' and active:row['manutencao_ativa']=True
            # Maintenance is an independent badge, not a fabricated HTTP failure.
            items.append(row)
        judicial=[r for r in items if r['ativo']]
        summary={k:sum(r['cor']==k for r in judicial) for k in ['verde','amarelo','vermelho','cinza']}
        summary.update(tribunais=sum(settings.get(c['id'],True) for c in courts if c['id'] in visible),instancias=len(judicial),enderecos=sum(bool(r['url']) for r in judicial),pendentes=sum(not r['url'] for r in judicial),portais=sum(settings.get(c['id'],True) for c in courts if c['id'] in visible))
        if admin:summary['inativos']=sum(not settings.get(c['id'],True) for c in courts)
        notes=[n for n in notes if n['tribunal'] in visible]
        notices=[n for n in notices if n['tribunal'] in visible]
        visible_targets={r['id'] for r in items}
        alerts=[a for a in alerts if a['alvo'] in visible or a['alvo'] in visible_targets]
        return {'ativo':enabled,'em_andamento':self.busy,'erro_monitor':self.error,'horarios':['08:00','12:30'],'timezone':'America/Sao_Paulo','rotinas':self.routine_status(actor),'fonte_cnj':CERT_CNJ,'fonte_inventario':'https://www.cnj.jus.br/tribunais/','tribunais':[{**c,'ativo':settings.get(c['id'],True)} for c in courts if c['id'] in visible],'resumo':summary,'itens':items,'lembretes':notes,'comunicados':notices,'alertas':alerts}

    def configure(self,enabled):
        if not isinstance(enabled,bool):raise ValueError('Informe ativar ou pausar.')
        with self.db() as c:c.execute('UPDATE settings SET enabled=? WHERE id=1',(int(enabled),))
        return self.status()

    def save_endpoint(self,body,actor):
        key=body.get('id')
        if key not in {r['id'] for r in self.catalog()}:raise ValueError('Instância desconhecida.')
        url=str(body.get('url','')).strip()
        source=str(body.get('fonte','')).strip()
        system=str(body.get('sistema','')).strip()[:50]
        if not url or not source or not system:raise ValueError('Informe sistema, URL e fonte oficial do endereço.')
        for target in [url,source]:
            p=urllib.parse.urlsplit(target)
            if p.scheme!='https' or not (p.hostname or '').endswith('.jus.br') or p.username or p.password or p.port not in (None,443):raise ValueError('Use somente URLs oficiais HTTPS de domínio .jus.br.')
            if p.query or p.fragment:raise ValueError('Use endereço público sem parâmetros de sessão ou fragmentos.')
        data={'url':url,'fonte_endpoint':source,'sistema':system,'alterado_por':actor['id'],'alterado_em':now()}
        with self.db() as c:
            c.execute('INSERT OR REPLACE INTO endpoints VALUES (?,?)',(key,json.dumps(data,ensure_ascii=False)))
            c.execute('DELETE FROM checks WHERE id=?',(key,))
        return {'salvo':True}

    def save_note(self,body,actor):
        court=body.get('tribunal')
        if court not in {c['id'] for c in self.courts()}:raise ValueError('Tribunal desconhecido.')
        target=body.get('alvo') or ''
        if target and not any(r['id']==target and r['tribunal']==court for r in self.catalog()):raise ValueError('Instância não pertence ao tribunal.')
        kind=body.get('tipo','lembrete')
        text=str(body.get('texto','')).strip()
        source=str(body.get('fonte','')).strip()
        if kind not in ('lembrete','manutencao') or not text or len(text)>2000:raise ValueError('Informe tipo e texto de até 2.000 caracteres.')
        if kind=='manutencao' and (not source.startswith('https://') or not (urllib.parse.urlsplit(source).hostname or '').endswith('.jus.br')):raise ValueError('Manutenção exige o link do comunicado oficial .jus.br.')
        if source and not source.startswith('https://'):raise ValueError('Fonte deve usar HTTPS.')
        start=body.get('inicio') or None
        end=body.get('fim') or None
        due=body.get('lembrar_em') or (start if kind=='manutencao' else None)
        try:
            for value in [start,end,due]:
                if value:iso(value)
            if start and end and iso(end)<iso(start):raise ValueError()
        except (ValueError,TypeError):raise ValueError('Datas inválidas. Informe data, hora e fuso; fim deve ser posterior ao início.')
        if kind=='manutencao' and (not start or not end):raise ValueError('Informe início e fim da manutenção conforme comunicado.')
        data=dict(tribunal=court,alvo=target,tipo=kind,texto=text,fonte=source,inicio=start,fim=end,lembrar_em=due,criado_por=actor['id'],criado_em=now(),arquivado=False)
        with self.db() as c:
            c.execute('INSERT INTO notes(data) VALUES (?)',(json.dumps(data,ensure_ascii=False),))
            key=c.execute('SELECT last_insert_rowid()').fetchone()[0]
        self.emit_reminders()
        return {'id':key}

    def archive_note(self,key,actor):
        with self.db() as c:
            row=c.execute('SELECT data FROM notes WHERE id=?',(key,)).fetchone()
            if not row:raise ValueError('Lembrete não encontrado.')
            data=json.loads(row[0]);data.update(arquivado=True,arquivado_por=actor['id'],arquivado_em=now())
            c.execute('UPDATE notes SET data=? WHERE id=?',(json.dumps(data,ensure_ascii=False),key))
        return {'arquivado':True}

    def review_notice(self,key):
        with self.db() as c:c.execute('UPDATE notices SET reviewed=1 WHERE id=?',(key,))
        return {'conferido':True}

    def acknowledge(self,key):
        with self.db() as c:c.execute('UPDATE alerts SET acknowledged=1 WHERE id=?',(key,))
        return {'reconhecido':True}

    def emit_reminders(self):
        with self.db() as c:
            for key,raw in c.execute('SELECT id,data FROM notes').fetchall():
                note=json.loads(raw)
                if note.get('arquivado') or note.get('notificado') or not note.get('lembrar_em'):continue
                setting=c.execute('SELECT enabled FROM courtsettings WHERE id=?',(note['tribunal'],)).fetchone()
                if setting and not setting[0]:continue
                if iso(note['lembrar_em'])<=dt.datetime.now(TZ):
                    c.execute('INSERT INTO alerts(target,at,kind,text) VALUES (?,?,?,?)',(note.get('alvo') or note['tribunal'],now(),'lembrete',note['texto']))
                    note['notificado']=now()
                    c.execute('UPDATE notes SET data=? WHERE id=?',(json.dumps(note,ensure_ascii=False),key))

    def request(self,court=None):
        if court and court not in {c['id'] for c in self.courts()}:raise ValueError('Tribunal desconhecido.')
        with self.lock:
            if court and not self.court_settings().get(court,True):raise ValueError('Tribunal inativo no JUSDOWN. Reative antes de verificar.')
            if self.busy or time.monotonic()-self.last.get(court or '*',-999999)<60:return False
            self.busy=True
            self.last[court or '*']=time.monotonic()
        slot=now()+'#manual-'+hashlib.sha256(str(time.monotonic()).encode()).hexdigest()[:8]
        with self.db() as c:c.execute('INSERT INTO daily_runs VALUES (?,?)',(slot,json.dumps({'slot':slot,'inicio':now(),'estado':'executando','manual':True,'tribunal':court,'portais':[]},ensure_ascii=False)))
        threading.Thread(target=self.run,args=(court,slot),daemon=True,name='jusdown-check').start()
        return True

    def run(self,court=None,slot=None):
        try:
            settings=self.court_settings()
            targets=[i for i in self.catalog() if i['url'] and settings.get(i['tribunal'],True) and (not court or i['tribunal']==court)]
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                results=list(pool.map(self.check,targets))
                sources={i['url_informacoes']:{**i,'id':'INFO-'+hashlib.sha256(i['url_informacoes'].encode()).hexdigest()[:16],'url':i['url_informacoes']} for i in targets if i.get('url_informacoes')}
                source_results=dict(zip(sources,pool.map(self.check,sources.values())))
            # Widespread lack of response is not proof that all courts went down.
            network_uncertain=len(results)>=5 and sum(r['estado']=='sem_resposta' for r in results)/len(results)>=0.8
            with self.db() as c:
                information={}
                for url,result in source_results.items():
                    previous=c.execute('SELECT data FROM page_seen WHERE id=?',(url,)).fetchone()
                    if result['estado']!='respondeu':
                        information[url]={'estado':'leitura_nao_confirmada','url':url,'detalhe':result.get('detalhe','Falha ao consultar a página pública de informações.'),'novidades':[],'referencias':[]}
                        continue
                    entries=result.get('conteudos',[])
                    before=json.loads(previous[0]) if previous else None
                    old={(x['url'],x['titulo']) for x in (before or [])}
                    fresh=[x for x in entries if (x['url'],x['titulo']) not in old] if before is not None else []
                    state='leitura_sem_informes' if not entries else 'primeira_leitura' if before is None else 'novidades' if fresh else 'sem_novidades_detectadas'
                    information[url]={'estado':state,'url':url,'verificado_em':result['verificado_em'],'novidades':fresh,'referencias':entries,'detalhe':'Leitura de links públicos relevantes da página; conteúdo autenticado, PDFs e páginas dinâmicas não foram examinados.'}
                    c.execute('INSERT OR REPLACE INTO page_seen VALUES (?,?)',(url,json.dumps(entries,ensure_ascii=False)))
                for item,result in zip(targets,results):
                    result['informacoes']=information.get(item.get('url_informacoes'),{'estado':'fonte_nao_configurada','novidades':[],'referencias':[]})
                    prior=c.execute('SELECT data FROM checks WHERE id=?',(item['id'],)).fetchone()
                    previous=json.loads(prior[0]) if prior else {}
                    if previous.get('url_consultada')!=item['url']:previous={}
                    value=color(result,previous,network_uncertain)
                    value['url_consultada']=item['url']
                    for notice in result.get('avisos',[]):
                        nid=hashlib.sha256((item['tribunal']+notice['url']+notice['titulo']).encode()).hexdigest()
                        payload={**notice,'tribunal':item['tribunal'],'detectado_em':now(),'fonte':item['url']}
                        inserted=c.execute('INSERT OR IGNORE INTO notices(id,tribunal,data) VALUES (?,?,?)',(nid,item['tribunal'],json.dumps(payload,ensure_ascii=False))).rowcount
                        if inserted:c.execute('INSERT INTO alerts(target,at,kind,text) VALUES (?,?,?,?)',(item['tribunal'],now(),'comunicado','Comunicado detectado: confira data e abrangência · '+notice['titulo']))
                    if previous.get('cor')!=value['cor'] and (value['cor'] in ('amarelo','vermelho') or (value['cor']=='verde' and previous.get('cor') in ('amarelo','vermelho'))):
                        title={'amarelo':'Instabilidade ou falha inicial','vermelho':'Sem resposta em verificações consecutivas','verde':'Resposta normal restabelecida'}[value['cor']]
                        c.execute('INSERT INTO alerts(target,at,kind,text) VALUES (?,?,?,?)',(item['id'],value['verificado_em'],value['cor'],title+' · '+item['tribunal']+' · '+item['grau']+' · '+(item['unidade'] or item['sistema'])))
                    c.execute('INSERT OR REPLACE INTO checks VALUES (?,?)',(item['id'],json.dumps(value,ensure_ascii=False)))
                    c.execute('INSERT INTO history VALUES (?,?,?,?)',(item['id'],value['verificado_em'],value['cor'],value.get('http')))
                c.execute('DELETE FROM history WHERE rowid NOT IN (SELECT rowid FROM history ORDER BY rowid DESC LIMIT 250000)')
                c.execute('DELETE FROM alerts WHERE id NOT IN (SELECT id FROM alerts ORDER BY id DESC LIMIT 2000)')
            self.error=None
            if slot:self.finish_routine(slot,targets,results)
        except Exception:
            self.error='Falha interna do monitor. Os resultados anteriores foram preservados; confira a última verificação.'
            if slot:
                try:self.fail_routine(slot)
                except (OSError,sqlite3.Error):pass
        finally:
            with self.lock:self.busy=False

    def add_portal(self,body,actor):
        if actor.get('role')!='administrador':raise ValueError('Acesso restrito ao administrador.')
        court=str(body.get('tribunal','')).strip().upper()
        title=str(body.get('nome','')).strip()[:150]
        system=str(body.get('sistema','')).strip()[:50]
        degree=str(body.get('grau','portal'))
        url=public_url(body.get('url',''))
        source=public_url(body.get('url_informacoes','') or url)
        if not re.fullmatch(r'[A-Z][A-Z0-9-]{1,19}',court) or not title or not system or degree not in ('1','2','portal','unificado','superior'):raise ValueError('Informe sigla, nome, sistema e grau válidos.')
        key='P-'+hashlib.sha256(url.encode()).hexdigest()[:16]
        base=next((c for c in self.courts() if c['id']==court),{})
        row={**base,'id':key,'tribunal':court,'nome':base.get('nome') or title,'nome_portal':title,'ramo':base.get('ramo','Meus portais'),'uf':base.get('uf',''),'estados':base.get('estados',''),'grau':degree,'unidade':'','sistema':system,'url':url,'url_informacoes':source,'portal':base.get('portal') or source,'fonte_endpoint':source,'origem':'Adicionado pelo administrador','fonte_certidao':base.get('fonte_certidao'),'tipo_fonte':base.get('tipo_fonte'),'alterado_por':actor['id'],'alterado_em':now()}
        with self.lock:
            if self.busy:raise ValueError('Aguarde a rodada atual terminar para alterar os portais.')
            with self.db() as c:
                existing=c.execute('SELECT removed FROM portal_catalog WHERE id=?',(key,)).fetchone()
                if existing and not existing[0]:raise ValueError('Esse endereço já está na lista.')
                c.execute('INSERT OR REPLACE INTO portal_catalog(id,data,removed) VALUES (?,?,0)',(key,json.dumps(row,ensure_ascii=False)))
                c.execute('DELETE FROM endpoints WHERE id=?',(key,))
                c.execute('DELETE FROM checks WHERE id=?',(key,))
        return {'id':key,'salvo':True}

    def remove_portal(self,key,actor):
        if actor.get('role')!='administrador':raise ValueError('Acesso restrito ao administrador.')
        with self.lock:
            if self.busy:raise ValueError('Aguarde a rodada atual terminar para remover o portal.')
            with self.db() as c:c.execute('UPDATE portal_catalog SET removed=1 WHERE id=?',(key,))
        return {'removido':True}

    def tick(self,current=None):
        current=(current or dt.datetime.now(TZ)).astimezone(TZ)
        if not self.status_enabled():return
        for slot_time in SLOTS:
            due=current.replace(hour=int(slot_time[:2]),minute=int(slot_time[3:]),second=0,microsecond=0)
            if due>current:continue
            key=due.isoformat(timespec='minutes')
            with self.lock:
                with self.db() as c:
                    if c.execute('SELECT 1 FROM daily_runs WHERE slot=?',(key,)).fetchone():continue
                    delay=(current-due).total_seconds()
                    if delay>900:
                        payload={'slot':key,'previsto':due.isoformat(),'estado':'nao_executada','motivo':'Servidor desligado, pausado ou ocupado na janela de execução.','portais':[]}
                        c.execute('INSERT OR IGNORE INTO daily_runs VALUES (?,?)',(key,json.dumps(payload,ensure_ascii=False)))
                        continue
                    if self.busy:continue
                    payload={'slot':key,'previsto':due.isoformat(),'inicio':current.isoformat(),'estado':'executando','portais':[]}
                    if not c.execute('INSERT OR IGNORE INTO daily_runs VALUES (?,?)',(key,json.dumps(payload,ensure_ascii=False))).rowcount:continue
                    self.busy=True
                threading.Thread(target=self.run,args=(None,key),daemon=True,name='jusdown-daily').start()

    def status_enabled(self):
        with self.db() as c:return bool(c.execute('SELECT enabled FROM settings WHERE id=1').fetchone()[0])

    def finish_routine(self,slot,targets,results):
        with self.db() as c:
            raw=c.execute('SELECT data FROM daily_runs WHERE slot=?',(slot,)).fetchone()
            payload=json.loads(raw[0]) if raw else {'slot':slot,'previsto':slot}
            latest={key:json.loads(data) for key,data in c.execute('SELECT id,data FROM checks')}
            payload.update(estado='concluida',fim=now(),portais=[{**item,**latest.get(item['id'],result)} for item,result in zip(targets,results)])
            c.execute('INSERT OR REPLACE INTO daily_runs VALUES (?,?)',(slot,json.dumps(payload,ensure_ascii=False)))
            c.execute('DELETE FROM daily_runs WHERE slot NOT IN (SELECT slot FROM daily_runs ORDER BY slot DESC LIMIT 60)')

    def fail_routine(self,slot):
        with self.db() as c:
            raw=c.execute('SELECT data FROM daily_runs WHERE slot=?',(slot,)).fetchone()
            if raw:
                payload=json.loads(raw[0]);payload.update(estado='falha',fim=now(),motivo='Falha interna do monitor; não equivale a falha dos portais.')
                c.execute('UPDATE daily_runs SET data=? WHERE slot=?',(json.dumps(payload,ensure_ascii=False),slot))

    def routine_status(self,actor=None,slot=None,details=False):
        catalog=self.catalog()
        settings=self.court_settings()
        visible={r['id'] for r in catalog if actor is None or actor.get('role')=='administrador' or settings.get(r['tribunal'],True)}
        with self.db() as c:
            raw=c.execute('SELECT data FROM daily_runs WHERE slot=?',(slot,)).fetchall() if slot else c.execute('SELECT data FROM daily_runs ORDER BY slot DESC LIMIT 60').fetchall()
            rows=[json.loads(data) for data, in raw]
        visible_courts={r['tribunal'] for r in catalog if r['id'] in visible}
        output=[]
        for row in rows:
            if row.get('tribunal') and row['tribunal'] not in visible_courts:continue
            row['portais']=[r for r in row.get('portais',[]) if r['id'] in visible]
            row['quantidade']=len(row['portais'])
            if not details:row.pop('portais',None)
            output.append(row)
        return output

    def start(self):
        with self.lock:
            if self.started:return
            self.started=True
        try:
            with self.db() as c:
                for key,raw in c.execute('SELECT slot,data FROM daily_runs').fetchall():
                    data=json.loads(raw)
                    if data.get('estado')=='executando':
                        data.update(estado='interrompida',motivo='Servidor reiniciado antes de confirmar o encerramento.')
                        c.execute('UPDATE daily_runs SET data=? WHERE slot=?',(json.dumps(data,ensure_ascii=False),key))
        except (OSError,sqlite3.Error):self.error='Banco do JUSDOWN indisponível; demais módulos continuam independentes deste banco.'
        def loop():
            last_reminder=0
            while not self.stop_event.is_set():
                try:
                    self.tick()
                    if time.monotonic()-last_reminder>=60:
                        self.emit_reminders();last_reminder=time.monotonic()
                except (OSError,sqlite3.Error,ValueError):pass
                self.stop_event.wait(1)
        threading.Thread(target=loop,daemon=True,name='jusdown-scheduler').start()

monitor=Monitor()
