# -*- coding: utf-8 -*-
"""
Serviço central de Inteligência Artificial para o ComentsIA.
Fornece limpeza e parsing de tradução de avaliações, detecção inteligente de idioma,
instruções hiper-realistas de tom de voz e suporte avançado a múltiplos idiomas.
"""

import re
import logging
from typing import Optional, Dict, Tuple, Any


def detect_text_language(text: Optional[str]) -> str:
    """
    Identifica de forma rápida e precisa o idioma principal do texto (pt, en, es, fr, de, it).
    """
    if not text:
        return "pt"
    
    t = str(text).lower()
    words = re.findall(r'\b[a-záàâãéèêíïóôõöúçñäüß]+\b', t)
    if not words:
        return "pt"
        
    word_set = set(words)
    
    # Stop-words características de cada idioma
    pt_words = {
        "o", "a", "os", "as", "um", "uma", "de", "do", "da", "dos", "das", "em", "no", "na",
        "nos", "nas", "para", "por", "com", "não", "muito", "bom", "boa", "quartos", "hotel",
        "atendimento", "ótimo", "excelente", "café", "foi", "estava", "serviço", "lugar",
        "equipe", "recomendo", "obrigado", "obrigada", "tudo", "mais", "suco", "pouca", "fruta"
    }
    en_words = {
        "the", "a", "an", "of", "to", "in", "for", "with", "on", "at", "from", "by", "not",
        "very", "good", "great", "hotel", "room", "rooms", "clean", "staff", "service",
        "breakfast", "was", "is", "were", "are", "we", "they", "it", "nice", "place",
        "stay", "recommend", "thanks", "thank", "just", "water", "fruit", "juice", "reminiscent"
    }
    es_words = {
        "el", "la", "los", "las", "un", "una", "de", "del", "en", "para", "por", "con", "no",
        "muy", "bueno", "buena", "hotel", "habitacion", "habitaciones", "limpio", "personal",
        "servicio", "desayuno", "estaba", "fue", "lugar", "recomiendo", "gracias", "todo"
    }
    fr_words = {
        "le", "la", "les", "un", "une", "de", "du", "des", "en", "pour", "par", "avec", "pas",
        "très", "bon", "bonne", "hôtel", "chambre", "chambres", "propre", "personnel",
        "service", "était", "merci", "séjour"
    }
    de_words = {
        "der", "die", "das", "ein", "eine", "von", "in", "für", "mit", "nicht", "sehr", "gut",
        "gute", "hotel", "zimmer", "sauber", "personal", "service", "frühstück", "war", "danke"
    }
    it_words = {
        "il", "lo", "la", "i", "gli", "le", "un", "uno", "una", "di", "del", "della", "in",
        "per", "con", "non", "molto", "buono", "buona", "albergo", "hotel", "camera", "camere",
        "pulito", "personale", "servizio", "colazione", "era", "grazie"
    }
    
    scores = {
        "pt": len(word_set.intersection(pt_words)),
        "en": len(word_set.intersection(en_words)),
        "es": len(word_set.intersection(es_words)),
        "fr": len(word_set.intersection(fr_words)),
        "de": len(word_set.intersection(de_words)),
        "it": len(word_set.intersection(it_words)),
    }
    
    # Marcadores ortográficos exclusivos
    if any(c in t for c in ["ã", "õ"]):
        scores["pt"] += 3
    if "ñ" in t:
        scores["es"] += 3
    if any(c in t for c in ["œ", "è", "ù"]):
        scores["fr"] += 2
    if any(c in t for c in ["ä", "ö", "ü", "ß"]):
        scores["de"] += 3
        
    best_lang = max(scores, key=scores.get)
    if scores[best_lang] == 0:
        return "pt"
    return best_lang


