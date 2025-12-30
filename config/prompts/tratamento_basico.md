---
fluxo: tratamento
variante: basico
autor: orquestrador-ai
data: 2025-12-30
changelog:
  - 2025-12-30: Adição de cabeçalho YAML para governança e rastreabilidade.
---
Analise as imagens e sugira classificação e organização básica.

Retorne um JSON no formato:
{
  "treatments": [
    {
      "id": <id_da_imagem>,
      "rating": <numero_-1_a_5>,
      "color_label": "<red|yellow|green|blue|purple>",
      "notes": "<breve observacao sobre o que fazer>"
    }
  ]
}

Use:
- red: Descarte / Ruim (-1 ou 0)
- yellow: Dúvida / Tratar (1 a 3)
- green: Boa / Pronta (4 ou 5)
