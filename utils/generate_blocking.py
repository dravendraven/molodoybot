import os

def generate_ids(srv_path):
    blocking_ids = set() # Unpass
    avoid_ids = set()    # Avoid
    current_id = None
    
    print(f"Lendo: {srv_path}...")
    
    try:
        with open(srv_path, 'r', encoding='latin-1', errors='ignore') as f:
            for line in f:
                line = line.strip()
                
                if line.startswith('TypeID'):
                    parts = line.split('=')
                    if len(parts) > 1:
                        id_part = parts[1].split('#')[0].strip()
                        if id_part.isdigit():
                            current_id = int(id_part)
                
                elif line.startswith('Flags') and current_id is not None:
                    # Lógica de Classificação
                    if 'Unpass' in line:
                        blocking_ids.add(current_id)
                    elif 'Avoid' in line:
                        avoid_ids.add(current_id)
                        
    except FileNotFoundError:
        print("Erro: objects.srv não encontrado.")
        return set(), set()

    return blocking_ids, avoid_ids

def print_set(name, data):
    print(f"{name} = {{")
    lst = sorted(list(data))
    chunk_size = 15
    for i in range(0, len(lst), chunk_size):
        chunk = lst[i:i + chunk_size]
        print("    " + ", ".join(str(x) for x in chunk) + ",")
    print("}")

if __name__ == "__main__":
    srv_file = "objects.srv" 
    if not os.path.exists(srv_file): srv_file = os.path.join("database", "objects.srv")

    block, avoid = generate_ids(srv_file)
    
    print("-" * 40)
    print("COPIE ABAIXO PARA database/tiles_config.py")
    print("-" * 40)
    
    # 1. Manuais (Sempre necessários)
    print("MANUAL_BLOCKING_IDS = {99} # Players/Creatures")
    print("")
    
    # 2. Gerados
    print_set("GENERATED_BLOCKING_IDS", block)
    print("")
    print_set("GENERATED_AVOID_IDS", avoid)
    
    print("-" * 40)
    print(f"Stats: {len(block)} Blocking, {len(avoid)} Avoid.")