def parse_review_text(raw_text: Optional[str]) -> Dict[str, Any]:
    """
    Separa a avaliação bruta em texto original e tradução (se fornecida pelo Google).
    Retorna um dicionário:
    {
        "original": "...",
        "translated": "..." ou None,
        "orig_lang": "pt|en|es|fr|de|it",
        "trans_lang": "pt|en|es|fr|de|it" ou None
    }
    """
    if not raw_text:
        return {"original": "", "translated": None, "orig_lang": "pt", "trans_lang": None}
    
    text = str(raw_text).strip()
    
    # 1. Caso B: (Translated by Google / Traduzido pelo Google) <trans> (Original) <orig>
    m_b = re.search(
        r'^\s*\((?:Traduzido pelo Google|Translated by Google|Traduit par Google|Traducido por Google|Von Google übersetzt|Tradotto da Google)[^\)]*\)\s*(.*?)\s*\((?:Original|original)\)\s*(.*)$',
        text,
        re.IGNORECASE | re.DOTALL
    )
    if m_b:
        trans_part = m_b.group(1).strip()
        orig_part = m_b.group(2).strip()
        if orig_part:
            orig_lang = detect_text_language(orig_part)
            trans_lang = detect_text_language(trans_part) if trans_part else None
            return {
                "original": orig_part,
                "translated": trans_part if trans_part else None,
                "orig_lang": orig_lang,
                "trans_lang": trans_lang
            }

    # 2. Caso A: <orig> (Translated by Google / Traduzido pelo Google) <trans>
    m_a = re.search(
        r'^(.*?)\s*\((?:Traduzido pelo Google|Translated by Google|Traduit par Google|Traducido por Google|Von Google übersetzt|Tradotto da Google)[^\)]*\)\s*(.*)$',
        text,
        re.IGNORECASE | re.DOTALL
    )
    if m_a:
        orig_part = m_a.group(1).strip()
        trans_part = m_a.group(2).strip()
        trans_part = re.sub(r'\s*\((?:Original|original)\)\s*$', '', trans_part, flags=re.IGNORECASE).strip()
        
        if orig_part and trans_part:
            orig_lang = detect_text_language(orig_part)
            trans_lang = detect_text_language(trans_part)
            return {
                "original": orig_part,
                "translated": trans_part,
                "orig_lang": orig_lang,
                "trans_lang": trans_lang
            }
        elif orig_part:
            return {
                "original": orig_part,
                "translated": None,
                "orig_lang": detect_text_language(orig_part),
                "trans_lang": None
            }
        elif trans_part:
            return {
                "original": trans_part,
                "translated": None,
                "orig_lang": detect_text_language(trans_part),
                "trans_lang": None
            }

    # 3. Caso C: (Original) <orig>
    m_c = re.search(r'^\s*\(Original\)\s*(.*)$', text, re.IGNORECASE | re.DOTALL)
    if m_c:
        orig_part = m_c.group(1).strip()
        return {
            "original": orig_part,
            "translated": None,
            "orig_lang": detect_text_language(orig_part),
            "trans_lang": None
        }

    # 4. Caso D: Texto comum sem marcador de tradução
    return {
        "original": text,
        "translated": None,
        "orig_lang": detect_text_language(text),
        "trans_lang": None
    }


def limpar_texto_review(text: Optional[str], target_lang: str = "pt") -> str:
    """
    Retorna o texto ideal e limpo para exibição.
    Se a avaliação foi escrita no mesmo idioma do usuário, retorna apenas o original limpo.
    Se a avaliação foi escrita em idioma diferente e há tradução disponível para o idioma alvo,
    retorna a tradução limpa.
    """
    parsed = parse_review_text(text)
    orig = parsed["original"]
    trans = parsed["translated"]
    orig_lang = parsed["orig_lang"]
    trans_lang = parsed["trans_lang"]

    if not trans:
        return orig

    # Se o texto original já é no idioma alvo do usuário, exibe o original sem a tradução duplicada
    if orig_lang == target_lang:
        return orig

    # Se o texto original é em outro idioma e a tradução bate com o idioma do usuário, usa a tradução
    if trans and trans_lang == target_lang:
        return trans

    return orig


