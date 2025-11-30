Você recebe fotos com metadados e (quando disponível) a própria imagem. Crie uma taxonomia
mais detalhada de tags de job/projeto, respeitando o formato "job:<categoria>[:subgrupo]".

Regras avançadas:
- Agrupe por narrativa/etapa (ex.: "job:cliente-x:making-of", "job:cliente-x:final").
- Reaproveite tags existentes quando os paths/nomes sugerirem relação com jobs anteriores.
- Adicione até 3 observações específicas por id, focando em cenas-chave ou problemas visuais.

Resposta APENAS em JSON:
{
  "tags": [
    {"tag": "job:cliente-x", "ids": [1,2]},
    {"tag": "job:cliente-x:making-of", "ids": [3]}
  ],
  "observacoes": {"<id>": "nota objetiva com até 20 palavras"}
}

Se nada for etiquetado, retorne estruturas vazias.
