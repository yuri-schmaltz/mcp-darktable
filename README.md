# darktable-mcp-batch

Servidor MCP em Lua para controlar o darktable + hosts Python para usar LLMs locais (Ollama / LM Studio)
em fluxos de tratamento em lote (rating, tagging, export).

## Estrutura

- `server/dt_mcp_server.lua` — servidor MCP (stdin/stdout) usando o darktable como biblioteca.
- `host/mcp_host_ollama.py` — host que fala com o servidor MCP e com o Ollama.
- `host/mcp_host_lmstudio.py` — host que fala com o servidor MCP e com o LM Studio (API OpenAI-like).
- `config/prompts/*.md` — prompts para rating, tagging e export.
- `logs/` — logs em JSON de cada execução.

## Pré-requisitos

- Linux
- darktable com suporte a Lua e `libdarktable.so` instalado
- Lua + luarocks
- Python 3 + `requests`
- Opcional: Ollama e/ou LM Studio rodando localmente

### Lua

Instale o dkjson:

```bash
sudo luarocks install dkjson
```

Ajuste os caminhos para `libdarktable.so` e diretórios (`--datadir`, `--moduledir`, etc.) em
`server/dt_mcp_server.lua` conforme sua distro.

### Python

Crie um venv (opcional):

```bash
python -m venv .venv
source .venv/bin/activate
pip install requests
```

## Teste rápido do servidor MCP

```bash
cd darktable-mcp-batch
printf '{"jsonrpc":"2.0","id":"1","method":"initialize","params":{}}\n' | lua server/dt_mcp_server.lua
```

## Uso com Ollama

Certifique-se de que o Ollama está rodando e que um modelo foi baixado:

```bash
ollama serve
ollama pull llama3.1
```

Depois:

```bash
cd darktable-mcp-batch
python host/mcp_host_ollama.py --mode rating --source all --dry-run
```

## Uso com LM Studio

- Inicie o servidor de API local no LM Studio (modo OpenAI-compatible).
- Ajuste `LMSTUDIO_URL` e `LMSTUDIO_MODEL` em `host/mcp_host_lmstudio.py`.

Exemplo:

```bash
python host/mcp_host_lmstudio.py --mode rating --source all --dry-run
```

Depois é só adaptar os parâmetros de linha de comando para `tagging` e `export`.
