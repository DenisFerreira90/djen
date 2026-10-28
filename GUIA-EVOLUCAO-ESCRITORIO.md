# Evolução do ConectaAdv

O objetivo é uma base comum de usuários, clientes, processos, responsabilidades e auditoria. Cada módulo deve consultar essa base; criar cópias independentes por setor aumenta divergências. Nenhum sistema elimina toda falha: precisamos detectar, limitar o impacto e recuperar o trabalho.

## Prioridade 1 — operação central e permissões

Antes de colocar toda a equipe no sistema: servidor central com HTTPS, cópia externa do banco, teste real de restauração e contas individuais. Não exponha o servidor de desenvolvimento diretamente na internet.

Revise todas as telas e APIs antigas. A restrição no painel e no chat não garante isolamento dos cadastros antigos. Adote permissões por ação e carteira: consultar, criar, alterar, concluir, aprovar, exportar e administrar. RH e financeiro precisam de acessos específicos, sem equivaler automaticamente a todo gestor de setor. A saída de um funcionário deve revogar sessões e delegações.

## Prioridade 2 — integridade jurídica

Cada prazo deve ter fonte, evento, destinatário, responsável e conferência. Separe prazo confirmado, prazo a conferir e meta interna. Não deduza ciência, suspensão ou vencimento de um texto isolado.

Mostre a idade dos dados e a cobertura real de cada consulta. Falha de coleta é pendência, nunca confirmação de ausência de movimentação. Registre o que faltou consultar e disponibilize retentativa.

Para peticionamento futuro: preparação, revisão, aprovação, envio e confirmação do protocolo devem ser estados distintos. Uma queda após envio exige conciliação antes de repetir. A integração de leitura atual não executa atos no tribunal.

## Prioridade 3 — distribuição de trabalho entre setores

Cada demanda precisa de dono, prazo interno, prioridade, dependências e evidência de conclusão. O chat apoia a conversa; decisões devem ser ligadas a tarefa, cliente ou processo para não desaparecerem no histórico.

Na agenda, conceda acesso deliberadamente: Consignados pode agendar para Contratação; Contratação confirma, realiza ou cancela. Defina quem resolve conflitos e faltas. Os registros de criação e alteração identificam quem fez o agendamento.

## Prioridade 4 — RH separado

Comece por cadastro profissional mínimo, setor, cargo, gestor, ramal, data de entrada e situação ativa/inativa. Depois avance para pedidos de férias/ausências, aprovações, integração de novos funcionários, treinamentos e devolução de equipamentos.

Folha, salários, documentos pessoais, avaliações e dados médicos precisam de módulo e armazenamento restritos. Não os coloque em grupos gerais, observações de processos ou calendário compartilhado. A versão 17 não entrega módulo de RH nem folha de pagamento.

## Prioridade 5 — documentos, auditoria e continuidade

Arquivos: versões, autoria, permissões, limites de tamanho, verificação contra malware e política de retenção. Os anexos atuais ficam no banco; meça crescimento e duração dos backups antes de escalar.

Auditoria: diferencie registro operacional de um mecanismo resistente a alteração por quem administra o banco. Atualmente a aplicação registra ações, mas não oferece auditoria externa criptograficamente imutável.

Backups: rotina de cópias, armazenamento independente, monitoramento de falhas e restauração periódica em ambiente isolado. Defina quanto trabalho pode ser perdido e em quanto tempo o escritório precisa voltar a funcionar.

Monitore fila acumulada, falhas consecutivas, sessão expirada, espaço em disco, banco indisponível e último backup válido. Mudanças devem passar por testes de permissão e migração, implantação gradual e possibilidade de voltar à versão anterior.

## O que a versão 17 acrescenta

Calendários pessoais/compartilhados com delegação por usuário ou grupo de setor; compromissos auditados; bloqueio de conflitos e de edições desatualizadas. Serviço de atualização com frequência configurável, fila persistente e orçamento cooperativo por rodada.

Ainda precisa de validação real de navegador, Windows e tribunal. Não equivale a operação de produção nem garante consulta completa de todos os processos, todos os tribunais ou todos os documentos em uma hora.
