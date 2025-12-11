import re

def parse_flags(flag_str):
    return {f.strip() for f in flag_str.split(',')}

def generate_obstacle_lists(filename):
    parcel_like = [] # Walkable single, Block stack, Movable
    table_like = []  # Block single, Movable
    
    with open(filename, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
        
    blocks = content.split("TypeID")
    
    for block in blocks[1:]:
        # Pega ID
        id_match = re.search(r'\s*=\s*(\d+)', block)
        if not id_match: continue
        tid = int(id_match.group(1))
        
        # Pega Nome
        name_match = re.search(r'Name\s*=\s*"([^"]*)"', block)
        name = name_match.group(1) if name_match else "unknown"
        
        # Pega Flags
        flags_match = re.search(r'Flags\s*=\s*{(.*?)}', block, re.DOTALL)
        flags = set()
        if flags_match:
            flags = parse_flags(flags_match.group(1))
            
        # ANÁLISE DE REGRAS
        
        is_unpass = 'Unpass' in flags
        is_unmove = 'Unmove' in flags
        is_take   = 'Take' in flags
        is_height = 'Height' in flags # A chave para o comportamento de stack
        
        # 1. Regra Parcel: Tem altura, dá pra pegar, não bloqueia sozinho
        if is_height and is_take and not is_unpass:
            parcel_like.append((tid, name))
            
        # 2. Regra Mesa: Bloqueia sempre, mas dá pra mover (não tem Unmove)
        # Nota: Algumas mesas não tem 'Take', mas não tem 'Unmove'.
        if is_unpass and not is_unmove:
            table_like.append((tid, name))

    return parcel_like, table_like

if __name__ == "__main__":
    parcels, tables = generate_obstacle_lists("objects.srv")
    
    print("# COPIE ISSO PARA O SEU CONFIG.PY OU MAP_READER.PY\n")
    
    print("PARCEL_LIKE_OBSTACLES = {")
    for tid, name in parcels:
        print(f"    {tid}, # {name}")
    print("}\n")
    
    print("TABLE_LIKE_OBSTACLES = {")
    for tid, name in tables:
        print(f"    {tid}, # {name}")
    print("}")