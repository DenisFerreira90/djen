"""Verifica arquivos e o servidor ativo antes de iniciar o ConectaAdv local."""
from pathlib import Path
import json
import os
import urllib.error
import urllib.request
import webbrowser

ROOT=Path(__file__).resolve().parent
EXPECTED_VERSION='68'

def installation_errors(root=ROOT):
    errors=[]
    if root.name.casefold()=='djen' and root.parent.name.casefold()=='djen':
        errors.append('Foi encontrada uma pasta djen dentro de djen. Copie o conteúdo do pacote para '+str(root.parent)+' e execute o INICIAR.bat dessa pasta.')
    required=('servidor.py','juridico_http.py','estoque.py','js/estoque.js','index.html','mandados_triagem.py','js/mandados.js')
    for name in required:
        if not (root/name).is_file():errors.append('Arquivo ausente: '+str(root/name))
    if errors:return errors
    js=(root/'js/estoque.js').read_text(encoding='utf-8-sig')
    if 'window.Estoque=' not in js:errors.append('O arquivo js/estoque.js não contém o módulo de estoque esperado.')
    index=(root/'index.html').read_text(encoding='utf-8-sig')
    if '/js/estoque.js' not in index:errors.append('O index.html desta pasta não carrega o estoque. Copie também esse arquivo da atualização.')
    server=(root/'servidor.py').read_text(encoding='utf-8-sig')
    if "'/js/estoque.js'" not in server or 'STATIC_MIME' not in server:errors.append('O servidor.py desta pasta não contém a atualização de entrega dos arquivos. Copie o pacote completo.')
    for name in ('servidor.py','estoque.py','juridico_http.py'):
        try:compile((root/name).read_text(encoding='utf-8-sig'),str(root/name),'exec')
        except SyntaxError:errors.append('Arquivo Python incompleto ou inválido: '+name)
    return errors

def running_server(base,opener=None):
    opener=opener or urllib.request.urlopen
    try:
        with opener(base+'/api/health',timeout=3) as response:health=json.loads(response.read(16384))
    except urllib.error.HTTPError:return {'estado':'ocupado','mensagem':'Há outro servidor respondendo nesta porta; a versão do ConectaAdv não foi confirmada.'}
    except (ValueError,UnicodeError):return {'estado':'ocupado','mensagem':'O serviço desta porta não forneceu a identificação esperada do ConectaAdv.'}
    except (urllib.error.URLError,TimeoutError,ConnectionError,OSError):return {'estado':'livre'}
    if not isinstance(health,dict):return {'estado':'ocupado','mensagem':'O serviço desta porta não forneceu a identificação esperada do ConectaAdv.'}
    if health.get('versao_aplicacao')!=EXPECTED_VERSION:return {'estado':'antigo','mensagem':f'O servidor ativo ainda não é a versão {EXPECTED_VERSION}. Atualizar os arquivos não reinicia o processo antigo.'}
    try:
        with opener(base+'/js/estoque.js?v=63',timeout=3) as response:
            ctype=response.headers.get('Content-Type','').split(';')[0].strip().lower()
            snippet=response.read(1024)
            valid=response.status==200 and ctype in ('text/javascript','application/javascript') and b'use strict' in snippet
            if not valid:return {'estado':'arquivo_invalido','mensagem':'O servidor ativo respondeu ao estoque com tipo '+ctype+'. A entrega do JavaScript não foi confirmada.'}
    except urllib.error.HTTPError as error:return {'estado':'arquivo_ausente','mensagem':'O servidor ativo respondeu HTTP '+str(error.code)+' ao arquivo do estoque. Confira a pasta da instalação ativa.'}
    except (urllib.error.URLError,TimeoutError,ConnectionError,OSError):return {'estado':'arquivo_invalido','mensagem':'A resposta do arquivo do estoque não pôde ser confirmada.'}
    return {'estado':'pronto','mensagem':f'Servidor {EXPECTED_VERSION} já está ativo e o JavaScript do estoque está correto.'}

def main():
    print(f'ConectaAdv {EXPECTED_VERSION} — início verificado')
    print('Pasta desta instalação:',ROOT)
    errors=installation_errors()
    if errors:
        for error in errors:print(error)
        print('Copie o conteúdo da pasta djen do pacote completo para esta pasta, preservando os dados.')
        return 1
    try:port=int(os.environ.get('DJEN_PORT','8765'))
    except ValueError:print('A variável DJEN_PORT precisa conter um número de porta.');return 1
    if not 1024<=port<=65535:print('A porta deve estar entre 1024 e 65535.');return 1
    base='http://127.0.0.1:'+str(port)
    status=running_server(base)
    if status['estado']=='pronto':
        print(status['mensagem']);print('Acesse:',base);webbrowser.open(base);return 0
    if status['estado']!='livre':
        print(status['mensagem'])
        print('Encerre o servidor antigo na janela dele com Ctrl+C. Depois abra INICIAR.bat desta pasta novamente.')
        print('Se não localizar essa janela, envie uma foto deste terminal; nenhum processo foi encerrado por este verificador.')
        return 2
    print('Arquivos conferidos. Iniciando o servidor atualizado.')
    import servidor
    servidor.main()
    return 0

if __name__=='__main__':raise SystemExit(main())
