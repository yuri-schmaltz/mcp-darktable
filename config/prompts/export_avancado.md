---
fluxo: export
variante: avancado
autor: orquestrador-ai
data: 2025-12-30
changelog:
  - 2025-12-30: Adição de cabeçalho YAML para governança e rastreabilidade.
---
Você recebe uma lista de fotos relacionadas (mesmo job/evento). Use visão + metadados para
selecionar as imagens finais de entrega.

Critérios avançados:
- Priorize consistência de narrativa: escolha sequências completas (ex.: entrada, pico, reação).
- Prefira arquivos RAW com rating >= 3 e colorlabels "green/blue"; aceite outras cores apenas se
  indispensáveis para contar a história.
- Evite variações redundantes; mantenha apenas a melhor de cada sequência.

Saída APENAS em JSON:
{
  "ids_para_exportar": [<ids>],
  "notas": {"<id>": "motivo da escolha ou motivo para excluir"}
}

Inclua pelo menos uma nota geral se nenhuma foto atingir rating 4 ou 5.
