"""
Gerador de movable_items_db.py a partir de objects.srv

Lógica:
- MOVABLE: items que NÃO têm {Unmove} E NÃO têm {Unpass}
- UNMOVABLE: items que têm {Unmove} OU {Unpass}

A flag {Take} NÃO é relevante para esta classificação.
"""
import re
import os

def parse_flags(flag_str):
    """Parse flags string into a set."""
    return {f.strip() for f in flag_str.split(',')}

def generate_movable_db(input_file, output_file):
    """Generate movable items database from objects.srv."""
    movable_ids = []
    unmovable_ids = []

    with open(input_file, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()

    blocks = content.split("TypeID")

    print(f"Processando {len(blocks) - 1} items...")

    for block in blocks[1:]:
        try:
            # Parse TypeID
            id_match = re.search(r'\s*=\s*(\d+)', block)
            if not id_match:
                continue
            type_id = int(id_match.group(1))

            # Parse Flags
            flags_match = re.search(r'Flags\s*=\s*{(.*?)}', block, re.DOTALL)
            flags = set()
            if flags_match:
                flags = parse_flags(flags_match.group(1))

            # Lógica correta:
            # MOVABLE = NÃO tem Unmove E NÃO tem Unpass
            # UNMOVABLE = tem Unmove OU tem Unpass
            has_unmove = 'Unmove' in flags
            has_unpass = 'Unpass' in flags

            if not has_unmove and not has_unpass:
                movable_ids.append(type_id)
            else:
                unmovable_ids.append(type_id)

        except Exception as e:
            continue

    # Sort IDs for cleaner output
    movable_ids.sort()
    unmovable_ids.sort()

    # Generate output file
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("# ARQUIVO GERADO AUTOMATICAMENTE a partir de objects.srv\n")
        f.write("# NÃO EDITE MANUALMENTE - use o script utils/generate_movable_db.py\n")
        f.write("\n")
        f.write("# Itens MOVÍVEIS: NÃO têm {Unmove} E NÃO têm {Unpass}\n")
        f.write("# Podem ser pegos/arrastados pelo jogador\n")
        f.write("MOVABLE_IDS = {\n")
        for type_id in movable_ids:
            f.write(f"    {type_id},\n")
        f.write("}\n")
        f.write("\n")
        f.write("# Itens NÃO MOVÍVEIS: têm {Unmove} OU {Unpass}\n")
        f.write("# Objetos do mapa: chão, paredes, obstáculos fixos, etc.\n")
        f.write("UNMOVABLE_IDS = {\n")
        for type_id in unmovable_ids:
            f.write(f"    {type_id},\n")
        f.write("}\n")
        f.write("\n")
        f.write("\n")
        f.write("def is_movable(item_id):\n")
        f.write('    """\n')
        f.write("    Verifica se um item pode ser movido.\n")
        f.write("    \n")
        f.write("    Baseado nas flags do objects.srv:\n")
        f.write("    - MOVABLE = NÃO tem {Unmove} E NÃO tem {Unpass}\n")
        f.write("    - UNMOVABLE = tem {Unmove} OU {Unpass}\n")
        f.write("    \n")
        f.write("    Args:\n")
        f.write("        item_id: ID do item\n")
        f.write("        \n")
        f.write("    Returns:\n")
        f.write("        True se pode ser movido, False se não pode, None se desconhecido\n")
        f.write('    """\n')
        f.write("    if item_id in MOVABLE_IDS:\n")
        f.write("        return True\n")
        f.write("    if item_id in UNMOVABLE_IDS:\n")
        f.write("        return False\n")
        f.write("    return None  # Item desconhecido\n")

    print(f"Gerado: {output_file}")
    print(f"  MOVABLE_IDS: {len(movable_ids)} items")
    print(f"  UNMOVABLE_IDS: {len(unmovable_ids)} items")

if __name__ == "__main__":
    # Paths relative to script location
    script_dir = os.path.dirname(os.path.abspath(__file__))
    db_dir = os.path.join(script_dir, "..", "database")

    input_file = os.path.join(db_dir, "objects.srv")
    output_file = os.path.join(db_dir, "movable_items_db.py")

    generate_movable_db(input_file, output_file)
