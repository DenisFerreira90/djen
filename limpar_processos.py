"""Limpeza local de processos importados, com prévia e backup obrigatório."""
import collections
from contextlib import closing
import getpass
import json
import os
from pathlib import Path
import socket
import sqlite3
import uuid
import juridico as legal


def tables(db):return {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
def plan(db):
 names=tables(db)
 if not {'users','records','audit'}<=names:raise ValueError('Banco jurídico não reconhecido.')
 records={r['id']:dict(r) for r in db.execute('SELECT * FROM records')}
 imported=set()
 if 'imported_keys' in names:imported={r[0] for r in db.execute('SELECT record_id FROM imported_keys')}
 creations={}
 for row in db.execute("SELECT entidade_id,acao FROM audit WHERE entidade='processos' AND acao IN ('importar_processo','importar','criar') ORDER BY id"):
  if str(row[0]).isdigit():creations[int(row[0])]=row[1]
 imported_cases={rid for rid,action in creations.items() if action in ('importar_processo','importar')}
 edited={int(r[0]) for r in db.execute("SELECT entidade_id FROM audit WHERE acao='alterar' AND entidade IN ('partes','prazos','tarefas','anotacoes','documentos','financeiro')") if str(r[0]).isdigit()}
 cases={rid for rid,r in records.items() if r['kind']=='processos' and (rid in imported or rid in imported_cases)}
 descendants=set(cases)
 while True:
  more={rid for rid,r in records.items() if r['case_id'] in descendants}-descendants
  if not more:break
  descendants.update(more)
 deleted=cases|{rid for rid in descendants-cases if rid in imported and rid not in edited and records[rid]['kind'] not in ('pessoas','financeiro')}
 detached={rid for rid,r in records.items() if rid not in deleted and r['case_id'] in deleted}
 counts=dict(collections.Counter(records[rid]['kind'] for rid in deleted))
 return {'apagar':sorted(deleted),'processos':sorted(cases),'desvincular':sorted(detached),'contagens':counts,'numeros':[json.loads(records[rid]['data']).get('numero','') for rid in cases],'preservados':len(records)-len(deleted)}

def preview(path):
 path=Path(path).resolve()
 if not path.is_file():raise ValueError('Banco não encontrado. Extraia os arquivos dentro da pasta djen em uso.')
 with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
  db.row_factory=sqlite3.Row
  return plan(db)

def clean(store,actor,expected=None):
 if actor.get('role')!='administrador':raise legal.AppError('Limpeza restrita à conta administradora.',403)
 if store.path.name=='chat.sqlite3':raise ValueError('Esta ferramenta não opera sobre o banco do chat.')
 with closing(store.connect()) as db:
  db.execute('BEGIN IMMEDIATE')
  try:
   summary=plan(db)
   if expected is not None and any(summary[k]!=expected[k] for k in ('apagar','desvincular','processos')):raise ValueError('Os dados mudaram desde a prévia. Execute novamente para conferir.')
   if not summary['processos']:db.rollback();return {'removidos':0,'backup':None,'resumo':summary}
   account=db.execute('SELECT * FROM users WHERE id=? AND ativo=1 AND role=?',(actor['id'],'administrador')).fetchone()
   if not account:raise ValueError('Conta administradora indisponível.')
   folder=store.path.parent/'backups';folder.mkdir(exist_ok=True)
   backup=folder/('antes-limpar-processos-'+uuid.uuid4().hex+'.sqlite3')
   # BEGIN IMMEDIATE bloqueia outro escritor, mas permite a conexão de leitura do backup.
   try:
    with closing(sqlite3.connect(store.path.resolve().as_uri()+'?mode=ro',uri=True)) as src,closing(sqlite3.connect(backup)) as out:
     src.backup(out)
     if out.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('O backup falhou na verificação de integridade.')
   except Exception:
    if backup.exists():backup.unlink()
    raise
   names=tables(db)
   db.execute('CREATE TEMP TABLE cleanup_ids(id INTEGER PRIMARY KEY)')
   db.executemany('INSERT INTO cleanup_ids VALUES(?)',[(i,) for i in summary['apagar']])
   db.execute('CREATE TEMP TABLE cleanup_numbers(numero TEXT PRIMARY KEY)')
   db.executemany('INSERT OR IGNORE INTO cleanup_numbers VALUES(?)',[(n,) for n in summary['numeros'] if n])
   # Preservar trabalho manual e financeiro; anotar o processo original ao desvincular.
   for rid in summary['desvincular']:
    row=db.execute('SELECT * FROM records WHERE id=?',(rid,)).fetchone();before=json.loads(row['data']);after=dict(before)
    parent=db.execute('SELECT data FROM records WHERE id=?',(row['case_id'],)).fetchone()
    number=json.loads(parent[0]).get('numero','') if parent else ''
    note='Vínculo removido na limpeza dos processos importados'+(' — processo '+number if number else '')+'.'
    after['observacoes']=(str(after.get('observacoes','')).strip()+'\n'+note).strip()
    if row['kind']=='partes' and after.get('representa_id') in summary['apagar']:after['representa_id']=None
    db.execute('UPDATE records SET case_id=NULL,data=?,version=version+1,atualizado=?,atualizado_por=? WHERE id=?',(legal.dumps(after),legal.now(),actor['id'],rid))
    store.audit(db,actor,'preservar_ao_limpar_processos',row['kind'],rid,before,after)
   for table in ('evidence','source_events','source_complements','control_items','mandate_alerts'):
    if table in names:db.execute('DELETE FROM '+table+' WHERE case_id IN (SELECT id FROM cleanup_ids)')
   if 'imported_keys'in names:
    db.execute('DELETE FROM imported_keys WHERE record_id IN (SELECT id FROM cleanup_ids)')
    db.executemany('DELETE FROM imported_keys WHERE record_id=?',[(i,) for i in summary['desvincular']])
   for table in ('sync_state','collection_queue'):
    if table in names:db.execute('DELETE FROM '+table+' WHERE numero IN (SELECT numero FROM cleanup_numbers)')
   db.execute('DELETE FROM records WHERE id IN (SELECT id FROM cleanup_ids)')
   if db.execute('PRAGMA foreign_key_check').fetchall():raise ValueError('Há vínculos não previstos. Limpeza cancelada, banco original preservado.')
   store.audit(db,actor,'limpar_processos_importados','manutencao',after={'removidos':summary['contagens'],'preservados_sem_vinculo':len(summary['desvincular']),'backup':backup.name})
   db.commit()
   return {'removidos':len(summary['processos']),'backup':str(backup),'resumo':summary}
  except Exception:db.rollback();raise

def main():
 import argparse
 parser=argparse.ArgumentParser(description='Remover processos criados por importação, preservando chat e trabalho manual.')
 parser.add_argument('--executar',action='store_true',help='Solicitar login e confirmação após a prévia; sem esta opção nada é alterado')
 args=parser.parse_args();path=legal.BASE/'dados_juridico'/'juridico.sqlite3'
 summary=preview(path)
 print('Banco selecionado:',path)
 print('\nPREVIA — registros importados que serão removidos:')
 for kind,count in sorted(summary['contagens'].items()):print(' ',kind+':',count)
 print('Trabalho manual/financeiro preservado, sem vínculo com processo removido:',len(summary['desvincular']))
 print('Usuários, chat, pessoas, calendários, sessão eproc, auditoria e arquivos de coleta: PRESERVADOS.')
 print('Processos criados manualmente: PRESERVADOS. Não são alvo desta limpeza.')
 if not args.executar or not summary['processos']:
  print('\nNenhuma alteração. Para limpar, execute LIMPAR_PROCESSOS_IMPORTADOS.bat.');return
 print('\nPare o servidor jurídico e as coletas/agendamentos antes de continuar.')
 port=int(os.environ.get('DJEN_PORT','8765'))
 try:
  with socket.create_connection(('127.0.0.1',port),timeout=.5):raise ValueError('A porta do servidor jurídico ainda está ativa. Encerre a janela INICIAR.bat primeiro.')
 except (ConnectionRefusedError,TimeoutError):pass
 login=input('Login administrador do ConectaAdv jurídico: ').strip();password=getpass.getpass('Senha (não aparece): ')
 store=legal.Store(path)
 with closing(store.connect()) as db:
  row=db.execute('SELECT * FROM users WHERE login=? COLLATE NOCASE AND ativo=1',(login,)).fetchone()
  if not row or row['role']!='administrador' or not store.password(password,row['password']):raise ValueError('Conta administradora ou senha inválida.')
  actor=store.public_user(row)
 if input('Digite LIMPAR PROCESSOS para confirmar: ').strip()!='LIMPAR PROCESSOS':print('Cancelado.');return
 result=clean(store,actor,summary)
 print('Processos importados removidos:',result['removidos']);print('Backup completo anterior:',result['backup'])
 print('Agora inicie INICIAR.bat e faça a nova coleta. Não reimporte os ZIPs antigos.')
if __name__=='__main__':
 try:main()
 except (ValueError,legal.AppError,sqlite3.Error,OSError,EOFError,KeyboardInterrupt) as e:
  print('Limpeza encerrada:',e);raise SystemExit(1)
