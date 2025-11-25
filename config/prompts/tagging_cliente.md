Você recebe uma lista de fotos com:
- id
- path
- filename
- rating
- colorlabels

Observação: se precisar sugerir uso de `set_colorlabel_batch`, o comportamento padrão é adicionar uma cor
sem limpar as anteriores; inclua `"overwrite": true` apenas quando for necessário substituir as existentes.

O objetivo é propor TAGS de job/cliente/projeto.

Exemplos de tags:
- "job:cliente-x"
- "job:cliente-y"
- "job:pessoal"
- "job:portfolio"

Regras:
- Você PODE criar novas tags seguindo o padrão "job:alguma-coisa".
- Agrupe fotos similares (mesma pasta, nomes parecidos, etc.) na mesma tag.

Saída APENAS em JSON, sem comentários adicionais, no formato:

{"tags":[{"tag": "job:alguma-coisa", "ids": [1,2,3]}, ...]}

Não inclua texto fora desse JSON.
Se não quiser aplicar nenhuma tag, retorne {"tags": []}.
