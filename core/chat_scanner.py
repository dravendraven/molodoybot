# core/chat_scanner.py
"""
Scanner de mensagens do chat do jogo.
Detecta novas mensagens e extrai informações do remetente.
"""
import time
import re
import hashlib
from dataclasses import dataclass
from typing import Optional

from config import OFFSET_CONSOLE_MSG, OFFSET_CONSOLE_AUTHOR

# Offset do ponteiro do console
OFFSET_CONSOLE_PTR = 0x31DD18


@dataclass
class ChatMessage:
    """Representa uma mensagem do chat do jogo."""
    sender: str           # Nome do player ("Dark Knight")
    text: str             # Conteúdo da mensagem ("hi there")
    msg_type: str         # Tipo: "say", "yell", "whisper"
    timestamp: float      # Timestamp de detecção
    raw_author: str       # String original ("Dark Knight says:")


class ChatScanner:
    """
    Scanner de mensagens do chat do jogo.
    Detecta novas mensagens comparando hash com a última lida.
    """

    # Padrões para extrair nome e tipo do author string
    # Exemplos: "Dark Knight says:", "Player yells:", "Someone whispers:"
    AUTHOR_PATTERNS = [
        (r'^(.+?) says:$', 'say'),
        (r'^(.+?) yells:$', 'yell'),
        (r'^(.+?) whispers:$', 'whisper'),
        (r'^(.+?):$', 'say'),  # Fallback genérico
    ]

    def __init__(self, pm, base_addr):
        self.pm = pm
        self.base_addr = base_addr
        # Hash da última mensagem RECEBIDA (evita re-detectar mesma mensagem)
        self.last_received_hash: Optional[str] = None
        # Hash da mensagem ENVIADA pelo bot (evita detectar própria mensagem)
        self.last_sent_hash: Optional[str] = None
        self.last_author: str = ""
        self.last_text: str = ""

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

    def _compute_hash(self, author: str, text: str) -> str:
        """Gera hash único para a mensagem."""
        content = f"{author}|{text}"
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

        Returns:
            ChatMessage se houver mensagem nova, None caso contrário
        """
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

        # Calcula hash para detectar se é nova
        current_hash = self._compute_hash(author_str, msg_str)

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

        # Extrai nome e tipo
        sender_name, msg_type = self._parse_author(author_str)

        return ChatMessage(
            sender=sender_name,
            text=msg_str,
            msg_type=msg_type,
            timestamp=time.time(),
            raw_author=author_str
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
        # Formato esperado no jogo: "NomeDoPlayer says:"
        expected_author = f"{my_name} says:"
        # Apenas marca o hash da mensagem enviada (não sobrescreve last_received)
        self.last_sent_hash = self._compute_hash(expected_author, text)
