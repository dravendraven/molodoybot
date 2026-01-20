# core/conversation_manager.py
"""
Gerenciador de histórico de conversas por jogador.
Mantém contexto para a IA responder de forma coerente.
"""
import time
from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class ConversationEntry:
    """Uma entrada no histórico de conversa."""
    speaker: str        # "me" ou nome do player
    text: str           # Conteúdo da mensagem
    timestamp: float    # Quando foi enviada
    is_from_me: bool    # True se foi o bot que enviou


class ConversationManager:
    """
    Mantém histórico de conversas por jogador.
    Limpa automaticamente conversas antigas.
    """

    def __init__(self, max_history: int = 10, timeout_seconds: int = 300):
        """
        Args:
            max_history: Máximo de mensagens por conversa
            timeout_seconds: Tempo em segundos para considerar conversa expirada (default: 5 min)
        """
        self.conversations: Dict[str, List[ConversationEntry]] = {}
        self.last_interaction: Dict[str, float] = {}
        self.max_history = max_history
        self.timeout = timeout_seconds

    def add_message(self, player: str, text: str, is_from_me: bool):
        """
        Adiciona uma mensagem ao histórico de conversa com um jogador.

        Args:
            player: Nome do jogador
            text: Conteúdo da mensagem
            is_from_me: True se foi o bot que enviou
        """
        player = player.strip()
        if not player:
            return

        # Inicializa lista se não existir
        if player not in self.conversations:
            self.conversations[player] = []

        # Cria entrada
        entry = ConversationEntry(
            speaker="me" if is_from_me else player,
            text=text,
            timestamp=time.time(),
            is_from_me=is_from_me
        )

        # Adiciona e mantém limite
        self.conversations[player].append(entry)
        if len(self.conversations[player]) > self.max_history:
            self.conversations[player] = self.conversations[player][-self.max_history:]

        # Atualiza timestamp de interação
        self.last_interaction[player] = time.time()

    def get_context(self, player: str) -> List[dict]:
        """
        Retorna histórico formatado para a IA.

        Args:
            player: Nome do jogador

        Returns:
            Lista de dicts com formato {"from": "me"|player, "text": str}
        """
        player = player.strip()
        if player not in self.conversations:
            return []

        return [
            {
                "from": entry.speaker,
                "text": entry.text,
                "time_ago": int(time.time() - entry.timestamp)
            }
            for entry in self.conversations[player]
        ]

    def get_context_as_string(self, player: str) -> str:
        """
        Retorna histórico como string formatada para prompt.

        Args:
            player: Nome do jogador

        Returns:
            String formatada tipo:
            "Dark Knight: hi
             me: hey
             Dark Knight: hunting here?"
        """
        context = self.get_context(player)
        if not context:
            return "(nenhuma conversa anterior)"

        lines = []
        for entry in context:
            speaker = "me" if entry["from"] == "me" else player
            lines.append(f"{speaker}: {entry['text']}")

        return "\n".join(lines)

    def has_recent_conversation(self, player: str, seconds: int = 60) -> bool:
        """
        Verifica se houve conversa recente com o jogador.

        Args:
            player: Nome do jogador
            seconds: Janela de tempo em segundos

        Returns:
            True se houve interação nos últimos N segundos
        """
        player = player.strip()
        if player not in self.last_interaction:
            return False

        return time.time() - self.last_interaction[player] < seconds

    def clear_old_conversations(self):
        """Remove conversas mais antigas que o timeout."""
        now = time.time()
        expired = []

        for player, last_time in self.last_interaction.items():
            if now - last_time > self.timeout:
                expired.append(player)

        for player in expired:
            del self.conversations[player]
            del self.last_interaction[player]

    def clear_player(self, player: str):
        """Remove histórico de um jogador específico."""
        player = player.strip()
        if player in self.conversations:
            del self.conversations[player]
        if player in self.last_interaction:
            del self.last_interaction[player]

    def clear_all(self):
        """Limpa todo o histórico."""
        self.conversations.clear()
        self.last_interaction.clear()

    def get_active_conversations(self) -> List[str]:
        """Retorna lista de jogadores com conversas ativas."""
        return list(self.conversations.keys())

    def get_conversation_count(self, player: str) -> int:
        """Retorna número de mensagens na conversa com um jogador."""
        player = player.strip()
        if player not in self.conversations:
            return 0
        return len(self.conversations[player])
