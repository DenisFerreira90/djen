"""Política do piloto de chat atrás de proxy HTTPS local, restrito à LAN/VPN."""
import ipaddress
import json
import re
from urllib.parse import urlsplit
import juridico as legal


def load(path):
    from pathlib import Path
    c=json.loads(Path(path).read_text(encoding='utf-8-sig'));u=urlsplit(str(c.get('origem','')))
    if u.scheme!='https' or not u.hostname or u.username or u.password or u.path not in ('','/') or u.query or u.fragment:raise ValueError('Informe uma origem HTTPS sem caminho, credenciais ou parâmetros.')
    if not re.fullmatch(r'[a-zA-Z0-9.-]+',u.hostname):raise ValueError('Nome de host inválido.')
    if u.port is not None and not 1024<=u.port<=65535 and u.port!=443:raise ValueError('Porta HTTPS inválida.')
    networks=c.get('redes_permitidas')
    if not isinstance(networks,list) or not networks:raise ValueError('Informe as redes locais e da VPN.')
    parsed=[]
    for value in networks:
        net=ipaddress.ip_network(value,strict=True)
        if net.version!=4 or not any(net.subnet_of(ipaddress.ip_network(r)) for r in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16')):raise ValueError('Use redes privadas IPv4 explícitas da LAN/VPN.')
        parsed.append(net)
    return {'origem':'https://'+u.netloc.lower(),'host':u.netloc.lower(),'redes':parsed}


def allowed_chat(path,method):
    if path in ('/api/juridico/sessao','/api/juridico/entrar','/api/juridico/sair','/api/juridico/configurar'):return True
    if path=='/api/juridico/usuarios' or re.fullmatch(r'/api/juridico/usuarios/\d+',path):return True
    if path.startswith('/api/juridico/chat/'):return True
    return method=='GET' and path in ('/api/juridico/auditoria','/api/juridico/backup','/api/health')


def origin(handler):
    p=getattr(handler.server,'rede_piloto',None)
    host=handler.headers.get('Host','').lower()
    if p:
        if host!=p['host']:raise legal.AppError('Endereço do servidor não permitido.',403)
        return p['origem']
    port=str(handler.server.server_address[1])
    if host not in ('127.0.0.1:'+port,'localhost:'+port):raise legal.AppError('Host não permitido.',403)
    return 'http://'+host


def check(handler,method):
    path=urlsplit(handler.path).path;p=getattr(handler.server,'rede_piloto',None)
    if p:
        # Somente o proxy do mesmo computador é confiável para informar o cliente.
        if not ipaddress.ip_address(handler.client_address[0]).is_loopback:raise legal.AppError('Acesso permitido somente pelo proxy local.',403)
        origin(handler)
        if handler.headers.get('X-Forwarded-Proto')!='https':raise legal.AppError('Use o endereço HTTPS do escritório.',403)
        forwarded=handler.headers.get('X-Forwarded-For','')
        try:client=ipaddress.ip_address(forwarded)
        except ValueError:raise legal.AppError('Origem de rede não confirmada.',403)
        if not any(client in net for net in p['redes']):raise legal.AppError('Conecte-se à rede do escritório ou à VPN.',403)
    if getattr(handler.server,'chat_only',False) and path.startswith('/api/') and not allowed_chat(path,method):raise legal.AppError('Este piloto disponibiliza apenas comunicação, contas e auditoria.',403)


def peer(handler):
    return handler.headers.get('X-Forwarded-For',handler.client_address[0]) if getattr(handler.server,'rede_piloto',None) else handler.client_address[0]
