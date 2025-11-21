Você recebe uma lista de fotos de um mesmo contexto (ex.: um job ou evento).

Cada foto tem:
- id
- path
- filename
- rating
- colorlabels

O objetivo é selecionar quais fotos devem ser EXPORTADAS para entrega ao cliente.

Regras sugeridas:
- Considere candidatas apenas com rating >= 3.
- Evite fotos duplicadas (mesmo filename base, numeração sequencial).
- Prefira fotos com colorlabel "green" ou "blue" se existir esse padrão.
- O conjunto final não precisa incluir todas as candidatas.

Saída APENAS em JSON, sem comentários adicionais, no formato:

{"ids_para_exportar":[1,2,3,...]}

Se não quiser exportar nenhuma, retorne {"ids_para_exportar": []}.
