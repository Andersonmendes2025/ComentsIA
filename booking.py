# booking.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import csv
import io
import re
import json
import html
import unicodedata
import hashlib
from datetime import datetime
from time import time
from functools import wraps
from typing import Dict, Any, List, Optional, Iterable

from flask import Blueprint, request, jsonify, render_template, session, current_app
from sqlalchemy.exc import IntegrityError
from werkzeug.utils import secure_filename

# CSRF (validação manual opcional, além do CSRFProtect global se houver)
try:
    from flask_wtf.csrf import validate_csrf
    _HAS_WTF_CSRF = True
except Exception:
    _HAS_WTF_CSRF = False

# >>> importe TODOS os models apenas daqui:
from models import db, Review, ReservationIndex, UploadLog

# ======= Helpers de data/timezone =======
try:
    import pytz
    BRT = pytz.timezone("America/Sao_Paulo")
    def agora_brt():
        return datetime.now(BRT)
except Exception:
    def agora_brt():
        return datetime.now()

booking_bp = Blueprint("booking", __name__, url_prefix="/booking")

ALLOWED_EXT = {".csv"}
ALLOWED_MIMETYPES = {
    "text/csv",
    "application/csv",
    "application/vnd.ms-excel",
    "text/plain",
}
MAX_FILE_BYTES = 2_000_000  # ~2MB
MAX_CSV_LINES = 100_000
MAX_ERRORS_RETURNED = 10
BOOKING_SOURCE = "booking"

# -------- Normalizadores ----------
_ws_re = re.compile(r"\s+", re.UNICODE)
_punct_re = re.compile(r"[^\w\s]", re.UNICODE)

def _norm_text(s: Optional[str]) -> str:
    if not s: return ""
    s = str(s)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = _ws_re.sub(" ", s.strip())
    return s

def _norm_header(h: str) -> str:
    s = _norm_text(h).lower()
    s = _punct_re.sub(" ", s)
    s = _ws_re.sub(" ", s).strip()
    return s

def _neutralize_excel_formula(s: Optional[str]) -> Optional[str]:
    if not s:
        return s
    st = str(s)
    if st and st[0] in ("=", "+", "-", "@"):
        return "'" + st
    return st

def _sanitize_errmsg(msg: Any) -> str:
    return html.escape(str(msg), quote=True)

# -------- utilidades básicas ----------
def _filename_ok(filename: str) -> bool:
    return bool(filename) and any(filename.lower().endswith(ext) for ext in ALLOWED_EXT)

def _mimetype_ok(mt: Optional[str]) -> bool:
    if not mt:
        return False
    return mt.lower() in ALLOWED_MIMETYPES

def _to_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(str(val).strip().replace(",", ".")) if str(val).strip() else None
    except Exception:
        return None

def _first_not_empty(*vals: Any) -> Optional[str]:
    for v in vals:
        s = ("" if v is None else str(v)).strip()
        if s:
            return s
    return None

def _detect_fields(headers: List[str]) -> Dict[str, str]:
    norm2orig: Dict[str, str] = {_norm_header(h): h for h in headers}
    def pick(*syns: str) -> str:
        for s in syns:
            s_norm = _norm_header(s)
            if s_norm in norm2orig:
                return norm2orig[s_norm]
        return ""
    return {
        "name": pick("nome do hospede", "hospede", "guest name", "reviewer name", "name", "autor", "author"),
        "title": pick("titulo da avaliacao", "review title", "title", "titulo"),
        "text_pos": pick("avaliacao positiva", "positive", "pros", "comentario positivo"),
        "text_neg": pick("avaliacao negativa", "negative", "cons", "comentario negativo"),
        "rating": pick("nota de avaliacao", "score", "rating", "nota", "overall score", "overall", "puntuacion", "pontuacao"),
        "date": pick("data da avaliacao", "submission date", "date", "data", "review date", "created", "created at"),
        "external_id": pick("numero da reserva", "número da reserva", "review id", "booking id", "id", "reviewid"),
    }

