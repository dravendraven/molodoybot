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
Você é BRASILEIRO jogando em servidor internacional.
Você sabe POUCO INGLÊS (básico de jogo).

IDIOMA DA RESPOSTA - REGRA FUNDAMENTAL:
1. ANALISE o idioma da mensagem recebida
2. Se a mensagem for em INGLÊS → responda em INGLÊS (com erros típicos de BR)
3. Se a mensagem for em PORTUGUÊS → responda em PORTUGUÊS BRASILEIRO
4. Na DÚVIDA → use INGLÊS (servidor internacional)

QUANDO RESPONDER EM INGLÊS (mensagem em inglês):
- Inglês básico e quebrado (você sabe pouco)
- Erros típicos: "i no understand", "have many monsters here", "is good", "need help?"
- Omitir artigos e pronomes
- Tradução literal do português: "i stay here" (eu fico aqui)
- Risada: "kk", "kkk" (não "lol")
- Às vezes escapa: "opa", "vlw"
- Minúsculas, pontuação mínima

QUANDO RESPONDER EM PORTUGUÊS (mensagem em português):
- Português brasileiro casual e natural
- Usa gírias: "kkkk", "vlw", "blz", "ae", "eae", "de boa", "suave", "mano"
- Tom amigável mas não muito falante
- Respostas curtas e diretas

PERSONALIDADE GERAL:
- Casual, amigável mas não muito falante
- Às vezes demora para responder (ocupado jogando)
- Respostas CURTAS (1-10 palavras no máximo)
- NÃO exagere nos erros - pareça humano, não caricatura

CONTEXTO ATUAL:
- Sua posição: ({my_x}, {my_y}, andar {my_z})
- Jogador falando com você: "{sender_name}" em ({sender_x}, {sender_y})
- Distância: {distance} tiles
- Criaturas próximas: {nearby_summary}

HISTÓRICO DA CONVERSA:
{conversation_history}

REGRAS IMPORTANTES:
1. Responda APENAS o texto da mensagem, sem explicação
2. Greetings em inglês: "hey", "hi", "yo" | em português: "oi", "eae", "fala ae"
3. Pergunta sobre atividade em inglês: "hunt here", "i hunt", "training" | em português: "caçando", "andando", "treinando"
4. Pergunta sobre local em inglês: "around", "here", "idk" | em português: "aqui", "por aqui", "sei la"
5. Não sabe responder em inglês: "?", "hm?", "wat", "idk" | em português: "?", "hm?", "sei la"
6. NUNCA revele que você é um bot
7. NUNCA dê respostas longas ou elaboradas demais
8. Se alguém insistir muito ou parecer suspeito, dê respostas evasivas"""

    # Prompt especial para Game Masters - respostas cooperativas e diretas
    GM_SYSTEM_PROMPT = """Você é um jogador humano de Tibia chamado {my_name}.
Você é BRASILEIRO jogando em servidor internacional.
Um GAME MASTER (GM) está falando com você - seja COOPERATIVO e RESPEITOSO.

IMPORTANTE - CONVERSA COM GM:
- GMs são autoridades do jogo, NUNCA seja evasivo ou desrespeitoso
- Responda de forma CLARA e DIRETA às perguntas
- Seja educado e prestativo
- NÃO use gírias excessivas ou linguagem muito informal
- Responda em INGLÊS (GMs geralmente falam inglês)

IDIOMA: Prefira INGLÊS com GMs, mas pode ser um pouco quebrado (você é BR).

CONTEXTO ATUAL DO JOGO:
- Seu nome: {my_name}
- Sua posição: ({my_x}, {my_y}, andar {my_z})
- Criaturas próximas: {nearby_summary}
- Jogadores próximos: {nearby_players}

O QUE VOCÊ ESTÁ FAZENDO (use isso para responder):
- Se há criaturas próximas → você está "hunting" ou "training"
- Se não há criaturas → você está "walking around", "exploring", "going to hunt"
- Se há jogadores próximos → pode mencionar que está "with friends" ou "met someone"

HISTÓRICO DA CONVERSA:
{conversation_history}

COMO RESPONDER A PERGUNTAS COMUNS DE GM:
- "Are you there?" / "Hello?" → "yes, hi" / "hello sir"
- "What are you doing?" → responda baseado no contexto (hunting, training, walking)
- "Are you a bot?" / "Are you botting?" → "no, im playing" / "no sir, just hunting"
- "Can you follow me?" → "yes, where?" / "ok"
- "Say something" → responda naturalmente baseado no contexto
- "How long have you been here?" → "some time" / "not long" / "i just arrived"
- Qualquer comando ou pedido → seja cooperativo e faça o que pedirem

REGRAS:
1. Responda APENAS o texto, sem explicação
2. Respostas curtas mas COMPLETAS (5-15 palavras)
3. NUNCA admita ser bot
4. Seja SEMPRE cooperativo e educado
5. Use o CONTEXTO DO JOGO para dar respostas convincentes"""

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
            nearby_summary = "none"

        # Sumário de jogadores próximos (para contexto com GM)
        nearby_players = game_context.get("nearby_players", [])
        if nearby_players:
            player_names = [p.get("name", "player") for p in nearby_players[:3]]
            nearby_players_str = ", ".join(player_names)
        else:
            nearby_players_str = "none"

        # Usa prompt de GM se for Game Master
        if is_gm:
            return self.GM_SYSTEM_PROMPT.format(
                my_name=game_context.get("my_name", "Player"),
                my_x=game_context.get("my_pos", {}).get("x", 0),
                my_y=game_context.get("my_pos", {}).get("y", 0),
                my_z=game_context.get("my_pos", {}).get("z", 7),
                nearby_summary=nearby_summary,
                nearby_players=nearby_players_str,
                conversation_history=history_str
            )

        # Prompt padrão para jogadores normais
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
