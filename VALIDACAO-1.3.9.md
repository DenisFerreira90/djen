# Validação 1.3.9

- 134 testes do coletor aprovados com integração HTTP local habilitada.
- Oito regressões adicionais de relatórios e eventos aprovadas.
- Tabela atrasada: endereço/contador zero antes do carregamento não confirmam lista.
- Tabela nunca carregada: modo visível mantém a janela para conferência; segundo plano exige conferir acesso.
- Pausa manual propaga e não vira sucesso de paginação.
- Recuperação: opções da última etapa preservam 925 identidades e quatro falhas; o checkpoint pode acrescentar as tentativas da etapa interrompida.
- Isolamento de tribunal e recuperação dos links das categorias somente em memória.
- O retorno da conferência manual não solicita ENTER duas vezes no mesmo caminho.

Não houve navegação autenticada ou teste visual no Windows. A causa exata da ausência da tabela no PC não foi observada. O ajuste elimina a aceitação prematura pelo endereço e oferece recuperação explícita da rodada encerrada. As falhas já tentadas são preservadas para revisão, não automaticamente refeitas nessa retomada.
