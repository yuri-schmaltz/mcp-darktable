# darktable-mcp-batch

> 📘 Consulte também: [docs/runbook-operacional.md](docs/runbook-operacional.md) para troubleshooting, setup rápido e checklist de release.

Servidor MCP em Lua para controlar o darktable + hosts Python para usar LLMs locais (Ollama / LM Studio)
em fluxos de tratamento em lote (rating, tagging, export).

## Estrutura

- `server/dt_mcp_server.lua` — servidor MCP (stdin/stdout) usando o darktable como biblioteca.
- `host/mcp_host_ollama.py` — host que fala com o servidor MCP e com o Ollama (por padrão em `http://localhost:11434`).
- `host/mcp_host_lmstudio.py` — host que fala com o servidor MCP e com o LM Studio (API OpenAI-like).
- `config/prompts/*.md` — prompts para rating, tagging e export.
- `logs/` — logs em JSON de cada execução.
- `host/interactive_cli.py` — interface interativa em terminal que monta e executa os hosts acima.

## Suporte a visão / multimodal

- Os hosts enviam a PRÓPRIA imagem (base64) junto aos metadados para modelos que suportam visão
  (ex.: Llama 3.2 Vision, Qwen-VL, LLaVA). Isso permite avaliar nitidez, exposição e duplicatas
  de forma real, não apenas por heurísticas de filename.
- Use `--text-only` caso queira desabilitar o envio de imagens e operar apenas com metadados.
- Garanta que o servidor LLM aceite mensagens multimodais (OpenAI-compatible com `image_url` ou
  API do Ollama com campo `images`).

## Limites e opções rápidas

| Modo/ação         | Rating mínimo | Rating máximo | Formatos de export suportados | Opções obrigatórias |
|-------------------|---------------|---------------|--------------------------------|----------------------|
| Filtragem/listagem| -1 (rejeitado) | 5            | —                              | `path_contains` com `--source path`; `tag` com `--source tag`. |
| Rating            | -1 (rejeitado) | 5            | —                              | Nenhuma (mas defina `--limit` para amostras menores). |
| Export            | n/a           | n/a           | Somente formatos alfanuméricos (padrão `jpg`) | `--target-dir` (criado automaticamente se não existir). |

## Pré-requisitos

- Linux
- darktable com suporte a Lua e `libdarktable.so` instalado
- Lua + luarocks
- Python 3 + `requests`
- Opcional: Ollama e/ou LM Studio rodando localmente

### Darktable via Flatpak

- O servidor MCP tenta localizar automaticamente bibliotecas e módulos do darktable em instalações
  Flatpak comuns (`~/.local/share/flatpak/app/org.darktable.Darktable/current/active/files` ou
  `/var/lib/flatpak/app/org.darktable.Darktable/current/active/files`).
- Para caminhos não convencionais, defina `DARKTABLE_FLATPAK_PREFIX` ou `DARKTABLE_PREFIX` com o
  prefixo que contém `libdarktable.so`, `share/darktable` e `lib*/darktable`.
- O fluxo de export passa a aceitar o comando `darktable-cli` exposto via Flatpak. Se ele não estiver no
  `PATH`, defina `DARKTABLE_CLI_CMD="flatpak run --command=darktable-cli org.darktable.Darktable"`
  (ou outro comando personalizado).
- A flag `--check-deps` dos hosts agora sinaliza quando o darktable foi encontrado via Flatpak ou por
  override em `DARKTABLE_CLI_CMD`.
- Use `--check-darktable` para validar a comunicação com o catálogo e listar coleções/fotos antes de rodar
  o LLM; o comando também informa quando o acesso ocorre via Flatpak.

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

Para análise visual, use um modelo multimodal (ex.: `llama3.2-vision`, `qwen2.5-vl`) e mantenha o host
em modo padrão (multimodal). Caso precise economizar banda/processamento, passe `--text-only` para
voltar ao comportamento baseado apenas em metadados.

Depois:

```bash
cd darktable-mcp-batch
python host/mcp_host_ollama.py --mode rating --source all --dry-run
```

As chamadas ao Ollama usam timeout padrão de 60s (configurável via `--timeout` ou
variável de ambiente `OLLAMA_TIMEOUT`). Se o tempo for excedido, o host informa o
motivo e sugere aumentar o limite.

Caso ainda não tenha o modelo local, o host pode acionar o download diretamente:

