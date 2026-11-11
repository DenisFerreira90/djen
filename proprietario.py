"""Área técnica exclusiva da conta proprietária já registrada na instalação."""
import juridico as legal
import chat_recursos

TECHNICAL_PREFIXES=(
 '/api/eproc/', '/api/juridico/saude-sistema/', '/api/juridico/jusdown',
 '/api/juridico/diagnostico/', '/api/juridico/reprocessar',
 '/api/juridico/controladoria', '/api/juridico/dados',
 '/api/juridico/monitoramento', '/api/juridico/evidencias/',
)
TECHNICAL_EXACT={
 '/api/juridico/email','/api/juridico/email/teste',
 '/api/juridico/agendamento','/api/juridico/servico-coleta','/api/juridico/fila-coleta',
 '/api/juridico/conectores','/api/juridico/importar',
 '/api/juridico/backup','/api/juridico/restaurar','/api/juridico/exportar',
 '/api/juridico/sincronizacao','/api/juridico/organizar',
 '/api/juridico/monitoramento/procurar','/api/juridico/monitoramento/repeticao',
 '/api/juridico/monitoramento/pedidos','/api/juridico/monitoramento/cancelar',
 '/api/juridico/monitoramento/config','/api/juridico/mandados/varrer',
}

def access(store,actor):
 with store.lock,store.connect() as db:
  owner_id=chat_recursos.owner(db)
 return {'proprietario':actor['id']==owner_id,'area_tecnica':actor['id']==owner_id}

def require(store,actor):
 if not access(store,actor)['area_tecnica']:
  raise legal.AppError('Área técnica exclusiva do proprietário do sistema.',403)

def technical(path):
 return path in TECHNICAL_EXACT or path.startswith(TECHNICAL_PREFIXES) or (path.startswith('/api/juridico/processos/') and path.endswith('/dados'))
