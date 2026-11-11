# ConectaAdv — apresentação à direção

## Objetivo
Centralizar processos, prazos, mandados e a organização da equipe, com dados de origem preservados e responsabilidades claras.

## Demonstração em 5 minutos
1. Entre com sua conta e clique em **Ver como equipe**. Esta prévia oculta a área técnica e usa seus dados reais; não troca a conta nem altera permissões.
2. **Visão geral**: mostre os totais de Fatalíssimo e próximos vencimentos, abra Detalhes e depois Origem e direcionamento de um processo. Demonstre tribunal, sistema, grau e comarca/vara quando informados. Não apresente link de portal como acesso direto ao processo. Explique o escopo exibido: escritório inteiro para administrador ou registros atribuídos para outros perfis. Os grupos de datas se sobrepõem e não devem ser somados.
3. **Processos**: localize uma ficha realmente preenchida; apresente partes, responsável e próxima ação. Mostre movimentações e datas com origem. Não use ficha com leitura incompleta como exemplo de histórico integral.
4. **Mandados e busca e apreensão**: apresente um caso conferido. O destaque do sistema não substitui a verificação do documento nem confirma a vigência da ordem.
5. **Prazos e agenda**, **Tarefas da equipe** e **Comunicação interna**: mostre distribuição e acompanhamento do trabalho.
6. Volte à sua área, se houver interesse técnico. Explique que a equipe não opera os coletores nem acessa backups e diagnósticos.

## Já organizado nesta versão
- Área do proprietário: operação da coleta, lista de consultas, rotinas, conectores, disponibilidade dos portais, recuperação de dados, backups, reprocessamento e diagnóstico.
- Acesso técnico verificado no servidor, independente do cargo administrador.
- Menus operacionais sem abas técnicas para outras contas.
- Indicador de coleta e consulta periódica de progresso exclusivos do proprietário.
- Ferramentas de consulta/reprocessamento removidas das fichas operacionais.
- Importação de planilha mantida para administradores, sem as abas de backup e recuperação.
- Tela inicial com atalhos de trabalho e pendências prioritárias; explicação dos indicadores recolhida.
- Entrada no sistema não dispara mais reprocessamento em lote.

## Próximas prioridades
1. **Confiabilidade da origem**: resolver a recusa HTTP 403 do TJRS e validar o acesso e a coleta real do TJRJ. SC já produziu uma coleta real auditada, mas o resultado foi parcial.
2. **Cobertura e transparência**: separar processos únicos, intimações, registros importados e falhas. Reconciliar contagem do painel do tribunal com a lista capturada. Incluir a categoria pendentes de citação/intimação. Na coleta SC enviada, 70 intimações correspondiam a 53 processos, com 19 históricos sem confirmação de completude.
3. **Desempenho da coleta**: implementar janela móvel de 20 dias ou data limite, mantendo a descoberta da lista completa. Incluir vencidos e explicar o tratamento de registros sem data; não descartar silenciosamente. No ConectaAdv original essa janela ainda não está incorporada; o coletor independente possui seu próprio filtro, que precisa ser validado no fluxo usado.
4. **Retomada**: deixar explícito o que foi concluído, o que falta e o que será retomado. Atualmente Cancelar e preservar mantém dados e a fila, mas não é uma pausa com retomada na posição exata.
5. **Perfil de gestão**: definir o que o CEO pode consultar em todo o escritório sem conceder acesso técnico ou edição desnecessária. Não foi criado um novo perfil de CEO nesta versão.
6. **Indicadores de negócio**: estabelecer, com a empresa, quais métricas serão oficiais e quais dependem de conferência. Mostrar dados ausentes em vez de transformar ausência de informação em sucesso.

## Critério para apresentar como operação consolidada
Validar um ciclo real: fonte → coleta → conferência → responsável → acompanhamento. O layout pode ser apresentado agora; não afirmar cobertura completa de tribunais, prontidão do PJe, login automático A1 ou histórico integral sem essa validação.

## Organização v60
Totais permanecem no início. Listas ficam recolhidas e têm paginação de 100 registros. Origens incompletas são contadas e explicitadas; novos imports eproc com tribunal identificado registram o grau do conector. Mandados têm uma área própria, com prioridades e detalhes recolhidos. Um prazo registrado de hoje permanece em Fatalíssimo geral e no recorte de mandados, sem criar outro registro. Indício sem vencimento não é promovido a prazo fatal.
