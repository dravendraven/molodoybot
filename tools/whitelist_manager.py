#!/usr/bin/env python3
# tools/whitelist_manager.py
"""
Gerenciador de Whitelist para MolodoyBot
Gera o JSON para upload no GitHub Gist.

Uso:
    python whitelist_manager.py          # Modo interativo
    python whitelist_manager.py add X    # Adiciona char
    python whitelist_manager.py remove X # Remove char
    python whitelist_manager.py list     # Lista chars
    python whitelist_manager.py json     # Gera JSON para o Gist
"""

import os
import sys
import json
from pathlib import Path

# ==============================================================================
# CONFIGURACAO
# ==============================================================================

WHITELIST_FILE = Path(__file__).parent / ".whitelist_data.json"

DEFAULT_CONFIG = {
    "enabled": True,
    "block_unauthorized": False,
    "grace_period": 300,
    "characters": []
}

# ==============================================================================
# ARMAZENAMENTO LOCAL
# ==============================================================================

def load_whitelist() -> dict:
    if WHITELIST_FILE.exists():
        with open(WHITELIST_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # Garante campos obrigatorios
            for key, val in DEFAULT_CONFIG.items():
                if key not in data:
                    data[key] = val
            return data
    return DEFAULT_CONFIG.copy()


def save_whitelist(data: dict):
    with open(WHITELIST_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ==============================================================================
# COMANDOS
# ==============================================================================

def add_char(name: str) -> bool:
    data = load_whitelist()
    chars = data.get("characters", [])
    normalized = name.strip()

    if not normalized:
        return False

    if any(c.lower() == normalized.lower() for c in chars):
        print(f"  [!] '{name}' ja existe")
        return False

    chars.append(normalized)
    data["characters"] = chars
    save_whitelist(data)
    print(f"  [+] Adicionado: {normalized}")
    return True


def remove_char(name: str) -> bool:
    data = load_whitelist()
    chars = data.get("characters", [])
    normalized_lower = name.strip().lower()
    original_count = len(chars)
    chars = [c for c in chars if c.lower() != normalized_lower]

    if len(chars) == original_count:
        print(f"  [!] '{name}' nao encontrado")
        return False

    data["characters"] = chars
    save_whitelist(data)
    print(f"  [-] Removido: {name}")
    return True


def list_chars():
    data = load_whitelist()
    chars = data.get("characters", [])

    print()
    print(f"  Configuracao atual:")
    print(f"  - enabled: {data.get('enabled', True)}")
    print(f"  - block_unauthorized: {data.get('block_unauthorized', False)}")
    print(f"  - grace_period: {data.get('grace_period', 300)}s")
    print()

    if not chars:
        print("  (whitelist vazia)")
    else:
        print(f"  Personagens ({len(chars)}):")
        print("  " + "-" * 30)
        for i, name in enumerate(sorted(chars), 1):
            print(f"  {i:2}. {name}")
    print()


def generate_json():
    data = load_whitelist()

    output = json.dumps(data, indent=2, ensure_ascii=False)

    print()
    print("  " + "=" * 60)
    print("  JSON PARA O GITHUB GIST:")
    print("  " + "=" * 60)
    print()
    print(output)
    print()
    print("  " + "=" * 60)
    print()
    print("  INSTRUCOES:")
    print("  1. Va em https://gist.github.com")
    print("  2. Cole o JSON acima")
    print("  3. Nomeie o arquivo como 'whitelist.json'")
    print("  4. Clique em 'Create secret gist'")
    print("  5. Clique em 'Raw' e copie a URL")
    print("  6. Cole a URL em core/whitelist.py na linha _REMOTE_WHITELIST_URL")
    print()


def toggle_enabled():
    data = load_whitelist()
    data["enabled"] = not data.get("enabled", True)
    save_whitelist(data)
    status = "ATIVADA" if data["enabled"] else "DESATIVADA"
    print(f"  [!] Whitelist {status}")


def toggle_block():
    data = load_whitelist()
    data["block_unauthorized"] = not data.get("block_unauthorized", False)
    save_whitelist(data)
    status = "ATIVADO" if data["block_unauthorized"] else "DESATIVADO"
    print(f"  [!] Bloqueio {status}")


def set_grace(seconds: int):
    data = load_whitelist()
    data["grace_period"] = seconds
    save_whitelist(data)
    print(f"  [!] Grace period: {seconds}s")


def clear_all():
    data = DEFAULT_CONFIG.copy()
    save_whitelist(data)
    print("  [!] Whitelist limpa")


# ==============================================================================
# INTERFACE INTERATIVA
# ==============================================================================

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')


def print_header():
    data = load_whitelist()
    count = len(data.get("characters", []))
    enabled = "ON" if data.get("enabled", True) else "OFF"
    block = "ON" if data.get("block_unauthorized", False) else "OFF"

    print()
    print("  ╔════════════════════════════════════════╗")
    print("  ║   WHITELIST MANAGER (Online/Gist)      ║")
    print("  ╠════════════════════════════════════════╣")
    print(f"  ║  Chars: {count:3}  |  Enabled: {enabled:3}  |  Block: {block:3} ║")
    print("  ╚════════════════════════════════════════╝")
    print()


def print_menu():
    print("  Comandos:")
    print("  ─────────────────────────────────────────")
    print("  [nome]      Adiciona personagem")
    print("  -[nome]     Remove personagem")
    print("  list        Lista todos + config")
    print("  json        Gera JSON para o Gist")
    print("  toggle      Liga/desliga whitelist")
    print("  block       Liga/desliga bloqueio")
    print("  grace [s]   Define tempo de graca")
    print("  clear       Limpa tudo")
    print("  exit        Sair")
    print("  ─────────────────────────────────────────")
    print()


def interactive_mode():
    clear_screen()
    print_header()
    list_chars()
    print_menu()

    while True:
        try:
            cmd = input("  > ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n  Bye!")
            break

        if not cmd:
            continue

        parts = cmd.split(maxsplit=1)
        cmd_lower = parts[0].lower()

        if cmd_lower in ['exit', 'quit', 'q', 'sair']:
            print("  Bye!")
            break

        elif cmd_lower in ['list', 'ls', 'l']:
            list_chars()

        elif cmd_lower in ['json', 'j', 'gen', 'generate']:
            generate_json()

        elif cmd_lower == 'toggle':
            toggle_enabled()

        elif cmd_lower == 'block':
            toggle_block()

        elif cmd_lower == 'grace' and len(parts) > 1:
            try:
                seconds = int(parts[1])
                set_grace(seconds)
            except ValueError:
                print("  [!] Uso: grace <segundos>")

        elif cmd_lower in ['clear', 'limpar']:
            confirm = input("  Tem certeza? (s/n): ").strip().lower()
            if confirm in ['s', 'sim', 'y', 'yes']:
                clear_all()

        elif cmd_lower in ['help', 'h', '?']:
            print_menu()

        elif cmd_lower == 'cls':
            clear_screen()
            print_header()

        elif cmd.startswith('-'):
            name = cmd[1:].strip()
            if name:
                remove_char(name)

        else:
            add_char(cmd)


# ==============================================================================
# MAIN
# ==============================================================================

def main():
    if len(sys.argv) > 1:
        cmd = sys.argv[1].lower()

        if cmd == "add" and len(sys.argv) >= 3:
            add_char(" ".join(sys.argv[2:]))
        elif cmd == "remove" and len(sys.argv) >= 3:
            remove_char(" ".join(sys.argv[2:]))
        elif cmd == "list":
            list_chars()
        elif cmd == "json":
            generate_json()
        elif cmd == "toggle":
            toggle_enabled()
        elif cmd == "block":
            toggle_block()
        elif cmd == "clear":
            clear_all()
        else:
            print(__doc__)
    else:
        interactive_mode()


if __name__ == "__main__":
    main()
