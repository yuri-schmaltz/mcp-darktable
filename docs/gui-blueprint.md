# Blueprint GUI — darktable-mcp

## Tela Principal (Painel de Controle)

### Componentes Críticos
- **Barra de título**: Nome do app, versão, status de conexão.
- **Seleção de modo**: rating, tagging, tratamento, export, completo.
- **Filtros**: source, path, tag, collection, min-rating, only-raw.
- **Prompt/Config**: seleção de prompt, variante, edição rápida.
- **Execução**: botão de rodar, dry-run, progresso, logs.
- **Feedback**: área de mensagens, erros, sucesso, loading.

### Layout (wireframe simplificado)

```
+------------------------------------------------------+
| darktable-mcp-batch vX.Y [Conectado ao LLM]          |
+------------------------------------------------------+
| Modo: [rating|tagging|tratamento|export|completo]    |
| Fonte: [all|path|tag|collection]  Filtros: [...]     |
| Prompt: [basico|avancado|custom]  [Editar]           |
+------------------------------------------------------+
| [Rodar] [Dry-run]   Progresso: [#####-----]  60%     |
| Log: [Ver detalhes]                                  |
+------------------------------------------------------+
| [Mensagens/feedback: sucesso, erro, loading...]      |
+------------------------------------------------------+
```

## Tokens de Design
- **Cores**: fundo claro, destaque azul para ações, vermelho para erros.
- **Tipografia**: fonte sans-serif, tamanhos 14–18px.
- **Espaçamento**: 16px entre seções, 8px entre campos.
- **Botões**: primário (azul), secundário (cinza), desabilitado (cinza claro).

## Guidelines de Acessibilidade
- Foco visível em todos os campos/botões.
- Contraste mínimo 4.5:1.
- Labels claros e associados a inputs.
- Feedback textual para loading, erro e sucesso.
- Navegação por teclado em todos os controles.

## Próximos Passos
- Implementar componentes base reutilizáveis.
- Validar blueprint com usuários finais.
- Evoluir para design tokens e documentação visual completa.
