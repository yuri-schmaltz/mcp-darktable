import os
import yaml
from pathlib import Path

def validate_prompt_header(prompt_path):
    with open(prompt_path, encoding='utf-8') as f:
        lines = f.readlines()
    if not lines or not lines[0].startswith('---'):
        return False, 'Sem cabeçalho YAML'
    header = []
    for line in lines[1:]:
        if line.startswith('---'):
            break
        header.append(line)
    try:
        meta = yaml.safe_load(''.join(header))
    except Exception as e:
        return False, f'YAML inválido: {e}'
    required = ['fluxo', 'variante', 'changelog']
    for field in required:
        if field not in meta:
            return False, f'Campo obrigatório ausente: {field}'
    return True, ''

def main():
    base = Path(__file__).parent.parent / 'config' / 'prompts'
    for file in base.glob('*.md'):
        ok, msg = validate_prompt_header(file)
        if not ok:
            print(f'ERRO: {file.name}: {msg}')
        else:
            print(f'OK: {file.name}')

if __name__ == '__main__':
    main()