def _parse_date(val: Any) -> Optional[datetime]:
    if not val: return None
    s = str(val).strip()
    fmts = ["%Y-%m-%d %H:%M:%S","%Y-%m-%d","%d/%m/%Y %H:%M:%S","%d/%m/%Y",
            "%d-%m-%Y %H:%M","%d-%m-%Y","%m/%d/%Y %H:%M:%S","%m/%d/%Y"]
    for f in fmts:
        try:
            return datetime.strptime(s, f)
        except Exception:
            pass
    return None

def _convert_to_five_scale(x: Optional[float]) -> Optional[float]:
    if x is None: return None
    v = float(x)
    if 0 <= v <= 5: return round(v, 1)
    if 0 <= v <= 10: return round(v/2.0, 1)
    if 0 <= v <= 100: return round((v/100.0)*5.0, 1)
    return 0.0 if v < 0 else 5.0

def _is_valid_extid(extid: Optional[str]) -> bool:
    if not extid: return False
    s = str(extid).strip()
    return s.isdigit() and 6 <= len(s) <= 16

def _set_if_attr(obj: Any, field: str, value: Any) -> None:
    if hasattr(obj, field):
        try: setattr(obj, field, value)
        except Exception: pass

def _get_current_user_id() -> Optional[str]:
    info = session.get("user_info") or {}
    return info.get("id")

def _require_login() -> bool:
    return "credentials" in session and bool(_get_current_user_id())

def _sanitize_name(name: Optional[str],
                   title: Optional[str],
                   pos: Optional[str],
                   neg: Optional[str]) -> Optional[str]:
    s = (name or "").strip()
    if not s:
        return None
    low = s.lower()
    if "\n" in s or len(s) >= 60 or len(s.split()) > 8:
        return None
    if low.endswith(".") or low.endswith("!") or low.endswith("?"):
        return None
    texts = [t for t in [title, pos, neg] if t]
    for t in texts:
        t_clean = str(t).strip()
        if not t_clean:
            continue
        if s == t_clean:
            return None
        if len(s) > 25 and (s in t_clean or t_clean in s):
            return None
    return s

# ---------- Rate limiting (fallback em memória) ----------
_rate_store: Dict[str, List[float]] = {}
def _rate_limit(scope: str, max_calls: int, window_seconds: int):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid = _get_current_user_id() or request.remote_addr or "anon"
            key = f"{scope}:{uid}"
            now = time()
            buf = [t for t in _rate_store.get(key, []) if now - t < window_seconds]
            if len(buf) >= max_calls:
                return jsonify(success=False, error="Limite de requisições atingido. Tente mais tarde."), 429
            buf.append(now)
            _rate_store[key] = buf
            return fn(*args, **kwargs)
        return wrapper
    return decorator

# ---------- Helpers batch (repostos) ----------
def _chunked(it: Iterable[Any], n: int = 900) -> Iterable[List[Any]]:
    buf: List[Any] = []
    for x in it:
        buf.append(x)
        if len(buf) >= n:
            yield buf
            buf = []
    if buf:
        yield buf

def _prefetch_existing_by_ext(user_id: str, ext_ids: List[str]) -> set[str]:
    """Busca no índice/tabela os external_id já existentes para este usuário/fonte."""
    found: set[str] = set()
    if not ext_ids:
        return found
    # 1) ReservationIndex (mais barato)
    for chunk in _chunked(ext_ids):
        try:
            rows = db.session.query(ReservationIndex.external_id).filter(
                ReservationIndex.user_id == user_id,
                ReservationIndex.source == BOOKING_SOURCE,
                ReservationIndex.external_id.in_(chunk)
            ).all()
            found.update(str(r[0]) for r in rows if r[0] is not None)
        except Exception:
            found = set()
            break
    # 2) Fallback para Review.external_id
    if not found:
        for chunk in _chunked(ext_ids):
            try:
                rows = db.session.query(Review.external_id).filter(
                    Review.user_id == user_id,
                    Review.source == BOOKING_SOURCE,
                    Review.external_id.in_(chunk)
                ).all()
                found.update(str(r[0]) for r in rows if r[0] is not None)
            except Exception:
                return set()
    return found

