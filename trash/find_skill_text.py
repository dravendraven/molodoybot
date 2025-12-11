import pymem
import pymem.process
from config import *
from auto_loot import get_gui_panels # Reaproveita seu scanner poderoso

# Offsets (uitibia.h)
OFFSET_UI_PARENT = 0x0C
OFFSET_UI_ID     = 0x2C
OFFSET_UI_CHILD  = 0x24
OFFSET_UI_NEXT   = 0x10

# Offsets de Texto (GUIText)
# Tenta ler a string em 0x24 (m_first) ou 0x28 (m_text)
TEXT_OFFSETS = [0x24, 0x28]

def read_str(pm, ptr):
    """Lê string de um ponteiro de memória."""
    if ptr < 0x10000: return None
    try:
        # O valor no offset é um ponteiro para a string
        str_addr = pm.read_int(ptr)
        if str_addr < 0x10000: return None
        
        raw = pm.read_bytes(str_addr, 64)
        text = raw.split(b'\x00')[0].decode('latin1', errors='ignore').strip()
        
        if len(text) > 0 and all(c.isprintable() for c in text):
            return text
    except: pass
    return None

def main():
    print("--- SCANNER DE XP/H (VIA PAINEL 168) ---")
    try:
        pm = pymem.Pymem(PROCESS_NAME)
        base_addr = pymem.process.module_from_name(pm.process_handle, PROCESS_NAME).lpBaseOfDll
    except:
        print("Erro: Tibia não encontrado.")
        return

    # 1. Encontrar o painel de conteúdo das Skills
    panels = get_gui_panels(pm, base_addr)
    skills_content_addr = 0
    
    print(f"Analisando {len(panels)} painéis...")
    
    for p in panels:
        try:
            parent = pm.read_int(p['addr'] + OFFSET_UI_PARENT)
            parent_id = pm.read_int(parent + OFFSET_UI_ID)
            
            if parent_id == 6: # ID 6 = SKILLS
                skills_content_addr = p['addr']
                print(f"✅ PAINEL SKILLS ENCONTRADO! Addr: {hex(skills_content_addr)}")
                break
        except: pass

    if skills_content_addr == 0:
        print("❌ Janela de Skills não encontrada (Verifique se está aberta).")
        return

    # 2. Varrer os textos dentro desse painel
    print("\n--- CONTEÚDO ---")
    print("IDX | ADDR       | TEXTO (0x24)        | TEXTO (0x28)")
    print("-" * 60)
    
    # Pega o primeiro filho (Lista de labels)
    curr_child = pm.read_int(skills_content_addr + OFFSET_UI_CHILD)
    index = 0
    
    while curr_child != 0 and index < 100:
        txt_24 = read_str(pm, curr_child + 0x24)
        txt_28 = read_str(pm, curr_child + 0x28)
        
        t24 = txt_24 if txt_24 else ""
        t28 = txt_28 if txt_28 else ""
        
        if t24 or t28:
            print(f"#{index:<2} | {hex(curr_child)} | {t24:<20} | {t28}")
            
            if "Exp" in t24 or "Exp" in t28:
                print("    >>> RÓTULO ENCONTRADO <<<")
            
        curr_child = pm.read_int(curr_child + OFFSET_UI_NEXT)
        index += 1
        
    print("-" * 60)

if __name__ == "__main__":
    main()