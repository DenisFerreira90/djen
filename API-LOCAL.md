# API local de gestão jurídica

Base padrão: `http://127.0.0.1:8765`. Todas as rotas abaixo exigem sessão local.
O servidor não foi preparado para exposição pública.

## Autenticação

`POST /api/juridico/entrar`, JSON com `login` e `senha` da conta do nosso sistema,
retorna `usuario` e `csrf` e define o cookie HttpOnly `juridico_session`.
O cliente deve manter o cookie. Mutações exigem `Content-Type: application/json`
e `X-CSRF-Token` com o valor retornado. Perfis de leitor não podem mutar/coletar.
As credenciais do eproc são independentes e nunca devem ser enviadas nesses campos.

| Método | Rota | Resultado |
|---|---|---|
| GET | `/api/juridico/processos/5323687-43.2024.8.21.0001/dados` | Cadastro local, vínculos e referências de origem |
| GET | `/api/juridico/diagnostico/ID` | Campos vazios e disponibilidade de origem válida |
| POST | `/api/juridico/reprocessar/ID` | Reestrutura a origem local de um processo |
| POST | `/api/juridico/reprocessar` | Reestrutura fichas vazias com origem guardada |
| GET | `/api/juridico/eventos/ID?pagina=1` | Até 100 eventos por página |
| GET | `/api/juridico/complementos/ID` | Até 30 versões recentes das listagens adicionais |
| POST | `/api/eproc/iniciar` | Inicia uma tarefa local de coleta autenticada |
| GET | `/api/eproc/status` | Progresso, log e execuções |
| POST | `/api/eproc/continuar` | Continua após o login/seleção no navegador |
| POST | `/api/eproc/cancelar` | Cancela e preserva a leitura parcial |

`ID` é o ID estável do cadastro local, não o número CNJ nem o identificador interno
do tribunal. Respostas de dados usam `{ "ok": true, "resultado": ... }`;
o status de coleta usa `atual` e `historico`. Erros usam `ok:false` e `erro`.
Os GETs consultam o banco local; não significam uma atualização em tempo real.

JSON para iniciar uma consulta individual complementar:

```json
{
  "opcoes": {
    "modo": "individual",
    "numero": "5323687-43.2024.8.21.0001",
    "complementos": ["pericias", "audiencias", "documentos", "alvaras", "custas", "depositos"]
  }
}
```

A sessão eproc pode exigir intervenção do titular. O processo deve estar na
lista consultada para que o fluxo individual localize seu link. Se não estiver,
a tarefa informa que não localizou; não inventa um endereço de detalhe.
Somente ações da lista restrita de leitura são utilizadas. A API não aceita
URLs arbitrárias, hashes externos, comandos de petição ou código JavaScript.
Listagens complementares preservam texto/tabelas; a normalização de todos esses
layouts ainda não foi validada, e arquivos de documentos não são baixados.

ConectaAdv — v7
POST /api/eproc/iniciar aceita {"opcoes":{"modo":"incremental","descobrir_consultas":true}}.
A descoberta também pode acompanhar modos completa, falhas e individual.
Modo individual exige numero CNJ formatado. Cookie de sessão e X-CSRF-Token são obrigatórios.
GET /api/juridico/consultas/ID é um alias autenticado para complementos/ID.
Resposta inclui mapa_consultas (ação, tipo, situação e motivo, sem hash/URL) e,
para listagens lidas, estrutura: tabelas com campos {chave,rotulo} e registros.
Cabeçalhos são inferidos e marcados para conferência; a API não inventa significado
jurídico para colunas. Preserva versões, texto e linhas de origem.
O coletor limita-se às seis ações de consulta mapeadas. Não aceita URLs de execução
arbitrárias, não submete formulários, não gera recursos ou petições.

ConectaAdv v8 — controladoria autenticada
GET /api/juridico/controladoria: indicadores, última execução, contagens por estado,
  até 100 pendências sem origem/erro e dez execuções recentes.
POST /api/juridico/controladoria/preencher: {"automatico":true} inicia uma vez por base
  nesta versão, ou retoma execução interrompida. {"automatico":false} inicia/retoma
  explicitamente. Permite apenas administrador/equipe. Exige cookie e CSRF.
POST /api/juridico/controladoria/pausar: {} respeita a ficha atual e pausa a próxima.
Progresso fica em SQLite; a fila roda no servidor local, sem rede. O primeiro login
com edição aciona o modo automático. Leitores não iniciam nem pausam.
Restaurar backup exige pausar a fila e aguardar a ficha atual.