def get_tone_instructions(tone: Optional[str]) -> str:
    """
    Retorna diretrizes profundas, distintas e hiper-realistas para cada tom de voz,
    evitando que as respostas fiquem genéricas ou pareçam todas iguais.
    """
    t = (tone or "profissional").strip().lower()
    
    if t in ["amigavel", "descontraido", "amigável", "descontraído"]:
        return (
            "DIRETRIZ DE TOM - AMIGÁVEL, DESCONTRAÍDO & JOVIAL:\n"
            "- Adote uma linguagem leve, dinâmica, calorosa e espontânea, como uma conversa humana e alegre com um cliente querido.\n"
            "- Demonstre entusiasmo genuíno ('Ficamos super felizes com seu carinho!', 'Que alegria receber você por aqui!', 'Adoramos saber disso!').\n"
            "- Use de 1 a 3 emojis simpáticos e naturais (ex: 😊, ✨, 👏, 💛) no meio ou final das frases.\n"
            "- É PROIBIDO soar robótico, frio ou usar clichês engessados como 'Prezado', 'Agradecemos a preferência' ou 'Permanecemos ao dispor'."
        )
    elif t in ["empatico", "compreensivo", "empático"]:
        return (
            "DIRETRIZ DE TOM - PROFUNDAMENTE EMPÁTICO, HUMANIZADO & AFETIVO:\n"
            "- Foque em escuta ativa, validação emocional e acolhimento humano.\n"
            "- Se a avaliação for POSITIVA (4 ou 5 estrelas): Expresse gratidão sincera e afetuosa ('O seu relato encheu nossa equipe de alegria e carinho').\n"
            "- Se a avaliação for CRÍTICA ou NEGATIVA (1 a 3 estrelas): NUNCA justifique, não dê desculpas técnicas e não transfira culpas. Valide imediatamente a frustração do cliente ('Sentimos muito que sua experiência não tenha sido impecável como você merece'), demonstre humildade e convide com respeito para um diálogo acolhedor."
        )
    elif t in ["direto", "objetivo", "curto"]:
        return (
            "DIRETRIZ DE TOM - CURTO, DIRETO & OBJETIVO:\n"
            "- Escreva uma resposta ultra sucinta de exatamente 2 a 3 frases precisas e ágeis.\n"
            "- Agradeça de forma pontual, responda diretamente ao ponto citado pelo cliente e encerre com agilidade, sem rodeios nem enrolação."
        )
    elif t in ["luxo", "sofisticado", "premium", "elegante"]:
        return (
            "DIRETRIZ DE TOM - LUXO, ELEGANTE & EXCLUSIVO:\n"
            "- Trate o cliente com máxima distinção, requinte e sofisticação ('É uma honra recebê-lo', 'Nosso compromisso inegociável é entregar uma experiência sublime em cada detalhe').\n"
            "- Utilize vocabulário refinado, nobre e polido, perfeito para estabelecimentos de alto padrão."
        )
    else:  # Padrão: profissional / formal
        return (
            "DIRETRIZ DE TOM - PROFISSIONAL & CORPORATIVO:\n"
            "- Adote linguagem formal, polida, culta e institucional.\n"
            "- Transmita competência, solidez, respeito e alta governança corporativa.\n"
            "- É PROIBIDO usar gírias, intimidades ou emojis infantis. Agradeça de maneira elegante e assegure o compromisso com a qualidade."
        )


def get_language_instructions(idioma: Optional[str]) -> Tuple[str, str]:
    """
    Retorna uma tupla (system_role_instruction, prompt_rule_instruction)
    para garantir 100% de aderência ao idioma especificado ou detecção inteligente.
    """
    idioma_clean = (idioma or "auto").strip()
    
    if idioma_clean.lower() in ["auto", "detectar", "detectar automaticamente", "detectar automaticamente (mesmo idioma do cliente)"]:
        system_inst = (
            "Você é um especialista em atendimento ao cliente poliglota de nível nativo. "
            "INSTRUÇÃO DE IDIOMA: Identifique com precisão o idioma em que a avaliação do cliente foi escrita e "
            "RESPONDA 100% NO MESMO IDIOMA NATIVO DO CLIENTE (seja Português, Inglês, Espanhol, Francês, Alemão, Italiano, etc.) "
            "com vocabulário natural e fluência perfeita. NUNCA misture idiomas."
        )
        prompt_rule = (
            "1. IDIOMA INTELIGENTE (DETECÇÃO AUTOMÁTICA): Identifique a língua da avaliação do cliente. "
            "Sua resposta DEVE ser escrita 100% no MESMO IDIOMA do cliente. É proibido traduzir para o português se o cliente escreveu em outra língua."
        )
    else:
        system_inst = (
            f"Você é um especialista em atendimento ao cliente NATIVO e FLUENTE em {idioma_clean.upper()}. "
            f"O seu texto de saída DEVE SER 100% ESCRITO EM {idioma_clean.upper()}."
        )
        prompt_rule = (
            f"1. IDIOMA OBRIGATÓRIO: A sua resposta DEVE ser escrita 100% em {idioma_clean.upper()}. "
            f"Adapte vocabulário, gramática e expressões para a região nativa deste idioma. É estritamente proibido usar outro idioma."
        )
        
    return system_inst, prompt_rule


def generate_claude_response(
    prompt: str,
    system_prompt: Optional[str] = None,
    model: str = "claude-3-5-haiku-20241022",
    max_tokens: int = 500,
    api_key: Optional[str] = None
) -> Optional[str]:
    """
    Gera respostas ou análises utilizando a API do Claude (Anthropic).
    Suporta modelos como claude-3-7-sonnet-20250219, claude-3-5-sonnet-20241022, claude-3-5-haiku-20241022.
    """
    import os
    key = api_key or os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not key:
        logging.warning("[Claude AI] ANTHROPIC_API_KEY não configurada.")
        return None

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=key)
        kwargs = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}]
        }
        if system_prompt:
            kwargs["system"] = system_prompt

        response = client.messages.create(**kwargs)
        if response and response.content:
            return response.content[0].text.strip()
    except Exception as e:
        logging.error(f"[Claude AI] Erro ao chamar Anthropic Claude: {e}")
    return None

