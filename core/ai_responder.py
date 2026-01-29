# core/ai_responder.py
"""
Gerador de respostas humanizadas usando OpenAI GPT.
Integra contexto do jogo para respostas naturais.
"""
import os
import random
from dataclasses import dataclass
from typing import List, Dict, Any, Optional

from dotenv import load_dotenv

from core.chat_scanner import ChatMessage
from core.message_analyzer import calculate_response_delay

# Carrega .env
load_dotenv()


@dataclass
class AIResponse:
    """Resposta gerada pela IA."""
    text: str               # Texto da resposta ("hey", "hunting here", etc)
    delay_seconds: float    # Delay humanizado antes de enviar
    should_pause: bool      # Se deve pausar o bot durante conversa
    success: bool           # Se a geração foi bem sucedida
    error: Optional[str]    # Mensagem de erro se falhou


class AIResponder:
    """
    Gera respostas humanizadas usando OpenAI GPT.
    Usa gpt-4o-mini para respostas rápidas e econômicas.
    """

    SYSTEM_PROMPT = """You are {my_name}, a friendly Brazilian player in Tibia.
Respond in English (casual, basic). Keep responses SHORT (1-6 words max).

Language: Only respond in Portuguese if the message is CLEARLY in Portuguese.
When in doubt, use English.

Style: Friendly but brief. Use "kk" not "lol". Words like "opa", "vlw" ok.

{context}

Rules:
1. Output ONLY the message text, nothing else
2. Never admit to being a bot
3. Keep it natural and short"""

    # Prompt especial para Game Masters - respostas cooperativas e diretas
    GM_SYSTEM_PROMPT = """You are {my_name}, a Brazilian player. A GAME MASTER is talking to you.
Be cooperative, clear, and polite. Short responses (3-10 words). English.

{context}

Rules:
1. Output ONLY the message text
2. Never admit to being a bot
3. Be helpful and respectful"""

    def __init__(self, model: str = "gpt-4o-mini"):
        """
        Inicializa o responder.

        Args:
            model: Modelo OpenAI a usar (default: gpt-4o-mini)
        """
        self.model = model
        self.client = None
        self._initialize_client()

    def _initialize_client(self):
        """Inicializa o cliente OpenAI."""
        try:
            from openai import OpenAI
            api_key = os.getenv("OPENAI_API_KEY")
            if api_key:
                self.client = OpenAI(api_key=api_key)
            else:
                print("[AIResponder] OPENAI_API_KEY não encontrada no .env")
        except ImportError:
            print("[AIResponder] Biblioteca 'openai' não instalada. Execute: pip install openai")
        except Exception as e:
            print(f"[AIResponder] Erro ao inicializar cliente: {e}")

    def generate_response(self,
                         message: ChatMessage,
                         sender_data: Dict[str, Any],
                         conversation_history: List[Dict],
                         game_context: Dict[str, Any]) -> AIResponse:
        """
        Gera resposta humanizada para uma mensagem.

        Args:
            message: Mensagem recebida
            sender_data: Dados do jogador que enviou (posição, facing, etc)
            conversation_history: Histórico de conversa com esse jogador
            game_context: Contexto do jogo (posição do bot, criaturas, etc)

        Returns:
            AIResponse com texto e metadados
        """
        # Cliente não inicializado
        if not self.client:
            return self._fallback_response(message)

        try:
            # Monta o prompt (usa prompt especial se for GM)
            system = self._build_system_prompt(
                sender_data, game_context, conversation_history, is_gm=message.is_gm
            )
            user_message = f'{sender_data.get("name", "Someone")}: {message.text}'

            if message.is_gm:
                print(f"[AIResponder] ⚠️ Detectado GM - usando prompt cooperativo")

            # Chama a API
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_message}
                ],
                max_tokens=50,  # Respostas curtas
                temperature=0.9,  # Mais criativo/variado
            )

            # Extrai texto
            text = response.choices[0].message.content.strip()

            # Limpa formatação indesejada
            text = self._clean_response(text)

            # Calcula delay humanizado
            delay = calculate_response_delay()

            return AIResponse(
                text=text,
                delay_seconds=delay,
                should_pause=True,
                success=True,
                error=None
            )

        except Exception as e:
            print(f"[AIResponder] Erro na API: {e}")
            return self._fallback_response(message)

    def _build_system_prompt(self, sender_data: Dict, game_context: Dict,
                             conversation_history: List[Dict], is_gm: bool = False) -> str:
        """Constrói o system prompt com contexto."""
        # Format the context section
        context_str = self._format_context_for_prompt(game_context, conversation_history)

        my_name = game_context.get("my_name", "Player")

        # Use GM prompt or regular prompt
        if is_gm:
            return self.GM_SYSTEM_PROMPT.format(
                my_name=my_name,
                context=context_str
            )

        return self.SYSTEM_PROMPT.format(
            my_name=my_name,
            context=context_str
        )

    def _clean_response(self, text: str) -> str:
        """Limpa e normaliza a resposta da IA."""
        # Remove aspas que a IA pode adicionar
        text = text.strip('"\'')

        # Remove prefixos que a IA pode adicionar
        prefixes_to_remove = ["me:", "you:", "player:", "response:"]
        for prefix in prefixes_to_remove:
            if text.lower().startswith(prefix):
                text = text[len(prefix):].strip()

        # Trunca se muito longo (máx 100 chars para chat do Tibia)
        if len(text) > 100:
            text = text[:97] + "..."

        # Se ficou vazio, usa fallback
        if not text:
            text = "?"

        return text

    def _format_context_for_prompt(self, game_context: Dict, conversation_history: List[Dict]) -> str:
        """Format game context into readable prompt section."""
        lines = []

        # Activity and location
        activity = game_context.get("activity", "walking around")
        floor = game_context.get("floor", "surface")
        lines.append(f"You are: {activity} ({floor})")

        # Health (only if not healthy)
        hp_percent = game_context.get("hp_percent", 100)
        if hp_percent < 90:
            hp_status = game_context.get("hp_status", "healthy")
            lines.append(f"Health: {hp_status} ({hp_percent}%)")

        # Combat
        if game_context.get("in_combat"):
            target = game_context.get("target_name", "creature")
            target_hp = game_context.get("target_hp", 100)
            lines.append(f"Fighting: {target} ({target_hp}% hp)")

        # Map matrix
        map_matrix = game_context.get("map_matrix", "")
        if map_matrix and map_matrix != "unavailable":
            lines.append(f"\nMap (@ = you):\n{map_matrix}")
            creature_legend = game_context.get("creature_legend", "")
            player_legend = game_context.get("player_legend", "")
            if creature_legend:
                lines.append(f"Creatures: {creature_legend}")
            if player_legend:
                lines.append(f"Players: {player_legend}")

        # Conversation history
        if conversation_history:
            history_lines = []
            for entry in conversation_history[-5:]:
                speaker = entry.get("from", "?")
                text = entry.get("text", "")
                history_lines.append(f"{speaker}: {text}")
            if history_lines:
                lines.append(f"\nRecent chat:\n" + "\n".join(history_lines))

        return "\n".join(lines)

    def _is_portuguese(self, text: str) -> bool:
        """
        Detecta se a mensagem está em português.

        Args:
            text: Texto da mensagem

        Returns:
            True se detectar português, False caso contrário
        """
        text_lower = text.lower()

        # Palavras exclusivas/indicadoras do português
        pt_words = {
            "vc", "você", "voce", "ta", "tá", "está", "esta",
            "que", "onde", "qual", "como", "porque", "pq",
            "sim", "não", "nao", "eae", "eai", "oi", "ola", "olá",
            "vlw", "valeu", "blz", "beleza", "cara", "mano",
            "fazendo", "caçando", "cacando", "andando", "treinando",
            "aqui", "la", "lá", "sei", "sou", "eh", "é"
        }

        # Verifica se alguma palavra portuguesa está na mensagem
        words = set(text_lower.split())
        return bool(words & pt_words)  # Interseção não-vazia

    def _fallback_response(self, message: ChatMessage) -> AIResponse:
        """
        Gera resposta fallback quando a IA não está disponível.
        Usa respostas pré-definidas baseadas no tipo de mensagem.
        """
        text_lower = message.text.lower().strip()

        # Fallback especial para GM - respostas cooperativas
        if message.is_gm:
            return self._gm_fallback_response(text_lower)

        # Greetings
        greetings = {"hi", "hello", "hey", "oi", "ola", "yo", "sup", "eae", "eai"}
        if text_lower in greetings:
            response = random.choice(["hey", "hi", "oi", "eae", "yo"])

        # Perguntas comuns
        elif "?" in message.text:
            if "hunt" in text_lower or "doing" in text_lower:
                response = random.choice(["hunt here", "i hunt", "training", "walk"])
            elif "name" in text_lower:
                response = random.choice(["?", "hm?", "wat"])
            elif "level" in text_lower or "lvl" in text_lower:
                response = random.choice(["low kk", "not much", "is ok"])
            elif "br" in text_lower or "brazil" in text_lower:
                response = random.choice(["ye", "sim", "yea"])
            else:
                response = random.choice(["idk", "?", "hm?", "wat"])

        # Despedidas
        elif text_lower in {"bye", "cya", "bb", "tc", "flw", "vlw"}:
            response = random.choice(["cya", "bb", "tc", "flw"])

        # Agradecimentos
        elif text_lower in {"ty", "thx", "thanks", "thank you", "vlw", "valeu"}:
            response = random.choice(["np", "de nada", "blz", "ok"])

        # Risadas
        elif text_lower in {"lol", "haha", "hehe", "kk", "kkk", "kkkk"}:
            response = random.choice(["kk", "kkk", "hehe", ""])

        # Default
        else:
            response = random.choice(["?", "hm?", "ok", "opa", ""])

        # Se resposta vazia, não responde
        if not response:
            return AIResponse(
                text="",
                delay_seconds=0,
                should_pause=False,
                success=True,
                error=None
            )

        return AIResponse(
            text=response,
            delay_seconds=calculate_response_delay(),
            should_pause=True,
            success=True,
            error="fallback (API indisponível)"
        )

    def _gm_fallback_response(self, text_lower: str) -> AIResponse:
        """
        Fallback específico para Game Masters.
        Respostas cooperativas e diretas quando a API não está disponível.
        """
        # Saudações
        if any(g in text_lower for g in ["hi", "hello", "hey"]):
            response = random.choice(["hello", "hi", "hello sir"])

        # Perguntas sobre presença
        elif any(w in text_lower for w in ["there", "afk", "online", "playing"]):
            response = random.choice(["yes im here", "yes, playing", "im here"])

        # Perguntas sobre atividade
        elif any(w in text_lower for w in ["doing", "hunt", "what are you"]):
            response = random.choice(["im hunting here", "just hunting", "training here", "walking around"])

        # Perguntas sobre bot
        elif any(w in text_lower for w in ["bot", "macro", "cheat"]):
            response = random.choice(["no sir, im playing", "no, just hunting", "no im real player"])

        # Pedidos para seguir/mover
        elif any(w in text_lower for w in ["follow", "come", "move"]):
            response = random.choice(["ok", "yes, where?", "ok sir"])

        # Pedidos para falar/responder
        elif any(w in text_lower for w in ["say", "speak", "talk", "answer"]):
            response = random.choice(["hello", "im here", "yes?"])

        # Perguntas sobre tempo
        elif any(w in text_lower for w in ["long", "time", "when"]):
            response = random.choice(["not long", "some time", "i just got here"])

        # Default - cooperativo
        else:
            response = random.choice(["yes?", "ok", "yes sir", "im here"])

        return AIResponse(
            text=response,
            delay_seconds=calculate_response_delay(),
            should_pause=True,
            success=True,
            error="fallback GM (API indisponível)"
        )

    def is_available(self) -> bool:
        """Verifica se o cliente está configurado e disponível."""
        return self.client is not None
