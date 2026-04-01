# core/telegram_handler.py
"""
Gerenciador de integração com Telegram.

Responsabilidades:
- Envio de alertas e notificações
- Recebimento de comandos remotos via long polling
- UI de botões interativos (inline keyboards)
- Envio de mensagens no jogo com delays humanizados
"""

import time
import json
import threading
import random
from typing import Optional, Callable

from database.tiles_config import BLOCKING_IDS, GROUND_SPEEDS
from core.battlelist import BattleListScanner


class TelegramHandler:
    """
    Gerencia todas as interações com o Telegram Bot API.

    Features:
    - Envio de alertas (GM detectado, disconnect, etc.)
    - Comandos remotos (/say, /status, /sayall)
    - Botões interativos para seleção de personagem
    - Delays humanizados para envio de mensagens
    """

    def __init__(
        self,
        token: str,
        chat_id: str,
        pm,
        base_addr: int,
        packet_manager,
        get_char_name_func: Callable[[], str],
        log_func: Callable[[str], None],
        bot_state,
        game_state,
        bot_settings: dict
    ):
        """
        Inicializa o handler do Telegram.

        Args:
            token: Bot token do BotFather
            chat_id: Chat ID autorizado
            pm: Process memory handle (pymem)
            base_addr: Base address do Tibia
            packet_manager: PacketManager para enviar mensagens no jogo
            get_char_name_func: Função para obter nome do personagem
            log_func: Função de log
            bot_state: Objeto state global
            game_state: Objeto game_state global
            bot_settings: Dicionário BOT_SETTINGS
        """
        self.token = token
        self.chat_id = chat_id
        self.pm = pm
        self.base_addr = base_addr
        self.packet = packet_manager
        self.get_char_name = get_char_name_func
        self.log = log_func
        self.state = bot_state
        self.game_state = game_state
        self.bot_settings = bot_settings

        # Estado interno do listener
        self._last_update_id = 0
        self._last_message_time = 0
        self._waiting_for_message = False
        self._waiting_chat_id = None
        self._waiting_timeout = 0

        # Thread de polling
        self._listener_thread = None
        self._stop_listener = False

        # Connection pooling para evitar SSL access violations
        self._session = None  # Será inicializado no listener_loop
        self._session_lock = threading.Lock()

    def send_alert(self, msg: str):
        """
        Envia alerta/notificação no Telegram usando session pooling quando disponível.
        Usado por outros módulos (alarm, disconnect, etc.).

        Args:
            msg: Mensagem a enviar (sem prefixo de char)
        """
        if not self.token or "TOKEN" in self.token:
            self.log("[TELEGRAM] Token não configurado, pulando.")
            print("[DEBUG TELEGRAM] Token não configurado")
            return

        if not self.chat_id:
            self.log("[TELEGRAM] Chat ID não configurado, pulando.")
            print("[DEBUG TELEGRAM] Chat ID vazio ou não configurado")
            return

        try:
            import requests

            # Usa session se disponível (evita criar nova conexão)
            session = self._session if self._session else requests

            # Obtém nome do personagem do bot_state (thread-safe)
            char_name = self.state.char_name if self.state.char_name else "Unknown"

            # Formato: [NomeChar] 🚨 Mensagem
            formatted_msg = f"[{char_name}] 🚨 {msg}"

            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            data = {"chat_id": self.chat_id, "text": formatted_msg}

            print(f"[DEBUG TELEGRAM] Enviando para chat_id={self.chat_id}")
            print(f"[DEBUG TELEGRAM] Mensagem: {formatted_msg}")

            response = session.post(url, data=data, timeout=15)

            print(f"[DEBUG TELEGRAM] Status code: {response.status_code}")
            print(f"[DEBUG TELEGRAM] Response: {response.text}")

            if response.status_code == 200:
                self.log("[TELEGRAM] Mensagem enviada.")
            else:
                self.log(f"[TELEGRAM] Falha no envio: {response.status_code} - {response.text}")
        except requests.exceptions.SSLError as e:
            self.log(f"[TELEGRAM] SSL Error: {e}")
            print(f"[DEBUG TELEGRAM] SSL Error: {e}")
        except Exception as e:
            self.log(f"[TELEGRAM ERROR] {e}")
            print(f"[DEBUG TELEGRAM] Exception: {e}")

    def handle_private_message(self, event):
        """
        Callback para mensagens privadas - envia alerta no Telegram.
        Usado pelo EventBus (EVENT_CHAT).

        Args:
            event: Objeto ChatEvent do sniffer
        """
        # Filtra apenas mensagens privadas recebidas (0x04 = PRIVATE_FROM)
        if event.speak_type != 0x04:
            return

        # Envia notificação
        msg = f"📩 PM de {event.speaker}: {event.message}"
        self.log(msg)
        self.send_alert(msg)

    def start_listener_loop(self):
        """Inicia thread de polling do Telegram em background."""
        if self._listener_thread is not None:
            return  # Já está rodando

        self._stop_listener = False
        self._listener_thread = threading.Thread(
            target=self._listener_loop,
            daemon=True,
            name="TelegramListener"
        )
        self._listener_thread.start()
        print("[Telegram Handler] Listener iniciado")

    def stop_listener(self):
        """Para a thread de polling."""
        self._stop_listener = True
        if self._listener_thread:
            self._listener_thread = None
        print("[Telegram Handler] Listener parado")

    def reset(self):
        """
        Reseta o estado do handler.
        Chamado ao desconectar do jogo.
        """
        self.packet = None
        self._waiting_for_message = False
        self._waiting_chat_id = None
        print("[Telegram Handler] Estado resetado")

    def _listener_loop(self):
        """
        Loop principal de polling do Telegram com connection pooling.
        Evita SSL access violations usando session persistente.
        """
        print("[Telegram Listener] Thread iniciada.")

        # Inicializa session com connection pooling
        import requests
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry

        self._session = requests.Session()

        # Configuração de retry automático para erros de rede
        retry_strategy = Retry(
            total=3,  # 3 tentativas
            backoff_factor=1,  # 1s, 2s, 4s
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"]
        )
        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=1,  # 1 conexão persistente
            pool_maxsize=1
        )
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)

        consecutive_errors = 0
        max_consecutive_errors = 5
        backoff_time = 5

        try:
            while self.state.is_running and not self._stop_listener:
                # Circuit breaker: para após muitos erros consecutivos
                if consecutive_errors >= max_consecutive_errors:
                    print(f"[Telegram Listener] Circuit breaker ativado - {consecutive_errors} erros consecutivos")
                    print(f"[Telegram Listener] Aguardando {backoff_time}s antes de retentar...")
                    time.sleep(backoff_time)
                    backoff_time = min(backoff_time * 2, 60)  # Exponential backoff (max 60s)
                    consecutive_errors = 0

                # Só processa se conectado e com token configurado
                if not self.state.is_connected or not self.token or "TOKEN" in self.token:
                    time.sleep(5)
                    continue

                try:
                    url = f"https://api.telegram.org/bot{self.token}/getUpdates"
                    params = {
                        "timeout": 30,  # Server-side long polling
                        "offset": self._last_update_id + 1,
                        "allowed_updates": ["message", "callback_query"]
                    }

                    # Timeout aumentado para 90s (30s server + 60s buffer)
                    response = self._session.get(url, params=params, timeout=90)

                    if response.status_code == 200:
                        consecutive_errors = 0  # Reset em caso de sucesso
                        backoff_time = 5

                        data = response.json()
                        for update in data.get("result", []):
                            self._last_update_id = update["update_id"]
                            self._process_command(update)
                    else:
                        print(f"[Telegram Listener] Erro HTTP: {response.status_code}")
                        consecutive_errors += 1
                        time.sleep(5)

                except requests.exceptions.Timeout:
                    # Long polling timeout - normal, apenas continua
                    consecutive_errors = 0
                    pass

                except requests.exceptions.SSLError as e:
                    print(f"[Telegram Listener] SSL Error (recriar session): {e}")
                    consecutive_errors += 1
                    # Recria session em caso de SSL error
                    try:
                        self._session.close()
                    except:
                        pass
                    self._session = requests.Session()
                    self._session.mount("https://", adapter)
                    time.sleep(10)

                except (requests.exceptions.ConnectionError, OSError) as e:
                    print(f"[Telegram Listener] Erro de conexão: {e}")
                    consecutive_errors += 1
                    time.sleep(10)

                except Exception as e:
                    print(f"[Telegram Listener] Erro inesperado: {type(e).__name__}: {e}")
                    consecutive_errors += 1
                    time.sleep(5)

        finally:
            # Cleanup ao encerrar thread
            if self._session:
                try:
                    self._session.close()
                    print("[Telegram Listener] Session fechada corretamente")
                except:
                    pass

        print("[Telegram Listener] Thread encerrada.")

    def _process_command(self, update: dict):
        """
        Processa um comando recebido do Telegram.

        Comandos suportados:
        - /say                     → Mostra botão com nome do char (interativo)
        - /say CharName: mensagem  → Envia mensagem no jogo (formato antigo)
        - /sayall mensagem         → Envia em todos os bots ativos
        - /status                  → Retorna status do personagem
        - /cancel                  → Cancela operação pendente
        """
        # Processa callback_query (clique em botão inline)
        if "callback_query" in update:
            self._handle_callback(update["callback_query"])
            return

        message = update.get("message", {})
        if not message:
            return

        text = message.get("text", "")
        chat_id = str(message.get("chat", {}).get("id", ""))

        # Valida chat_id autorizado
        authorized_chat_id = self.bot_settings.get('telegram_chat_id', '')
        if chat_id != authorized_chat_id:
            print(f"[Telegram Listener] Chat ID não autorizado: {chat_id}")
            return

        # Verifica timeout do estado de espera (30 segundos)
        if self._waiting_for_message and time.time() - self._waiting_timeout > 30:
            self._waiting_for_message = False
            self._waiting_chat_id = None
            print("[Telegram Listener] Timeout do estado de espera")

        # Se está aguardando mensagem deste chat, envia no jogo
        if self._waiting_for_message and chat_id == self._waiting_chat_id:
            if not text.startswith("/"):  # Ignora outros comandos
                self._send_game_message(text)
                self._waiting_for_message = False
                self._waiting_chat_id = None
                return

        # /say sem parâmetros → Mostra botão interativo
        if text.strip() == "/say":
            self._show_button(chat_id)
            return

        # /say CharName: mensagem (formato com prefixo - mantém compatibilidade)
        if text.startswith("/say "):
            content = text[5:].strip()

            if ":" in content:
                # Formato com prefixo: /say CharName: mensagem
                target_char, msg = content.split(":", 1)
                target_char = target_char.strip()
                msg = msg.strip()

                # Só executa se for para este personagem (case-insensitive)
                current_char = self.get_char_name()
                if target_char.lower() == current_char.lower():
                    self._send_game_message(msg)
                else:
                    print(f"[Telegram Listener] Comando para '{target_char}', ignorando (sou '{current_char}')")
            else:
                # Formato sem prefixo e sem ":" - mostra botão
                self._show_button(chat_id)
            return

        # /sayall mensagem - envia para todos os bots
        if text.startswith("/sayall "):
            msg = text[8:].strip()
            if msg:
                self._send_game_message(msg)
            return

        # /status - retorna status do personagem
        if text.strip() == "/status":
            self._send_status()
            return

        # /cancel - cancela estado de espera
        if text.strip() == "/cancel":
            if self._waiting_for_message:
                self._waiting_for_message = False
                self._waiting_chat_id = None
                self.send_alert("❌ Operação cancelada")
            return

    def _send_game_message(self, text: str):
        """
        Envia uma mensagem no jogo com delay humanizado.
        Simula tempo de digitação para parecer humano.

        Args:
            text: Texto a enviar no jogo
        """
        # Rate limiting (5 segundos entre mensagens)
        elapsed = time.time() - self._last_message_time
        if elapsed < 5.0:
            remaining = 5.0 - elapsed
            self.send_alert(f"⏳ Aguarde {remaining:.1f}s para enviar outra mensagem")
            return

        # Validações
        if not text:
            return

        if len(text) > 255:
            text = text[:255]
            self.send_alert("⚠️ Mensagem truncada para 255 caracteres")

        # Verifica se PacketManager está disponível
        if self.packet is None:
            self.send_alert("❌ Erro: PacketManager não disponível")
            return

        # Delay humanizado: simula tempo de digitação
        # ~50ms por caractere + variação aleatória
        typing_time = len(text) * 0.05 + random.gauss(2.0, 0.5)
        typing_time = max(1.0, min(typing_time, 8.0))  # Entre 1s e 8s

        char_name = self.get_char_name()
        self.send_alert(f"⌨️ [{char_name}] Digitando... ({typing_time:.1f}s)")

        time.sleep(typing_time)

        # Envia a mensagem no jogo
        try:
            self.packet.say(text)
            self._last_message_time = time.time()

            # Confirma no Telegram
            preview = text[:50] + "..." if len(text) > 50 else text
            self.send_alert(f"✅ [{char_name}] Enviado: {preview}")
            self.log(f"[Telegram] Mensagem remota enviada: {text}")

        except Exception as e:
            self.send_alert(f"❌ [{char_name}] Erro ao enviar: {e}")
            print(f"[Telegram Listener] Erro ao enviar mensagem: {e}")

    def _show_button(self, chat_id: str):
        """
        Mostra botão inline com o nome do personagem.
        Quando clicado, o bot entra em modo de espera por mensagem.

        Args:
            chat_id: ID do chat do Telegram
        """
        char_name = self.get_char_name()
        if not char_name:
            return

        try:
            import requests

            url = f"https://api.telegram.org/bot{self.token}/sendMessage"

            # Inline keyboard com botão do personagem
            keyboard = {
                "inline_keyboard": [[
                    {"text": f"🎮 {char_name}", "callback_data": f"say:{char_name}"}
                ]]
            }

            data = {
                "chat_id": chat_id,
                "text": "Clique no personagem para enviar mensagem:",
                "reply_markup": json.dumps(keyboard)
            }

            requests.post(url, json=data, timeout=10)

        except Exception as e:
            print(f"[Telegram Listener] Erro ao mostrar botão: {e}")

    def _handle_callback(self, callback: dict):
        """
        Processa clique em botão inline.

        Args:
            callback: Objeto callback_query do Telegram
        """
        callback_id = callback.get("id", "")
        data = callback.get("data", "")
        message = callback.get("message", {})
        chat_id = str(message.get("chat", {}).get("id", ""))

        # Valida chat_id autorizado
        authorized_chat_id = self.bot_settings.get('telegram_chat_id', '')
        if chat_id != authorized_chat_id:
            self._answer_callback(callback_id, "❌ Não autorizado")
            return

        # Formato: "say:CharName"
        if data.startswith("say:"):
            target_char = data[4:]
            current_char = self.get_char_name()

            # Só responde se for o char correto (este bot)
            if target_char.lower() == current_char.lower():
                # Responde ao callback (remove "loading" do botão)
                self._answer_callback(callback_id, f"✅ {current_char} selecionado")

                # Pede a mensagem
                self.send_alert(f"💬 Digite a mensagem para {current_char}:\n(ou /cancel para cancelar)")

                # Entra em modo "aguardando mensagem"
                self._waiting_for_message = True
                self._waiting_chat_id = chat_id
                self._waiting_timeout = time.time()

                print(f"[Telegram Listener] Aguardando mensagem para {current_char}")
            else:
                # Outro bot vai responder a este callback
                pass

    def _answer_callback(self, callback_id: str, text: str = ""):
        """
        Responde ao callback query (obrigatório pelo Telegram).
        Mostra uma notificação breve no topo da tela do usuário.

        Args:
            callback_id: ID do callback query
            text: Texto da notificação (opcional)
        """
        try:
            import requests

            url = f"https://api.telegram.org/bot{self.token}/answerCallbackQuery"
            data = {"callback_query_id": callback_id}
            if text:
                data["text"] = text

            requests.post(url, data=data, timeout=5)

        except Exception as e:
            print(f"[Telegram Listener] Erro ao responder callback: {e}")

    def _tile_to_emoji(self, tile) -> str:
        """
        Converte tile em emoji baseado no item do topo.

        Args:
            tile: MemoryTile object

        Returns:
            Emoji representando o tile
        """
        if tile.count == 0:
            return "❓"  # Tile vazio (estranho)

        top_item_id = tile.get_top_item()

        # ID 99 = Creature/Player (mas já filtramos acima via battlelist)
        # Se chegou aqui com ID 99, é criatura não detectada na battlelist
        if top_item_id == 99:
            return "👹"

        # Usa BLOCKING_IDS do tiles_config.py para detectar paredes/obstáculos
        if top_item_id in BLOCKING_IDS:
            return "⬛"

        # Usa GROUND_SPEEDS do tiles_config.py para detectar terreno walkable
        if top_item_id in GROUND_SPEEDS:
            return "🟩"

        # Qualquer outra coisa = item no chão
        return "📦"

    def _render_map_emoji(self) -> str:
        """
        Renderiza mapa do campo de visão usando emojis (15x15 tiles).

        Emojis:
        👤 = Você (player)
        👹 = Creature (monster)
        👥 = Outro player
        ⬛ = Parede/Objeto sólido
        🟩 = Chão/Terreno walkable
        📦 = Item no chão
        ❓ = Tile não lido/inválido

        Returns:
            String com mapa formatado com emojis
        """
        if not self.game_state or not self.game_state.memory_map:
            return "❌ Mapa não disponível"

        memory_map = self.game_state.memory_map

        # ===== CORREÇÃO: Força calibração do mapa =====
        # O game_state.memory_map não é calibrado automaticamente
        # Precisamos chamar read_full_map(player_id) antes de usar
        player_state = self.game_state.get_player_state()
        player_id = player_state.char_id

        if not memory_map.read_full_map(player_id):
            return "❌ Falha ao calibrar mapa"
        # ================================================

        player_pos = self.game_state.get_player_position()

        # Scan fresh do battlelist para dados em tempo real
        scanner = BattleListScanner(self.pm, self.base_addr)
        all_entities = scanner.scan_all()

        # Separa creatures e players (filtra: mesmo Z + vivos + visíveis)
        creatures = [c for c in all_entities if not c.is_player and c.position.z == player_pos.z and c.is_visible and c.hp_percent > 0]
        players = [c for c in all_entities if c.is_player and c.id != player_id and c.position.z == player_pos.z and c.is_visible]

        # Cria mapa de posições para lookup rápido
        creature_positions = {(c.position.x, c.position.y, c.position.z): c for c in creatures}
        player_positions = {(p.position.x, p.position.y, p.position.z): p for p in players}

        # Range: -7 a +7 (15x15 tiles)
        RANGE = 7
        lines = []

        # Header
        lines.append("```")
        lines.append("📍 Mapa 15x15 (visão do bot)")
        lines.append("")

        # Renderiza grid
        for rel_y in range(-RANGE, RANGE + 1):
            row = ""
            for rel_x in range(-RANGE, RANGE + 1):
                # Centro = você
                if rel_x == 0 and rel_y == 0:
                    row += "👤"
                    continue

                # Calcula posição absoluta
                abs_x = player_pos.x + rel_x
                abs_y = player_pos.y + rel_y
                abs_z = player_pos.z

                # Verifica se tem player nessa posição
                if (abs_x, abs_y, abs_z) in player_positions:
                    row += "👥"
                    continue

                # Verifica se tem creature nessa posição
                if (abs_x, abs_y, abs_z) in creature_positions:
                    row += "👹"
                    continue

                # Lê tile da memória
                tile = memory_map.get_tile_visible(rel_x, rel_y)

                if tile is None:
                    row += "❓"  # Fora do range ou erro
                    continue

                # Determina emoji baseado nos items do tile
                emoji = self._tile_to_emoji(tile)
                row += emoji

            lines.append(row)

        lines.append("```")

        return "\n".join(lines)

    def _count_creatures_from_map(self) -> int:
        """
        Conta tiles com ID 99 (creatures/players) no mapa.
        Usado como fallback quando a battlelist está vazia.

        Returns:
            Número de creatures/players detectados no mapa
        """
        if not self.game_state or not self.game_state.memory_map:
            return 0

        memory_map = self.game_state.memory_map
        count = 0
        RANGE = 7

        for rel_y in range(-RANGE, RANGE + 1):
            for rel_x in range(-RANGE, RANGE + 1):
                if rel_x == 0 and rel_y == 0:
                    continue  # Pula o próprio player

                tile = memory_map.get_tile_visible(rel_x, rel_y)
                if tile and tile.get_top_item() == 99:
                    count += 1

        return count

    def _render_nearby_entities(self) -> str:
        """
        Lista creatures e players próximos, ordenados por distância.

        Returns:
            String formatada com lista de entidades próximas
        """
        if not self.game_state or not self.pm:
            return ""

        # Scan fresh do battlelist para dados em tempo real
        scanner = BattleListScanner(self.pm, self.base_addr)
        all_entities = scanner.scan_all()

        # Obtém player_id e posição para filtros
        player_state = self.game_state.get_player_state()
        player_id = player_state.char_id
        player_pos = self.game_state.get_player_position()

        # Separa creatures e players (filtra: mesmo Z + vivos + visíveis)
        creatures = [c for c in all_entities if not c.is_player and c.position.z == player_pos.z and c.is_visible and c.hp_percent > 0]
        players = [c for c in all_entities if c.is_player and c.id != player_id and c.position.z == player_pos.z and c.is_visible]

        # Fallback: se battlelist vazia, conta tiles com ID 99 do mapa
        if not creatures and not players:
            creature_count = self._count_creatures_from_map()
            if creature_count > 0:
                return f"\n👹 {creature_count} creature(s) detectada(s) no mapa"
            return "\n🟢 Nenhuma creature/player próximo"

        # Calcula distância e ordena
        def calc_distance(entity):
            dx = entity.position.x - player_pos.x
            dy = entity.position.y - player_pos.y
            # Distância euclidiana
            return (dx**2 + dy**2) ** 0.5

        # Combina creatures e players com flag de tipo
        entities = []
        for c in creatures:
            entities.append({
                'name': c.name,
                'type': 'creature',
                'distance': calc_distance(c),
                'hp_percent': c.hp_percent if hasattr(c, 'hp_percent') else None
            })
        for p in players:
            entities.append({
                'name': p.name,
                'type': 'player',
                'distance': calc_distance(p),
                'hp_percent': None
            })

        # Ordena por distância
        entities.sort(key=lambda e: e['distance'])

        # Limita a 10 mais próximos
        entities = entities[:10]

        if not entities:
            return "\n🟢 Nenhuma creature/player próximo"

        # Formata lista
        lines = ["\n👁️ Criaturas/Players próximos:"]
        for e in entities:
            emoji = "👹" if e['type'] == 'creature' else "👥"
            dist = int(e['distance'])

            # Adiciona HP se disponível
            hp_info = ""
            if e['hp_percent'] is not None:
                hp_info = f" ({e['hp_percent']:.0f}% HP)"

            lines.append(f"  {emoji} {e['name']} - {dist} sqm{hp_info}")

        return "\n".join(lines)

    def _send_status(self):
        """Envia status do personagem no Telegram com mapa e lista de entidades."""
        try:
            char_name = self.get_char_name()

            # GameState API: get_player_hp() retorna (hp, hp_max, hp_percent)
            if self.game_state:
                hp_current, hp_max, _ = self.game_state.get_player_hp()
                mana_current, mana_max, _ = self.game_state.get_player_mana()
                pos = self.game_state.get_player_position()

                hp = f"{hp_current}/{hp_max}"
                mana = f"{mana_current}/{mana_max}"
                position = f"{pos.x}, {pos.y}, {pos.z}"
            else:
                hp = mana = position = "?"

            # Monta status básico
            status = f"📊 Status [{char_name}]\n"
            status += f"❤️ HP: {hp}\n"
            status += f"💙 Mana: {mana}\n"
            status += f"📍 Pos: {position}\n"
            status += f"🤖 Bot: {'Ativo' if self.state.is_running else 'Parado'}\n"

            # Adiciona mapa com emojis
            status += "\n"
            status += self._render_map_emoji()

            # Adiciona lista de entidades próximas
            status += self._render_nearby_entities()

            self.send_alert(status)
        except Exception as e:
            self.send_alert(f"❌ Erro ao obter status: {e}")
