"""Executar localmente, com servidor parado, para identificar a conta proprietária."""
import getpass
import juridico as legal
import chat_recursos as chat

def main():
 print('ConectaAdv — proprietário exclusivo do chat\nPare o servidor antes de continuar. Use SUA conta administradora do ConectaAdv.')
 login=input('Seu login no ConectaAdv: ').strip()
 senha=getpass.getpass('Sua senha no ConectaAdv (não aparece): ')
 from chat_servico import CHAT_PATH
 store=legal.Store(CHAT_PATH) if CHAT_PATH.is_file() else legal.store
 print('Base selecionada:', 'chat independente' if CHAT_PATH.is_file() else 'base jurídica legada')
 with store.lock,store.connect() as db:
  row=db.execute('SELECT * FROM users WHERE login=? COLLATE NOCASE AND ativo=1',(login,)).fetchone()
  if not row or row['role']!='administrador' or not store.password(senha,row['password']):raise legal.AppError('Conta administradora ou senha inválida.')
  chat.schema(db)
  print('Conta escolhida:',row['nome'],'—',row['login'])
  if input('Digite CONFIRMAR para torná-la proprietária exclusiva: ').strip()!='CONFIRMAR':print('Nada alterado.');return
  previous=db.execute('SELECT owner_id FROM chat_control WHERE id=1').fetchone()
  db.execute('INSERT OR REPLACE INTO chat_control VALUES(1,?)',(row['id'],))
  db.execute("UPDATE chat_rooms SET owner_id=? WHERE direct_key='__geral__'",(row['id'],))
  store.audit(db,store.public_user(row),'definir_proprietario_chat','chat',before={'owner_id':previous[0] if previous else None},after={'owner_id':row['id'],'origem':'configurador_local'})
 print('Proprietário configurado. Inicie o ConectaAdv e abra Permissões do chat.')
if __name__=='__main__':
 try:main()
 except (legal.AppError,EOFError,KeyboardInterrupt) as e:print('Configuração encerrada:',e)
