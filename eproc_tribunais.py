"""Entradas fixas por tribunal; nenhum endereço de sessão é persistido."""
import re
from urllib.parse import urlsplit, parse_qs
TRIBUNAIS = {
    'TJRS': {'host':'eproc1g.tjrs.jus.br','sso':'sso.tjrs.jus.br','sessao':'sessao','codigo':'21'},
    'TJSC': {'host':'eproc1g.tjsc.jus.br','sso':'sso.tjsc.jus.br','sessao':'sessao_tjsc','codigo':'24'},
}
def config(tribunal='TJRS'):
    if not isinstance(tribunal,str) or tribunal not in TRIBUNAIS:
        raise ValueError('Tribunal inválido. Selecione TJRS ou TJSC.')
    return TRIBUNAIS[tribunal]
def from_number(number):
    match=re.fullmatch(r'\d{7}-\d{2}\.\d{4}\.8\.(21|24)\.\d{4}',str(number))
    return {'21':'TJRS','24':'TJSC'}.get(match[1],'') if match else ''
def valid_url(value,tribunal='TJRS',actions=None):
    cfg=config(tribunal)
    if not isinstance(value,str) or len(value)>4096:return False
    try:u=urlsplit(value);port=u.port
    except ValueError:return False
    if not (u.scheme=='https' and u.hostname==cfg['host'] and u.path=='/eproc/controlador.php' and not u.username and not u.password and port in (None,443) and not u.fragment):return False
    selected=parse_qs(u.query).get('acao',[])
    return len(selected)==1 and (actions is None or selected[0] in actions)
def entry(tribunal='TJRS'):
    return 'https://'+config(tribunal)['host']+'/eproc/'
