"""Gera configuração revisável; não abre firewall nem altera roteador/VPN."""
import ipaddress
import json
from pathlib import Path
import rede_piloto


def configure(folder,origin,bind,networks,chat_port=8766):
    if type(chat_port)is not int or not 1024<=chat_port<=65535:raise ValueError('Porta local inválida.')
    ip=ipaddress.ip_address(bind)
    ranges=[ipaddress.ip_network(n) for n in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16')]
    if ip.version!=4 or not any(ip in n for n in ranges):raise ValueError('Informe o IP privado fixo do computador servidor.')
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True);path=folder/'piloto-rede.json'
    data={'origem':origin,'redes_permitidas':networks}
    # Validação antes de substituir qualquer configuração existente.
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        check=Path(tmp)/'rede.json';check.write_text(json.dumps(data));policy=rede_piloto.load(check)
    origin=policy['origem'];authority=policy['host'];nets=' '.join(str(n) for n in policy['redes'])
    caddy='''# Piloto interno. Restrinja também o firewall à LAN/VPN. Sem encaminhamento público.
ORIGIN {
    bind BIND
    tls internal
    @escritorio remote_ip NETWORKS
    handle @escritorio {
        reverse_proxy 127.0.0.1:CHAT_PORT {
            header_up Host AUTHORITY
            header_up X-Forwarded-For {remote_host}
            header_up X-Forwarded-Proto https
        }
    }
    handle {
        respond "Acesso somente pela rede do escritorio ou VPN." 403
    }
}
'''.replace('CHAT_PORT',str(chat_port)).replace('ORIGIN',origin).replace('BIND',str(ip)).replace('NETWORKS',nets).replace('AUTHORITY',authority)
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');(folder/'Caddyfile').write_text(caddy,encoding='utf-8')
    return origin

if __name__=='__main__':
    try:
        print('Piloto do chat — peça ao responsável pela rede o IP fixo e as faixas LAN/VPN. Não altera firewall automaticamente.')
        origin=input('Endereço HTTPS interno, por exemplo https://conectaadv.interno:9443: ').strip()
        bind=input('IP privado fixo do servidor: ').strip()
        nets=[n.strip() for n in input('Redes permitidas em CIDR, separadas por vírgula: ').split(',') if n.strip()]
        print('Configuração gerada para '+configure(Path(__file__).parent,origin,bind,nets))
        print('Revise Caddyfile com o TI, configure o certificado confiável e o firewall. Depois inicie o servidor e o proxy.')
    except (ValueError,OSError,KeyError):
        print('Não foi possível gerar: confira endereço HTTPS, IP privado e faixas CIDR.');raise SystemExit(1)
