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
from core.models import Position
from core.battlelist import BattleListScanner
from core.map_core import get_player_pos
from core.player_core import get_connected_char_name
from config import (
    AI_MODEL,
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
        self.conversation_mgr = ConversationManager(max_history=10, timeout_seconds=300)
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
        print(f"[ChatHandler] 💬 {message.sender}: \"{message.text}\"")
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
        """Constrói contexto do jogo para a IA."""
        context = {
            "my_name": self.my_name,
            "my_pos": {
                "x": my_pos.x,
                "y": my_pos.y,
                "z": my_pos.z
            },
            "nearby_creatures": [],
            "nearby_players": []
        }

        # Busca criaturas próximas
        try:
            creatures = self.battlelist.get_monsters(player_z=my_pos.z)
            for c in creatures[:5]:  # Limita a 5 para não poluir
                context["nearby_creatures"].append({
                    "name": c.name,
                    "distance": my_pos.chebyshev_to(c.position)
                })
        except Exception:
            pass

        # Busca players próximos
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

        return context

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
