"""Prepare a private HTTPS pilot. Does not change firewall, DNS or VPN."""
from pathlib import Path
from configurar_piloto_rede import configure
if __name__=='__main__':
    try:
        print('Piloto completo ConectaAdv: peça ao TI IP fixo, nome interno e faixas LAN/VPN.')
        origin=input('Endereço HTTPS interno (ex.: https://conectaadv.interno:9443): ').strip()
        bind=input('IP privado fixo do computador servidor: ').strip()
        networks=[v.strip() for v in input('Redes privadas autorizadas em CIDR, separadas por vírgula: ').split(',') if v.strip()]
        result=configure(Path(__file__).resolve().parent/'rede_escritorio',origin,bind,networks,chat_port=8765)
        print('Configuração preparada: '+result)
        print('O TI deve configurar resolução do nome, confiança no certificado HTTPS e firewall restrito à LAN/VPN.')
        print('Use INICIAR_REDE_ESCRITORIO.bat e, em outra janela, INICIAR_PROXY_ESCRITORIO.bat.')
    except (ValueError,OSError,KeyError) as exc:
        print('Não foi possível configurar: '+str(exc));raise SystemExit(1)
