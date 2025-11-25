# darktable-mcp-batch

Servidor MCP em Lua para controlar o darktable + hosts Python para usar LLMs locais (Ollama / LM Studio)
em fluxos de tratamento em lote (rating, tagging, export).

## Estrutura

- `server/dt_mcp_server.lua` — servidor MCP (stdin/stdout) usando o darktable como biblioteca.
- `host/mcp_host_ollama.py` — host que fala com o servidor MCP e com o Ollama (por padrão em `http://localhost:11434`).
- `host/mcp_host_lmstudio.py` — host que fala com o servidor MCP e com o LM Studio (API OpenAI-like).
- `config/prompts/*.md` — prompts para rating, tagging e export.
- `logs/` — logs em JSON de cada execução.
- `host/interactive_cli.py` — interface interativa em terminal que monta e executa os hosts acima.

## Pré-requisitos

- Linux
- darktable com suporte a Lua e `libdarktable.so` instalado
- Lua + luarocks
- Python 3 + `requests`
- Opcional: Ollama e/ou LM Studio rodando localmente

Use `python host/mcp_host_lmstudio.py --check-deps` para verificar rapidamente se `lua`, `darktable-cli`
e a biblioteca `requests` estão acessíveis.

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

Certifique-se de que o Ollama está rodando e que um modelo foi baixado (o endereço padrão usado é `http://localhost:11434`):

```bash
ollama serve
ollama pull llama3.1  # ou use --download-model no host
```

Depois:

```bash
cd darktable-mcp-batch
python host/mcp_host_ollama.py --mode rating --source all --dry-run
```

Caso ainda não tenha o modelo local, o host pode acionar o download diretamente:

```bash
python host/mcp_host_ollama.py --download-model llama3.2 --mode rating --source all --dry-run
```

Você também pode usar o botão **Baixar modelo** na interface GUI para solicitar os downloads mais comuns (por exemplo, `llama3.2`, `phi3`, `mistral`, `gemma2`).

### Interface interativa (CLI)

Se preferir um passo a passo guiado, use a interface interativa. Ela pergunta pelos
parâmetros principais (host, modo, fonte, filtros, prompt customizado, etc.) e monta
o comando final antes de executar:

```bash
python host/interactive_cli.py
```

Por padrão o modo é `rating`, o host é `ollama` e o script executa em `--dry-run`
para evitar mudanças acidentais. A tela de resumo mostra o comando completo e só
roda após confirmação.

## Instruções completas de uso

1. **Configure o caminho do darktable**
   - Abra `server/dt_mcp_server.lua` e ajuste os caminhos para `libdarktable.so`, `--datadir` e `--moduledir` conforme sua distribuição.
   - Se estiver testando fora do ambiente padrão, confirme que `darktable-cli` está no `PATH`.

2. **Instale dependências**
   - Lua + luarocks e o módulo `dkjson` (`sudo luarocks install dkjson`).
   - Python 3 com `requests` (use um venv se preferir: `python -m venv .venv && source .venv/bin/activate && pip install requests`).
   - Opcional: Ollama e/ou LM Studio executando localmente com um modelo baixado.

3. **Verifique rapidamente o ambiente**
   - Rode `python host/mcp_host_lmstudio.py --check-deps` para validar binários (`lua`, `darktable-cli`) e o pacote `requests`.

4. **Escolha e ajuste o host**
   - **Ollama**: confira `OLLAMA_URL` e `OLLAMA_MODEL` em `host/mcp_host_ollama.py` ou passe `--ollama-url`/`--model` na linha de comando.
   - **LM Studio**: inicie o servidor local em modo OpenAI-compatible e ajuste `LMSTUDIO_URL`/`LMSTUDIO_MODEL` em `host/mcp_host_lmstudio.py`.

