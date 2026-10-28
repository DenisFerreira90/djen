"""Opcional: credenciais apenas na memória do processo, sem gravar senha em arquivo."""
import getpass
import os
import servidor

if __name__ == '__main__':
    os.environ['EPROC_USUARIO'] = input('Usuário eproc: ').strip()
    os.environ['EPROC_SENHA'] = getpass.getpass('Senha eproc (não será exibida): ')
    servidor.main()
