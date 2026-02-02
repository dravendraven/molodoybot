import time
from datetime import datetime, timedelta
from pathlib import Path
from database import foods_db
from database.creatures_stats import get_creature_max_hp

def get_exp_for_level(level):
    """
    Retorna a experiência total necessária para alcançar um nível.
    Fórmula do Tibia: (50 * n^3 - 150 * n^2 + 400 * n) / 3
    """
    if level < 1: return 0
    return int((50 * level**3 - 150 * level**2 + 400 * level) / 3)

class ExpTracker:
    def __init__(self):
        self.start_time = time.time()
        self.start_exp = -1
        self.current_exp = -1
        self.gained_exp = 0
        self.last_check_exp = -1

    def update(self, current_exp):
        if self.start_exp == -1:
            self.start_exp = current_exp
            self.last_check_exp = current_exp
            self.start_time = time.time()
            return

        diff = current_exp - self.last_check_exp
        if diff > 0:
            self.gained_exp += diff
            self.last_check_exp = current_exp
        
        self.current_exp = current_exp

    def get_stats(self, current_level):
        elapsed = time.time() - self.start_time
        if elapsed < 1: elapsed = 1
        
        # XP por Hora
        xp_per_hour = (self.gained_exp / elapsed) * 3600
        
        # Quanto falta para o próximo level?
        next_level_exp = get_exp_for_level(current_level)
        exp_left = next_level_exp - self.current_exp
        if exp_left < 0: exp_left = 0 # Upol?
        
        # ETA
        if xp_per_hour > 0:
            total_seconds = int((exp_left / xp_per_hour) * 3600)
            
            # Cálculo manual para formato HHH:MM
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            
            time_left_str = f"{hours}:{minutes:02d}" # Ex: "36:10"
        else:
            time_left_str = "--:--"

        return {
            "xp_hour": int(xp_per_hour),
            "left": exp_left,
            "eta": time_left_str
        }

# ==============================================================================
# FUNÇÃO DE BENCHMARK (Baseada no código C++ do Servidor)
# ==============================================================================
def get_benchmark_min_per_pct(level, vocation="Knight", skill_type="Melee"):
    """
    Retorna o tempo ideal (em minutos) para avançar 1% do skill.
    Fórmula derivada de crplayer.cc: Hits = Delta * (Factor/1000)^(Level - 10)
    Assumindo treino perfeito (1 hit a cada 2 segundos).
    """
    # Tabela de Dificuldade (Extraída de crplayer.cc)
    # Formato: (Factor, Delta)
    config = {
        "Knight": {
            "Melee": (1100, 50),   # Sword/Axe/Club
            "Shield": (1100, 50), # Shielding
            "Dist": (1400, 30)     # Distance (Péssimo para Knight)
        },
        "Paladin": {
            "Melee": (1200, 50),
            "Shield": (1100, 100),
            "Dist": (1100, 30)     # Distance (Ótimo para Paladin)
        },
        "Mage": {
            "Melee": (2000, 50),
            "Shield": (1500, 100),
            "Dist": (1800, 30)
        }
    }

    # Pega os valores ou usa padrão Knight/Melee se não achar
    factor, delta = config.get(vocation, {}).get(skill_type, (1100, 50))
    
    # Se o level for menor que 10, o cálculo exponencial quebra ou fica irrelevante.
    if level < 10: level = 10

    # 1. Calcular Total de Hits para o próximo nível completo
    base = factor / 1000.0
    exponent = level - 10
    total_hits_next_level = delta * (base ** exponent)

    # 2. Converter Hits em Minutos (Hit ideal = 2 segundos)
    total_minutes = (total_hits_next_level * 2) / 60

    # 3. Calcular minutos para 1%
    min_per_1pct = total_minutes / 100
    
    return min_per_1pct

