# core/bot_state.py
"""
Estado global do bot com acesso thread-safe.
Substitui variáveis globais espalhadas no main.py.

IMPORTANTE: Este módulo gerencia apenas FLAGS DE CONTROLE do bot:
- is_safe_to_bot, is_gm_detected, resume_timestamp, etc.

NÃO armazena dados de memória do jogo (HP, posição, criaturas).
Esses dados DEVEM ser lidos em tempo real a cada ciclo.
"""
import threading
import time
from typing import Optional, Callable, Dict

# Importa offset para leitura do player ID
from config import OFFSET_PLAYER_ID, CLIENT_TYPE
from core.player_core import get_player_id as player_core_get_player_id


class BotState:
    """
    Encapsula todo o estado de controle compartilhado entre threads.
    Todos os acessos são thread-safe via Lock.
    
    Uso:
        from core.bot_state import state
        
        # Verificar se pode agir
        if state.is_safe():
            # executar ação
        
        # Disparar alarme
        state.trigger_alarm(is_gm=False)
        
        # Limpar alarme com cooldown
        state.clear_alarm(cooldown_seconds=15.0)
    """
    
    def __init__(self):
        self._lock = threading.Lock()
        
        # ===== Estado de Conexão =====
        self._is_connected: bool = False
        
        # ===== Estado de Segurança =====
        self._is_safe_to_bot: bool = True
        self._is_gm_detected: bool = False
        self._resume_timestamp: float = 0.0
        self._pause_reason: str = ""  # "MONSTER", "PLAYER", "GM", "MANUAL"
        self._cavebot_active: bool = False  # Flag para ignorar pausa de alarme quando Cavebot ativo
        
        # ===== Estado de Execução =====
        self._bot_running: bool = True
        
        # ===== Dados de Sessão (constantes durante conexão) =====
        self._char_name: str = ""
        self._char_id: int = 0

        # ===== Contextos de Jogo (coordenação entre módulos) =====
        self._is_in_combat: bool = False
        self._has_open_loot: bool = False
        self._is_processing_loot: bool = False  # NOVO: Cobre DYING → fim loot (ciclo completo)
        self._last_combat_time: float = 0.0
        self._is_runemaking: bool = False
        self._runemaker_fleeing: bool = False  # True enquanto runemaker está fugindo para safe_pos
        self._is_chat_paused: bool = False  # Pausado por conversa de chat
        self._chat_pause_until: float = 0.0  # Timestamp até quando pausar por chat

        # ===== AFK Humanization =====
        self._is_afk_paused: bool = False    # Pausado por AFK humanization
        self._afk_pause_until: float = 0.0   # Timestamp até quando pausar por AFK

        # ===== Follow State (Spear Picker Integration) =====
        self._is_following: bool = False           # True quando seguindo criatura (antes de atacar)
        self._follow_target_id: int = 0            # ID da criatura sendo seguida
        self._is_spear_pickup_pending: bool = False  # True quando spear pickup deve rodar após loot
        self._has_visible_targets: bool = False    # True quando há criaturas atacáveis visíveis (trainer atualiza)

        # ===== Cavebot State (for Alarm Stuck Detection) =====
        self._cavebot_current_state: str = ""      # Estado atual do cavebot (STATE_WALKING, STATE_PAUSED, etc)

        # ===== Combat Movement (Experimental) =====
        self._combat_movement_enabled: bool = False  # Toggle para movimentação humanizada em combate
        self._route_context: dict = {                 # Contexto da rota (cavebot → trainer)
            'current_wp': None,      # {'x': int, 'y': int, 'z': int}
            'next_wp': None,         # Próximo waypoint
            'route_direction': None, # (dx, dy) normalizado
            'wp_visible': False,     # Waypoint dentro do viewport?
        }

        # ===== Alarm Movement Detection =====
        self._alarm_origin_pos: tuple = None  # (x, y, z) posição de origem ao ligar alarme

        # ===== Spawn Protection (Race Condition Prevention) =====
        # Blacklist de criaturas suspeitas (possível GM summon)
        # Trainer e Alarm populam; safe_attack() verifica antes de atacar
        # Dict com {creature_id: timestamp} para TTL automático
        self._suspicious_creature_ids: Dict[int, float] = {}
        self._suspicious_creature_lock = threading.Lock()
        self._suspicious_ttl: float = 300.0  # 5 minutos TTL
        self._suspicious_max_size: int = 200  # Limite máximo de entradas
    
    # =========================================================================
    # CONEXÃO
    # =========================================================================
    
    @property
    def is_connected(self) -> bool:
        """Retorna True se conectado ao cliente Tibia."""
        with self._lock:
            return self._is_connected
    
    @is_connected.setter
    def is_connected(self, value: bool):
        with self._lock:
            self._is_connected = value
            # Limpa dados de sessão ao desconectar
            if not value:
                self._char_name = ""
                self._char_id = 0

    @property
    def cavebot_active(self) -> bool:
        """Retorna True se Cavebot está ativo."""
        with self._lock:
            return self._cavebot_active

    # =========================================================================
    # SEGURANÇA - Métodos principais
    # =========================================================================
    
    def is_safe(self) -> bool:
        """
        Verifica se é seguro executar ações do bot.

        Considera:
        - Flag is_safe_to_bot
        - Cooldown (resume_timestamp)
        - Estado do Cavebot (se ativo, ignora alarme)

        Returns:
            True se pode executar ações, False caso contrário

        EXCEÇÃO: Se Cavebot estiver ativo, retorna True mesmo com alarme
        para permitir que módulos continuem operando durante navegação.
        """
        with self._lock:
            # Se Cavebot ativo, permite módulos continuarem independente do alarme
            if self._cavebot_active:
                return True

            if not self._is_safe_to_bot:
                return False
            if time.time() < self._resume_timestamp:
                return False
            return True
    
    def is_safe_raw(self) -> bool:
        """
        Retorna o estado bruto de segurança (ignora cooldown).
        Útil para verificar se alarme está ativo.
        """
        with self._lock:
            return self._is_safe_to_bot
    
    def trigger_alarm(self, is_gm: bool = False, reason: str = ""):
        """
        Dispara estado de alarme - para todas as ações do bot.
        
        Args:
            is_gm: True se foi detectado GM/CM/God
            reason: Motivo do alarme ("MONSTER", "PLAYER", "GM", "MANUAL")
        """
        with self._lock:
            self._is_safe_to_bot = False
            self._is_gm_detected = is_gm
            self._pause_reason = reason or ("GM" if is_gm else "UNKNOWN")
    
    def clear_alarm(self, cooldown_seconds: float = 0.0):
        """
        Limpa estado de alarme e define cooldown antes de retomar.
        
        Args:
            cooldown_seconds: Segundos para aguardar antes de retomar ações
        """
        with self._lock:
            self._is_safe_to_bot = True
            self._is_gm_detected = False
            self._pause_reason = ""
            if cooldown_seconds > 0:
                self._resume_timestamp = time.time() + cooldown_seconds
            else:
                self._resume_timestamp = 0.0
    
    def set_cooldown(self, seconds: float):
        """
        Define cooldown sem alterar estado de alarme.
        Útil para delays entre ações normais.
        
        Args:
            seconds: Segundos de cooldown
        """
        with self._lock:
            self._resume_timestamp = time.time() + seconds

    def set_cavebot_state(self, active: bool):
        """
        Define se Cavebot está ativo.

        Quando True, is_safe() sempre retorna True independente do alarme,
        permitindo que módulos (Trainer, Loot, Runemaker) continuem operando
        durante navegação.

        Args:
            active: True para ativar, False para desativar
        """
        with self._lock:
            self._cavebot_active = active

    # =========================================================================
    # SEGURANÇA - Propriedades de leitura
    # =========================================================================
    
    @property
    def is_gm_detected(self) -> bool:
        """Retorna True se GM/CM/God foi detectado."""
        with self._lock:
            return self._is_gm_detected
    
    @property
    def pause_reason(self) -> str:
        """Retorna o motivo da pausa atual."""
        with self._lock:
            return self._pause_reason
    
    @property
    def cooldown_remaining(self) -> float:
        """Retorna segundos restantes de cooldown (0 se não há cooldown)."""
        with self._lock:
            remaining = self._resume_timestamp - time.time()
            return max(0.0, remaining)
    
    @property
    def resume_timestamp(self) -> float:
        """Retorna o timestamp quando as ações podem ser retomadas."""
        with self._lock:
            return self._resume_timestamp
    
    # =========================================================================
    # EXECUÇÃO
    # =========================================================================
    
    @property
    def is_running(self) -> bool:
        """Retorna True se o bot está rodando (não foi encerrado)."""
        with self._lock:
            return self._bot_running
    
    def stop(self):
        """Para o bot (sinaliza para todas as threads encerrarem)."""
        with self._lock:
            self._bot_running = False
    
    def start(self):
        """Inicia/reinicia o bot."""
        with self._lock:
            self._bot_running = True
    
    # =========================================================================
    # DADOS DE SESSÃO (constantes durante conexão)
    # =========================================================================
    
    @property
    def char_name(self) -> str:
        """Nome do personagem conectado (constante na sessão)."""
        with self._lock:
            return self._char_name
    
    @char_name.setter
    def char_name(self, value: str):
        with self._lock:
            self._char_name = value
    
    @property
    def char_id(self) -> int:
        """ID do personagem conectado (constante na sessão)."""
        with self._lock:
            return self._char_id
    
    @char_id.setter
    def char_id(self, value: int):
        with self._lock:
            self._char_id = value

    def get_player_id(self, pm, base_addr: int) -> int:
        """
        Retorna o player_id cacheado, ou lê da memória se não cacheado.

        O player_id é constante durante toda a sessão de conexão.
        O cache é limpo automaticamente quando is_connected = False.

        Args:
            pm: Instância do Pymem conectada ao processo
            base_addr: Endereço base do cliente Tibia

        Returns:
            Player ID (int), ou 0 se não conectado
        """
        with self._lock:
            if self._char_id != 0:
                return self._char_id

        # Usa player_core que suporta Mas Vis (busca por nome) e Tibia (offset direto)
        try:
            player_id = player_core_get_player_id(pm, base_addr)
            if player_id != 0:
                with self._lock:
                    self._char_id = player_id
                return player_id
        except Exception:
            pass

        return 0

    def clear_player_id_cache(self):
        """
        Limpa o cache do player_id.
        Deve ser chamado quando o jogador desconecta.
        Nota: Já é chamado automaticamente em is_connected.setter quando False.
        """
        with self._lock:
            self._char_id = 0

    # =========================================================================
    # CONTEXTOS DE JOGO - Coordenação entre Módulos
    # =========================================================================

    @property
    def is_in_combat(self) -> bool:
        """Retorna True se há combate ativo (target_id != 0)."""
        with self._lock:
            return self._is_in_combat

    @property
    def has_open_loot(self) -> bool:
        """Retorna True se há containers de loot abertos."""
        with self._lock:
            return self._has_open_loot

    @property
    def last_combat_time(self) -> float:
        """Retorna timestamp do último combate (para cooldowns)."""
        with self._lock:
            return self._last_combat_time

    def set_combat_state(self, in_combat: bool):
        """
        Atualiza estado de combate.

        Args:
            in_combat: True se há combate ativo, False caso contrário
        """
        with self._lock:
            self._is_in_combat = in_combat
            if in_combat:
                self._last_combat_time = time.time()

    def set_loot_state(self, has_loot: bool):
        """
        Atualiza estado de loot.

        Args:
            has_loot: True se há containers de loot abertos, False caso contrário
        """
        with self._lock:
            self._has_open_loot = has_loot

    @property
    def is_processing_loot(self) -> bool:
        """
        Retorna True se o bot está processando loot (desde DYING até fim).
        Cobre: polling de despawn + abertura do corpo + processamento + fechamento.
        Protege contra race conditions durante TODO o ciclo de morte/loot.
        """
        with self._lock:
            return self._is_processing_loot

    def start_loot_cycle(self):
        """
        Marca início do ciclo de loot completo.
        Chamado pelo trainer quando:
        - death_state = DYING (fluxo normal, antes do polling)
        - death_state = CORPSE_READY (morte imediata, antes de abrir corpo)
        """
        with self._lock:
            self._is_processing_loot = True

    def end_loot_cycle(self):
        """
        Marca fim do ciclo de loot completo.
        Chamado pelo auto_loot ao finalizar (ou em exceção via finally).
        """
        with self._lock:
            self._is_processing_loot = False

    @property
    def is_runemaking(self) -> bool:
        """Retorna True se runemaker está executando ciclo."""
        with self._lock:
            return self._is_runemaking

    def set_runemaking(self, value: bool):
        """
        Atualiza estado de runemaking.

        Args:
            value: True se runemaker está executando, False caso contrário
        """
        with self._lock:
            self._is_runemaking = value

    @property
    def runemaker_fleeing(self) -> bool:
        """Retorna True se runemaker está fugindo para safe_pos."""
        with self._lock:
            return self._runemaker_fleeing

    def set_runemaker_fleeing(self, value: bool):
        """
        Atualiza estado de fuga do runemaker.

        Args:
            value: True se runemaker está fugindo, False caso contrário
        """
        with self._lock:
            self._runemaker_fleeing = value

    @property
    def is_chat_paused(self) -> bool:
        """Retorna True se bot está pausado por conversa de chat."""
        with self._lock:
            if not self._is_chat_paused:
                return False
            # Verifica se timeout expirou
            if time.time() >= self._chat_pause_until:
                self._is_chat_paused = False
                return False
            return True

    def set_chat_pause(self, paused: bool, duration: float = 10.0):
        """
        Atualiza estado de pausa por chat.

        Args:
            paused: True para pausar, False para retomar
            duration: Duração da pausa em segundos (se paused=True)
        """
        with self._lock:
            self._is_chat_paused = paused
            if paused:
                self._chat_pause_until = time.time() + duration
            else:
                self._chat_pause_until = 0.0

    def get_chat_pause_remaining(self) -> float:
        """Retorna segundos restantes de pausa por chat."""
        with self._lock:
            if not self._is_chat_paused:
                return 0.0
            remaining = self._chat_pause_until - time.time()
            return max(0.0, remaining)

    # =========================================================================
    # AFK HUMANIZATION
    # =========================================================================

    @property
    def is_afk_paused(self) -> bool:
        """Retorna True se bot está pausado por AFK humanization."""
        with self._lock:
            if not self._is_afk_paused:
                return False
            # Verifica se timeout expirou
            if time.time() >= self._afk_pause_until:
                self._is_afk_paused = False
                return False
            return True

    def set_afk_pause(self, paused: bool, duration: float = 30.0):
        """
        Atualiza estado de pausa AFK.

        Args:
            paused: True para pausar, False para retomar
            duration: Duração da pausa em segundos (se paused=True)
        """
        with self._lock:
            self._is_afk_paused = paused
            if paused:
                self._afk_pause_until = time.time() + duration
            else:
                self._afk_pause_until = 0.0

    def get_afk_pause_remaining(self) -> float:
        """Retorna segundos restantes de pausa AFK."""
        with self._lock:
            if not self._is_afk_paused:
                return 0.0
            remaining = self._afk_pause_until - time.time()
            return max(0.0, remaining)

    # =========================================================================
    # FOLLOW STATE (Spear Picker Integration)
    # =========================================================================

    @property
    def is_following(self) -> bool:
        """Retorna True se está seguindo uma criatura (antes de atacar)."""
        with self._lock:
            return self._is_following

    @property
    def follow_target_id(self) -> int:
        """Retorna o ID da criatura sendo seguida."""
        with self._lock:
            return self._follow_target_id

    def start_follow(self, creature_id: int):
        """
        Inicia estado de follow.
        Também seta is_in_combat=True para pausar cavebot automaticamente.

        Args:
            creature_id: ID da criatura a seguir
        """
        with self._lock:
            self._is_following = True
            self._follow_target_id = creature_id
            self._is_in_combat = True  # Follow = combat para fins de pausa

    def stop_follow(self):
        """
        Para estado de follow.
        Chamado quando: criatura morre, troca para attack, ou target muda.
        Nota: is_in_combat é gerenciado separadamente pelo trainer.
        """
        with self._lock:
            self._is_following = False
            self._follow_target_id = 0

    @property
    def is_spear_pickup_pending(self) -> bool:
        """Retorna True se spear pickup deve rodar após loot."""
        with self._lock:
            return self._is_spear_pickup_pending

    def set_spear_pickup_pending(self, pending: bool):
        """
        Marca se spear pickup deve rodar após loot cycle.

        Args:
            pending: True para ativar ciclo prioritário, False para desativar

        Nota: Quando pending=False (finalizando pickup), atualiza last_combat_time
        para acionar cooldown pós-combate no cavebot, dando tempo para o trainer
        selecionar novos alvos antes da navegação retomar.
        """
        with self._lock:
            self._is_spear_pickup_pending = pending

            # Quando spear pickup FINALIZA, atualiza last_combat_time
            # para acionar cooldown pós-combate no cavebot
            if not pending:
                self._last_combat_time = time.time()

    # =========================================================================
    # VISIBLE TARGETS (Trainer → Cavebot Coordination)
    # =========================================================================

    @property
    def has_visible_targets(self) -> bool:
        """
        Retorna True se há criaturas atacáveis visíveis na tela.
        Atualizado pelo trainer a cada ciclo de scan.
        Usado pelo cavebot para evitar iniciar navegação quando há alvos.
        """
        with self._lock:
            return self._has_visible_targets

    def set_visible_targets(self, has_targets: bool):
        """
        Atualiza flag de alvos visíveis.
        Chamado pelo trainer após filtrar valid_candidates.

        Args:
            has_targets: True se há criaturas atacáveis visíveis
        """
        with self._lock:
            self._has_visible_targets = has_targets

    # =========================================================================
    # CAVEBOT STATE (Alarm Stuck Detection)
    # =========================================================================

    @property
    def cavebot_current_state(self) -> str:
        """
        Retorna o estado atual do cavebot.
        Usado pelo alarm.py para verificar se cavebot está stuck.
        """
        with self._lock:
            return self._cavebot_current_state

    def set_cavebot_current_state(self, state_name: str):
        """
        Atualiza o estado atual do cavebot.
        Chamado pelo cavebot ao final de run_cycle().

        Args:
            state_name: Nome do estado (STATE_WALKING, STATE_PAUSED, etc)
        """
        with self._lock:
            self._cavebot_current_state = state_name

    # =========================================================================
    # COMBAT MOVEMENT (EXPERIMENTAL)
    # =========================================================================

    @property
    def combat_movement_enabled(self) -> bool:
        """Retorna True se Combat Movement está habilitado."""
        with self._lock:
            return self._combat_movement_enabled

    def set_combat_movement_enabled(self, enabled: bool):
        """
        Ativa/desativa movimentação humanizada em combate.
        Chamado pelo settings quando toggle é alterada.
        """
        with self._lock:
            self._combat_movement_enabled = enabled

    def set_route_context(self, current_wp: dict, next_wp: dict, player_pos: tuple):
        """
        Atualiza contexto da rota para uso do Combat Movement.
        Chamado pelo cavebot antes de pausar para combate.

        Args:
            current_wp: Waypoint atual {'x': int, 'y': int, 'z': int}
            next_wp: Próximo waypoint
            player_pos: Posição atual do player (x, y, z)
        """
        # Calcular direção da rota
        if current_wp and next_wp:
            dx = next_wp['x'] - current_wp['x']
            dy = next_wp['y'] - current_wp['y']
            # Normalizar para -1, 0, ou 1
            route_dir = (
                1 if dx > 0 else (-1 if dx < 0 else 0),
                1 if dy > 0 else (-1 if dy < 0 else 0)
            )
        else:
            route_dir = (0, 0)

        # Verificar se waypoint está visível (±7 tiles)
        wp_visible = (current_wp is not None and
                      abs(current_wp['x'] - player_pos[0]) <= 7 and
                      abs(current_wp['y'] - player_pos[1]) <= 7)

        with self._lock:
            self._route_context = {
                'current_wp': current_wp,
                'next_wp': next_wp,
                'route_direction': route_dir,
                'wp_visible': wp_visible,
            }

    def get_route_context(self) -> dict:
        """
        Retorna contexto da rota atual.
        Usado pelo trainer para movimentação em combate.
        """
        with self._lock:
            return self._route_context.copy()

    # =========================================================================
    # MÉTODOS DE CONVENIÊNCIA
    # =========================================================================
    
    def can_act(self) -> bool:
        """
        Verifica todas as condições para executar ações:
        - Bot rodando
        - Conectado
        - Seguro (sem alarme, sem cooldown)
        
        Returns:
            True se todas as condições são satisfeitas
        """
        with self._lock:
            if not self._bot_running:
                return False
            if not self._is_connected:
                return False
            if not self._is_safe_to_bot:
                return False
            if time.time() < self._resume_timestamp:
                return False
            return True
    
    def get_status(self) -> dict:
        """
        Retorna snapshot do estado atual (para debug/GUI).

        Returns:
            Dict com todos os estados
        """
        with self._lock:
            return {
                'is_connected': self._is_connected,
                'is_running': self._bot_running,
                'is_safe': self._is_safe_to_bot,
                'is_gm_detected': self._is_gm_detected,
                'pause_reason': self._pause_reason,
                'cooldown_remaining': max(0.0, self._resume_timestamp - time.time()),
                'char_name': self._char_name,
                'char_id': self._char_id,
                'is_in_combat': self._is_in_combat,
                'has_open_loot': self._has_open_loot,
                'is_processing_loot': self._is_processing_loot,
                'last_combat_time': self._last_combat_time,
                'is_runemaking': self._is_runemaking,
                'is_chat_paused': self._is_chat_paused,
                'chat_pause_until': self._chat_pause_until,
                'is_afk_paused': self._is_afk_paused,
                'afk_pause_until': self._afk_pause_until,
                'is_following': self._is_following,
                'follow_target_id': self._follow_target_id,
                'is_spear_pickup_pending': self._is_spear_pickup_pending,
                'has_visible_targets': self._has_visible_targets,
                'cavebot_current_state': self._cavebot_current_state,
                'combat_movement_enabled': self._combat_movement_enabled,
                'suspicious_creature_count': self.get_suspicious_creature_count(),
            }
    
    def reset(self):
        """
        Reseta todos os estados para valores iniciais.
        Útil ao desconectar ou reiniciar.
        """
        with self._lock:
            self._is_connected = False
            self._is_safe_to_bot = True
            self._is_gm_detected = False
            self._resume_timestamp = 0.0
            self._pause_reason = ""
            self._char_name = ""
            self._char_id = 0
            self._is_in_combat = False
            self._has_open_loot = False
            self._is_processing_loot = False
            self._last_combat_time = 0.0
            self._is_runemaking = False
            self._is_chat_paused = False
            self._chat_pause_until = 0.0
            self._is_afk_paused = False
            self._afk_pause_until = 0.0
            self._is_following = False
            self._follow_target_id = 0
            self._is_spear_pickup_pending = False
            self._has_visible_targets = False
            self._cavebot_current_state = ""
            self._combat_movement_enabled = False
            self._route_context = {
                'current_wp': None,
                'next_wp': None,
                'route_direction': None,
                'wp_visible': False,
            }
            self._alarm_origin_pos = None
            # NÃO reseta _bot_running

        # Limpa blacklist de criaturas suspeitas (lock separado)
        self.clear_suspicious_creatures()

    # =========================================================================
    # ALARM MOVEMENT DETECTION
    # =========================================================================

    @property
    def alarm_origin_pos(self) -> tuple:
        """Posição de origem definida ao ligar o alarme (x, y, z) ou None."""
        with self._lock:
            return self._alarm_origin_pos

    @alarm_origin_pos.setter
    def alarm_origin_pos(self, value: tuple):
        with self._lock:
            self._alarm_origin_pos = value

    # =========================================================================
    # SPAWN PROTECTION - Prevenção de Race Condition GM Summon
    # =========================================================================

    def _cleanup_suspicious_creatures(self):
        """
        Remove criaturas expiradas da blacklist (TTL) e limita tamanho.
        DEVE ser chamado com lock já adquirido.
        """
        now = time.time()
        cutoff = now - self._suspicious_ttl

        # Remove entradas expiradas
        self._suspicious_creature_ids = {
            cid: ts for cid, ts in self._suspicious_creature_ids.items()
            if ts > cutoff
        }

        # Limita tamanho (remove mais antigas se exceder)
        if len(self._suspicious_creature_ids) > self._suspicious_max_size:
            # Ordena por timestamp e mantém apenas as mais recentes
            sorted_items = sorted(
                self._suspicious_creature_ids.items(),
                key=lambda x: x[1],
                reverse=True
            )
            self._suspicious_creature_ids = dict(sorted_items[:self._suspicious_max_size])

    def add_suspicious_creature(self, creature_id: int, reason: str = ""):
        """
        Marca criatura como suspeita (possível summon de GM).
        Thread-safe via lock dedicado para alta frequência de acesso.
        Entradas expiram automaticamente após TTL (5 minutos).

        Chamado por:
        - Trainer (detecção inline) - proteção primária
        - Alarm (SpawnTracker) - proteção backup
        """
        with self._suspicious_creature_lock:
            self._suspicious_creature_ids[creature_id] = time.time()
            self._cleanup_suspicious_creatures()

    def is_suspicious_creature(self, creature_id: int) -> bool:
        """
        Verifica se criatura está na blacklist de suspeitos.
        DEVE ser chamado antes de CADA packet.attack() via safe_attack().
        Retorna False para entradas expiradas.
        """
        with self._suspicious_creature_lock:
            if creature_id not in self._suspicious_creature_ids:
                return False
            # Verifica se não expirou
            ts = self._suspicious_creature_ids[creature_id]
            if time.time() - ts > self._suspicious_ttl:
                del self._suspicious_creature_ids[creature_id]
                return False
            return True

    def remove_suspicious_creature(self, creature_id: int):
        """Remove criatura da blacklist (quando morre ou despawna)."""
        with self._suspicious_creature_lock:
            self._suspicious_creature_ids.pop(creature_id, None)

    def clear_suspicious_creatures(self):
        """Limpa blacklist (ao mudar de andar ou resetar sessão)."""
        with self._suspicious_creature_lock:
            self._suspicious_creature_ids.clear()

    def get_suspicious_creature_count(self) -> int:
        """Retorna quantidade de criaturas na blacklist (após cleanup)."""
        with self._suspicious_creature_lock:
            self._cleanup_suspicious_creatures()
            return len(self._suspicious_creature_ids)


# =============================================================================
# INSTÂNCIA GLOBAL ÚNICA
# =============================================================================

state = BotState()


# =============================================================================
# FUNÇÕES DE CONVENIÊNCIA (opcional, para compatibilidade)
# =============================================================================

def is_safe() -> bool:
    """Atalho para state.is_safe()"""
    return state.is_safe()

def is_connected() -> bool:
    """Atalho para state.is_connected"""
    return state.is_connected

def trigger_alarm(is_gm: bool = False, reason: str = ""):
    """Atalho para state.trigger_alarm()"""
    state.trigger_alarm(is_gm, reason)

def clear_alarm(cooldown: float = 0.0):
    """Atalho para state.clear_alarm()"""
    state.clear_alarm(cooldown)
