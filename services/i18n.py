# -*- coding: utf-8 -*-
"""
services/i18n.py
Motor de Internacionalização (i18n) do ComentsIA.
Suporta detecção automática de idioma pelo navegador do usuário (Accept-Language / navigator.language),
parâmetros de URL (?lang=...), sessão e cookies persistentes.

Idiomas suportados:
  - pt_BR: Português (Brasil) [Padrão]
  - pt_PT: Português (Portugal)
  - en: English (US)
  - es: Español
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

from flask import g, has_request_context, request, session

# Diretório de arquivos de tradução
TRANSLATIONS_DIR = Path(__file__).parent.parent / "translations"

SUPPORTED_LANGUAGES = {
    "pt_BR": {
        "code": "pt_BR",
        "name": "Português (BR)",
        "flag": "🇧🇷",
        "locale": "pt-BR",
        "html_lang": "pt-BR"
    },
    "pt_PT": {
        "code": "pt_PT",
        "name": "Português (PT)",
        "flag": "🇵🇹",
        "locale": "pt-PT",
        "html_lang": "pt-PT"
    },
    "en": {
        "code": "en",
        "name": "English",
        "flag": "🇺🇸",
        "locale": "en-US",
        "html_lang": "en"
    },
    "es": {
        "code": "es",
        "name": "Español",
        "flag": "🇪🇸",
        "locale": "es-ES",
        "html_lang": "es"
    }
}

DEFAULT_LANGUAGE = "pt_BR"

# Cache de dicionários em memória
_TRANSLATION_CACHE: Dict[str, Dict[str, str]] = {}


def _normalize_lang_code(raw_code: Optional[str]) -> Optional[str]:
    """Normaliza códigos como 'pt-br', 'en-US', 'pt-pt', 'es-419' para os padrões suportados."""
    if not raw_code:
        return None
    
    code = raw_code.strip().replace("-", "_").lower()
    
    if code in ("pt_pt", "pt-pt"):
        return "pt_PT"
    if code.startswith("pt"):
        return "pt_BR"
    if code.startswith("en"):
        return "en"
    if code.startswith("es"):
        return "es"
    
    return None


def load_translations(lang: str) -> Dict[str, str]:
    """Carrega o arquivo JSON de tradução para a memória."""
    if lang in _TRANSLATION_CACHE:
        return _TRANSLATION_CACHE[lang]

    json_path = TRANSLATIONS_DIR / f"{lang}.json"
    if not json_path.exists():
        # Fallback para o arquivo padrão se não existir
        json_path = TRANSLATIONS_DIR / f"{DEFAULT_LANGUAGE}.json"

    if json_path.exists():
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                _TRANSLATION_CACHE[lang] = data
                return data
        except Exception as e:
            logging.error(f"[i18n] Erro ao carregar arquivo de tradução {json_path}: {e}")

    _TRANSLATION_CACHE[lang] = {}
    return {}


def get_current_locale() -> str:
    """
    Identifica o idioma ativo seguindo a ordem de prioridade:
    1. Parâmetro de URL: ?lang=...
    2. Sessão: session['lang']
    3. Cookie: request.cookies.get('coments_lang')
    4. Cabeçalho Accept-Language do navegador do usuário
    5. Fallback padrão: pt_BR
    """
    if not has_request_context():
        return DEFAULT_LANGUAGE

    # Cache por requisição no objeto 'g' do Flask
    if hasattr(g, "current_locale") and g.current_locale:
        return g.current_locale

    # 1. Parâmetro de URL ?lang=
    param_lang = request.args.get("lang")
    normalized_param = _normalize_lang_code(param_lang)
    if normalized_param and normalized_param in SUPPORTED_LANGUAGES:
        g.current_locale = normalized_param
        try:
            session["lang"] = normalized_param
        except Exception:
            pass
        return normalized_param

    # 2. Sessão
    try:
        sess_lang = session.get("lang")
        normalized_sess = _normalize_lang_code(sess_lang)
        if normalized_sess and normalized_sess in SUPPORTED_LANGUAGES:
            g.current_locale = normalized_sess
            return normalized_sess
    except Exception:
        pass

    # 3. Cookie
    cookie_lang = request.cookies.get("coments_lang")
    normalized_cookie = _normalize_lang_code(cookie_lang)
    if normalized_cookie and normalized_cookie in SUPPORTED_LANGUAGES:
        g.current_locale = normalized_cookie
        return normalized_cookie

    # 4. Detecção automática do Navegador (Accept-Language)
    try:
        accept_languages = request.accept_languages
        if accept_languages:
            # Lista de preferências do navegador
            for client_lang, quality in accept_languages:
                client_norm = _normalize_lang_code(client_lang)
                if client_norm and client_norm in SUPPORTED_LANGUAGES:
                    g.current_locale = client_norm
                    return client_norm
    except Exception as e:
        logging.debug(f"[i18n] Erro ao analisar Accept-Language: {e}")

    g.current_locale = DEFAULT_LANGUAGE
    return DEFAULT_LANGUAGE


def t(key: str, default: Optional[str] = None, **kwargs: Any) -> str:
    """
    Função principal de tradução.
    Exemplo: t('navbar.reviews') ou t('welcome.user', name='Anderson')
    """
    lang = get_current_locale()
    translations = load_translations(lang)

    # Busca a chave com suporte a aninhamento (ex: 'navbar.reviews')
    val = None
    if "." in key:
        parts = key.split(".")
        current = translations
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                current = None
                break
        if isinstance(current, str):
            val = current

    if val is None:
        val = translations.get(key)

    # Fallback para pt_BR se não encontrar no idioma atual
    if val is None and lang != DEFAULT_LANGUAGE:
        default_trans = load_translations(DEFAULT_LANGUAGE)
        if "." in key:
            parts = key.split(".")
            current = default_trans
            for part in parts:
                if isinstance(current, dict) and part in current:
                    current = current[part]
                else:
                    current = None
                    break
            if isinstance(current, str):
                val = current
        if val is None:
            val = default_trans.get(key)

    if val is None:
        val = default if default is not None else key

    # Interpolação de variáveis
    if kwargs and isinstance(val, str):
        try:
            return val.format(**kwargs)
        except Exception:
            return val

    return str(val)


# Alias amigável para Jinja e Python
_ = t


def init_app_i18n(app):
    """Inicializa os hooks e variáveis globais de i18n no Flask."""
    app.jinja_env.globals["t"] = t
    app.jinja_env.globals["_"] = _
    app.jinja_env.globals["get_current_locale"] = get_current_locale
    app.jinja_env.globals["SUPPORTED_LANGUAGES"] = SUPPORTED_LANGUAGES

    @app.context_processor
    def inject_i18n():
        current_locale = get_current_locale()
        return {
            "current_lang": current_locale,
            "lang_info": SUPPORTED_LANGUAGES.get(current_locale, SUPPORTED_LANGUAGES[DEFAULT_LANGUAGE]),
            "available_languages": SUPPORTED_LANGUAGES,
            "t": t,
            "_": _
        }
