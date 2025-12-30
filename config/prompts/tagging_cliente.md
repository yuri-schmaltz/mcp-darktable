---
fluxo: tagging
variante: cliente
autor: orquestrador-ai
data: 2025-12-30
changelog:
  - 2025-12-30: Adição de cabeçalho YAML para governança e rastreabilidade.
---
Você recebe uma lista de fotos com metadados (id, path, filename, rating, colorlabels) e, quando
disponível, a própria imagem é enviada em mensagens multimodais. Use a imagem como base e os
metadados apenas como apoio.

Observação: se precisar sugerir uso de `set_colorlabel_batch`, o comportamento padrão é adicionar uma cor
sem limpar as anteriores; inclua `"overwrite": true` apenas quando for necessário substituir as existentes.

O objetivo é propor TAGS de job/cliente/projeto a partir do conteúdo visual (ex.: briefing, cenário,
tema da sessão, objetos/locações recorrentes).

Exemplos de tags:
- "job:cliente-x"
- "job:cliente-y"
- "job:pessoal"
- "job:portfolio"

Regras:
- Você PODE criar novas tags seguindo o padrão "job:alguma-coisa".
- Agrupe fotos similares (mesma pasta, nomes parecidos, elementos visuais parecidos) na mesma tag.

Saída APENAS em JSON, sem comentários adicionais, no formato:

{
  "tags":[{"tag": "job:alguma-coisa", "ids": [1,2,3]}],
  "observacoes": {"<id>": "nota curta opcional sobre o conteúdo"}
}

Não inclua texto fora desse JSON.
Se não quiser aplicar nenhuma tag, retorne {"tags": [], "observacoes": {}}.
