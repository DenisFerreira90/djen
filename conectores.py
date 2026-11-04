"""Catálogo de integrações. Planejamento não concede acesso nem ativa um coletor."""
from dataclasses import dataclass
from typing import Protocol
import eproc_tribunais

@dataclass(frozen=True)
class Capabilities:
    cadastro: bool=False
    eventos: bool=False
    documentos: bool=False
    incremental: bool=False

class Connector(Protocol):
    """Interface para futuros adaptadores; retorno deve preservar fonte e cobertura."""
    id: str
    capabilities: Capabilities
    def collect(self, numero: str, session: object) -> dict: ...


def catalog():
    installed=[{'id':'eproc:'+key,'tribunal':key,'sistema':'eproc',
                'estado':'instalado' if eproc_tribunais.enabled(key) else 'desativado_temporariamente','acesso':'Depende de autenticação e permissões no tribunal',
                'capacidades':vars(Capabilities(cadastro=True,eventos=True)),
                'observacao':'Coleta assistida existente. Documentos completos ainda não implementados.'}
               for key in sorted(eproc_tribunais.TRIBUNAIS)]
    planned=[{'id':key,'tribunal':'Conforme implantação futura','sistema':name,
              'estado':'planejado','acesso':'Não configurado',
              'capacidades':vars(Capabilities()),'observacao':note}
             for key,name,note in [
                 ('eproc:expansao','eproc — outros tribunais','Requer adaptar e validar cada implantação.'),
                 ('esaj','e-SAJ','Requer conector e validação por tribunal.'),
                 ('pje','PJe','Requer conector e validação por tribunal.'),
                 ('pdpj','PDPJ — serviços de integração','Requer serviço específico, credenciamento e integração; não substitui os sistemas processuais.')]]
    return {'versao_contrato':1,'itens':installed+planned,
            'fluxo':['identificar origem','verificar acesso','coletar','validar cobertura','comparar','persistir'],
            'aviso':'Instalado não significa sessão autenticada. Planejado não executa consultas.'}