# ==============================================================================
# CLASSE DE SKILLS (Calculadora de XP/h)
# ==============================================================================
class SkillTracker:
    def __init__(self, name):
        self.name = name
        self.current_pct = -1
        
        # Variáveis de Controle de Tempo
        self.last_advance_time = time.time() # Momento do último avanço
        self.measured_speed = 0.0 # Guardará o resultado final (min/%)
        self.first_reading = True # Para ignorar o primeiro cálculo (setup)

        self.speed_history = []

    def update(self, read_val):
        """
        Chamado centenas de vezes por minuto pela thread rápida.
        Só faz cálculo se o valor mudar.
        """
        # Inicialização na primeira leitura
        if self.current_pct == -1:
            self.current_pct = read_val
            self.last_advance_time = time.time()
            return

        # Se o percentual mudou (Avançou!)
        if read_val != self.current_pct:
            now = time.time()
            
            # Detecta quanto avançou (lidando com virada de nível 99->0)
            if read_val < self.current_pct:
                # Ex: Estava 99, foi pra 0 (UPOU LEVEL)
                diff = (100 - self.current_pct) + read_val
            else:
                # Ex: Estava 50, foi pra 51
                diff = read_val - self.current_pct
            
            # Só atualiza a velocidade se houve progresso positivo
            if diff > 0:
                # --- O CÁLCULO MÁGICO ---
                # Tempo decorrido desde o último avanço
                elapsed_seconds = now - self.last_advance_time
                elapsed_minutes = elapsed_seconds / 60
                
                # Minutos necessários para 1%
                # Ex: Se demorou 2 min para subir 1%, speed = 2.0
                # Ex: Se demorou 2 min para subir 2% (lag?), speed = 1.0
                if not self.first_reading:
                    self.measured_speed = elapsed_minutes / diff
                    self.speed_history.append(self.measured_speed)
                    # Mantém apenas os últimos 30 avanços para o gráfico não ficar gigante
                    if len(self.speed_history) > 30:
                        self.speed_history.pop(0)
                else:
                    self.first_reading = False

                # Reseta o cronômetro para o próximo %
                self.last_advance_time = now
            
            # Atualiza o percentual atual
            self.current_pct = read_val

    def get_display_data(self):
        """ Retorna os dados prontos para a GUI, sem fazer cálculos pesados """
        return {
            "pct": self.current_pct,
            "speed": self.measured_speed,
            "history": self.speed_history
        }

sword_tracker = SkillTracker("Sword")
shield_tracker = SkillTracker("Shield")

