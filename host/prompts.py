"""
Módulo utilitário para carregamento e validação de prompts YAML.
"""
import os
import yaml
from pathlib import Path

PROMPT_DIR = Path(__file__).parent.parent / 'config' / 'prompts'

def list_prompts():
    return list(PROMPT_DIR.glob('*.md'))

def load_prompt_file(filename):
    path = PROMPT_DIR / filename
    with open(path, encoding='utf-8') as f:
        content = f.read()
    header, body = None, content
    if content.startswith('---'):
        parts = content.split('---', 2)
        if len(parts) >= 3:
            header = yaml.safe_load(parts[1])
            body = parts[2].lstrip('\n')
    return header, body

def validate_prompt_header(header):
    required = ['fluxo', 'variante', 'changelog']
    if not header:
        return False, 'Sem cabeçalho YAML'
    for field in required:
        if field not in header:
            return False, f'Campo obrigatório ausente: {field}'
    return True, ''

def get_prompt(mode, variant='basico'):
    """Carrega prompt pelo modo e variante, validando header."""
    fname = f'{mode}_{variant}.md'
    header, body = load_prompt_file(fname)
    ok, msg = validate_prompt_header(header)
    if not ok:
        raise ValueError(f'Prompt inválido: {fname}: {msg}')
    return body