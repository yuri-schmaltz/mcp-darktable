# Runbook Operacional MCP Darktable

## Setup Rápido

1. Instale dependências Python (venv recomendado):
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
2. Instale dependências Lua:
   ```bash
   sudo luarocks install dkjson
   ```
3. Ajuste caminhos do darktable em `server/dt_mcp_server.lua` se necessário.

## Troubleshooting

- **Erro de exportação:**
  - Verifique se o diretório de destino existe e tem permissão de escrita.
  - Cheque logs em `logs/` e mensagens de erro no terminal.
- **Erro de conexão LLM:**
  - Confirme se Ollama/LM Studio está rodando e acessível na URL configurada.
  - Teste conexão via `curl` ou browser.
- **Problemas de permissão:**
  - Execute com permissões adequadas ou ajuste permissões dos diretórios de trabalho.
- **Falha no servidor MCP:**
  - Rode o teste rápido:
    ```bash
    printf '{"jsonrpc":"2.0","id":"1","method":"initialize","params":{}}\n' | lua server/dt_mcp_server.lua
    ```
  - Verifique dependências e variáveis de ambiente.

## Checklist de Release

- [ ] Testes em dry-run para todos os modos
- [ ] Auditoria de dependências (pip-audit)
- [ ] Logs e métricas revisados
- [ ] Atualização do README e runbook

## Referências
- Consulte o README.md para instruções detalhadas e exemplos de uso.
