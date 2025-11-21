# Avaliação da base darktable-mcp-batch

Este documento resume observações sobre a estrutura do repositório, coerência dos scripts Lua/Python e oportunidades de melhoria na robustez, usabilidade e documentação.

## Visão geral da estrutura
- `server/dt_mcp_server.lua` implementa o servidor MCP, expondo ferramentas para consulta de coleção, aplicação de ratings, colorlabels, tags e exportação via `darktable-cli`.
- `host/mcp_host_ollama.py` e `host/mcp_host_lmstudio.py` funcionam como clientes MCP que encadeiam o servidor Lua com LLMs locais (Ollama / LM Studio) para decidir operações de rating, tagging e export.
- `config/prompts/*.md` contém prompts específicos por modo de operação e os hosts referenciam esses arquivos por nome.

## Integração e coerência
- O fluxo principal inicia o servidor Lua via `McpClient` (stdin/stdout), lista ferramentas disponíveis (`initialize` + `tools/list`) e chama uma ferramenta conforme o modo. Ambos os hosts mantêm a mesma interface de linha de comando e reusam a convenção de prompts e diretório de logs.
- O servidor MCP expõe esquemas de entrada detalhados em `tools/list`, o que facilita introspecção por hosts/clients e reduz ambiguidades.
- O `export_collection` usa `darktable-cli` externo e monta o caminho de saída a partir de `img.path` + `img.filename`, mas assume que a CLI estará disponível no `PATH` e não valida o sucesso da execução.

## Bugs e pontos críticos
- `host/mcp_host_lmstudio.py` faltava importar módulos usados (`argparse`, `json`, `subprocess`), impedindo a execução do host antes mesmo de iniciar o servidor Lua. A inclusão explícita corrige o crash imediato no parse do arquivo Python.
- O servidor Lua usa `os.execute` com caminhos recebidos via JSON-RPC (`target_dir`, nomes de arquivo); não há sanitização ou tratamento de erros do comando externo, o que pode mascarar falhas de exportação.
- A seleção de colorlabels em `set_colorlabel_batch` ativa apenas a cor solicitada sem limpar marcas prévias; se a intenção for sobrescrever cores, pode haver estado residual. Se a intenção for combinar cores, o comportamento está correto, mas falta documentação.

## Melhorias recomendadas
- **Robustez**: capturar códigos de retorno de `os.execute` no `export_collection` e reportar falhas por imagem; considerar validar/normalizar `target_dir` e `format` para evitar comandos inválidos.
- **Usabilidade de CLI**: oferecer `--version` e comando rápido de verificação de dependências (dkjson, darktable, requests) para reduzir tentativas e erro na preparação do ambiente.
- **Experiência de logs**: registrar stderr do servidor Lua e das chamadas a LLMs (latência, modelo, URL) para depuração e auditoria, e rotacionar arquivos em `logs/`.
- **Documentação**: explicitar no README exemplos de entrada/saída esperada dos LLMs (formato JSON) e explicar o comportamento de sobrescrita de colorlabels/export. Incluir tabela de requisitos de sistema e passos mínimos para testar sem LLM (modo dry-run + prompts mockados).

## Documentação existente
- O README cobre pré-requisitos básicos e exemplos de uso, mas ainda carece de detalhes operacionais (caminhos esperados do darktable em diferentes distros, exemplos de resposta das ferramentas e troubleshooting). Uma seção de "Fluxo MCP" com diagrama simples ajudaria novos usuários.
