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
from typing import Optional, Callable


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
        
        # ===== Estado de Execução =====
        self._bot_running: bool = True
        
        # ===== Dados de Sessão (constantes durante conexão) =====
        self._char_name: str = ""
        self._char_id: int = 0
    
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
    
    # =========================================================================
    # SEGURANÇA - Métodos principais
    # =========================================================================
    
    def is_safe(self) -> bool:
        """
        Verifica se é seguro executar ações do bot.
        
        Considera:
        - Flag is_safe_to_bot
        - Cooldown (resume_timestamp)
        
        Returns:
            True se pode executar ações, False caso contrário
        """
        with self._lock:
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
            # NÃO reseta _bot_running


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