```bash
python host/mcp_host_ollama.py --download-model llama3.2 --mode rating --source all --dry-run
```

Você também pode usar o botão **Baixar modelo** na interface GUI para solicitar os downloads mais comuns (por exemplo, `llama3.2`, `phi3`, `mistral`, `gemma2`).

Para um guia visual da tela de configuração de LLM (framework, URL, modelo e botões de ação), consulte `docs/llm-gui-explicacao.md`.

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

### Parâmetros principais (GUI)

A interface gráfica exibe um painel de "Parâmetros principais" que corresponde
às opções mais usadas no fluxo de rating/tagging/export. Cada campo da captura
abaixo corresponde a um parâmetro aceito pelos hosts de linha de comando:

- **Modo** (`rating`, `tagging`, `tratamento`, `export`, `completo`): define a
  ação principal. `tratamento` registra sugestões de pós-processo; `completo`
  roda automaticamente rating → tagging → tratamento → export (também exige
  `--target-dir`).
- **Fonte** (`all`, `path`, `tag`): escolhe a origem das fotos. `all` processa
  todo o catálogo; `path` filtra por trecho de caminho (`--path-contains`);
  `tag` limita a imagens que já possuam uma tag específica (`--tag`).
- **Rating mínimo**: limite inferior para incluir imagens na amostra enviada ao
  modelo. O valor `-2` corresponde a rejeitados; aumente para ignorar fotos com
  avaliações muito baixas e reduzir custos de inferência.
- **Limite**: número máximo de imagens processadas na execução. Útil para
  amostrar subconjuntos antes de aplicar em lotes maiores.

## Instruções completas de uso

1. **Configure o caminho do darktable**
   - Abra `server/dt_mcp_server.lua` e ajuste os caminhos para `libdarktable.so`, `--datadir` e `--moduledir` conforme sua distribuição.
   - Se estiver testando fora do ambiente padrão, confirme que `darktable-cli` está no `PATH`.

