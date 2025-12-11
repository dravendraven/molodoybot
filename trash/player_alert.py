import pymem
import pymem.process
import time
import winsound
import requests # pip install requests
import os

# ==============================================================================
# CONFIGURAÇÕES DE TELEGRAM
# ==============================================================================
USE_TELEGRAM = True
BOT_TOKEN = "7238077578:AAELH9lr8dLGJqOE5mZlXmYkpH4fIHDAGAM"
CHAT_ID = "452514119"

# ==============================================================================
# CONFIGURAÇÕES DO JOGO
# ==============================================================================
PROCESS_NAME = "Tibia.exe"
MY_PLAYER_NAME = "It is Molodoy"

SAFE_CREATURES = ["Troll", "Wolf", "Deer", "Rabbit", "Spider", "Bug", "Rat"]

# Offsets (Seus Validados)
TARGET_ID_PTR = 0x1C681C 
REL_FIRST_ID = 0x130
STEP_SIZE = 156
OFFSET_NAME = 4
OFFSET_Z = 0x2C
OFFSET_VISIBLE = 0x8C # 148

MAX_CREATURES = 250

# Controle de Spam de Alerta
last_alert_time = 0
ALERT_COOLDOWN = 60 # Segundos (Só manda msg pro celular a cada 1 min)

# ==============================================================================
# FUNÇÃO DE ENVIO BLINDADA (FAIL PROOF)
# ==============================================================================
def send_alert_failproof(msg):
    """ 
    Tenta enviar a mensagem até 3 vezes se der erro.
    """
    if not USE_TELEGRAM: return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": f"🚨 TIBIA ALARM: {msg}"}
    
    max_retries = 3
    
    for attempt in range(1, max_retries + 1):
        try:
            # Timeout de 5s para não travar o bot se a net cair
            response = requests.post(url, data=data, timeout=5)
            
            if response.status_code == 200:
                print(f"   [TELEGRAM] Alerta enviado com sucesso.")
                return # Sucesso! Sai da função.
            else:
                print(f"   [TELEGRAM] Erro {response.status_code}. Tentando novamente ({attempt}/{max_retries})...")
        
        except Exception as e:
            print(f"   [TELEGRAM] Falha de Conexão: {e}. Tentando novamente ({attempt}/{max_retries})...")
        
        # Espera um pouco antes de tentar de novo
        time.sleep(3)

    print("   [ERRO CRÍTICO] Falha ao enviar alerta após todas as tentativas.")

def get_my_z(pm, list_addr):
    for i in range(20):
        try:
            slot = list_addr + (i * STEP_SIZE)
            if pm.read_int(slot) > 0:
                raw = pm.read_string(slot + OFFSET_NAME, 32)
                if raw.split('\x00')[0].strip() == MY_PLAYER_NAME:
                    return pm.read_int(slot + OFFSET_Z)
        except: pass
    return 7

def main():
    global last_alert_time
    os.system('cls')
    print("=== TIBIA PLAYER ALERT (FAIL PROOF) ===")
    
    try:
        pm = pymem.Pymem(PROCESS_NAME)
        base = pymem.process.module_from_name(pm.process_handle, PROCESS_NAME).lpBaseOfDll
        
        target_addr = base + TARGET_ID_PTR
        first_creature = target_addr + REL_FIRST_ID
        
        print("Vigiando... (Ctrl+C para parar)")
        
        # Teste de envio ao iniciar (opcional, pra ver se o token tá certo)
        # send_alert_failproof("Bot Iniciado! Monitoramento ativo.")

        while True:
            my_z = get_my_z(pm, first_creature)
            danger_found = False
            danger_name = ""
            
            for i in range(MAX_CREATURES):
                current_slot = first_creature + (i * STEP_SIZE)
                try:
                    c_id = pm.read_int(current_slot)
                    
                    if c_id > 0:
                        c_vis = pm.read_int(current_slot + OFFSET_VISIBLE)
                        c_z = pm.read_int(current_slot + OFFSET_Z)
                        
                        if c_vis != 0 and c_z == my_z:
                            raw_name = pm.read_string(current_slot + OFFSET_NAME, 32)
                            c_name = raw_name.split('\x00')[0].strip()
                            
                            if c_name == MY_PLAYER_NAME: continue
                            
                            is_safe = any(safe in c_name for safe in SAFE_CREATURES)
                            
                            if not is_safe:
                                danger_found = True
                                danger_name = c_name
                                break 
                except: continue
            
            if danger_found:
                print(f"\n[PERIGO] {danger_name} NA TELA!")
                
                # Alarme Sonoro (Sempre toca)
                winsound.Beep(1000, 500)
                
                # Alarme Telegram (Respeita cooldown)
                if (time.time() - last_alert_time) > ALERT_COOLDOWN:
                    print(">>> Enviando alerta blindado...")
                    send_alert_failproof(f"PERIGO! {danger_name} apareceu!")
                    last_alert_time = time.time()
            
            time.sleep(0.5)

    except Exception as e:
        print(f"Erro: {e}")

if __name__ == "__main__":
    main()