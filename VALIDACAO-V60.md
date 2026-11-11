# ConectaAdv v60 — validação

- 353 testes Python passaram, incluindo API HTTP, autenticação, permissões, importações e novos cenários de proveniência.
- 16 testes DOM passaram. O novo cenário verifica que as listas começam recolhidas, os destinos respeitam o grau e a paginação carrega a próxima página.
- Os novos cenários Python verificam 205 prazos em três páginas sem repetição, totais completos, separação DJEN/PJe, recusa de URLs temporárias/não autorizadas, conflito de grau, prazos de mandados presentes nos recortes geral e específico, e indícios sem prazo fora de Fatalíssimo.
- Não houve teste visual em navegador real, acesso autenticado a tribunal ou validação do conteúdo dos links cadastrados. Porta de entrada e origem de processo são diferenciadas na interface.
- O pacote contém arquivos do programa, sem banco de clientes, credenciais ou sessões. A abertura do dashboard não reprocessa a base antiga.
