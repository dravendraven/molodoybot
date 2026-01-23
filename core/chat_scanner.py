# core/chat_scanner.py
"""
Scanner de mensagens do chat do jogo.
Detecta novas mensagens via pacotes (sniffer) ou leitura de memória (fallback).
"""
import time
import re
import hashlib
from dataclasses import dataclass
from typing import Optional

from config import OFFSET_CONSOLE_MSG, OFFSET_CONSOLE_AUTHOR

# Offset do ponteiro do console
OFFSET_CONSOLE_PTR = 0x31DD18

# Mapeamento de speak_type para msg_type string
# APENAS say, yell, whisper são válidos para resposta do ChatHandler
# Todos os outros tipos são canais/sistema e devem ser ignorados
SPEAK_TYPE_MAP = {
    0x01: "say",           # Fala normal - VÁLIDO
    0x02: "whisper",       # Sussurro - VÁLIDO
    0x03: "yell",          # Grito - VÁLIDO
    0x04: "private_from",  # PM recebida - canal privado
    0x05: "private_to",    # PM enviada / Trade channel
    0x06: "channel_mgmt",  # Gerenciamento de canal
    0x07: "channel_y",     # Canal amarelo (trade, help, etc)
    0x08: "channel_o",     # Canal laranja (tutor)
    0x09: "spell",         # Fala de spell
    0x0A: "npc_from",      # NPC falando
    0x0B: "npc_to",        # Falando com NPC
    0x0C: "broadcast",     # Broadcast do servidor
    0x0D: "channel_r1",    # Canal vermelho (GM)
    0x0E: "private_red_from",  # PM vermelha recebida
    0x0F: "private_red_to",    # PM vermelha enviada
    0x11: "channel_r2",    # Canal vermelho anônimo
    0x13: "monster_say",   # Monstro falando
    0x14: "monster_yell",  # Monstro gritando
}

# Default para tipos desconhecidos (será filtrado)
DEFAULT_MSG_TYPE = "unknown"


@dataclass
class ChatMessage:
    """Representa uma mensagem do chat do jogo."""
    sender: str           # Nome do player ("Dark Knight")
    text: str             # Conteúdo da mensagem ("hi there")
    msg_type: str         # Tipo: "say", "yell", "whisper"
    timestamp: float      # Timestamp de detecção
    raw_author: str       # String original ("Dark Knight says:")
    is_gm: bool = False   # True se detectado como GM/CM
    from_packet: bool = False  # True se veio do sniffer (mais confiável)


