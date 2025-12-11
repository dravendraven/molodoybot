import re

# Definições de "Role" (Papel do item no jogo)
ROLE_WALK  = 0  # Chão normal / Item inofensivo
ROLE_BLOCK = 1  # Parede / Obstáculo fixo
ROLE_STACK = 2  # Parcel-like (Puxar para o pé)
ROLE_MOVE  = 3  # Table-like (Empurrar para o lado)

def parse_flags(flag_str):
    return {f.strip() for f in flag_str.split(',')}

def get_item_role(flags):
    is_unpass = 'Unpass' in flags
    is_unmove = 'Unmove' in flags
    is_take   = 'Take' in flags
    is_height = 'Height' in flags or 'Elevation' in flags # As vezes aparece como Elevation

    # 1. Parede Sólida (Não passa, não move)
    if is_unpass and is_unmove:
        return ROLE_BLOCK

    # 2. Obstáculo Móvel "Duro" (Mesa/Cadeira)
    # Não passa, mas dá pra mover.
    if is_unpass and not is_unmove:
        return ROLE_MOVE

    # 3. Obstáculo de Pilha "Mole" (Parcel/Box)
    # Passa (se for 1), tem altura (vira parede se empilhar), dá pra pegar/mover.
    # Nota: Alguns itens tem Height mas não Take (ex: balcão de loja). Esses sao BLOCK ou MOVE.
    # Parcel ideal: Não é Unpass, tem Height, tem Take.
    if not is_unpass and is_height and is_take:
        return ROLE_STACK

    # 4. Resto (Chão, Decoração rasteira, Gold, etc)
    return ROLE_WALK

def generate_db(filename):
    db_content = "ITEMS = {\n"
    count = 0
    
    with open(filename, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
        
    blocks = content.split("TypeID")
    
    print(f"Lendo {len(blocks)} blocos...")

    for block in blocks[1:]:
        try:
            # ID
            id_match = re.search(r'\s*=\s*(\d+)', block)
            if not id_match: continue
            tid = int(id_match.group(1))
            
            # Flags
            flags_match = re.search(r'Flags\s*=\s*{(.*?)}', block, re.DOTALL)
            flags = set()
            if flags_match:
                flags = parse_flags(flags_match.group(1))
            
            role = get_item_role(flags)
            
            # Só salvamos no DB se o item for relevante (não for WALK padrão)
            # Isso economiza memória e tamanho do arquivo. 
            # Se o ID não estiver no dict, assumimos que é WALK.
            if role != ROLE_WALK:
                # Comentário com o nome pra facilitar debug
                name_match = re.search(r'Name\s*=\s*"([^"]*)"', block)
                name = name_match.group(1) if name_match else "???"
                
                db_content += f"    {tid}: {role}, # {name}\n"
                count += 1
                
        except Exception as e:
            continue

    db_content += "}\n"
    
    with open("items_db.py", "w", encoding='utf-8') as f:
        f.write("# ARQUIVO GERADO AUTOMATICAMENTE\n")
        f.write("# ROLES: 0=WALK (Default), 1=BLOCK, 2=STACK (Parcel), 3=MOVE (Table)\n")
        f.write(db_content)
        
    print(f"Database gerada com {count} itens especiais.")

if __name__ == "__main__":
    generate_db("objects.srv")