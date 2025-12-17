"""
core/packet_mutex.py

Sistema de sincronização para evitar ações conflitantes entre módulos.

Propósito:
  Impedir que múltiplos módulos (Fisher, Runemaker, Trainer, etc) executem
  ações de packet simultaneamente, evitando conflitos como:
    - Fisher use_with + Runemaker move_item ao mesmo tempo
    - Auto-loot move_item + Trainer use_item ao mesmo tempo

Como usar:
  1. Importar: from core.packet_mutex import PacketMutex
  2. Antes de ação: PacketMutex.acquire("fisher")
  3. Fazer ação de packet
  4. Depois: PacketMutex.release("fisher")

Ou com context manager (recomendado):
  with PacketMutex("fisher"):
      # Fazer ações de packet
      packet.use_with(...)
      packet.move_item(...)

Prioridades:
  Runemaker: 100 (alta - operações críticas)
  Trainer:   80
  Fisher:    60
  Auto-loot: 40
  Stacker:   30
  Eater:     20 (baixa - operações oportunísticas)
"""

import time
import threading
from typing import Optional, Dict


def _get_module_group(module_name: str) -> str:
    """Retorna o grupo de um módulo para verificar relacionamento."""
    return MODULE_GROUPS.get(module_name.lower(), f"{module_name.lower()}_SOLO")

# Prioridades dos módulos (quanto maior, maior a prioridade)
MODULE_PRIORITIES = {
    "runemaker": 100,
    "trainer": 80,
    "fisher": 60,
    "auto_loot": 40,
    "stacker": 30,
    "eater": 20,
}

# Grupos de módulos relacionados (módulos do mesmo grupo compartilham contexto)
MODULE_GROUPS = {
    "fisher": "FISHER_GROUP",
    "stacker": "FISHER_GROUP",  # Stacker faz parte do grupo Fisher

    "auto_loot": "LOOT_GROUP",
    "eater": "LOOT_GROUP",

    "runemaker": "RUNEMAKER_GROUP",  # Isolado
    "trainer": "TRAINER_GROUP",      # Isolado
    "cavebot": "CAVEBOT_GROUP",      # Isolado
}

# Delay mínimo entre ações de módulos diferentes (em segundos)
INTER_MODULE_DELAY = 1.0