5. **Prepare os prompts**
   - Use os padrões em `config/prompts/` (`rating_basico.md`, `tagging_cliente.md`, `export_job.md`) ou indique outro arquivo com `--prompt-file`.
   - Personalize tags, linguagem e limites no prompt antes de rodar para evitar retrabalhos.

6. **Execute um dry-run** (recomendado)
   - Liste e visualize o plano sem aplicar mudanças:
     - Ollama: `python host/mcp_host_ollama.py --mode rating --source all --dry-run`
     - LM Studio: `python host/mcp_host_lmstudio.py --mode rating --source all --dry-run`

7. **Filtre o conjunto de fotos**
   - `--source path --path-contains <trecho>` para restringir por caminho.
   - `--source tag --tag <nome>` para filtrar por tag existente.
   - Combine com `--min-rating` e `--only-raw` para limitar envio ao modelo.

8. **Rodando para cada modo**
   - **Rating**: remove ou confirma a seleção de imagens. Ex.: `python host/mcp_host_ollama.py --mode rating --limit 150`
   - **Tagging**: adiciona tags sugeridas pelo modelo. Ex.: `python host/mcp_host_lmstudio.py --mode tagging --tag viagem --dry-run`
   - **Export**: exige `--target-dir` (apenas letras/números) e valida caminho antes de exportar. Ex.:
     ```bash
     python host/mcp_host_ollama.py --mode export --source path --path-contains cliente-x --target-dir out_job_x
     ```

9. **Aplicando de fato**
   - Remova `--dry-run` quando estiver satisfeito com o plano retornado pelo modelo.
   - Acompanhe o stderr do host para ver eventuais falhas de export ou setagem de labels.

10. **Logs e auditoria**
    - Cada execução gera `logs/batch-<modo>-<timestamp>.json` com amostra das imagens, prompt e resposta bruta do modelo.
    - Guarde os logs para replays ou auditoria e ajuste o prompt conforme necessário.

11. **Dicas de depuração**
    - Se o MCP não responder, rode o teste rápido do servidor Lua (seção "Teste rápido do servidor MCP") e confira permissões dos diretórios do darktable.
    - Ative `--dry-run` sempre que alterar prompts ou filtros para evitar aplicar mudanças incorretas na base.

## Uso com LM Studio

- Inicie o servidor de API local no LM Studio (modo OpenAI-compatible).
- Ajuste `LMSTUDIO_URL` e `LMSTUDIO_MODEL` em `host/mcp_host_lmstudio.py`.

Exemplo:

```bash
python host/mcp_host_lmstudio.py --mode rating --source all --dry-run
```

Depois é só adaptar os parâmetros de linha de comando para `tagging` e `export`.

Para ver a versão do host ou confirmar dependências antes de rodar, use `--version` e `--check-deps`.

## Formato esperado de respostas do LLM

Os hosts esperam respostas JSON simples. Exemplos mínimos por modo:

- `rating`: `{ "edits": [ { "id": 123, "rating": 3 } ] }`
- `tagging`: `{ "tags": [ { "tag": "job:cliente-x", "ids": [1,2,3] } ] }`
- `export`: `{ "ids_para_exportar": [1,2,3] }` (ou `ids`)

O log em `logs/batch-*.json` inclui a resposta bruta do modelo e metadados da chamada (modelo, URL, latência).

## Comportamento de colorlabels e export

- `set_colorlabel_batch` ativa a cor solicitada em cada imagem, sem limpar marcas anteriores. Caso precise
  sobrescrever cores existentes, faça um passo de limpeza antes de aplicar novas cores.
- `export_collection` valida o diretório alvo e o formato (somente letras/números) e exige `darktable-cli`
  no `PATH`. A função registra no stderr cada export que falhar e retorna um resumo com eventuais erros em
  JSON para ajudar na depuração.

## Avaliação rápida da base

Para uma visão consolidada da arquitetura, riscos atuais e sugestões de robustez/usabilidade, consulte o relatório em [ANALYSIS.md](ANALYSIS.md).
