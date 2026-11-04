"""Recomeço offline das coletas, com backup e arquivos antigos arquivados."""
from contextlib import closing
from pathlib import Path
import getpass,json,os,socket,uuid,sqlite3
import juridico as legal
import limpar_processos as cleanup


def archives(root):
 data=Path(root)/'dados_eproc'
 return sorted({p.parent for name in ('execucao.json','checkpoint.json','log.jsonl','processos.json') for p in data.glob('*/'+name) if p.parent.name!='sessao' and not p.parent.is_symlink()})


def restart(store,actor,root,expected=None):
 if actor.get('role')!='administrador':raise legal.AppError('Somente administradores podem reiniciar as coletas.',403)
 # Requer servidor parado. Os arquivos ficam fora da pasta lida pelo coletor.
 folder=store.path.parent/'backups'/('coletas-arquivadas-'+uuid.uuid4().hex)
 moves=[]
 try:
  for source in archives(root):
   folder.mkdir(parents=True,exist_ok=True)
   destination=folder/source.name
   source.rename(destination);moves.append((source,destination))
  result=cleanup.clean(store,actor,expected=expected,restart=True)
 except Exception:
  for source,destination in reversed(moves):destination.rename(source)
  raise
 result['arquivos_arquivados']=len(moves);result['pasta_arquivo']=str(folder) if moves else None
 return result


def main():
 import argparse
 parser=argparse.ArgumentParser(description='Zerar coletas antigas e lista, preservando trabalho manual, chat e RH.')
 parser.add_argument('--executar',action='store_true');args=parser.parse_args()
 root=legal.BASE;path=root/'dados_juridico'/'juridico.sqlite3'
 summary=cleanup.preview(path)
 print('RECOMEÇAR AS COLETAS — banco:',path)
 print('Processos importados a remover:',len(summary['processos']))
 print('Trabalho manual/financeiro a preservar sem vínculo:',len(summary['desvincular']))
 print('Execuções antigas a arquivar:',len(archives(root)))
 print('Também zera: lista salva, erros, resultados, referências de comparação, pedidos e agendamentos internos.')
 print('Preserva: usuários, clientes, chat, RH, trabalho manual, histórico de envios, credenciais e sessão eproc.')
 if not args.executar:print('Prévia apenas. Para executar, abra RECOMECAR_COLETAS.bat.');return
 port=int(os.environ.get('DJEN_PORT','8765'))
 try:
  with socket.create_connection(('127.0.0.1',port),timeout=.5):raise ValueError('Feche o servidor jurídico e as coletas antes de continuar.')
 except (ConnectionRefusedError,TimeoutError):pass
 print('Pause também o Agendador de Tarefas/serviço do Windows que possa iniciar uma coleta.')
 login=input('Login administrador do ConectaAdv: ').strip();password=getpass.getpass('Senha do ConectaAdv (não aparece): ')
 store=legal.Store(path)
 with closing(store.connect()) as db:
  row=db.execute('SELECT * FROM users WHERE login=? COLLATE NOCASE AND ativo=1',(login,)).fetchone()
  if not row or row['role']!='administrador' or not store.password(password,row['password']):raise ValueError('Administrador ou senha inválida.')
  actor=store.public_user(row)
 if input('Digite RECOMEÇAR COLETAS para confirmar: ').strip()!='RECOMEÇAR COLETAS':print('Cancelado.');return
 result=restart(store,actor,root,expected=summary)
 print('Limpeza concluída. Backup do banco:',result['backup'])
 print('Execuções arquivadas:',result['arquivos_arquivados']);print('Pasta:',result['pasta_arquivo'] or 'Nenhuma execução antiga')
 print('Abra o sistema, carregue apenas a nova planilha e clique em Procurar. Não reimporte os arquivos antigos.')
if __name__=='__main__':
 try:main()
 except (ValueError,legal.AppError,sqlite3.Error,OSError,EOFError,KeyboardInterrupt) as exc:
  print('Recomeço encerrado:',exc);raise SystemExit(1)