> Consulte a seção [Fluxo host ↔ dt_mcp_server ↔ LLM](#fluxo-host--dt_mcp_server--llm) para um passo a passo do ciclo completo (incluindo dry-run seguro e exemplos de JSON).

2. **Instale dependências**
   - Lua + luarocks e o módulo `dkjson` (`sudo luarocks install dkjson`).
   - Python 3 com `requests` (use um venv se preferir: `python -m venv .venv && source .venv/bin/activate && pip install requests`).
   - Opcional: Ollama e/ou LM Studio executando localmente com um modelo baixado.

3. **Verifique rapidamente o ambiente**
   - Rode `python host/mcp_host_lmstudio.py --check-deps` para validar binários (`lua`, `darktable-cli`) e o pacote `requests`.
   - Para confirmar a conexão com o catálogo, rode `python host/mcp_host_ollama.py --check-darktable --limit 20` (ou use o botão
     **Checar darktable** na GUI). O comando lista coleções conhecidas e traz uma amostra de fotos com paths completos, avisando
     quando o acesso está vindo de uma instalação Flatpak.

4. **Escolha e ajuste o host**
   - **Ollama**: confira `OLLAMA_URL` e `OLLAMA_MODEL` em `host/mcp_host_ollama.py` ou passe `--ollama-url`/`--model` na linha de comando.
   - **LM Studio**: inicie o servidor local em modo OpenAI-compatible e ajuste `LMSTUDIO_URL`/`LMSTUDIO_MODEL` em `host/mcp_host_lmstudio.py`.

5. **Prepare os prompts**
   - Use os padrões em `config/prompts/` (`*_basico.md`) ou as variantes avançadas (`*_avancado.md`) e selecione-as via `--prompt-variant basico|avancado`. Também é possível indicar um arquivo específico com `--prompt-file`.
   - Personalize tags, linguagem e limites no prompt antes de rodar para evitar retrabalhos.

6. **Execute um dry-run** (recomendado)
   - Liste e visualize o plano sem aplicar mudanças:
     - Ollama: `python host/mcp_host_ollama.py --mode rating --source all --dry-run`
     - LM Studio: `python host/mcp_host_lmstudio.py --mode rating --source all --dry-run`

7. **Filtre o conjunto de fotos**
   - `--source path --path-contains <trecho>` para restringir por caminho.
   - `--source tag --tag <nome>` para filtrar por tag existente.
   - `--source collection --collection <caminho>` para trabalhar com uma
     coleção/pasta específica listada pelo darktable (`--list-collections`
     mostra as opções conhecidas).
   - Combine com `--min-rating` e `--only-raw` para limitar envio ao modelo.

8. **Rodando para cada modo**
   - **Rating**: remove ou confirma a seleção de imagens. Ex.: `python host/mcp_host_ollama.py --mode rating --limit 150`
   - **Tagging**: adiciona tags sugeridas pelo modelo. Ex.: `python host/mcp_host_lmstudio.py --mode tagging --tag viagem --dry-run`
   - **Tratamento**: gera um plano automatizado de pós-processo. Ex.: `python host/mcp_host_ollama.py --mode tratamento --source all --limit 50`
   - **Export**: exige `--target-dir` sem `..`, redirecionamentos ou caracteres de shell e aceita apenas
     formatos `jpg`, `jpeg`, `tif`, `tiff`, `png` e `webp`. Ex.:
     ```bash
     python host/mcp_host_ollama.py --mode export --source path --path-contains cliente-x --target-dir out_job_x
     ```
   - **Completo**: roda rating → tagging → tratamento → export em sequência. Exige `--target-dir` e respeita o `--prompt-variant` escolhido:
     ```bash
     python host/mcp_host_ollama.py --mode completo --source all --target-dir entrega_evento --prompt-variant avancado
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

## Fluxo host ↔ dt_mcp_server ↔ LLM

O ciclo completo começa com o host subindo `dt_mcp_server.lua`, descobrindo ferramentas disponíveis e, em seguida, combinando metadados + imagens com o LLM. Sempre que estiver experimentando prompts novos, mantenha `--dry-run` para garantir que nenhum rating/tag/export seja aplicado no catálogo.

### Diagrama simplificado

```
Host (Python) --initialize--> dt_mcp_server.lua --tools/list--> catálogo do darktable
Host <--lista de ferramentas-- dt_mcp_server.lua
Host --list_collection/list_by_*--> dt_mcp_server.lua --> darktable (metadados/imagens)
Host (envia imagens+metadados) --> LLM (gera plano + tool_calls) --> Host --tools/call--> dt_mcp_server.lua
```

### Exemplos de requisições/respostas JSON

- **Handshake inicial**
  - Requisição: `{"jsonrpc":"2.0","id":"1","method":"initialize","params":{}}`
  - Resposta esperada (resumida):
    ```json
    {
      "jsonrpc": "2.0",
      "id": "1",
      "result": {
        "protocolVersion": "2024-11-05",
        "serverInfo": {"name": "darktable-mcp-batch", "version": "0.2.0"},
        "capabilities": {"tools": {"listChanged": false}}
      }
    }
    ```

- **Listar coleção**
  - Requisição: `{"jsonrpc":"2.0","id":"2","method":"tools/call","params":{"name":"list_collection","arguments":{"min_rating":0,"only_raw":false,"collection_path":"cliente-x"}}}`
  - Resposta (trecho):
    ```json
    {
      "jsonrpc": "2.0",
      "id": "2",
      "result": {
        "content": [
          {"type": "json", "json": [{"id": 123, "path": "/home/user/fotos/cliente-x", "rating": 2, "is_raw": true}]}
        ],
        "isError": false
      }
    }
    ```

- **Resposta esperada do LLM para aplicar ações** (exemplo OpenAI-compatible com tool call de rating):
  ```json
  {
    "role": "assistant",
    "tool_calls": [
      {
        "id": "call-1",
        "type": "function",
        "function": {
          "name": "apply_batch_edits",
          "arguments": "{\"edits\":[{\"id\":123,\"rating\":3},{\"id\":124,\"rating\":5}]}"
        }
      }
    ],
    "content": "Ajustando ratings conforme nitidez/duplicatas."
  }
  ```

### Dry-run seguro

- **CLI Ollama**: `python host/mcp_host_ollama.py --mode rating --source all --dry-run`
- **CLI LM Studio**: `python host/mcp_host_lmstudio.py --mode rating --source all --dry-run`
- Resultado esperado: o host imprime o plano (tool calls, filtros e amostra de imagens) e encerra sem chamar `apply_batch_edits`, `tag_batch` ou `export_collection`.

### Troubleshooting do fluxo

- **Timeout ao aguardar o LLM**: aumente `--timeout` no host, valide conectividade com `curl <LLM_URL>/v1/models` e reduza `--limit` para mandar amostras menores.
- **`darktable-cli` ausente**: confirme com `which darktable-cli` ou use `DARKTABLE_CLI_CMD="flatpak run --command=darktable-cli org.darktable.Darktable"`. Sem o binário, `export_collection` falhará.
- **Permissões do diretório de export**: garanta que o usuário possa criar/gravar no `--target-dir`; em ambientes restritos, teste primeiro com `--dry-run` e depois rode `mkdir -p <dir>` antes do export.

## Uso com LM Studio

- Inicie o servidor de API local no LM Studio (modo OpenAI-compatible).
- Ajuste `LMSTUDIO_URL` e `LMSTUDIO_MODEL` em `host/mcp_host_lmstudio.py`.

Exemplo:

```bash
python host/mcp_host_lmstudio.py --mode rating --source all --dry-run
```

Escolha um modelo com suporte a visão (por exemplo, checkpoints *Vision* servidos via API OpenAI-like).
Use `--text-only` se quiser cair no fluxo antigo baseado apenas em metadados.

Depois é só adaptar os parâmetros de linha de comando para `tagging` e `export`.

Para ver a versão do host ou confirmar dependências antes de rodar, use `--version` e `--check-deps`.

## Logs e diagnóstico

- Os hosts salvam sempre um JSON em `logs/batch-<modo>-<timestamp>.json` com a amostra enviada ao modelo,
  a resposta bruta e metadados como o modo e a fonte. Anote o caminho impresso na saída para abrir o arquivo
  correto depois de cada execução.
- Os logs facilitam reproduzir falhas: registre o `mode`, `source` e o trecho de imagens (`images_sample`)
  ao abrir um relatório para depuração.
- Caso precise compartilhar logs, remova ou anonimize caminhos e nomes de arquivos antes de enviar.

## Troubleshooting rápido

- **`target_dir deve ser string não vazia` ou `target_dir is required`**: o export exige `--target-dir` com
  um nome simples (sem quebras de linha). Se o diretório não existir, ele é criado automaticamente; passe
  `--target-dir out_job_x` ou similar.
- **`format deve conter apenas letras/números`**: use formatos alfanuméricos como `jpg` ou `tif` no `--format`.
- **`darktable-cli não encontrado no PATH`**: instale o pacote do darktable com CLI ou ajuste o PATH antes de
  exportar. No Linux, confirmar com `which darktable-cli` e reinstalar via gerenciador de pacotes se necessário.
- **Export falha para caminhos específicos**: verifique permissões e se o disco está acessível; o stderr do host
  lista cada ID que falhou e o comando usado. Use `--dry-run` antes para validar caminhos e formatos.
- **Erros ao baixar ou usar modelos**: confira se o servidor Ollama/LM Studio está em execução e se o modelo
  existe localmente. Rode `python host/mcp_host_ollama.py --check-deps` para validar dependências rapidamente.

## Formato esperado de respostas do LLM

Os hosts esperam respostas JSON simples. Exemplos mínimos por modo:

- `rating`: `{ "edits": [ { "id": 123, "rating": 3 } ] }`
- `tagging`: `{ "tags": [ { "tag": "job:cliente-x", "ids": [1,2,3] } ] }`
- `export`: `{ "ids_para_exportar": [1,2,3] }` (ou `ids`)

O log em `logs/batch-*.json` inclui a resposta bruta do modelo e metadados da chamada (modelo, URL, latência).

## Comportamento de colorlabels e export

- `set_colorlabel_batch` ativa a cor solicitada em cada imagem, sem limpar marcas anteriores. Caso precise
  sobrescrever cores existentes, faça um passo de limpeza antes de aplicar novas cores.
- `export_collection` valida o diretório alvo e o formato (somente letras/números), rejeitando `..`,
  redirecionamentos (`>`, `<`, `|`) ou caracteres de shell como `;`, `&`, `` ` `` e `$()`.
  Formatos aceitos: `jpg`, `jpeg`, `tif`, `tiff`, `png` e `webp`. A função exige `darktable-cli` no `PATH`,
  registra no stderr cada export que falhar e retorna um resumo com eventuais erros em JSON para ajudar na
  depuração.

## Avaliação rápida da base

Para uma visão consolidada da arquitetura, riscos atuais e sugestões de robustez/usabilidade, consulte o relatório em [ANALYSIS.md](ANALYSIS.md).
