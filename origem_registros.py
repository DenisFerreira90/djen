"""Provenance shown to the team; never infer system or instance from CNJ."""
import re,unicodedata
from urllib.parse import urlsplit,parse_qs

PORTALS={
 'EPROC_TJRS_1G':('TJRS','eproc','1','https://eproc1g.tjrs.jus.br/eproc/'),
 'EPROC_TJSC_1G':('TJSC','eproc','1','https://eproc1g.tjsc.jus.br/eproc/'),
 'EPROC_TJRJ_1G':('TJRJ','eproc','1','https://eproc1g.tjrj.jus.br/eproc/'),
 'PJE_RJ_1G':('TJRJ','pje','1','https://tjrj.pje.jus.br/1g/'),
 'PJE_PE_1G':('TJPE','pje','1','https://pje.cloud.tjpe.jus.br/1g/'),
 'PJE_PE_2G':('TJPE','pje','2','https://pje.cloud.tjpe.jus.br/2g/'),
 'PJE_BA_1G':('TJBA','pje','1','https://pje.tjba.jus.br/pje/'),
 'PJE_BA_2G':('TJBA','pje','2','https://pje2g.tjba.jus.br/pje/'),
 'DJEN':('','djen','','https://comunica.pje.jus.br/'),
}
LABELS={'eproc':'eproc','pje':'PJe','esaj':'e-SAJ','projudi':'Projudi','djen':'DJEN','manual':'Cadastro da equipe','planilha':'Planilha'}

def norm(value):return ''.join(c for c in unicodedata.normalize('NFD',str(value or '').lower()) if not unicodedata.combining(c)).strip()

def system(value):
    value=norm(value)
    if value.startswith('eproc'):return 'eproc'
    if value.startswith('pje'):return 'pje'
    if value in ('e-saj','esaj'):return 'esaj'
    if value in LABELS:return value
    return ''

def degree(value):
    value=norm(value).replace('º','').replace('°','').replace('grau','').replace('g','').strip()
    return value if value in ('1','2') else ''

def portal_for_url(value):
    try:
        url=urlsplit(value)
        if url.scheme!='https' or url.username or url.password or url.port not in (None,443):return None
        for key,config in PORTALS.items():
            base=urlsplit(config[3])
            if url.hostname==base.hostname and (url.path.rstrip('/')+'/').startswith(base.path):return key
    except (ValueError,TypeError):pass
    return None

def stable_link(value):
    key=portal_for_url(value)
    if not key:return None
    url=urlsplit(value);query=parse_qs(url.query)
    volatile={'hash','cid','state','nonce','token','access_token','execution','tab_id','code','session_state'}
    if url.fragment or volatile.intersection(k.lower() for k in query) or 'jsessionid' in url.path.lower():return None
    action=query.get('acao',[''])[0]
    if action and action not in ('processo_selecionar','processo_consultar'):return None
    if any(word in norm(url.path) for word in ('login','peticionar','assinar','ciencia','responder','logout')):return None
    config=PORTALS[key]
    if value!=config[3] and config[1]=='eproc' and (url.path!='/eproc/controlador.php' or action not in ('processo_selecionar','processo_consultar')):return None
    if value!=config[3] and config[1]=='pje' and not any(word in norm(url.path) for word in ('consultaprocesso','autosdigitais','painel/painel_usuario/advogado.seam')):return None
    return value

def provenance(data,case=None,case_id=None):
    case=case or {}
    def field(*keys):
        for source in (data,case):
            for key in keys:
                if source.get(key) not in (None,''):return str(source[key])
        return ''
    number=field('numero','numero_processo')
    tribunal=field('tribunal').upper()
    if not tribunal and re.fullmatch(r'\d{7}-\d{2}\.\d{4}\.8\.\d{2}\.\d{4}',number):
        tribunal={'05':'TJBA','17':'TJPE','19':'TJRJ','21':'TJRS','24':'TJSC','26':'TJSP'}.get(number.split('.')[3],'')
    own_system=system(data.get('sistema_origem') or data.get('sistema')) or system(data.get('origem'))
    case_system=system(case.get('sistema_origem') or case.get('sistema')) or system(case.get('origem'))
    origin=own_system or case_system
    separate=bool(own_system and case_system and own_system!=case_system)
    grade=degree(data.get('grau') if separate else field('grau'))
    portal=str(data.get('portal_origem') or '') if separate else field('portal_origem');explicit=PORTALS.get(portal)
    raw=str(data.get('link_origem') or data.get('url_origem') or '') if separate else field('link_origem','url_origem');link=stable_link(raw) if raw else None
    linked=PORTALS.get(portal_for_url(raw)) if raw else None
    # A known URL may establish its portal, not the truth of its process content.
    config=linked or explicit
    conflict=False
    if config:
        conflict=bool((tribunal and config[0] and tribunal!=config[0]) or (origin and origin!=config[1]) or (grade and config[2] and grade!=config[2]))
        if not conflict:
            tribunal=tribunal or config[0];origin=origin or config[1];grade=grade or config[2]
        else:link=None
    known=next((v for v in PORTALS.values() if v[:3]==(tribunal,origin,grade)),None)
    if origin=='djen' and not known:known=PORTALS['DJEN']
    missing=[]
    if not tribunal:missing.append('tribunal')
    if not origin:missing.append('sistema')
    if origin!='djen' and not grade:missing.append('grau')
    orgao=field('orgao','vara','juizo_codigo');comarca=field('comarca')
    if not comarca:missing.append('comarca')
    if not orgao:missing.append('vara/órgão')
    if conflict:missing.append('origem divergente')
    destination=link or (known[3] if known and not conflict else '')
    direct=bool(link and link!=PORTALS.get(portal_for_url(link),('','','',''))[3])
    return {'processo_id':case_id,'numero':number,'tribunal':tribunal or 'Não informado','sistema':LABELS.get(origin,'Não informado'),
            'grau':(grade+'º grau') if grade else ('Publicação nacional' if origin=='djen' else 'Não informado'),
            'comarca':comarca or 'Não informada','orgao':orgao or 'Não informado','fonte':field('fonte','origem') or 'Não informada',
            'url':destination,'tipo_link':'origem' if direct else 'portal' if destination else 'indisponivel',
            'origem_pendente':bool(missing),'campos_pendentes':missing,'link_pendente':not bool(destination),
            'aviso_link':'Confira o processo na origem; a sessão do tribunal pode ser exigida.' if direct else 'Abre o portal correspondente. Use o número CNJ para localizar o processo.' if destination else 'Cadastre sistema, grau e origem para habilitar o direcionamento.'}