# ======= Views =======
@booking_bp.route("/", methods=["GET"])
@_rate_limit("form_upload", 120, 60)
def form_upload():
    if not _require_login():
        return ("Não autenticado.", 401)
    return render_template("booking_upload.html")

@booking_bp.route("/uploads", methods=["GET"])
@_rate_limit("list_uploads", 240, 60)
def list_uploads():
    if not _require_login():
        return jsonify(success=False, error="Não autenticado."), 401
    user_id = _get_current_user_id()
    logs = (UploadLog.query
            .filter_by(user_id=user_id, source=BOOKING_SOURCE)
            .order_by(UploadLog.started_at.desc())
            .limit(100)
            .all())
    def to_dict(u: UploadLog) -> Dict[str, Any]:
        return dict(
            id=u.id,
            filename=u.filename,
            filesize=u.filesize,
            started_at=(u.started_at.isoformat() if u.started_at else None),
            finished_at=(u.finished_at.isoformat() if u.finished_at else None),
            inserted=u.inserted,
            duplicates=u.duplicates,
            skipped=u.skipped,
            status=u.status,
            errors=json.loads(u.errors_json) if u.errors_json else []
        )
    return jsonify(success=True, uploads=[to_dict(u) for u in logs])

@booking_bp.route("/uploads/<int:log_id>", methods=["DELETE"])
@_rate_limit("delete_upload_log", 30, 3600)
def delete_upload_log(log_id: int):
    if not _require_login():
        return jsonify(success=False, error="Não autenticado."), 401

    # CSRF extra (se disponível)
    if _HAS_WTF_CSRF:
        token = request.headers.get("X-CSRFToken") or request.form.get("csrf_token")
        try:
            validate_csrf(token)
        except Exception:
            return jsonify(success=False, error="CSRF inválido."), 400

    user_id = _get_current_user_id()
    log = UploadLog.query.filter_by(id=log_id, user_id=user_id, source=BOOKING_SOURCE).first()
    if not log:
        return jsonify(success=False, error="Registro não encontrado."), 404
    try:
        db.session.delete(log)
        db.session.commit()
        return jsonify(success=True, message="Histórico de upload excluído.")
    except Exception:
        db.session.rollback()
        return jsonify(success=False, error="Falha ao excluir."), 400

