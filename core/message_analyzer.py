# core/message_analyzer.py
"""
Analisador de mensagens para determinar se são direcionadas ao bot.
Usa dados do battlelist (posição, direção, movimento) para calcular probabilidade.
"""
import random
from dataclasses import dataclass
from typing import Optional, Dict, Any

from core.chat_scanner import ChatMessage
from core.battlelist import BattleListScanner
from core.models import Position, Creature
from config import (
    DIR_NORTH, DIR_EAST, DIR_SOUTH, DIR_WEST,
    CHAT_RESPONSE_DELAY_MIN, CHAT_RESPONSE_DELAY_MAX
)


@dataclass
class MessageIntent:
    """Resultado da análise de uma mensagem."""
    is_directed_at_me: bool     # Conclusão final
    confidence: float           # 0.0 a 1.0
    sender_data: Dict[str, Any] # Dados do player (pos, facing, moving)
    reasoning: str              # Explicação para debug
    should_respond: bool        # Considera confidence + aleatoriedade


class MessageAnalyzer:
    """
    Analisa se uma mensagem é direcionada ao bot.

    Fatores considerados:
    - Distância do player que enviou
    - Se está parado e olhando para o bot
    - Se está se movendo em direção ao bot ou se afastando
    - Tipo de mensagem (greeting, pergunta, etc)
    """

    # Greetings comuns que indicam início de conversa
    GREETINGS = {
        'hi', 'hello', 'hey', 'oi', 'ola', 'olá', 'yo', 'sup',
        'hola', 'greetings', 'good morning', 'good evening',
        'e ai', 'eai', 'fala', 'salve', 'opa'
    }

    # Palavras que indicam pergunta/interação
    QUESTION_INDICATORS = {'?', 'what', 'where', 'how', 'why', 'when', 'who', 'can', 'could', 'do', 'does'}

    def __init__(self, pm, base_addr):
        self.pm = pm
        self.base_addr = base_addr
        self.scanner = BattleListScanner(pm, base_addr)

        # Cache de posições anteriores para detectar aproximação
        self._position_cache: Dict[str, Position] = {}

    def analyze(self, message: ChatMessage, my_pos: Position) -> MessageIntent:
        """
        Analisa uma mensagem e determina probabilidade de ser direcionada ao bot.

        Args:
            message: Mensagem do chat
            my_pos: Posição atual do bot

        Returns:
            MessageIntent com resultado da análise
        """
        # Busca o player no battlelist
        sender = self._get_sender_creature(message.sender)

        # Player não encontrado no battlelist (longe ou saiu da tela)
        if not sender:
            return MessageIntent(
                is_directed_at_me=False,
                confidence=0.1,
                sender_data={"found": False, "name": message.sender},
                reasoning="Player não visível no battlelist",
                should_respond=False
            )

        # Coleta dados do sender
        sender_data = self._build_sender_data(sender, my_pos)

        # Calcula probabilidade base
        confidence = self._calculate_confidence(message, sender, my_pos, sender_data)

        # Atualiza cache de posição para próxima análise
        self._position_cache[message.sender] = sender.position

        # Decisão final com componente aleatório (humano não responde sempre)
        should_respond = self._should_respond(confidence, message)

        # Gera reasoning para debug
        reasoning = self._build_reasoning(sender_data, confidence)

        return MessageIntent(
            is_directed_at_me=confidence > 0.5,
            confidence=confidence,
            sender_data=sender_data,
            reasoning=reasoning,
            should_respond=should_respond
        )

    def _get_sender_creature(self, sender_name: str) -> Optional[Creature]:
        """Busca o player no battlelist pelo nome."""
        players = self.scanner.get_players()
        for player in players:
            if player.name.lower() == sender_name.lower():
                return player
        return None

    def _build_sender_data(self, sender: Creature, my_pos: Position) -> Dict[str, Any]:
        """Constrói dicionário com dados relevantes do sender."""
        distance = my_pos.chebyshev_to(sender.position)
        is_facing_me = self._is_facing_me(sender, my_pos)
        movement_status = self._get_movement_status(sender, my_pos)

        return {
            "found": True,
            "name": sender.name,
            "position": {
                "x": sender.position.x,
                "y": sender.position.y,
                "z": sender.position.z
            },
            "relative_pos": {
                "x": sender.position.x - my_pos.x,
                "y": sender.position.y - my_pos.y
            },
            "distance": distance,
            "is_moving": sender.is_moving,
            "facing_direction": sender.facing_direction,
            "facing_direction_name": self._direction_name(sender.facing_direction),
            "is_facing_me": is_facing_me,
            "movement_status": movement_status  # "approaching", "departing", "stationary"
        }

    def _calculate_confidence(self, message: ChatMessage, sender: Creature,
                              my_pos: Position, sender_data: Dict) -> float:
        """Calcula probabilidade (0.0 - 1.0) de a mensagem ser para o bot."""
        confidence = 0.0

        distance = sender_data["distance"]
        is_facing_me = sender_data["is_facing_me"]
        is_moving = sender_data["is_moving"]
        movement_status = sender_data["movement_status"]

        # 1. DISTÂNCIA (quanto mais perto, mais provável)
        if distance <= 1:
            confidence += 0.45  # Adjacente = muito provável
        elif distance <= 3:
            confidence += 0.35  # Perto
        elif distance <= 5:
            confidence += 0.20  # Médio
        elif distance <= 7:
            confidence += 0.10  # Borda da tela
        else:
            confidence += 0.05  # Longe

        # 2. OLHANDO PARA MIM? (parado + facing = forte indicador)
        if not is_moving and is_facing_me:
            confidence += 0.35  # Parado e olhando = muito provável

        # 3. MOVIMENTO (se aproximando vs se afastando)
        if is_moving:
            if movement_status == "approaching":
                confidence += 0.15  # Vindo em minha direção
            elif movement_status == "departing":
                confidence -= 0.20  # Se afastando = provavelmente não é pra mim
            # "stationary" ou "parallel" não altera

        # 4. CONTEÚDO DA MENSAGEM
        text_lower = message.text.lower().strip()

        # Greeting direto = alta probabilidade de ser início de conversa
        if text_lower in self.GREETINGS:
            confidence += 0.70

        # Pergunta = provável interação
        if '?' in message.text:
            confidence += 0.40

        # Mensagem muito curta (1-2 palavras) = mais provável ser direcionada
        word_count = len(message.text.split())
        if word_count <= 2:
            confidence += 0.05

        # 5. TIPO DE MENSAGEM
        if message.msg_type == "whisper":
            confidence += 0.30  # Whisper é sempre direcionado
        elif message.msg_type == "yell":
            confidence -= 0.10  # Yell geralmente é para todos

        # Clamp entre 0 e 1
        return max(0.0, min(1.0, confidence))

    def _is_facing_me(self, creature: Creature, my_pos: Position) -> bool:
        """
        Verifica se o player está olhando na direção do bot.

        facing_direction: 0=Norte, 1=Este, 2=Sul, 3=Oeste
        """
        dx = my_pos.x - creature.position.x
        dy = my_pos.y - creature.position.y

        # Se estamos no mesmo tile, considera como olhando
        if dx == 0 and dy == 0:
            return True

        facing = creature.facing_direction

        # Norte (dy negativo = bot está ao norte do sender)
        if facing == DIR_NORTH and dy < 0:
            return abs(dx) <= abs(dy)  # Mais ao norte do que aos lados

        # Sul (dy positivo = bot está ao sul)
        if facing == DIR_SOUTH and dy > 0:
            return abs(dx) <= abs(dy)

        # Leste (dx positivo = bot está ao leste)
        if facing == DIR_EAST and dx > 0:
            return abs(dy) <= abs(dx)

        # Oeste (dx negativo = bot está ao oeste)
        if facing == DIR_WEST and dx < 0:
            return abs(dy) <= abs(dx)

        return False

    def _get_movement_status(self, sender: Creature, my_pos: Position) -> str:
        """
        Determina se o player está se aproximando, afastando ou parado.

        Returns:
            "approaching", "departing", "stationary", ou "parallel"
        """
        if not sender.is_moving:
            return "stationary"

        # Verifica se temos posição anterior em cache
        prev_pos = self._position_cache.get(sender.name)
        if not prev_pos:
            # Sem histórico, usa direção que está olhando
            return self._infer_movement_from_facing(sender, my_pos)

        # Calcula distâncias
        prev_distance = my_pos.chebyshev_to(prev_pos)
        curr_distance = my_pos.chebyshev_to(sender.position)

        if curr_distance < prev_distance:
            return "approaching"
        elif curr_distance > prev_distance:
            return "departing"
        else:
            return "parallel"  # Mesma distância (movendo lateralmente)

    def _infer_movement_from_facing(self, sender: Creature, my_pos: Position) -> str:
        """Infere direção de movimento baseado na facing_direction."""
        dx = my_pos.x - sender.position.x
        dy = my_pos.y - sender.position.y
        facing = sender.facing_direction

        # Se está olhando na minha direção enquanto anda = approaching
        if facing == DIR_NORTH and dy < 0:
            return "approaching"
        if facing == DIR_SOUTH and dy > 0:
            return "approaching"
        if facing == DIR_EAST and dx > 0:
            return "approaching"
        if facing == DIR_WEST and dx < 0:
            return "approaching"

        return "departing"

    def _direction_name(self, direction: int) -> str:
        """Converte código de direção para nome legível."""
        names = {
            DIR_NORTH: "norte",
            DIR_EAST: "leste",
            DIR_SOUTH: "sul",
            DIR_WEST: "oeste"
        }
        return names.get(direction, "desconhecido")

    def _should_respond(self, confidence: float, message: ChatMessage) -> bool:
        """
        Decide se deve responder, com componente aleatório humano.

        Humanos não respondem 100% das vezes, mesmo quando alguém fala com eles.
        """
        # Confidence muito alta = responde quase sempre
        if confidence >= 0.8:
            return random.random() < 0.95

        # Confidence alta = responde geralmente
        if confidence >= 0.6:
            return random.random() < 0.85

        # Confidence média = responde às vezes
        if confidence >= 0.4:
            return random.random() < 0.60

        # Confidence baixa = raramente responde
        if confidence >= 0.25:
            return random.random() < 0.30

        # Muito baixa = quase nunca
        return random.random() < 0.10

    def _build_reasoning(self, sender_data: Dict, confidence: float) -> str:
        """Constrói string de reasoning para debug/log."""
        if not sender_data.get("found"):
            return "Player não encontrado no battlelist"

        parts = []
        parts.append(f"Distância: {sender_data['distance']} tiles")

        if sender_data["is_moving"]:
            parts.append(f"Movendo ({sender_data['movement_status']})")
        else:
            parts.append("Parado")

        if sender_data["is_facing_me"]:
            parts.append("Olhando para mim")
        else:
            parts.append(f"Olhando {sender_data['facing_direction_name']}")

        parts.append(f"Confidence: {confidence:.0%}")

        return " | ".join(parts)


def calculate_response_delay() -> float:
    """
    Calcula delay humanizado para resposta.
    Usa distribuição gaussiana para parecer natural.
    """
    try:
        min_delay = CHAT_RESPONSE_DELAY_MIN
        max_delay = CHAT_RESPONSE_DELAY_MAX
    except NameError:
        min_delay = 1.5
        max_delay = 4.0

    mean = (min_delay + max_delay) / 2
    std = (max_delay - min_delay) / 4

    delay = random.gauss(mean, std)
    return max(min_delay, min(max_delay, delay))
