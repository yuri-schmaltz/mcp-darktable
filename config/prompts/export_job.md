Você recebe uma lista de fotos de um mesmo contexto (ex.: um job ou evento).

Cada foto tem:
- id
- path
- filename
- rating
- colorlabels

Observação: ao usar `set_colorlabel_batch`, a cor indicada é adicionada às existentes. Use
`"overwrite": true` apenas quando quiser limpar todas as colorlabels antes de aplicar a nova cor.

O objetivo é selecionar quais fotos devem ser EXPORTADAS para entrega ao cliente.

Regras sugeridas:
- Considere candidatas apenas com rating >= 3.
- Evite fotos duplicadas (mesmo filename base, numeração sequencial).
- Prefira fotos com colorlabel "green" ou "blue" se existir esse padrão.
- O conjunto final não precisa incluir todas as candidatas.

Saída APENAS em JSON, sem comentários adicionais, no formato:

{"ids_para_exportar":[1,2,3,...]}

Se não quiser exportar nenhuma, retorne {"ids_para_exportar": []}.
