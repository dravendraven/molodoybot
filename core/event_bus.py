# core/event_bus.py
"""
Sistema de eventos thread-safe para comunicação entre sniffer e módulos.
Permite pub/sub de eventos como chat, containers, etc.
"""
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Any
from collections import deque


@dataclass
class ChatEvent:
    """Evento de mensagem de chat recebida via pacote."""
    speaker: str          # Nome do falante
    message: str          # Conteúdo da mensagem
    speak_type: int       # Tipo: 0x01=say, 0x02=whisper, 0x03=yell, 0x0D=GM_channel
    is_gm: bool           # True se detectado como GM/CM
    timestamp: float = field(default_factory=time.time)
    position: Optional[tuple] = None  # (x, y, z) se disponível
    channel_id: Optional[int] = None  # ID do canal se for mensagem de canal


@dataclass
class ContainerEvent:
    """Evento de container aberto/fechado."""
    event_type: str       # "open" ou "close"
    container_id: int     # ID do container (0-15)
    name: str             # Nome do container ("bag", "dead rat", etc)
    item_count: int       # Número de itens (apenas em open)
    timestamp: float = field(default_factory=time.time)


@dataclass
class SystemMessageEvent:
    """Evento de mensagem do sistema (TEXT_MESSAGE 0xB4)."""
    msg_type: int         # 0x12=RED, 0x13=ORANGE, 0x19=GREEN, 0x1B=BLUE
    message: str          # Texto da mensagem
    timestamp: float = field(default_factory=time.time)


class EventBus:
    """
    Barramento de eventos thread-safe.
    Singleton para acesso global.
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._listeners: Dict[str, List[Callable]] = {}
        self._latest_events: Dict[str, Any] = {}
        self._event_history: Dict[str, deque] = {}
        self._history_size = 50  # Guarda últimos N eventos de cada tipo
        self._sub_lock = threading.Lock()
        self._initialized = True

    @classmethod
    def get_instance(cls) -> 'EventBus':
        """Retorna a instância singleton do EventBus."""
        return cls()

    def subscribe(self, event_type: str, callback: Callable) -> None:
        """
        Inscreve um callback para receber eventos de um tipo.

        Args:
            event_type: Tipo do evento ("chat", "container_open", "container_close")
            callback: Função que recebe o evento como parâmetro
        """
        with self._sub_lock:
            if event_type not in self._listeners:
                self._listeners[event_type] = []
            if callback not in self._listeners[event_type]:
                self._listeners[event_type].append(callback)

    def unsubscribe(self, event_type: str, callback: Callable) -> None:
        """Remove um callback da lista de listeners."""
        with self._sub_lock:
            if event_type in self._listeners:
                try:
                    self._listeners[event_type].remove(callback)
                except ValueError:
                    pass

    def publish(self, event_type: str, event: Any) -> None:
        """
        Publica um evento para todos os listeners inscritos.

        Args:
            event_type: Tipo do evento
            event: Objeto do evento (ChatEvent, ContainerEvent, etc)
        """
        # Atualiza latest e histórico
        self._latest_events[event_type] = event

        if event_type not in self._event_history:
            self._event_history[event_type] = deque(maxlen=self._history_size)
        self._event_history[event_type].append(event)

        # Notifica listeners (cópia para evitar modificação durante iteração)
        with self._sub_lock:
            listeners = self._listeners.get(event_type, []).copy()

        for callback in listeners:
            try:
                callback(event)
            except Exception as e:
                print(f"[EventBus] Erro no callback {callback.__name__}: {e}")

    def get_latest(self, event_type: str) -> Optional[Any]:
        """
        Retorna o último evento de um tipo.

        Args:
            event_type: Tipo do evento

        Returns:
            Último evento ou None se não houver
        """
        return self._latest_events.get(event_type)

    def get_recent(self, event_type: str, max_age_seconds: float = 5.0) -> List[Any]:
        """
        Retorna eventos recentes de um tipo dentro de uma janela de tempo.

        Args:
            event_type: Tipo do evento
            max_age_seconds: Idade máxima dos eventos em segundos

        Returns:
            Lista de eventos recentes
        """
        if event_type not in self._event_history:
            return []

        cutoff = time.time() - max_age_seconds
        return [e for e in self._event_history[event_type] if e.timestamp >= cutoff]

    def clear(self, event_type: Optional[str] = None) -> None:
        """
        Limpa eventos armazenados.

        Args:
            event_type: Tipo específico para limpar, ou None para limpar todos
        """
        if event_type:
            self._latest_events.pop(event_type, None)
            if event_type in self._event_history:
                self._event_history[event_type].clear()
        else:
            self._latest_events.clear()
            for history in self._event_history.values():
                history.clear()

    def reset(self) -> None:
        """Reseta completamente o EventBus (para testes)."""
        with self._sub_lock:
            self._listeners.clear()
        self._latest_events.clear()
        self._event_history.clear()


# Tipos de eventos disponíveis
EVENT_CHAT = "chat"
EVENT_CONTAINER_OPEN = "container_open"
EVENT_CONTAINER_CLOSE = "container_close"
EVENT_SYSTEM_MSG = "system_msg"
