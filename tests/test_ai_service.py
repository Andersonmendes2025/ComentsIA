# -*- coding: utf-8 -*-
import pytest
from services.ai_service import (
    limpar_texto_review,
    parse_review_text,
    detect_text_language,
    get_tone_instructions,
    get_language_instructions,
)


def test_user_screenshot_review_parsing():
    # Caso exato do Wagner Nascimento no print do usuário
    raw = (
        "Hotel muito bom quartos limpo e bem organizado suco do café já não é muito bom lembra "
        "o suco da escola muita água e pouca fruta só pra dá a cor mesmo (Translated by Google) "
        "Very good hotel, clean and well-organized rooms. The coffee juice isn't very good, "
        "it's reminiscent of school juice, too much water and not much fruit, just enough to give it color."
    )
    parsed = parse_review_text(raw)
    assert parsed["orig_lang"] == "pt"
    assert parsed["trans_lang"] == "en"
    assert "Hotel muito bom quartos limpo" in parsed["original"]
    assert "Translated by Google" not in parsed["original"]
    assert "Very good hotel, clean and well-organized rooms" in parsed["translated"]
    assert "Translated by Google" not in parsed["translated"]

    # Para usuário em português (target_lang="pt"), deve exibir somente o português original
    clean_pt = limpar_texto_review(raw, target_lang="pt")
    assert "Hotel muito bom" in clean_pt
    assert "Translated by Google" not in clean_pt
    assert "Very good hotel" not in clean_pt


def test_limpar_texto_review_translated_and_original():
    # Caso 1: Google com (Translated) e (Original) em inglês -> português
    raw_1 = "(Translated by Google) The food was amazing! (Original) A comida estava maravilhosa!"
    parsed = parse_review_text(raw_1)
    assert parsed["original"] == "A comida estava maravilhosa!"
    assert parsed["translated"] == "The food was amazing!"

    # Caso 2: Google com (Traduzido pelo Google) e (Original) em português -> inglês
    raw_2 = "(Traduzido pelo Google) O atendimento foi ótimo! (Original) The service was great!"
    parsed_2 = parse_review_text(raw_2)
    assert parsed_2["original"] == "The service was great!"
    assert parsed_2["translated"] == "O atendimento foi ótimo!"

    # Caso 3: Apenas prefixo (Traduzido pelo Google) sem marcador (Original)
    raw_3 = "(Traduzido pelo Google) Café da manhã excelente com muitas frutas."
    assert limpar_texto_review(raw_3) == "Café da manhã excelente com muitas frutas."

    # Caso 4: Texto sem tradução (já original e limpo)
    raw_4 = "Gostei muito do hotel e recomendo para famílias."
    assert limpar_texto_review(raw_4) == "Gostei muito do hotel e recomendo para famílias."

    # Caso 5: Vazio ou None
    assert limpar_texto_review("") == ""
    assert limpar_texto_review(None) == ""


def test_detect_text_language():
    assert detect_text_language("Hotel muito bom e atendimento impecável") == "pt"
    assert detect_text_language("Very good room, very clean and friendly staff") == "en"
    assert detect_text_language("Habitación muy limpia y excelente desayuno") == "es"
    assert detect_text_language("Très bon hôtel et chambre très propre") == "fr"
    assert detect_text_language("Sehr gutes Hotel und sauberes Zimmer") == "de"
    assert detect_text_language("Albergo molto pulito e bella camera") == "it"


def test_get_tone_instructions():
    tones = ["profissional", "amigavel", "empatico", "direto", "luxo"]
    for t in tones:
        inst = get_tone_instructions(t)
        assert inst is not None and len(inst) > 20
        assert t.upper() in inst or t == "amigavel" or t == "empatico"

    inst_prof = get_tone_instructions("profissional")
    inst_amig = get_tone_instructions("amigavel")
    inst_emp = get_tone_instructions("empatico")
    inst_dir = get_tone_instructions("direto")
    inst_lux = get_tone_instructions("luxo")

    assert "formal" in inst_prof.lower() or "polida" in inst_prof.lower()
    assert "emojis" in inst_amig.lower() or "descontraída" in inst_amig.lower()
    assert "escuta ativa" in inst_emp.lower() or "afeto" in inst_emp.lower()
    assert "2 a 3 frases" in inst_dir.lower()
    assert "nobre" in inst_lux.lower() or "sofisticação" in inst_lux.lower()


def test_get_language_instructions():
    sys_auto, rule_auto = get_language_instructions("auto")
    assert "mesmo idioma" in sys_auto.lower()
    assert "mesmo idioma" in rule_auto.lower()

    sys_en, rule_en = get_language_instructions("Inglês (Estados Unidos)")
    assert "INGLÊS (ESTADOS UNIDOS)" in sys_en
    assert "INGLÊS (ESTADOS UNIDOS)" in rule_en

    sys_es, rule_es = get_language_instructions("Espanhol")
    assert "ESPANHOL" in sys_es
    assert "ESPANHOL" in rule_es
