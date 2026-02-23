#!/usr/bin/env python3
# tools/whitelist_manager.py
"""
Ferramenta de Gerenciamento de Whitelist para MolodoyBot
Interface interativa para gerenciar personagens autorizados.
"""

import base64
import os
import sys
import json
from pathlib import Path

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

# ==============================================================================
# CONFIGURACAO
# ==============================================================================

WHITELIST_FILE = Path(__file__).parent / ".whitelist_data.json"
PASSPHRASE = "MolodoySecretBot2024!MB"

# ==============================================================================
# FUNCOES DE CRIPTOGRAFIA
# ==============================================================================

def derive_key(passphrase: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=480000,
    )
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode()))


def generate_salt() -> bytes:
    return os.urandom(16)


# ==============================================================================
# ARMAZENAMENTO
# ==============================================================================

def load_whitelist() -> dict:
    if WHITELIST_FILE.exists():
        with open(WHITELIST_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"names": [], "salt": None}


def save_whitelist(data: dict):
    with open(WHITELIST_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ==============================================================================
# COMANDOS
# ==============================================================================

def add_char(name: str) -> bool:
    """Adiciona um personagem. Retorna True se adicionou."""
    data = load_whitelist()
    names = data.get("names", [])
    normalized = name.strip()

    if not normalized:
        return False

    if any(n.lower() == normalized.lower() for n in names):
        print(f"  [!] '{name}' ja existe")
        return False

    names.append(normalized)
    data["names"] = names
    save_whitelist(data)
    print(f"  [+] Adicionado: {normalized}")
    return True


def remove_char(name: str) -> bool:
    """Remove um personagem. Retorna True se removeu."""
    data = load_whitelist()
    names = data.get("names", [])
    normalized_lower = name.strip().lower()
    original_count = len(names)
    names = [n for n in names if n.lower() != normalized_lower]

    if len(names) == original_count:
        print(f"  [!] '{name}' nao encontrado")
        return False

    data["names"] = names
    save_whitelist(data)
    print(f"  [-] Removido: {name}")
    return True


def list_chars():
    """Lista todos os personagens."""
    data = load_whitelist()
    names = data.get("names", [])

    print()
    if not names:
        print("  (whitelist vazia)")
    else:
        print(f"  Personagens autorizados ({len(names)}):")
        print("  " + "-" * 30)
        for i, name in enumerate(sorted(names), 1):
            print(f"  {i:2}. {name}")
    print()


def generate_blob():
    """Gera e mostra o blob criptografado."""
    data = load_whitelist()
    names = data.get("names", [])

    if not names:
        print("\n  [!] Whitelist vazia. Adicione personagens primeiro.\n")
        return

    salt = data.get("salt")
    if salt:
        salt = base64.b64decode(salt)
    else:
        salt = generate_salt()
        data["salt"] = base64.b64encode(salt).decode('ascii')
        save_whitelist(data)

    plaintext = "\n".join(names)
    key = derive_key(PASSPHRASE, salt)
    fernet = Fernet(key)
    encrypted = fernet.encrypt(plaintext.encode('utf-8'))

    salt_b64 = base64.b64encode(salt).decode('ascii')
    encrypted_b64 = base64.b64encode(encrypted).decode('ascii')

    print()
    print("  " + "=" * 60)
    print("  COPIE PARA core/whitelist.py:")
    print("  " + "=" * 60)
    print()
    print(f'  _EMBEDDED_SALT = "{salt_b64}"')
    print()
    print(f'  _EMBEDDED_WHITELIST = "{encrypted_b64}"')
    print()
    print("  " + "=" * 60)
    print(f"  {len(names)} personagem(ns) criptografado(s)")
    print("  " + "=" * 60)
    print()


def clear_all():
    """Limpa toda a whitelist."""
    data = {"names": [], "salt": None}
    save_whitelist(data)
    print("  [!] Whitelist limpa")


# ==============================================================================
# INTERFACE INTERATIVA
# ==============================================================================

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')


def print_header():
    data = load_whitelist()
    count = len(data.get("names", []))

    print()
    print("  ╔════════════════════════════════════════╗")
    print("  ║     WHITELIST MANAGER - MolodoyBot     ║")
    print("  ╠════════════════════════════════════════╣")
    print(f"  ║  Personagens autorizados: {count:3}          ║")
    print("  ╚════════════════════════════════════════╝")
    print()


def print_menu():
    print("  Comandos:")
    print("  ─────────────────────────────────────────")
    print("  [nome]     Adiciona personagem")
    print("  -[nome]    Remove personagem (ex: -Hacker)")
    print("  list       Lista todos")
    print("  gen        Gera codigo criptografado")
    print("  clear      Limpa tudo")
    print("  exit       Sair")
    print("  ─────────────────────────────────────────")
    print()


def interactive_mode():
    """Modo interativo principal."""
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

        cmd_lower = cmd.lower()

        if cmd_lower in ['exit', 'quit', 'q', 'sair']:
            print("  Bye!")
            break

        elif cmd_lower in ['list', 'ls', 'l']:
            list_chars()

        elif cmd_lower in ['gen', 'generate', 'g']:
            generate_blob()

        elif cmd_lower in ['clear', 'limpar']:
            confirm = input("  Tem certeza? (s/n): ").strip().lower()
            if confirm in ['s', 'sim', 'y', 'yes']:
                clear_all()
                list_chars()

        elif cmd_lower in ['help', 'h', '?']:
            print_menu()

        elif cmd_lower == 'cls':
            clear_screen()
            print_header()

        elif cmd.startswith('-'):
            # Remove personagem
            name = cmd[1:].strip()
            if name:
                remove_char(name)

        else:
            # Adiciona personagem
            add_char(cmd)


# ==============================================================================
# MAIN
# ==============================================================================

def main():
    # Se tiver argumentos, usa modo CLI tradicional
    if len(sys.argv) > 1:
        cmd = sys.argv[1].lower()

        if cmd == "add" and len(sys.argv) >= 3:
            add_char(" ".join(sys.argv[2:]))
        elif cmd == "remove" and len(sys.argv) >= 3:
            remove_char(" ".join(sys.argv[2:]))
        elif cmd == "list":
            list_chars()
        elif cmd in ["gen", "generate"]:
            generate_blob()
        elif cmd == "clear":
            clear_all()
        else:
            print("Uso: python whitelist_manager.py [comando]")
            print("  Sem argumentos = modo interativo")
            print("  add <nome>    = adiciona personagem")
            print("  remove <nome> = remove personagem")
            print("  list          = lista todos")
            print("  gen           = gera blob")
    else:
        # Modo interativo
        interactive_mode()


if __name__ == "__main__":
    main()