@booking_bp.route("/upload", methods=["POST"])
@_rate_limit("upload_csv", 10, 3600)
def upload_csv():
    if not _require_login():
        return jsonify(success=False, error="Não autenticado."), 401

    # CSRF extra (se disponível)
    if _HAS_WTF_CSRF:
        token = request.headers.get("X-CSRFToken") or request.form.get("csrf_token")
        try:
            validate_csrf(token)
        except Exception:
            return jsonify(success=False, error="CSRF inválido."), 400

    file_obj = request.files.get("file")
    if not file_obj:
        return jsonify(success=False, error="Arquivo não enviado."), 400

    if (request.content_length or 0) > MAX_FILE_BYTES:
        return jsonify(success=False, error="Arquivo muito grande."), 413

    fname_raw = (file_obj.filename or "").strip()
    if not _filename_ok(fname_raw):
        return jsonify(success=False, error="Extensão não suportada (use .csv)."), 400
    if file_obj.mimetype and not _mimetype_ok(file_obj.mimetype):
        pass

    safe_name = secure_filename(fname_raw) or "arquivo.csv"
    user_id = _get_current_user_id() or "anonymous"

    # Log inicial
    upload_log = UploadLog(
        user_id=user_id, source=BOOKING_SOURCE,
        filename=safe_name,
        filesize=(file_obj.content_length or None),
        status="running", started_at=agora_brt(),
    )
    # Auditoria básica
    _set_if_attr(upload_log, "ip", request.remote_addr)
    _set_if_attr(upload_log, "user_agent", request.user_agent.string if request.user_agent else None)

    db.session.add(upload_log)
    db.session.commit()

    inserted = 0
    duplicates = 0
    skipped = 0
    errors: List[str] = []

    # Ler arquivo
    try:
        raw = file_obj.read()
        text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
    except Exception:
        upload_log.status = "error"
        upload_log.finished_at = agora_brt()
        upload_log.errors_json = json.dumps(["Falha ao ler o arquivo."])
        db.session.commit()
        return jsonify(success=False, error="Falha ao ler o arquivo."), 400

    # CSV reader (robusto)
    try:
        buf = io.StringIO(text)
        sample = text[:2048]
        try:
            dialect = csv.Sniffer().sniff(sample)
        except Exception:
            dialect = csv.excel
        buf.seek(0)
        reader = csv.DictReader(buf, dialect=dialect)
        headers = reader.fieldnames or []
    except Exception:
        buf = io.StringIO(text)
        reader = csv.DictReader(buf)
        headers = reader.fieldnames or []

    if not headers:
        upload_log.status = "error"
        upload_log.finished_at = agora_brt()
        upload_log.errors_json = json.dumps(["CSV sem cabeçalhos."])
        db.session.commit()
        return jsonify(success=False, error="CSV sem cabeçalhos."), 400

    fieldmap = _detect_fields(headers)
    if not fieldmap["external_id"]:
        upload_log.status = "error"
        upload_log.finished_at = agora_brt()
        upload_log.errors_json = json.dumps(["CSV sem coluna de 'Número da reserva' reconhecida."])
        db.session.commit()
        return jsonify(success=False, error="CSV sem coluna de 'Número da reserva' reconhecida."), 400

    # Passo 1: parse + validação
    rows_parsed: List[Dict[str, Any]] = []
    extids_file: List[str] = []
    seen_extids_in_file: set[str] = set()

    for i, row in enumerate(reader, start=1):
        if i > MAX_CSV_LINES:
            errors.append(f"Limite de {MAX_CSV_LINES} linhas excedido. Processamento interrompido.")
            break
        try:
            raw_ext = row.get(fieldmap["external_id"])
            extid = str(raw_ext).strip() if raw_ext is not None else ""
            if not _is_valid_extid(extid):
                skipped += 1
                errors.append(f"Linha {i}: 'Número da reserva' ausente ou inválido.")
                continue

            if extid in seen_extids_in_file:
                duplicates += 1
                errors.append(f"Linha {i}: 'Número da reserva' repetido no arquivo ({extid}).")
                continue
            seen_extids_in_file.add(extid)
            extids_file.append(extid)

            title = row.get(fieldmap["title"]) if fieldmap["title"] else None
            pos   = row.get(fieldmap["text_pos"]) if fieldmap["text_pos"] else None
            neg   = row.get(fieldmap["text_neg"]) if fieldmap["text_neg"] else None
            raw_name = row.get(fieldmap["name"]) if fieldmap["name"] else None

            text_joined = _first_not_empty((pos or ""), (neg or "")) or ""
            if pos and neg:
                text_joined = f"Positivo: {pos}\nNegativo: {neg}".strip()
            text_joined = _neutralize_excel_formula(_norm_text(text_joined))

            title = _neutralize_excel_formula(_norm_text(title)) if title else None

            name = _sanitize_name(raw_name, title, pos, neg) or "Hóspede Booking"
            name = _neutralize_excel_formula(name)

            rating_10 = _to_float(row.get(fieldmap["rating"])) if fieldmap["rating"] else None
            rating_5  = _convert_to_five_scale(rating_10)

            raw_date_val = row.get(fieldmap["date"]) if fieldmap["date"] else None
            parsed_dt = _parse_date(raw_date_val)
            dt_to_save = parsed_dt or agora_brt()

            rows_parsed.append(dict(
                i=i, external_id=extid, name=name, title=title,
                pos=pos, neg=neg, text=text_joined,
                rating_10=rating_10, rating_5=rating_5,
                dt_save=dt_to_save
            ))
        except Exception as e:
            skipped += 1
            errors.append(f"Linha {i}: {_sanitize_errmsg(e)}")

    if not rows_parsed:
        upload_log.status = "error"
        upload_log.finished_at = agora_brt()
        upload_log.inserted = inserted
        upload_log.duplicates = duplicates
        upload_log.skipped = skipped
        upload_log.errors_json = json.dumps(errors[:MAX_ERRORS_RETURNED])
        db.session.commit()
        return jsonify(success=False, error="Nenhuma linha válida para importar.",
                       duplicates=duplicates, skipped=skipped, errors=errors[:MAX_ERRORS_RETURNED])

    # Passo 2: confere no banco os external_id existentes
    existing_exts = _prefetch_existing_by_ext(user_id, extids_file)

    # Passo 3: insere só inéditos + reserva no índice (atomic via unique)
    for item in rows_parsed:
        extid = item["external_id"]
        if extid in existing_exts:
            duplicates += 1
            continue

        try:
            idx = ReservationIndex(user_id=user_id, source=BOOKING_SOURCE, external_id=extid)
            db.session.add(idx)
            db.session.flush()
        except IntegrityError:
            db.session.rollback()
            duplicates += 1
            continue

        review = Review()
        _set_if_attr(review, "user_id", user_id)
        _set_if_attr(review, "reviewer_name", item["name"])
        _set_if_attr(review, "author_name", item["name"])
        _set_if_attr(review, "title", item["title"])
        _set_if_attr(review, "text", item["text"])
        _set_if_attr(review, "content", item["text"])
        _set_if_attr(review, "comment", item["text"])
        _set_if_attr(review, "rating", item["rating_5"])
        _set_if_attr(review, "date", item["dt_save"])
        _set_if_attr(review, "original_rating", item["rating_10"])
        _set_if_attr(review, "original_scale", "0-10")
        _set_if_attr(review, "source", BOOKING_SOURCE)
        _set_if_attr(review, "external_id", extid)

        try:
            fp = hashlib.sha256(f"{user_id}|{BOOKING_SOURCE}|{extid}".encode("utf-8")).hexdigest()
            _set_if_attr(review, "fingerprint", fp)
        except Exception:
            pass

        _set_if_attr(review, "booking_title", item["title"])
        _set_if_attr(review, "booking_positive", item["pos"])
        _set_if_attr(review, "booking_negative", item["neg"])

        db.session.add(review)
        inserted += 1

    # Commit + atualizar log
    try:
        db.session.commit()
        upload_log.status = "success"
    except Exception:
        db.session.rollback()
        upload_log.status = "error"
        errors.append("Falha ao salvar.")
        if current_app and current_app.logger:
            current_app.logger.exception("Falha ao salvar import Booking")

    upload_log.finished_at = agora_brt()
    upload_log.inserted = inserted
    upload_log.duplicates = duplicates
    upload_log.skipped = skipped
    upload_log.errors_json = json.dumps(errors[:MAX_ERRORS_RETURNED]) if errors else None
    db.session.commit()

    return jsonify(
        success=(upload_log.status == "success"),
        inserted=inserted,
        duplicates=duplicates,
        skipped=skipped,
        errors=errors[:MAX_ERRORS_RETURNED],
        message="Importação concluída (somente inéditos por Número da reserva).",
        upload_id=upload_log.id
    )

@booking_bp.route("/count", methods=["GET"])
@_rate_limit("count_booking_reviews", 240, 60)
def count_booking_reviews():
    if not _require_login():
        return jsonify(success=False, error="Não autenticado."), 401
    user_id = _get_current_user_id()
    q = Review.query
    try:
        if user_id and hasattr(Review, "user_id"):
            q = q.filter_by(user_id=user_id)
        if hasattr(Review, "source"):
            q = q.filter_by(source=BOOKING_SOURCE)
        count = q.count()
    except Exception:
        count = 0
    return jsonify(success=True, count=count)