class ChatScanner:
    """
    Scanner de mensagens do chat do jogo.
    Usa eventos do sniffer (tempo real) com fallback para leitura de memória.
    """

    # Padrões para extrair nome e tipo do author string
    # Exemplos: "Dark Knight says:", "Player yells:", "Someone whispers:"
    AUTHOR_PATTERNS = [
        (r'^(.+?) says:$', 'say'),
        (r'^(.+?) yells:$', 'yell'),
        (r'^(.+?) whispers:$', 'whisper'),
        (r'^(.+?):$', 'say'),  # Fallback genérico
    ]

    def __init__(self, pm, base_addr, use_events: bool = True):
        self.pm = pm
        self.base_addr = base_addr
        self.use_events = use_events

        # Hash da última mensagem RECEBIDA (evita re-detectar mesma mensagem)
        self.last_received_hash: Optional[str] = None
        # Hash da mensagem ENVIADA pelo bot (evita detectar própria mensagem)
        self.last_sent_hash: Optional[str] = None
        self.last_author: str = ""
        self.last_text: str = ""

        # Integração com EventBus
        self._event_bus = None
        self._pending_events: list = []
        self._events_lock = None

        if use_events:
            self._setup_event_listener()

    def _setup_event_listener(self):
        """Configura listener para eventos de chat do sniffer."""
        try:
            import threading
            from core.event_bus import EventBus, EVENT_CHAT

            self._event_bus = EventBus.get_instance()
            self._events_lock = threading.Lock()

            def on_chat_event(event):
                """Callback chamado pelo sniffer quando recebe chat."""
                with self._events_lock:
                    self._pending_events.append(event)

            self._event_bus.subscribe(EVENT_CHAT, on_chat_event)
        except ImportError:
            self.use_events = False

    def _get_event_message(self) -> Optional[ChatMessage]:
        """Retorna próxima mensagem da fila de eventos do sniffer."""
        if not self._events_lock or not self._pending_events:
            return None

        with self._events_lock:
            if not self._pending_events:
                return None
            event = self._pending_events.pop(0)

        # Converte ChatEvent para ChatMessage
        # Usa DEFAULT_MSG_TYPE para tipos desconhecidos (serão filtrados pelo ChatHandler)
        msg_type = SPEAK_TYPE_MAP.get(event.speak_type, DEFAULT_MSG_TYPE)
        raw_author = f"{event.speaker} {msg_type}s:" if msg_type in ("say", "yell", "whisper") else event.speaker

        # Verifica hash ANTES de retornar para evitar duplicatas
        # Usa sender + texto (normalizado) para garantir consistência entre sniffer e memória
        current_hash = self._compute_hash(event.speaker, event.message)

        # Mesma mensagem já processada (duplicata)
        if current_hash == self.last_received_hash:
            return None  # Ignora duplicata

        # É a própria mensagem do bot aparecendo no console
        if current_hash == self.last_sent_hash:
            self.last_sent_hash = None  # Limpa após detectar
            return None

        # Nova mensagem - atualiza estado
        self.last_received_hash = current_hash
        self.last_author = raw_author
        self.last_text = event.message

        return ChatMessage(
            sender=event.speaker,
            text=event.message,
            msg_type=msg_type,
            timestamp=event.timestamp,
            raw_author=raw_author,
            is_gm=event.is_gm,
            from_packet=True
        )

    def _read_chat_entry(self) -> tuple[Optional[str], Optional[str]]:
        """
        Lê a última entrada do chat da memória.
        Returns: (author_string, message_string) ou (None, None)
        """
        try:
            # Via Ponteiro (método principal)
            console_struct = self.pm.read_int(self.base_addr + OFFSET_CONSOLE_PTR)
            if console_struct > 0:
                author_str = self.pm.read_string(console_struct + 0xF0, 128)
                msg_str = self.pm.read_string(console_struct + 0x118, 128)
                return author_str, msg_str
        except Exception:
            pass

        try:
            # Fallback: Endereços estáticos
            author_str = self.pm.read_string(self.base_addr + OFFSET_CONSOLE_AUTHOR, 128)
            msg_str = self.pm.read_string(self.base_addr + OFFSET_CONSOLE_MSG, 128)
            return author_str, msg_str
        except Exception:
            return None, None

    def _compute_hash(self, sender: str, text: str) -> str:
        """Gera hash único para a mensagem baseado em sender + texto (normalizado)."""
        content = f"{sender.lower()}|{text}"
        return hashlib.md5(content.encode('utf-8', errors='ignore')).hexdigest()

    def _parse_author(self, author_str: str) -> tuple[str, str]:
        """
        Extrai nome e tipo da string de autor.

        Args:
            author_str: String como "Dark Knight says:" ou "Player yells:"

        Returns:
            (player_name, message_type)
        """
        if not author_str:
            return "", "unknown"

        author_str = author_str.strip()

        for pattern, msg_type in self.AUTHOR_PATTERNS:
            match = re.match(pattern, author_str, re.IGNORECASE)
            if match:
                return match.group(1).strip(), msg_type

        # Fallback: retorna string inteira como nome
        return author_str.rstrip(':'), "unknown"

    def _is_valid_chat_author(self, author_str: str) -> bool:
        """
        Verifica se a string de autor corresponde a um padrão de mensagem de chat.
        Retorna False para mensagens de sistema como "You see..." (look).
        """
        if not author_str:
            return False
        author_str = author_str.strip()
        # Verifica apenas padrões válidos de chat (says/yells/whispers)
        # Exclui o fallback genérico que aceita qualquer coisa com ":"
        for pattern, _ in self.AUTHOR_PATTERNS[:-1]:
            if re.match(pattern, author_str, re.IGNORECASE):
                return True
        return False

    def get_new_message(self) -> Optional[ChatMessage]:
        """
        Verifica se há uma nova mensagem no chat.
        Prioriza eventos do sniffer (tempo real), com fallback para memória.

        Returns:
            ChatMessage se houver mensagem nova, None caso contrário
        """
        # 1. Tenta obter do sniffer (mais rápido e confiável)
        if self.use_events:
            event_msg = self._get_event_message()
            if event_msg:
                # Hash já foi atualizado dentro de _get_event_message()
                return event_msg

        # 2. Fallback: leitura de memória
        return self._get_memory_message()

    def _get_memory_message(self) -> Optional[ChatMessage]:
        """Lê mensagem da memória (método original)."""
        author_str, msg_str = self._read_chat_entry()

        # Nenhuma mensagem lida
        if not author_str or not msg_str:
            return None

        # Limpa strings
        author_str = author_str.strip()
        msg_str = msg_str.strip()

        # Ignora mensagens vazias
        if not author_str or not msg_str:
            return None

        # Valida se o autor segue padrão de mensagem de chat (says/yells/whispers)
        # Ignora mensagens de sistema como "You see..." (look)
        if not self._is_valid_chat_author(author_str):
            return None

        # Extrai nome e tipo ANTES de calcular hash (consistência com sniffer)
        sender_name, msg_type = self._parse_author(author_str)

        # Calcula hash usando sender + texto (consistente com eventos do sniffer)
        current_hash = self._compute_hash(sender_name, msg_str)

        # Mesma mensagem recebida de antes (evita duplicatas)
        if current_hash == self.last_received_hash:
            return None

        # É a própria mensagem do bot aparecendo no console
        if current_hash == self.last_sent_hash:
            self.last_sent_hash = None  # Limpa após detectar
            return None

        # Nova mensagem detectada!
        self.last_received_hash = current_hash
        self.last_author = author_str
        self.last_text = msg_str

        return ChatMessage(
            sender=sender_name,
            text=msg_str,
            msg_type=msg_type,
            timestamp=time.time(),
            raw_author=author_str,
            is_gm=False,
            from_packet=False
        )

    def get_last_message(self) -> Optional[ChatMessage]:
        """
        Retorna a última mensagem lida (sem verificar se é nova).
        Útil para debug/testes.
        """
        if not self.last_author or not self.last_text:
            return None

        sender_name, msg_type = self._parse_author(self.last_author)

        return ChatMessage(
            sender=sender_name,
            text=self.last_text,
            msg_type=msg_type,
            timestamp=time.time(),
            raw_author=self.last_author
        )

    def reset(self):
        """Reseta o estado do scanner (limpa hashes anteriores)."""
        self.last_received_hash = None
        self.last_sent_hash = None
        self.last_author = ""
        self.last_text = ""

    def mark_sent_message(self, my_name: str, text: str):
        """
        Marca uma mensagem como enviada pelo bot.
        Pré-computa o hash para que não seja detectada como nova.

        Args:
            my_name: Nome do bot/player
            text: Texto da mensagem enviada
        """
        # Usa sender + texto diretamente (consistente com _compute_hash normalizado)
        self.last_sent_hash = self._compute_hash(my_name, text)
