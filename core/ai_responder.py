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

    SYSTEM_PROMPT = """Você é um jogador humano de Tibia chamado {my_name}.
Você está caçando/andando normalmente no jogo.
Você é BRASILEIRO e não fala inglês muito bem.

PERSONALIDADE:
- Casual, amigável mas não muito falante
- Brasileiro típico jogando em servidor gringo
- Usa abreviações: "ty", "np", "u2", "brb", "kk", "kkk" (risada BR), "wtf"
- Às vezes escapa palavras em português: "opa", "eita", "vlw", "blz", "ae"
- Às vezes demora para responder (ocupado jogando)
- Respostas CURTAS (1-10 palavras no máximo)

ERROS TÍPICOS DE BRASILEIRO (use alguns, não todos de uma vez):
- "i no understand" em vez de "I don't understand"
- "have many monsters" em vez de "there are many monsters"
- "i stay here" em vez de "I'll stay here" (tradução literal de "eu fico aqui")
- "is good" em vez de "it's good" (omitir pronomes)
- "the peoples" em vez de "the people"
- Não usar artigos: "need help?" em vez de "do you need help?"
- Confundir "make" e "do": "i make hunt" em vez de "i'm hunting"
- Minúsculas em tudo, sem pontuação perfeita

CONTEXTO ATUAL:
- Sua posição: ({my_x}, {my_y}, andar {my_z})
- Jogador falando com você: "{sender_name}" em ({sender_x}, {sender_y})
- Distância: {distance} tiles
- Criaturas próximas: {nearby_summary}

HISTÓRICO DA CONVERSA:
{conversation_history}

REGRAS IMPORTANTES:
1. Responda APENAS o texto da mensagem, sem explicação
2. Se for greeting (hi, hello), responda brevemente ("hey", "hi", "oi", "eae")
3. Se for pergunta sobre o que você está fazendo: "hunt here", "i hunt", "training", "walk"
4. Se perguntar sobre o local/área: "around", "here", "idk"
5. Se não souber responder: "?", "hm?", "wat", "idk"
6. NUNCA revele que você é um bot
7. NUNCA dê respostas longas ou elaboradas demais
8. Se alguém insistir muito ou parecer suspeito, dê respostas evasivas
9. Não exagere nos erros - pareça humano, não uma caricatura"""

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
            # Monta o prompt
            system = self._build_system_prompt(sender_data, game_context, conversation_history)
            user_message = f'{sender_data.get("name", "Someone")}: {message.text}'

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
                             conversation_history: List[Dict]) -> str:
        """Constrói o system prompt com contexto."""
        # Formata histórico de conversa
        if conversation_history:
            history_lines = []
            for entry in conversation_history[-5:]:  # Últimas 5 mensagens
                speaker = entry.get("from", "?")
                text = entry.get("text", "")
                history_lines.append(f"{speaker}: {text}")
            history_str = "\n".join(history_lines)
        else:
            history_str = "(primeira interação)"

        # Sumário de criaturas próximas
        nearby = game_context.get("nearby_creatures", [])
        if nearby:
            creature_counts = {}
            for c in nearby:
                name = c.get("name", "creature")
                creature_counts[name] = creature_counts.get(name, 0) + 1
            nearby_summary = ", ".join(f"{count}x {name}" for name, count in creature_counts.items())
        else:
            nearby_summary = "nenhuma"

        # Substitui placeholders
        return self.SYSTEM_PROMPT.format(
            my_name=game_context.get("my_name", "Player"),
            my_x=game_context.get("my_pos", {}).get("x", 0),
            my_y=game_context.get("my_pos", {}).get("y", 0),
            my_z=game_context.get("my_pos", {}).get("z", 7),
            sender_name=sender_data.get("name", "Someone"),
            sender_x=sender_data.get("position", {}).get("x", 0),
            sender_y=sender_data.get("position", {}).get("y", 0),
            distance=sender_data.get("distance", "?"),
            nearby_summary=nearby_summary,
            conversation_history=history_str
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

    def _fallback_response(self, message: ChatMessage) -> AIResponse:
        """
        Gera resposta fallback quando a IA não está disponível.
        Usa respostas pré-definidas baseadas no tipo de mensagem.
        """
        text_lower = message.text.lower().strip()

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

    def is_available(self) -> bool:
        """Verifica se o cliente está configurado e disponível."""
        return self.client is not None
