"""Opcional: credenciais apenas na memória do processo, sem gravar senha em arquivo."""
import getpass
import os
import servidor

if __name__ == '__main__':
    tribunal = input('Tribunal [TJRS / TJSC / TJRJ] (padrão TJRS): ').strip().upper() or 'TJRS'
    if tribunal not in ('TJRS','TJSC','TJRJ'):
        raise SystemExit('Tribunal inválido.')
    prefix = 'EPROC' if tribunal == 'TJRS' else 'EPROC_' + tribunal
    os.environ[prefix + '_USUARIO'] = input('Usuário eproc ' + tribunal + ': ').strip()
    os.environ[prefix + '_SENHA'] = getpass.getpass('Senha eproc (não será exibida): ')
    servidor.main()
