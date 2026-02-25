"""Script auxiliar para atualizar CURRENT_VERSION no auto_update.py"""
import re
import sys

def update_version(version):
    with open('auto_update.py', 'r', encoding='utf-8') as f:
        content = f.read()

    new_content = re.sub(
        r'CURRENT_VERSION = "[^"]+"',
        f'CURRENT_VERSION = "{version}"',
        content
    )

    with open('auto_update.py', 'w', encoding='utf-8') as f:
        f.write(new_content)

    print(f'CURRENT_VERSION atualizado para {version}')

if __name__ == '__main__':
    if len(sys.argv) > 1:
        update_version(sys.argv[1])
    else:
        # Lê do version.txt
        with open('version.txt', 'r') as f:
            version = f.read().strip()
        update_version(version)
