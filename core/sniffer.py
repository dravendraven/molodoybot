# core/sniffer.py
"""
Sniffer de pacotes Tibia 7.72 integrado ao bot.
Captura pacotes do servidor e publica eventos no EventBus.
"""
import struct
import threading
import time
from typing import Optional, Tuple

try:
    from scapy.all import sniff, TCP, IP, Raw, conf
    conf.verb = 0  # Silencia scapy
    SCAPY_AVAILABLE = True
except ImportError:
    SCAPY_AVAILABLE = False

try:
    import pymem
    PYMEM_AVAILABLE = True
except ImportError:
    PYMEM_AVAILABLE = False

from core.event_bus import EventBus, ChatEvent, ContainerEvent, SystemMessageEvent
from core.event_bus import EVENT_CHAT, EVENT_CONTAINER_OPEN, EVENT_CONTAINER_CLOSE, EVENT_SYSTEM_MSG

# Configuração
XTEA_KEY_ADDRESS = 0x719D78  # Endereço absoluto da chave XTEA

# Prefixos de GM para detecção
GM_PREFIXES = ("GM ", "CM ", "GOD ", "[GM]", "[CM]", "ADM ")

# Tipos de fala que indicam GM
GM_SPEAK_TYPES = (0x0C, 0x0D, 0x0E, 0x0F, 0x11)  # Broadcast, Red channels

# Opcodes relevantes
class Opcode:
    CREATURE_SPEAK = 0xAA
    TEXT_MESSAGE = 0xB4
    CONTAINER_OPEN = 0x6E
    CONTAINER_CLOSE = 0x6F


class SpeakType:
    SAY = 0x01
    WHISPER = 0x02
    YELL = 0x03
    PRIVATE_FROM = 0x04
    CHANNEL_Y = 0x07
    BROADCAST = 0x0C
    CHANNEL_R1 = 0x0D  # GM Red channel
    MONSTER_SAY = 0x13
    MONSTER_YELL = 0x14


def xtea_decrypt(data: bytes, key: tuple) -> bytes:
    """Decripta dados usando XTEA."""
    if len(data) % 8 != 0:
        data = data + b'\x00' * (8 - len(data) % 8)

    result = bytearray()
    delta = 0x9E3779B9
    num_rounds = 32

    for i in range(0, len(data), 8):
        v0 = struct.unpack('<I', data[i:i+4])[0]
        v1 = struct.unpack('<I', data[i+4:i+8])[0]
        total = (delta * num_rounds) & 0xFFFFFFFF

        for _ in range(num_rounds):
            v1 = (v1 - (((v0 << 4 ^ v0 >> 5) + v0) ^ (total + key[(total >> 11) & 3]))) & 0xFFFFFFFF
            total = (total - delta) & 0xFFFFFFFF
            v0 = (v0 - (((v1 << 4 ^ v1 >> 5) + v1) ^ (total + key[total & 3]))) & 0xFFFFFFFF

        result.extend(struct.pack('<I', v0))
        result.extend(struct.pack('<I', v1))

    return bytes(result)


class PacketReader:
    """Leitor de pacotes binários."""

    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def remaining(self) -> int:
        return len(self.data) - self.pos

    def read_byte(self) -> int:
        if self.pos >= len(self.data):
            raise IndexError("End of packet")
        val = self.data[self.pos]
        self.pos += 1
        return val

    def read_u16(self) -> int:
        if self.pos + 2 > len(self.data):
            raise IndexError("End of packet")
        val = struct.unpack_from('<H', self.data, self.pos)[0]
        self.pos += 2
        return val

    def read_u32(self) -> int:
        if self.pos + 4 > len(self.data):
            raise IndexError("End of packet")
        val = struct.unpack_from('<I', self.data, self.pos)[0]
        self.pos += 4
        return val

    def read_string(self) -> str:
        length = self.read_u16()
        if self.pos + length > len(self.data):
            raise IndexError("End of packet")
        val = self.data[self.pos:self.pos + length]
        self.pos += length
        try:
            return val.decode('latin-1')
        except:
            return val.decode('utf-8', errors='replace')

    def read_position(self) -> Tuple[int, int, int]:
        x = self.read_u16()
        y = self.read_u16()
        z = self.read_byte()
        return (x, y, z)


