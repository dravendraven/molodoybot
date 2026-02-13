# core/chat_handler.py
"""
Orquestrador do sistema de chat inteligente.
Integra ChatScanner, MessageAnalyzer, ConversationManager e AIResponder.
"""
import time
import threading
from typing import Optional, Dict, Any, List

from core.chat_scanner import ChatScanner, ChatMessage
from core.message_analyzer import MessageAnalyzer, MessageIntent
from core.conversation_manager import ConversationManager
from core.ai_responder import AIResponder, AIResponse
from core.models import Position, Creature
from core.battlelist import BattleListScanner
from core.map_core import get_player_pos
from core.player_core import get_connected_char_name, get_target_id
from core.inventory_core import get_item_id_in_hand
from core.bot_state import state as bot_state
from database.lootables_db import LOOTABLES
from config import (
    AI_MODEL, OFFSET_PLAYER_HP, OFFSET_PLAYER_HP_MAX,
    OFFSET_PLAYER_MANA, OFFSET_PLAYER_MANA_MAX,
    CHAT_RESPONSE_COOLDOWN, CHAT_PAUSE_BOT, CHAT_PAUSE_DURATION
)


class ChatHandler:
    """
    Orquestra detecção, análise e resposta de mensagens de chat.

    Fluxo:
    1. ChatScanner detecta nova mensagem
    2. MessageAnalyzer determina se é direcionada ao bot
    3. AIResponder gera resposta humanizada
    4. ConversationManager mantém histórico
    5. Resposta é enviada com delay humano
    """

    def __init__(self, pm, base_addr, packet, memory_map=None):
        """
        Inicializa o handler.

        Args:
            pm: Process memory handle (pymem)
            base_addr: Base address do Tibia
            packet: PacketManager para enviar mensagens
            memory_map: MemoryMap opcional para contexto de grid
        """
        self.pm = pm
        self.base_addr = base_addr
        self.packet = packet
        self.memory_map = memory_map

        # Configuração - lê nome do personagem da memória (dinâmico)
        # Captura antes de criar o analyzer para passar o nome
        self.my_name = get_connected_char_name(pm, base_addr) or "Unknown"

        # Componentes
        self.chat_scanner = ChatScanner(pm, base_addr)
        self.analyzer = MessageAnalyzer(pm, base_addr, my_name=self.my_name)
        # === MEMORY OPTIMIZATION: Reduzido de 300s para 120s para limpeza mais agressiva ===
        self.conversation_mgr = ConversationManager(max_history=10, timeout_seconds=120)
        self.ai_responder = AIResponder(model=AI_MODEL)
        self.battlelist = BattleListScanner(pm, base_addr)
        self.enabled = True  # Controlado externamente via enable()/disable()

        # Estado
        self.is_responding = False
        self.last_response_time = 0
        self.response_cooldown = CHAT_RESPONSE_COOLDOWN
        self.pause_until = 0  # Timestamp até quando pausar

        # Thread de resposta
        self._response_thread: Optional[threading.Thread] = None

        # Callbacks
        self._on_message_received = None
        self._on_response_sent = None

        print(f"[ChatHandler] Inicializado. AI {'habilitada' if self.enabled else 'desabilitada'}. Player: {self.my_name}")

    def set_callbacks(self, on_message=None, on_response=None):
        """
        Define callbacks para eventos.

        Args:
            on_message: Chamado quando mensagem é recebida (sender, text, intent)
            on_response: Chamado quando resposta é enviada (text)
        """
        self._on_message_received = on_message
        self._on_response_sent = on_response

    def tick(self) -> bool:
        """
        Chamado no loop principal. Verifica e processa novas mensagens.

        Returns:
            True se o bot deve pausar (em conversa), False caso contrário
        """
        # Desabilitado
        if not self.enabled:
            return False

        # Tenta detectar nome do player se ainda não foi detectado
        if self.my_name == "Unknown":
            detected_name = get_connected_char_name(self.pm, self.base_addr)
            if detected_name:
                self.my_name = detected_name
                # Atualiza o analyzer para detectar menções ao nome
                self.analyzer.set_my_name(detected_name)
                print(f"[ChatHandler] Player detectado: {self.my_name}")

        # Já respondendo
        if self.is_responding:
            return self._is_paused()

        # Cooldown entre respostas
        if time.time() - self.last_response_time < self.response_cooldown:
            return self._is_paused()

        # Limpa conversas antigas periodicamente
        self.conversation_mgr.clear_old_conversations()

        # Busca nova mensagem
        message = self.chat_scanner.get_new_message()
        if not message:
            return self._is_paused()

        # Ignora próprias mensagens
        if message.sender.lower() == self.my_name.lower():
            return self._is_paused()

        # Ignora mensagens de canais (trade, help, etc.) - só responde say/yell/whisper
        # Mensagens de canal não são interações diretas com o player
        valid_types = ("say", "yell", "whisper")
        if message.msg_type not in valid_types:
            # Log apenas em debug para não poluir
            # print(f"[ChatHandler] Ignorando canal: {message.sender} ({message.msg_type})")
            return self._is_paused()

        # Processa a mensagem
        self._process_message(message)

        return self._is_paused()

    def _process_message(self, message: ChatMessage):
        """Processa uma mensagem recebida."""
        # Obtém posição atual
        try:
            px, py, pz = get_player_pos(self.pm, self.base_addr)
            my_pos = Position(px, py, pz)
        except Exception as e:
            print(f"[ChatHandler] Erro ao obter posição: {e}")
            return

        # Analisa a mensagem
        intent = self.analyzer.analyze(message, my_pos)

        # Log para debug
        gm_indicator = " ⚠️ [GM]" if message.is_gm else ""
        print(f"[ChatHandler] 💬{gm_indicator} {message.sender}: \"{message.text}\"")
        print(f"[ChatHandler]    → {intent.reasoning}")

        # Callback de mensagem recebida
        if self._on_message_received:
            try:
                self._on_message_received(message.sender, message.text, intent)
            except Exception:
                pass

        # Não deve responder
        if not intent.should_respond:
            print(f"[ChatHandler]    → Ignorando (confidence={intent.confidence:.0%})")
            return

        # Adiciona ao histórico
        self.conversation_mgr.add_message(message.sender, message.text, is_from_me=False)

        # Gera contexto do jogo
        game_context = self._build_game_context(my_pos)

        # Obtém histórico de conversa
        history = self.conversation_mgr.get_context(message.sender)

        # Gera resposta via IA
        print(f"[ChatHandler]    → Gerando resposta via IA...")
        response = self.ai_responder.generate_response(
            message, intent.sender_data, history, game_context
        )

        # Resposta vazia = não responder
        if not response.text:
            print(f"[ChatHandler]    → IA decidiu não responder")
            return

        # Agenda resposta com delay humano
        print(f"[ChatHandler]    → Resposta: \"{response.text}\" (delay: {response.delay_seconds:.1f}s)")
        self._schedule_response(response, message.sender)

        # Pausa o bot se configurado
        if CHAT_PAUSE_BOT and response.should_pause:
            self.pause_until = time.time() + CHAT_PAUSE_DURATION

    def _schedule_response(self, response: AIResponse, sender: str):
        """
        Agenda envio de resposta em thread separada.
        Aplica delay humanizado antes de enviar.
        """
        def send_delayed():
            self.is_responding = True
            try:
                # Delay humano
                time.sleep(response.delay_seconds)

                # Envia mensagem
                self.packet.say(response.text)

                # Marca a mensagem enviada para evitar re-detecção pelo scanner
                self.chat_scanner.mark_sent_message(self.my_name, response.text)

                # Adiciona ao histórico
                self.conversation_mgr.add_message(sender, response.text, is_from_me=True)

                # Registra conversa ativa no analyzer (bônus para próximas mensagens)
                self.analyzer.register_response(sender)

                # Atualiza timestamp
                self.last_response_time = time.time()

                # Callback
                if self._on_response_sent:
                    try:
                        self._on_response_sent(response.text)
                    except Exception:
                        pass

                print(f"[ChatHandler] 📤 Enviado: \"{response.text}\"")

            except Exception as e:
                print(f"[ChatHandler] Erro ao enviar resposta: {e}")
            finally:
                self.is_responding = False

        # Inicia thread
        self._response_thread = threading.Thread(target=send_delayed, daemon=True)
        self._response_thread.start()

    def _build_game_context(self, my_pos: Position) -> Dict[str, Any]:
        """Constrói contexto do jogo para a IA com informações ricas."""
        # Store current position for tile char lookup
        self._current_pos = my_pos

        # Initialize context
        context = {
            "my_name": self.my_name,
            "my_pos": {"x": my_pos.x, "y": my_pos.y, "z": my_pos.z},
            "floor": self._get_floor_description(my_pos.z),
            "nearby_creatures": [],
            "nearby_players": [],
            "hp_percent": 100,
            "mana_percent": 100,
            "hp_status": "healthy",
            "in_combat": False,
            "target_name": "",
            "target_hp": 0,
            "left_hand": "empty",
            "right_hand": "empty",
            "map_matrix": "",
            "creature_legend": "",
            "player_legend": "",
        }

        creatures = []
        players = []

        # Get HP/Mana
        try:
            hp = self.pm.read_int(self.base_addr + OFFSET_PLAYER_HP)
            hp_max = self.pm.read_int(self.base_addr + OFFSET_PLAYER_HP_MAX)
            mana = self.pm.read_int(self.base_addr + OFFSET_PLAYER_MANA)
            mana_max = self.pm.read_int(self.base_addr + OFFSET_PLAYER_MANA_MAX)

            context["hp_percent"] = int((hp / hp_max * 100) if hp_max > 0 else 100)
            context["mana_percent"] = int((mana / mana_max * 100) if mana_max > 0 else 100)
            context["hp_status"] = self._get_hp_status(context["hp_percent"])
        except Exception:
            pass

        # Get equipment
        try:
            left_id = get_item_id_in_hand(self.pm, self.base_addr, is_left=True)
            right_id = get_item_id_in_hand(self.pm, self.base_addr, is_left=False)
            context["left_hand"] = self._get_item_name(left_id)
            context["right_hand"] = self._get_item_name(right_id)
        except Exception:
            pass

        # Get creatures nearby
        try:
            creatures = self.battlelist.get_monsters(player_z=my_pos.z)
            for c in creatures[:5]:
                context["nearby_creatures"].append({
                    "name": c.name,
                    "distance": my_pos.chebyshev_to(c.position),
                    "hp": c.hp_percent
                })
        except Exception:
            pass

        # Get players nearby
        try:
            from config import OFFSET_PLAYER_ID
            player_id = self.pm.read_int(self.base_addr + OFFSET_PLAYER_ID)
            players = self.battlelist.get_players(exclude_self_id=player_id)
            for p in players[:5]:
                context["nearby_players"].append({
                    "name": p.name,
                    "distance": my_pos.chebyshev_to(p.position)
                })
        except Exception:
            pass

        # Get combat state
        try:
            target_id = get_target_id(self.pm, self.base_addr)
            if target_id != 0:
                context["in_combat"] = True
                # Find target in creatures
                for c in creatures:
                    if c.id == target_id:
                        context["target_name"] = c.name
                        context["target_hp"] = c.hp_percent
                        break
        except Exception:
            pass

        # Build map matrix
        try:
            map_str, creature_legend, player_legend = self._build_map_matrix(
                my_pos, creatures, players
            )
            context["map_matrix"] = map_str
            context["creature_legend"] = creature_legend
            context["player_legend"] = player_legend
        except Exception:
            context["map_matrix"] = "unavailable"

        # Infer activity
        context["activity"] = self._infer_activity(context)

        return context

    def _build_map_matrix(self, my_pos: Position, creatures: List, players: List) -> tuple:
        """
        Build 7x7 ASCII map centered on player.

        Returns:
            Tuple of (map_string, creature_legend, player_legend)
        """
        size = 7
        half = size // 2
        lines = []
        creature_chars = {}  # Track which char represents which creature
        player_chars = {}    # Track which char represents which player

        for dy in range(-half, half + 1):
            row = ""
            for dx in range(-half, half + 1):
                if dx == 0 and dy == 0:
                    row += "@"  # Player position
                else:
                    char = self._get_tile_char(
                        my_pos.x + dx, my_pos.y + dy, my_pos.z,
                        creatures, players, creature_chars, player_chars
                    )
                    row += char
            lines.append(row)

        # Build legends
        creature_legend = ", ".join(
            f"{char}={name}({hp}%)"
            for char, (name, hp) in creature_chars.items()
        ) if creature_chars else ""

        player_legend = ", ".join(
            f"{char}={name}"
            for char, name in player_chars.items()
        ) if player_chars else ""

        return "\n".join(lines), creature_legend, player_legend

    def _get_tile_char(self, x: int, y: int, z: int,
                       creatures: List, players: List,
                       creature_chars: dict, player_chars: dict) -> str:
        """Get character representation for a tile."""
        # Check for creature at position
        for c in creatures:
            if c.position.x == x and c.position.y == y and c.position.z == z:
                char = c.name[0].upper() if c.name else "?"
                if char not in creature_chars:
                    creature_chars[char] = (c.name, c.hp_percent)
                return char

        # Check for player at position
        for p in players:
            if p.position.x == x and p.position.y == y and p.position.z == z:
                player_chars["P"] = p.name
                return "P"

        # Check walkability from map analyzer
        if self.memory_map:
            try:
                from core.map_analyzer import MapAnalyzer
                analyzer = MapAnalyzer(self.memory_map)
                # Convert to relative coordinates
                rel_x = x - self._current_pos.x if hasattr(self, '_current_pos') else 0
                rel_y = y - self._current_pos.y if hasattr(self, '_current_pos') else 0
                props = analyzer.get_tile_properties(rel_x, rel_y)
                if props.get('walkable', False):
                    return "."
            except Exception:
                pass

        return "#"  # Blocked or unknown

    def _infer_activity(self, context: dict) -> str:
        """Infer what the player is doing based on game state."""
        # Check if runemaking
        if bot_state.is_runemaking:
            return "making runes"

        # Check combat
        if context.get("in_combat"):
            target = context.get("target_name", "creature")
            return f"fighting {target}"

        # Check equipment for hints
        left_hand = context.get("left_hand", "")
        right_hand = context.get("right_hand", "")

        if "rod" in left_hand.lower() or "rod" in right_hand.lower():
            return "fishing"
        if "spear" in left_hand.lower() or "spear" in right_hand.lower():
            return "training"

        # Check creatures nearby
        if context.get("nearby_creatures"):
            return "hunting"

        return "walking around"

    def _get_floor_description(self, z: int) -> str:
        """Get human-readable floor description."""
        if z == 7:
            return "surface"
        elif z < 7:
            return f"rooftop +{7 - z}"
        else:
            return f"underground -{z - 7}"

    def _get_hp_status(self, hp_percent: float) -> str:
        """Get human-readable HP status."""
        if hp_percent >= 90:
            return "healthy"
        elif hp_percent >= 50:
            return "wounded"
        elif hp_percent >= 25:
            return "badly hurt"
        else:
            return "critical"

    def _get_item_name(self, item_id: int) -> str:
        """Get item name from ID."""
        if item_id == 0:
            return "empty"
        item_data = LOOTABLES.get(item_id)
        if item_data and item_data.get('name'):
            return item_data['name']
        return f"item #{item_id}"

    def _is_paused(self) -> bool:
        """Verifica se o bot deve estar pausado (em conversa)."""
        if not CHAT_PAUSE_BOT:
            return False
        return time.time() < self.pause_until

    def is_ai_available(self) -> bool:
        """Verifica se a IA está disponível."""
        return self.ai_responder.is_available()

    def get_status(self) -> Dict[str, Any]:
        """Retorna status atual do handler para GUI."""
        return {
            "enabled": self.enabled,
            "ai_available": self.is_ai_available(),
            "is_responding": self.is_responding,
            "is_paused": self._is_paused(),
            "pause_remaining": max(0, self.pause_until - time.time()),
            "active_conversations": self.conversation_mgr.get_active_conversations(),
            "last_response_time": self.last_response_time
        }

    def enable(self):
        """Habilita o handler."""
        self.enabled = True
        print("[ChatHandler] Habilitado")

    def disable(self):
        """Desabilita o handler."""
        self.enabled = False
        print("[ChatHandler] Desabilitado")

    def reset(self):
        """Reseta o estado do handler."""
        self.chat_scanner.reset()
        self.conversation_mgr.clear_all()
        self.is_responding = False
        self.pause_until = 0
        print("[ChatHandler] Reset completo")
