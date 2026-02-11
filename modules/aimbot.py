# modules/aimbot.py
"""
Aimbot Module - Uso de runas via hotkey.

Quando a hotkey e pressionada, usa a runa configurada no alvo atual.
Funciona como "instant SD" - pressiona F5 e a runa e disparada.

Configuracoes (config.py):
    AIMBOT_ENABLED: bool - Ativa/desativa modulo
    AIMBOT_HOTKEY: str - Tecla para disparar ("F5", "MOUSE4", etc)
    AIMBOT_RUNE_TYPE: str - Tipo de runa ("SD", "HMM", "GFB", "EXPLO")
"""

import time
import threading
import ctypes
from core.packet import PacketManager, get_container_pos
from core.inventory_core import find_item_in_containers
from core.player_core import get_target_id
from core.bot_state import state
from database.attack_runes import ATTACK_RUNES, VK_CODES, get_rune_info, get_vk_code

# Win32 API para detectar teclas globais
user32 = ctypes.windll.user32


class AimbotModule:
    """
    Aimbot ativado por hotkey.

    Escuta uma hotkey global (ex: F5) e quando pressionada,
    usa a runa configurada no alvo que estamos atacando.

    Uso:
        aimbot = AimbotModule(pm, base_addr, config_getter, log_callback)
        aimbot.start()
        # ... bot rodando ...
        aimbot.stop()
    """

    def __init__(self, pm, base_addr, config_getter, log_callback):
        """
        Args:
            pm: Instancia do Pymem
            base_addr: Endereco base do processo Tibia
            config_getter: Funcao que retorna valor de config (ex: get_cfg("key", default))
            log_callback: Funcao para logar mensagens
        """
        self.pm = pm
        self.base_addr = base_addr
        self.get_cfg = config_getter
        self.log = log_callback
        self.packet = PacketManager(pm, base_addr)

        # Estado interno
        self.running = False
        self.thread = None
        self.last_shot_time = 0
        self.key_was_pressed = False  # Evita repeticao ao segurar tecla

    def start(self):
        """Inicia o listener de hotkey em thread separada."""
        if self.running:
            return

        self.running = True
        self.thread = threading.Thread(target=self._hotkey_loop, daemon=True)
        self.thread.start()

        hotkey = self.get_cfg("AIMBOT_HOTKEY", "F5")
        rune = self.get_cfg("AIMBOT_RUNE_TYPE", "SD")
        self.log(f"[AIMBOT] Iniciado - {hotkey} para usar {rune}")

    def stop(self):
        """Para o listener de hotkey."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=1.0)
        self.log("[AIMBOT] Parado")

    def _hotkey_loop(self):
        """Loop principal - detecta hotkey e dispara runa."""
        while self.running:
            try:
                # Se modulo desativado, espera mais
                if not self._is_enabled():
                    time.sleep(0.1)
                    continue

                # Detecta hotkey
                if self._is_hotkey_pressed():
                    if not self.key_was_pressed:  # Primeira vez pressionada
                        self.key_was_pressed = True
                        self._try_shoot_rune()
                else:
                    self.key_was_pressed = False  # Soltou a tecla

                time.sleep(0.01)  # 10ms polling (responsivo)

            except Exception as e:
                self.log(f"[AIMBOT] Erro: {e}")
                time.sleep(0.5)

    def _is_enabled(self) -> bool:
        """Verifica se aimbot esta habilitado na config."""
        return self.get_cfg("AIMBOT_ENABLED", False)

    def _is_hotkey_pressed(self) -> bool:
        """Detecta se a hotkey configurada esta pressionada."""
        hotkey_name = self.get_cfg("AIMBOT_HOTKEY", "F5")
        vk_code = get_vk_code(hotkey_name)

        # GetAsyncKeyState retorna valor com bit 15 setado se tecla esta pressionada
        return user32.GetAsyncKeyState(vk_code) & 0x8000 != 0

    def _try_shoot_rune(self):
        """Tenta usar runa no alvo atual."""

        # 1. Verifica seguranca (GM detectado, etc)
        if not state.is_safe():
            self.log("[AIMBOT] Unsafe! Ignorando...")
            return

        # 2. Obtem info da runa configurada
        rune_type = self.get_cfg("AIMBOT_RUNE_TYPE", "SD")
        rune_info = get_rune_info(rune_type)

        if not rune_info:
            self.log(f"[AIMBOT] Runa desconhecida: {rune_type}")
            return

        # 3. Verifica cooldown (exhaust)
        cooldown = rune_info.get("cooldown", 2.0)
        elapsed = time.time() - self.last_shot_time

        if elapsed < cooldown:
            remaining = cooldown - elapsed
            self.log(f"[AIMBOT] Exhaust! Aguarde {remaining:.1f}s")
            return

        # 4. Le target atual (do trainer)
        target_id = get_target_id(self.pm, self.base_addr)

        if target_id == 0:
            self.log("[AIMBOT] Sem alvo!")
            return

        # 5. Encontra runa no inventario
        rune_id = rune_info["id"]
        rune_location = find_item_in_containers(self.pm, self.base_addr, rune_id)

        if not rune_location:
            self.log(f"[AIMBOT] Sem {rune_type} na BP!")
            return

        # 6. Monta posicao da runa no container
        rune_pos = get_container_pos(
            rune_location["container_index"],
            rune_location["slot_index"]
        )

        # 7. Envia pacote use_on_creature
        self.packet.use_on_creature(
            from_pos=rune_pos,
            item_id=rune_id,
            stack_pos=0,
            creature_id=target_id
        )

        # 8. Atualiza cooldown
        self.last_shot_time = time.time()
        self.log(f"[AIMBOT] {rune_type} disparado!")


# Funcao auxiliar para uso standalone (sem GUI)
def aimbot_loop(pm, base_addr, config_getter, log_callback, stop_event=None):
    """
    Loop standalone do aimbot.

    Pode ser usado em threading.Thread diretamente.

    Args:
        pm: Instancia Pymem
        base_addr: Endereco base
        config_getter: Funcao de config
        log_callback: Funcao de log
        stop_event: threading.Event opcional para parar o loop
    """
    aimbot = AimbotModule(pm, base_addr, config_getter, log_callback)

    # Roda ate stop_event ser setado (ou forever se None)
    while stop_event is None or not stop_event.is_set():
        try:
            if not aimbot._is_enabled():
                time.sleep(0.1)
                continue

            if aimbot._is_hotkey_pressed():
                if not aimbot.key_was_pressed:
                    aimbot.key_was_pressed = True
                    aimbot._try_shoot_rune()
            else:
                aimbot.key_was_pressed = False

            time.sleep(0.01)

        except Exception as e:
            log_callback(f"[AIMBOT] Erro: {e}")
            time.sleep(0.5)
