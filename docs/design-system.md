# Design System — darktable-mcp

## Objetivo
Padronizar componentes, tokens e guidelines para garantir consistência visual, acessibilidade e evolução sustentável da GUI.

## Tokens de Design
- **Cores**:
  - Primária: #2563eb (azul)
  - Erro: #dc2626 (vermelho)
  - Fundo: #f8fafc (cinza claro)
  - Texto: #1e293b (cinza escuro)
- **Tipografia**:
  - Fonte: 'Inter', Arial, sans-serif
  - Tamanhos: 14px, 16px, 18px (títulos)
- **Espaçamento**:
  - Base: 8px, 16px, 24px
- **Borda**:
  - Raio: 4px

## Componentes Base
- Botão (primário, secundário, desabilitado)
- Input/textfield
- Select/dropdown
- Feedback (alerta, sucesso, erro, loading)
- Card/painel

## Guidelines de Acessibilidade
- Foco visível em todos os controles
- Contraste mínimo 4.5:1
- Labels claros e associados
- Navegação por teclado
- Mensagens de erro e loading textuais

## Governança
- Toda alteração em tokens/componentes deve ser documentada neste arquivo.
- Revisão visual a cada release.
- Checklist de acessibilidade obrigatório antes de merge.

## Referências
- [WCAG 2.1](https://www.w3.org/WAI/WCAG21/quickref/)
- [Material Design](https://m3.material.io/)