class TrainingMonitor:
    def __init__(self, log_callback=None, log_hits=True):
        """
        log_callback: Função para enviar mensagens para a GUI principal.
        """
        self.log = log_callback if log_callback else print
        self.log_hits = log_hits
        self.hit_log_path = Path("hits_monitor.txt")
        self.reset()

    def reset(self):
        self.target_id = 0
        self.target_name = "Unknown"
        self.target_max_hp = None
        self.start_time = 0
        self.last_hp = 100
        self.damage_timestamps = []
        self.active = False

    def start(self, tid, name, hp):
        self.reset()
        self.target_id = tid
        self.target_name = name
        self.target_max_hp = get_creature_max_hp(name)
        self.start_time = time.time()
        self.last_hp = hp
        self.damage_timestamps = [time.time()]
        self.active = True
        # Opcional: Avisar no console que começou
        print(f"[MONITOR] Iniciado em {name} (ID: {tid})")

    def update(self, current_hp):
            if not self.active: return
            
            # Se HP baixou (Houve Dano)
            if current_hp < self.last_hp:
                now = time.time()
                
                # Calcula tempo desde o último evento registrado
                diff = now - self.damage_timestamps[-1]
                
                # Calcula quanto de dano foi dado
                dmg = self.last_hp - current_hp
                raw_dmg = self._convert_percent_to_hp(dmg)
                
                # >>> AQUI ESTÁ O PRINT QUE VOCÊ QUERIA <<<
                if self.log_hits:
                    if raw_dmg is not None:
                        print(f"   [HIT] Dano: {raw_dmg} HP (~{dmg}%)  |  Gap: {diff:.2f}s  |  HP: {current_hp}%")
                    else:
                        print(f"   [HIT] Dano: {dmg}%  |  Gap: {diff:.2f}s  |  HP: {current_hp}%")
                if current_hp > 0:
                    self._log_hit_to_file(dmg)

                # Atualiza listas e estado
                self.damage_timestamps.append(now)
                self.last_hp = current_hp
                
            # Se curou (HP subiu), atualiza referência para não bugar o próximo cálculo de dano
            elif current_hp > self.last_hp:
                self.last_hp = current_hp

    def stop_and_report(self):
        if not self.active: return
        
        end_time = time.time()
        total_duration = end_time - self.start_time
        
        # Filtra treinos muito curtos (menos de 5s)
        if total_duration < 5: 
            self.active = False
            return

        self.damage_timestamps.append(end_time)
        
        inefficient_time = 0
        max_gap = 0
        
        # Análise estatística
        for i in range(1, len(self.damage_timestamps)):
            diff = self.damage_timestamps[i] - self.damage_timestamps[i-1]
            if diff > 20: inefficient_time += (diff - 20)
            if diff > max_gap: max_gap = diff

        efficient_time = total_duration - inefficient_time
        efficiency_pct = (efficient_time / total_duration) * 100 if total_duration > 0 else 0
        
        status = "RUIM ⚠️"
        if efficiency_pct > 95: status = "PERFEITO 🌟"
        elif efficiency_pct > 80: status = "BOM ✅"

        # Usa a função de log que foi passada pelo arquivo principal
        self.log(f"💀 {self.target_name} Morto em {total_duration:.0f}s")
        self.log(f"   Eficiência: {efficiency_pct:.1f}% [{status}]")
        self.log(f"   Maior Gap: {max_gap:.1f}s")
        
        # Log detalhado no Terminal
        if self.log_hits:
            print(f"   [FIM] {self.target_name} eliminado.")
            print(f"   [STATS] Hits: {len(self.damage_timestamps)-2} | Maior Gap: {max_gap:.2f}s")
            print(f"   [STATS] Tempo Total: {total_duration:.2f}s | Tempo Eficiente: {efficient_time:.2f}s ({efficiency_pct:.2f}%) | Tempo ineficiente: {inefficient_time:.2f}s")
            print("-" * 50)
        
        self.active = False

    def _log_hit_to_file(self, damage_percent):
        if not self.log_hits:
            return

        timestamp = datetime.now().strftime("%H:%M:%S")
        raw_damage = self._convert_percent_to_hp(damage_percent)

        if raw_damage is not None:
            line = f"[{timestamp}] Dealt {raw_damage} damage to {self.target_name} (~{damage_percent}%).\n"
        else:
            line = f"[{timestamp}] Dealt {damage_percent}% damage to {self.target_name}.\n"

        try:
            with self.hit_log_path.open("a", encoding="utf-8") as log_file:
                log_file.write(line)
        except Exception as err:
            print(f"[MONITOR] Failed to write hit log: {err}")

    def _convert_percent_to_hp(self, percent_value):
        if not self.target_max_hp or percent_value <= 0:
            return None
        return int(round(self.target_max_hp * (percent_value / 100.0)))

class GoldTracker:
    def __init__(self):
        # Defina os valores aqui. O usuário pediu Crystal = 1000
        self.VALUES = {3031: 1, 3035: 100, 3043: 1000} 
        self.session_gold = 0
        self.start_time = time.time()
        self.inventory_gold = 0

    def add_loot(self, item_id, count):
        val = self.VALUES.get(item_id, 0)
        self.session_gold += (val * count)

    def update_inventory(self, container_list):
        # Recebe a lista de containers já lida para evitar leitura dupla de memória
        total = 0
        for cont in container_list:
            for item in cont.items:
                val = self.VALUES.get(item.id, 0)
                total += (val * item.count)
        self.inventory_gold = total

    def get_stats(self):
        elapsed = time.time() - self.start_time
        if elapsed < 1: elapsed = 1
        gp_h = (self.session_gold / elapsed) * 3600
        return {
            "session": self.session_gold,
            "inventory": self.inventory_gold,
            "gp_h": int(gp_h)
        }
    
class RegenTracker:
    def __init__(self):
        self.total_seconds = 0

    def update_inventory(self, container_list):
        """
        Percorre os containers e soma o tempo de regen de todas as comidas encontradas.
        """
        seconds = 0
        for cont in container_list:
            for item in cont.items:
                # O foods_db.get_regen_time retorna 0 se não for comida
                regen = foods_db.get_regen_time(item.id)
                if regen > 0:
                    seconds += (regen * item.count)
        
        self.total_seconds = seconds

    def get_display_string(self):
        """Retorna string formatada (Ex: '1h 30m' ou '45m')"""
        if self.total_seconds == 0:
            return "--"
        
        hours = self.total_seconds // 3600
        minutes = (self.total_seconds % 3600) // 60
        
        if hours > 0:
            return f"{hours}h {minutes:02d}m"
        else:
            return f"{minutes} min"
