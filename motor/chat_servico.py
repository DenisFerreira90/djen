"""Banco exclusivo da comunicação; migração inicial sem alterar a base jurídica."""
from pathlib import Path
import os
import sqlite3
import tempfile
from contextlib import closing
import juridico as legal

CHAT_PATH=legal.BASE/'dados_chat'/'chat.sqlite3'
def migrate(source,destination):
 source=Path(source).resolve();destination=Path(destination).resolve()
 if source==destination:raise ValueError('Origem e destino devem ser diferentes.')
 if not source.is_file():raise ValueError('Banco jurídico de origem não encontrado.')
 if destination.exists():raise ValueError('O banco do chat já existe. Não foi sobrescrito nem mesclado.')
 destination.parent.mkdir(parents=True,exist_ok=True)
 with tempfile.TemporaryDirectory(dir=destination.parent) as folder:
  snapshot=Path(folder)/'snapshot.sqlite3';target=Path(folder)/'chat.sqlite3'
  with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as src,closing(sqlite3.connect(snapshot)) as snap:src.backup(snap)
  store=legal.Store(target)
  with closing(sqlite3.connect(snapshot)) as src,closing(store.connect()) as dst:
   src.row_factory=sqlite3.Row
   tables=src.execute("SELECT name,sql FROM sqlite_master WHERE type='table' AND (name='users' OR name LIKE 'chat\\_%' ESCAPE '\\') ORDER BY name").fetchall()
   if not any(t['name']=='users' for t in tables):raise ValueError('A origem não possui contas do ConectaAdv.')
   quote=lambda name:'"'+name.replace('"','""')+'"'
   for t in tables:
    if t['name']!='users':dst.execute(t['sql'])
    rows=src.execute('SELECT * FROM '+quote(t['name'])).fetchall()
    if rows:
     cols=','.join(quote(c) for c in rows[0].keys());marks=','.join('?' for _ in rows[0])
     dst.executemany('INSERT INTO '+quote(t['name'])+' ('+cols+') VALUES ('+marks+')',[tuple(r) for r in rows])
   exists=src.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='audit'").fetchone()
   if exists:
    rows=src.execute("SELECT * FROM audit WHERE entidade LIKE 'chat%' OR acao LIKE '%chat%'").fetchall()
    if rows:dst.executemany('INSERT INTO audit VALUES('+','.join('?' for _ in rows[0])+')',[tuple(r) for r in rows])
   dst.execute('INSERT INTO audit(data,actor_name,acao,entidade,entidade_id,ip,depois) VALUES(?,?,?,?,?,?,?)',(legal.now(),'Migração local','migrar_chat','chat','', '127.0.0.1',legal.dumps({'origem':'base jurídica','sessoes_copiadas':False})))
   counts={t['name']:dst.execute('SELECT COUNT(*) FROM '+quote(t['name'])).fetchone()[0] for t in tables}
   if dst.execute('PRAGMA foreign_key_check').fetchall():raise ValueError('Falha de integridade: nenhum banco foi ativado.')
   if dst.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Falha de integridade do banco.')
   dst.commit()
  # Criação exclusiva: nunca substituir um destino criado por outro processo.
  os.link(target,destination)
 return counts

def main():
 import argparse
 parser=argparse.ArgumentParser(description='Separar comunicação da base do eproc. Pare ambos os servidores antes de migrar.')
 parser.add_argument('--origem',type=Path,default=legal.BASE/'dados_juridico'/'juridico.sqlite3')
 parser.add_argument('--destino',type=Path,default=CHAT_PATH)
 args=parser.parse_args()
 print('Migração inicial. O original é preservado; sessões e processos não são copiados.')
 try:
  counts=migrate(args.origem,args.destino)
  print('Concluído:',args.destino)
  print('Contas:',counts.get('users',0),'Mensagens:',counts.get('chat_messages',0))
  print('A partir de agora, use INICIAR_CHAT_LOCAL.bat ou INICIAR_CHAT_ESCRITORIO.bat para o chat.')
 except (ValueError,OSError,sqlite3.Error) as e:parser.exit(1,'Não foi possível migrar: '+str(e)+'\n')
if __name__=='__main__':main()
