# booking.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import csv
import io
import os
import re
import json
import html
import time as time_mod
import unicodedata
import hashlib
from datetime import datetime
from time import time
from functools import wraps
from typing import Dict, Any, List, Optional, Iterable, Iterator, Tuple

from flask import Blueprint, request, jsonify, render_template, session, current_app
from sqlalchemy.exc import IntegrityError
from werkzeug.utils import secure_filename

# Scheduler para processar em segundo plano
from apscheduler.schedulers.background import BackgroundScheduler

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
MAX_FILE_BYTES = 2_000_000  # ~2MB (apenas para upload imediato; processamento é em stream)
MAX_CSV_LINES = 100_000
MAX_ERRORS_RETURNED = 10
BOOKING_SOURCE = "booking"

# processamento em background
CHUNK_BYTES = 150 * 1024  # 150 KB
BATCH_ROWS = 400          # insere/commita a cada 400 linhas válidas (ajuda na RAM)
SLEEP_BETWEEN_CHUNKS = 0.05  # descanso curto entre blocos, suaviza CPU/RAM

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

# ---------- Helpers batch ----------
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

# ---------- Streaming CSV (150 KB) ----------
def _iter_lines_from_file(path: str, chunk_bytes: int = CHUNK_BYTES) -> Iterator[str]:
    """Lê o arquivo em blocos e emite linhas completas (sem quebrar no meio)."""
    with open(path, "rb") as f:
        leftover = b""
        while True:
            chunk = f.read(chunk_bytes)
            if not chunk:
                if leftover:
                    # última linha (sem \n)
                    try:
                        yield leftover.decode("utf-8", errors="replace")
                    except Exception:
                        yield leftover.decode("latin-1", errors="replace")
                break
            data = leftover + chunk
            lines = data.split(b"\n")
            leftover = lines.pop()  # mantém o pedaço incompleto
            for ln in lines:
                # suporta CRLF
                ln = ln.rstrip(b"\r")
                try:
                    yield ln.decode("utf-8", errors="replace")
                except Exception:
                    yield ln.decode("latin-1", errors="replace")

def _build_dict_reader(lines_iter: Iterator[str]) -> Tuple[csv.DictReader, List[str]]:
    """
    Consome a primeira linha (cabeçalho), detecta delimitador e cria um DictReader
    sobre o iterador remanescente, sem carregar tudo na memória.
    """
    try:
        header_line = next(lines_iter)
    except StopIteration:
        # arquivo vazio
        raise ValueError("CSV vazio.")
    sample = header_line[:2048]
    try:
        dialect = csv.Sniffer().sniff(sample) if sample else csv.excel
    except Exception:
        dialect = csv.excel

    # Normaliza separadores reconhecidos (vírgula/;/\t)
    delimiter = getattr(dialect, "delimiter", ",") or ","
    headers = [h.strip() for h in header_line.split(delimiter)]
    # Cria DictReader passando fieldnames (para não consumir nova linha)
    reader = csv.DictReader(lines_iter, fieldnames=headers, dialect=dialect)
    return reader, headers

# ---------- Scheduler global (daemon) ----------
_scheduler: Optional[BackgroundScheduler] = None

def _get_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler(daemon=True)
        _scheduler.start()
    return _scheduler

