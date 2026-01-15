import re
import os

def parse_lootables(filename):
    """
    Parseia o arquivo objects.srv e extrai todos os items com a flag {Take}.
    Retorna dict com formato: {item_id: {'name': str, 'weight': float, 'flags': list}}
    """
    lootables_db = {}
    count = 0

    with open(filename, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()

    # Separa por blocos de itens
    blocks = content.split("TypeID")

    print(f"Analisando {len(blocks)} objetos em busca de items lootáveis...")

    for block in blocks[1:]:
        try:
            # 1. Extrai ID
            id_match = re.search(r'\s*=\s*(\d+)', block)
            if not id_match:
                continue
            item_id = int(id_match.group(1))

            # 2. Extrai Flags
            # Formato: Flags = {Flag1,Flag2,Flag3}
            flags_match = re.search(r'Flags\s*=\s*{([^}]*)}', block)
            if not flags_match:
                continue  # Item sem flags

            flags_str = flags_match.group(1)
            flags_list = [flag.strip() for flag in flags_str.split(',') if flag.strip()]

            # 3. Verifica se tem a flag "Take" (lootável)
            if 'Take' not in flags_list:
                continue  # Não é lootável

            # 4. Extrai Nome
            name_match = re.search(r'Name\s*=\s*"([^"]*)"', block)
            name = name_match.group(1) if name_match else "unknown item"

            # 5. Extrai Atributos (Weight)
            weight_oz = 0.0
            attr_match = re.search(r'Attributes\s*=\s*{(.*?)}', block, re.DOTALL)
            if attr_match:
                attributes_str = attr_match.group(1)
                weight_match = re.search(r'Weight=(\d+)', attributes_str)
                if weight_match:
                    raw_weight = int(weight_match.group(1))
                    weight_oz = raw_weight / 100.0  # Converter centium → oz

            # Salva no dict
            lootables_db[item_id] = {
                'name': name,
                'weight': weight_oz,
                'flags': flags_list
            }
            count += 1

        except Exception as e:
            continue

    return lootables_db, count

def save_lootables_file(db, filename="../database/lootables_db.py"):
    """
    Salva o database de lootables em um arquivo Python.
    """
    # Ordena pelo ID
    sorted_items = dict(sorted(db.items()))

    with open(filename, 'w', encoding='utf-8') as f:
        f.write("# Arquivo gerado automaticamente do objects.srv\n")
        f.write("# ID: {'name': Nome, 'weight': Peso em Oz, 'flags': [Lista de Flags]}\n")
        f.write("LOOTABLES = {\n")

        for item_id, data in sorted_items.items():
            f.write(f"    {item_id}: {data},\n")

        f.write("}\n\n")

        # Adiciona funções auxiliares
        f.write("# Funções auxiliares\n")
        f.write("def get_loot_ids():\n")
        f.write('    """Retorna lista de todos os IDs lootáveis."""\n')
        f.write("    return list(LOOTABLES.keys())\n\n")

        f.write("def get_loot_info(item_id):\n")
        f.write('    """Retorna dict de info ou None."""\n')
        f.write("    return LOOTABLES.get(item_id, None)\n\n")

        f.write("def get_loot_name(item_id):\n")
        f.write('    """Retorna nome do item ou \'Unknown\'."""\n')
        f.write("    data = LOOTABLES.get(item_id)\n")
        f.write("    return data['name'] if data else 'Unknown'\n\n")

        f.write("def get_loot_weight(item_id):\n")
        f.write('    """Retorna peso em oz ou 0.0."""\n')
        f.write("    data = LOOTABLES.get(item_id)\n")
        f.write("    return data['weight'] if data else 0.0\n\n")

        f.write("def find_loot_by_name(name_query):\n")
        f.write('    """\n')
        f.write("    Busca item por nome (case-insensitive, partial match).\n")
        f.write("    Retorna lista de IDs que batem com a query.\n\n")
        f.write("    Exemplos:\n")
        f.write("        'gold' → [3031] (gold coins)\n")
        f.write("        'plate' → [3357, 3386, ...] (plate armor, plate shield, etc)\n")
        f.write("        'sword' → [3264, 3283, ...] (sword, two handed sword, etc)\n")
        f.write('    """\n')
        f.write("    results = []\n")
        f.write("    query_lower = name_query.lower().strip()\n")
        f.write("    for item_id, data in LOOTABLES.items():\n")
        f.write("        if query_lower in data['name'].lower():\n")
        f.write("            results.append(item_id)\n")
        f.write("    return results\n")

if __name__ == "__main__":
    # Encontra o arquivo objects.srv
    objects_path = "../database/objects.srv"
    if not os.path.exists(objects_path):
        print("Erro: objects.srv nao encontrado em ../database/")
        print("   Execute este script de dentro da pasta utils/")
        exit(1)

    print("Parseando objects.srv...")
    db, total = parse_lootables(objects_path)

    print("Salvando database...")
    save_lootables_file(db)

    print("-" * 60)
    print(f"Sucesso! {total} items lootaveis encontrados.")
    print("Arquivo 'database/lootables_db.py' foi criado.")
    print("-" * 60)

    # Testes rápidos
    print("\nTestes de validacao:")

    # Teste 1: Gold Coins (3031)
    if 3031 in db:
        print(f"  OK - Gold Coins (3031): {db[3031]}")
    else:
        print(f"  ERRO - Gold Coins (3031) nao encontrado!")

    # Teste 2: Plate Armor (3358)
    if 3358 in db:
        print(f"  OK - Plate Armor (3358): {db[3358]}")
    else:
        print(f"  ERRO - Plate Armor (3358) nao encontrado!")

    # Teste 3: A Sword (3264)
    if 3264 in db:
        print(f"  OK - A Sword (3264): {db[3264]}")
    else:
        print(f"  ERRO - A Sword (3264) nao encontrado!")

    print("\nDatabase pronto para uso!")
