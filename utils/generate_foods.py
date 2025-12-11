import re

def parse_foods(filename):
    foods_db = {}
    count = 0
    
    with open(filename, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
        
    # Separa por blocos de itens
    blocks = content.split("TypeID")
    
    print(f"Analisando {len(blocks)} objetos em busca de comida...")
    
    for block in blocks[1:]:
        try:
            # 1. Extrai ID
            id_match = re.search(r'\s*=\s*(\d+)', block)
            if not id_match: continue
            item_id = int(id_match.group(1))
            
            # 2. Extrai Atributos
            # O bloco Attributes geralmente é: Attributes = {Key=Val, Key=Val}
            attr_match = re.search(r'Attributes\s*=\s*{(.*?)}', block, re.DOTALL)
            
            if not attr_match:
                continue # Item sem atributos não é comida regenerativa
                
            attributes_str = attr_match.group(1)
            
            # 3. Verifica se tem "Nutrition"
            # Procura por "Nutrition=NUMERO"
            nutri_match = re.search(r'Nutrition=(\d+)', attributes_str)
            
            if nutri_match:
                # É COMIDA!
                nutrition_ticks = int(nutri_match.group(1))
                
                # Cálculo de Segundos (Tick * 12)
                regen_seconds = nutrition_ticks * 12
                
                # 4. Extrai Nome
                name_match = re.search(r'Name\s*=\s*"([^"]*)"', block)
                name = name_match.group(1) if name_match else "unknown food"
                
                # 5. Extrai Peso (Weight)
                # Se não tiver peso, assumimos 0
                weight_match = re.search(r'Weight=(\d+)', attributes_str)
                raw_weight = int(weight_match.group(1)) if weight_match else 0
                weight_oz = raw_weight / 100.0
                
                # Salva no dict
                foods_db[item_id] = {
                    'name': name,
                    'regen': regen_seconds, # Tempo total que a comida cura
                    'weight': weight_oz     # Peso em oz.
                }
                count += 1
                
        except Exception as e:
            continue

    return foods_db, count

def save_foods_file(db, filename="foods_db.py"):
    # Ordena pelo ID para ficar bonitinho
    sorted_items = dict(sorted(db.items()))
    
    with open(filename, 'w', encoding='utf-8') as f:
        f.write("# Arquivo gerado automaticamente do objects.srv\n")
        f.write("# ID: {'name': Nome, 'regen': Segundos de Regen, 'weight': Peso em Oz}\n")
        f.write("FOODS = {\n")
        
        for item_id, data in sorted_items.items():
            f.write(f"    {item_id}: {data},\n")
            
        f.write("}\n")

if __name__ == "__main__":
    db, total = parse_foods("objects.srv")
    save_foods_file(db)
    print("-" * 40)
    print(f"Sucesso! {total} comidas encontradas.")
    print("Arquivo 'foods_db.py' foi criado.")
    
    # Teste rápido: Vamos ver se achou a Meat (3577) e o Fish (3578)
    if 3577 in db:
        print(f"Teste Meat (3577): {db[3577]} (Esperado: 180s, 13.0oz)")
    if 3578 in db:
        print(f"Teste Fish (3578): {db[3578]} (Esperado: 144s, 5.2oz)")