class PacketSniffer(threading.Thread):
    """
    Thread que captura pacotes do servidor Tibia e publica eventos.
    """

    def __init__(self, server_ip: str, process_name: str = "Tibia.exe"):
        super().__init__(daemon=True)
        self.server_ip = server_ip
        self.process_name = process_name
        self.event_bus = EventBus.get_instance()

        self.running = False
        self.connected = False
        self.xtea_key: Optional[tuple] = None
        self.pm = None

        self._stats = {"packets": 0, "chat": 0, "containers": 0, "system_msg": 0}

    def _connect_tibia(self) -> bool:
        """Conecta ao processo Tibia para ler XTEA key."""
        if not PYMEM_AVAILABLE:
            print("[Sniffer] pymem não disponível")
            return False

        try:
            self.pm = pymem.Pymem(self.process_name)
            return True
        except Exception as e:
            print(f"[Sniffer] Falha ao conectar ao {self.process_name}: {e}")
            return False

    def _read_xtea_key(self) -> Optional[tuple]:
        """Lê a chave XTEA da memória do Tibia."""
        if not self.pm:
            return None

        try:
            key_addr = XTEA_KEY_ADDRESS
            k0 = self.pm.read_uint(key_addr)
            k1 = self.pm.read_uint(key_addr + 4)
            k2 = self.pm.read_uint(key_addr + 8)
            k3 = self.pm.read_uint(key_addr + 12)
            return (k0, k1, k2, k3)
        except Exception as e:
            return None

    def _decrypt_packet(self, data: bytes) -> bytes:
        """Decripta pacote XTEA."""
        if not self.xtea_key or len(data) < 2:
            return data

        try:
            encrypted = data[2:]
            if len(encrypted) < 8:
                return data
            decrypted = xtea_decrypt(encrypted, self.xtea_key)
            return data[:2] + decrypted
        except:
            return data

    def _parse_creature_speak(self, data: bytes) -> Optional[ChatEvent]:
        """Parseia pacote de fala e retorna ChatEvent."""
        try:
            reader = PacketReader(data)

            # Statement ID (4 bytes)
            statement_id = reader.read_u32()

            # Nome do speaker
            speaker = reader.read_string()

            # Tipo de fala
            speak_type = reader.read_byte()

            position = None
            channel_id = None

            # Position ou Channel dependendo do tipo
            if speak_type in (SpeakType.SAY, SpeakType.WHISPER, SpeakType.YELL,
                             SpeakType.MONSTER_SAY, SpeakType.MONSTER_YELL):
                position = reader.read_position()

            elif speak_type in (SpeakType.CHANNEL_Y, SpeakType.CHANNEL_R1):
                channel_id = reader.read_u16()

            # Mensagem
            message = reader.read_string()

            # Verifica se é GM
            is_gm = (
                any(speaker.upper().startswith(prefix.upper()) for prefix in GM_PREFIXES) or
                speak_type in GM_SPEAK_TYPES
            )

            return ChatEvent(
                speaker=speaker,
                message=message,
                speak_type=speak_type,
                is_gm=is_gm,
                position=position,
                channel_id=channel_id
            )

        except Exception:
            return None

    def _parse_container_open(self, data: bytes) -> Optional[ContainerEvent]:
        """Parseia abertura de container."""
        try:
            reader = PacketReader(data)
            container_id = reader.read_byte()
            item_id = reader.read_u16()
            name = reader.read_string()
            capacity = reader.read_byte()
            has_parent = reader.read_byte()
            item_count = reader.read_byte()

            return ContainerEvent(
                event_type="open",
                container_id=container_id,
                name=name,
                item_count=item_count
            )

        except Exception:
            return None

    def _parse_container_close(self, data: bytes) -> Optional[ContainerEvent]:
        """Parseia fechamento de container."""
        try:
            reader = PacketReader(data)
            container_id = reader.read_byte()

            return ContainerEvent(
                event_type="close",
                container_id=container_id,
                name="",
                item_count=0
            )

        except Exception:
            return None

    def _parse_text_message(self, data: bytes) -> Optional[SystemMessageEvent]:
        """Parseia mensagem de sistema (TEXT_MESSAGE 0xB4)."""
        try:
            reader = PacketReader(data)
            msg_type = reader.read_byte()
            message = reader.read_string()

            return SystemMessageEvent(
                msg_type=msg_type,
                message=message
            )

        except Exception:
            return None

    def _process_packet(self, data: bytes, direction: str):
        """Processa um pacote decriptado."""
        if direction == "C->S":
            return  # Ignora pacotes do cliente

        # Decripta
        decrypted = self._decrypt_packet(data)

        if len(decrypted) < 5:
            return

        # Estrutura: [len 2][inner_len 2][payload...]
        payload = decrypted[2:]

        if len(payload) < 3:
            return

        packet_data = payload[2:]  # Dados após inner_len

        if len(packet_data) < 1:
            return

        opcode = packet_data[0]
        opcode_payload = packet_data[1:]

        self._stats["packets"] += 1

        # Parse baseado no opcode
        if opcode == Opcode.CREATURE_SPEAK:
            event = self._parse_creature_speak(opcode_payload)
            if event:
                self._stats["chat"] += 1
                self.event_bus.publish(EVENT_CHAT, event)

        elif opcode == Opcode.CONTAINER_OPEN:
            event = self._parse_container_open(opcode_payload)
            if event:
                self._stats["containers"] += 1
                self.event_bus.publish(EVENT_CONTAINER_OPEN, event)

        elif opcode == Opcode.CONTAINER_CLOSE:
            event = self._parse_container_close(opcode_payload)
            if event:
                self._stats["containers"] += 1
                self.event_bus.publish(EVENT_CONTAINER_CLOSE, event)

        elif opcode == Opcode.TEXT_MESSAGE:
            event = self._parse_text_message(opcode_payload)
            if event:
                self._stats["system_msg"] += 1
                self.event_bus.publish(EVENT_SYSTEM_MSG, event)

    def _on_packet(self, pkt):
        """Callback para cada pacote capturado."""
        if not pkt.haslayer(TCP) or not pkt.haslayer(Raw):
            return

        ip = pkt[IP]
        tcp = pkt[TCP]
        data = bytes(pkt[Raw].load)

        # Direção
        if ip.src == self.server_ip:
            direction = "S->C"
            port = tcp.sport
        elif ip.dst == self.server_ip:
            direction = "C->S"
            port = tcp.dport
        else:
            return

        # Só processa game server (7172) e login (7171)
        if port not in (7171, 7172):
            return

        self._process_packet(data, direction)

    def run(self):
        """Thread principal do sniffer."""
        if not SCAPY_AVAILABLE:
            print("[Sniffer] Scapy não disponível - sniffer desativado")
            return

        print(f"[Sniffer] Iniciando...")

        # Conecta ao Tibia
        if not self._connect_tibia():
            print("[Sniffer] Falha ao conectar ao Tibia - sniffer desativado")
            return

        # Aguarda login (XTEA key válida)
        print("[Sniffer] Aguardando XTEA key (faça login no jogo)...")
        while self.running:
            self.xtea_key = self._read_xtea_key()
            if self.xtea_key and self.xtea_key[0] != 0:
                break
            time.sleep(1)

        if not self.running:
            return

        print(f"[Sniffer] XTEA key obtida - iniciando captura")
        print(f"[Sniffer] Servidor: {self.server_ip}")
        self.connected = True

        # Inicia captura
        try:
            sniff(
                filter=f"host {self.server_ip}",
                prn=self._on_packet,
                store=False,
                stop_filter=lambda x: not self.running
            )
        except Exception as e:
            print(f"[Sniffer] Erro na captura: {e}")

        self.connected = False
        print("[Sniffer] Parado")

    def start(self):
        """Inicia a thread do sniffer."""
        self.running = True
        super().start()

    def stop(self):
        """Para o sniffer."""
        self.running = False

    def get_stats(self) -> dict:
        """Retorna estatísticas do sniffer."""
        return {
            "running": self.running,
            "connected": self.connected,
            "packets": self._stats["packets"],
            "chat_events": self._stats["chat"],
            "container_events": self._stats["containers"],
            "system_msg_events": self._stats["system_msg"]
        }

    def is_connected(self) -> bool:
        """Retorna True se o sniffer está conectado e capturando."""
        return self.connected


# Instância global do sniffer (opcional)
_sniffer_instance: Optional[PacketSniffer] = None


def get_sniffer() -> Optional[PacketSniffer]:
    """Retorna a instância global do sniffer."""
    return _sniffer_instance


def start_sniffer(server_ip: str, process_name: str = "Tibia.exe") -> Optional[PacketSniffer]:
    """
    Inicia o sniffer global.

    Args:
        server_ip: IP do servidor Tibia
        process_name: Nome do processo (padrão: Tibia.exe)

    Returns:
        Instância do sniffer ou None se falhar
    """
    global _sniffer_instance

    if _sniffer_instance and _sniffer_instance.running:
        print("[Sniffer] Já está rodando")
        return _sniffer_instance

    _sniffer_instance = PacketSniffer(server_ip, process_name)
    _sniffer_instance.start()
    return _sniffer_instance


def stop_sniffer():
    """Para o sniffer global."""
    global _sniffer_instance

    if _sniffer_instance:
        _sniffer_instance.stop()
        _sniffer_instance = None