# ---------- Worker em segundo plano ----------
def _process_booking_file_bg(app_import_path: str, log_id: int, file_path: str, user_id: str) -> None:
    """
    Worker: processa o CSV em 150 KB por vez, insere em lotes, atualiza UploadLog.
    app_import_path: caminho para importar a app Flask (ex: 'main:app' ou 'main')
    """
    # carrega app e cria app_context para usar db/session
    # aceitamos 'main' (módulo) ou 'main:app'
    module_name = app_import_path.split(":")[0]
    app_obj_name = app_import_path.split(":")[1] if ":" in app_import_path else "app"
    flask_app = None
    try:
        mod = __import__(module_name)
        flask_app = getattr(mod, app_obj_name)
    except Exception:
        # fallback: usa current_app se disponível
        flask_app = current_app._get_current_object() if current_app else None

    if flask_app is None:
        # sem app; marca erro no log e sai
        try:
            log = db.session.get(UploadLog, log_id)
            if log:
                log.status = "error"
                log.finished_at = agora_brt()
                log.errors_json = json.dumps(["Falha ao inicializar contexto da aplicação."])
                db.session.commit()
        except Exception:
            db.session.rollback()
        return

    with flask_app.app_context():
        log = db.session.get(UploadLog, log_id)
        if not log:
            return

        log.status = "processing"
        db.session.commit()

        inserted = log.inserted or 0
        duplicates = log.duplicates or 0
        skipped = log.skipped or 0
        errors: List[str] = json.loads(log.errors_json) if log.errors_json else []

        try:
            # iterador de linhas em streaming
            lines_iter = _iter_lines_from_file(file_path, CHUNK_BYTES)
            reader, headers = _build_dict_reader(lines_iter)

            if not headers:
                raise ValueError("CSV sem cabeçalhos.")

            fieldmap = _detect_fields(headers)
            if not fieldmap["external_id"]:
                raise ValueError("CSV sem coluna de 'Número da reserva' reconhecida.")

            # Pré-filtro de existentes por lote (por performance)
            batch_rows: List[Dict[str, Any]] = []
            extids_batch: List[str] = []
            seen_in_file: set[str] = set()

            line_num = 0
            for row in reader:
                line_num += 1
                if line_num > MAX_CSV_LINES:
                    errors.append(f"Limite de {MAX_CSV_LINES} linhas excedido. Processamento interrompido.")
                    break

                try:
                    raw_ext = row.get(fieldmap["external_id"])
                    extid = str(raw_ext).strip() if raw_ext is not None else ""
                    if not _is_valid_extid(extid):
                        skipped += 1
                        if len(errors) < MAX_ERRORS_RETURNED:
                            errors.append(f"Linha {line_num}: 'Número da reserva' ausente ou inválido.")
                        continue
                    if extid in seen_in_file:
                        duplicates += 1
                        if len(errors) < MAX_ERRORS_RETURNED:
                            errors.append(f"Linha {line_num}: 'Número da reserva' repetido no arquivo ({extid}).")
                        continue
                    seen_in_file.add(extid)
                    extids_batch.append(extid)

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

                    batch_rows.append(dict(
                        external_id=extid, name=name, title=title,
                        pos=pos, neg=neg, text=text_joined,
                        rating_10=rating_10, rating_5=rating_5,
                        dt_save=dt_to_save
                    ))

                    # quando atinge um lote, processa/insere
                    if len(batch_rows) >= BATCH_ROWS:
                        # checa duplicados no banco
                        existing = _prefetch_existing_by_ext(user_id, extids_batch)
                        # cria e insere só inéditos
                        for item in batch_rows:
                            extid_i = item["external_id"]
                            if extid_i in existing:
                                duplicates += 1
                                continue
                            try:
                                idx = ReservationIndex(user_id=user_id, source=BOOKING_SOURCE, external_id=extid_i)
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
                            _set_if_attr(review, "external_id", extid_i)
                            try:
                                fp = hashlib.sha256(f"{user_id}|{BOOKING_SOURCE}|{extid_i}".encode("utf-8")).hexdigest()
                                _set_if_attr(review, "fingerprint", fp)
                            except Exception:
                                pass
                            _set_if_attr(review, "booking_title", item["title"])
                            _set_if_attr(review, "booking_positive", item["pos"])
                            _set_if_attr(review, "booking_negative", item["neg"])

                            db.session.add(review)
                            inserted += 1

                        # commit do lote
                        db.session.commit()

                        # atualiza log parcial
                        log = db.session.get(UploadLog, log_id)
                        if log:
                            log.status = "processing"
                            log.inserted = inserted
                            log.duplicates = duplicates
                            log.skipped = skipped
                            # mantemos só alguns erros para não inchar
                            log.errors_json = json.dumps(errors[:MAX_ERRORS_RETURNED]) if errors else None
                            db.session.commit()

                        # limpa buffers do lote
                        batch_rows.clear()
                        extids_batch.clear()

                        # alivia CPU/RAM
                        time_mod.sleep(SLEEP_BETWEEN_CHUNKS)

                except Exception as e:
                    skipped += 1
                    if len(errors) < MAX_ERRORS_RETURNED:
                        errors.append(_sanitize_errmsg(e))

            # processa resto do lote
            if batch_rows:
                existing = _prefetch_existing_by_ext(user_id, extids_batch)
                for item in batch_rows:
                    extid_i = item["external_id"]
                    if extid_i in existing:
                        duplicates += 1
                        continue
                    try:
                        idx = ReservationIndex(user_id=user_id, source=BOOKING_SOURCE, external_id=extid_i)
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
                    _set_if_attr(review, "external_id", extid_i)
                    try:
                        fp = hashlib.sha256(f"{user_id}|{BOOKING_SOURCE}|{extid_i}".encode("utf-8")).hexdigest()
                        _set_if_attr(review, "fingerprint", fp)
                    except Exception:
                        pass
                    _set_if_attr(review, "booking_title", item["title"])
                    _set_if_attr(review, "booking_positive", item["pos"])
                    _set_if_attr(review, "booking_negative", item["neg"])

                    db.session.add(review)
                    inserted += 1

                db.session.commit()

            # finaliza
            log = db.session.get(UploadLog, log_id)
            if log:
                log.status = "success"
                log.finished_at = agora_brt()
                log.inserted = inserted
                log.duplicates = duplicates
                log.skipped = skipped
                log.errors_json = json.dumps(errors[:MAX_ERRORS_RETURNED]) if errors else None
                db.session.commit()

        except Exception as e:
            db.session.rollback()
            log = db.session.get(UploadLog, log_id)
            if log:
                log.status = "error"
                log.finished_at = agora_brt()
                errors.append(_sanitize_errmsg(e))
                log.errors_json = json.dumps(errors[:MAX_ERRORS_RETURNED])
                db.session.commit()
        finally:
            # remove arquivo temporário
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
            except Exception:
                pass
            # liberação de sessão para o worker
            db.session.remove()

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
    """
    Novo fluxo:
    - Salva o arquivo em /tmp (sem carregar na RAM)
    - Cria UploadLog com status 'queued'
    - Agenda processamento em background que lê 150 KB por vez
    - Retorna imediatamente {status: queued, upload_id: ...}
    """
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
        # apenas alerta silencioso; alguns browsers mandam mimetype genérico
        pass

    safe_name = secure_filename(fname_raw) or "arquivo.csv"
    user_id = _get_current_user_id() or "anonymous"

    # Garante diretório temp
    tmp_dir = os.environ.get("UPLOAD_TMP_DIR") or "/tmp"
    os.makedirs(tmp_dir, exist_ok=True)
    tmp_path = os.path.join(tmp_dir, f"booking_{int(time())}_{safe_name}")

    # Salva em disco sem carregar tudo na RAM
    try:
        with open(tmp_path, "wb") as f:
            while True:
                chunk = file_obj.stream.read(CHUNK_BYTES)
                if not chunk:
                    break
                f.write(chunk)
    except Exception:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
        return jsonify(success=False, error="Falha ao salvar arquivo temporário."), 400

    # Log inicial (status queued)
    upload_log = UploadLog(
        user_id=user_id, source=BOOKING_SOURCE,
        filename=safe_name,
        filesize=os.path.getsize(tmp_path),
        status="queued", started_at=agora_brt(),
    )
    _set_if_attr(upload_log, "ip", request.remote_addr)
    _set_if_attr(upload_log, "user_agent", request.user_agent.string if request.user_agent else None)
    db.session.add(upload_log)
    db.session.commit()

    # agenda job em background
    app_import_path = os.environ.get("FLASK_APP_IMPORT", "main:app")  # configure se usar outro nome
    scheduler = _get_scheduler()
    scheduler.add_job(
        _process_booking_file_bg,
        kwargs=dict(app_import_path=app_import_path, log_id=upload_log.id, file_path=tmp_path, user_id=user_id),
        # usa id único para não duplicar
        id=f"booking_upload_{upload_log.id}",
        replace_existing=True,
        misfire_grace_time=3600,
        max_instances=1,
    )

    return jsonify(
        success=True,
        status="queued",
        message="Arquivo recebido. Processamento iniciado em segundo plano.",
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