class PacketMutex:
    """
    Mutex para sincronizar ações de packet entre módulos.

    Garante que apenas um módulo execute ações de packet por vez,
    com suporte a prioridades para operações críticas.
    """

    # Variáveis de classe (compartilhadas entre instâncias)
    _lock = threading.Lock()
    _current_holder: Optional[str] = None
    _last_holder: Optional[str] = None  # Rastreia o último titular (para comparar grupos)
    _last_action_time: float = 0.0
    _action_start_time: Optional[float] = None
    _wait_queue: Dict[str, float] = {}  # module_name -> request_time
    _reused_context: bool = False  # Indica se mutex foi reutilizado de outro módulo

    def __init__(self, module_name: str, timeout: float = 30.0):
        """
        Inicializa o mutex para um módulo.

        Args:
            module_name: Nome do módulo (ex: "fisher", "runemaker")
            timeout: Tempo máximo para adquirir o lock (segundos)
        """
        self.module_name = module_name.lower()
        self.timeout = timeout
        self.priority = MODULE_PRIORITIES.get(self.module_name, 50)
        self.acquired = False
        self._reused_context = False  # Rastreia se reutilizou contexto de outro módulo

    def __enter__(self):
        """Context manager entry."""
        # Se já temos um holder do mesmo grupo, reutiliza o contexto (sem adquirir novo)
        with self._lock:
            if self._current_holder is not None:
                current_group = _get_module_group(self._current_holder)
                this_group = _get_module_group(self.module_name)

                if current_group == this_group and current_group != f"{self.module_name}_SOLO":
                    # Mesmo grupo - reutiliza contexto
                    self._reused_context = True
                    self.acquired = True
                    print(f"[PACKET-MUTEX] 🔄 {self.module_name.upper()} reutilizando mutex de {self._current_holder.upper()} (grupo: {current_group})")
                    return self

        # Senão, adquire normalmente
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        # Apenas libera se foi o titular do mutex (não se foi reutilizado)
        if not self._reused_context:
            self.release()
        return False

    @classmethod
    def acquire(cls, module_name: str, timeout: float = 30.0) -> bool:
        """
        Adquire o mutex para um módulo.

        Args:
            module_name: Nome do módulo
            timeout: Tempo máximo de espera

        Returns:
            True se adquiriu com sucesso, False se timeout
        """
        instance = cls(module_name, timeout)
        instance.acquire()
        return instance.acquired

    @classmethod
    def release(cls, module_name: str) -> bool:
        """
        Libera o mutex para um módulo.

        Args:
            module_name: Nome do módulo

        Returns:
            True se liberou com sucesso
        """
        instance = cls(module_name)
        instance.release()
        return True

    def acquire(self, blocking: bool = True) -> bool:
        """
        Tenta adquirir o mutex.

        Args:
            blocking: Se True, aguarda até conseguir (até timeout)
                     Se False, retorna imediatamente

        Returns:
            True se adquiriu, False caso contrário
        """
        start_time = time.time()
        request_time = start_time

        # Registra requisição na fila
        self._wait_queue[self.module_name] = request_time

        try:
            while True:
                with self._lock:
                    # Verifica se está livre
                    if self._current_holder is None:
                        # Verifica delay mínimo desde última ação
                        time_since_last = time.time() - self._last_action_time
                        if time_since_last < INTER_MODULE_DELAY:
                            # NOVO: Apenas força delay se for módulo NÃO-RELACIONADO
                            last_holder_group = _get_module_group(self._last_holder) if self._last_holder else None
                            current_group = _get_module_group(self.module_name)

                            # Se são do mesmo grupo (módulos relacionados), SEM DELAY
                            if last_holder_group != current_group:
                                if not blocking:
                                    self._wait_queue.pop(self.module_name, None)
                                    return False

                                # Aguarda o delay mínimo para módulos não-relacionados
                                remaining_delay = INTER_MODULE_DELAY - time_since_last
                                time.sleep(remaining_delay)
                                continue

                        # Adquire o lock
                        self._current_holder = self.module_name
                        self._action_start_time = time.time()
                        self.acquired = True
                        self._wait_queue.pop(self.module_name, None)

                        print(f"[PACKET-MUTEX] 🔒 {self.module_name.upper()} adquiriu mutex")
                        return True

                    # Verifica timeout
                    if time.time() - start_time > self.timeout:
                        self._wait_queue.pop(self.module_name, None)
                        print(f"[PACKET-MUTEX] ⏱️ {self.module_name.upper()} TIMEOUT aguardando mutex")
                        return False

                    # Não bloqueante
                    if not blocking:
                        self._wait_queue.pop(self.module_name, None)
                        return False

                # Sleep antes de tentar novamente
                time.sleep(0.05)

        except Exception as e:
            print(f"[PACKET-MUTEX] ❌ Erro ao adquirir mutex ({self.module_name}): {e}")
            self._wait_queue.pop(self.module_name, None)
            return False

    def release(self) -> bool:
        """
        Libera o mutex.

        Returns:
            True se liberou com sucesso
        """
        with self._lock:
            if self._current_holder == self.module_name:
                self._last_holder = self._current_holder  # Registra o último titular
                self._current_holder = None
                self._last_action_time = time.time()
                self.acquired = False

                # Calcula tempo que manteve o lock
                elapsed = time.time() - (self._action_start_time or time.time())
                print(f"[PACKET-MUTEX] 🔓 {self.module_name.upper()} liberou mutex (duração: {elapsed:.2f}s)")
                return True

        print(f"[PACKET-MUTEX] ⚠️ {self.module_name.upper()} tentou liberar mutex que não possui")
        return False

    @classmethod
    def get_status(cls) -> Dict:
        """
        Retorna status atual do mutex.

        Returns:
            Dicionário com status
        """
        with cls._lock:
            return {
                "current_holder": cls._current_holder,
                "waiting_modules": list(cls._wait_queue.keys()),
                "last_action_time": cls._last_action_time,
                "time_since_last_action": time.time() - cls._last_action_time,
            }

    @classmethod
    def reset(cls):
        """Reseta o mutex (apenas para testes)."""
        with cls._lock:
            cls._current_holder = None
            cls._last_holder = None
            cls._last_action_time = 0.0
            cls._action_start_time = None
            cls._wait_queue.clear()
        print("[PACKET-MUTEX] ⚙️ Mutex foi resetado")


# Aliases para facilitar uso
def acquire_packet_mutex(module_name: str, timeout: float = 30.0) -> bool:
    """Adquire mutex para ações de packet."""
    return PacketMutex.acquire(module_name, timeout)


def release_packet_mutex(module_name: str) -> bool:
    """Libera mutex após ações de packet."""
    return PacketMutex.release(module_name)


def get_packet_mutex_status() -> Dict:
    """Retorna status do mutex."""
    return PacketMutex.get_status()
