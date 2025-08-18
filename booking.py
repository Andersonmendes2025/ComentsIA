# booking.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import csv
import io
import os
import hashlib
from datetime import datetime
from typing import Dict, Any, List, Optional

from flask import Blueprint, request, jsonify, render_template, session
from werkzeug.utils import secure_filename
from models import db, Review

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
MAX_FILE_BYTES = 2_000_000  # ~2MB

# -------- utilidades básicas ----------
def _filename_ok(filename: str) -> bool:
    return bool(filename) and any(filename.lower().endswith(ext) for ext in ALLOWED_EXT)

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
    hmap = {h.lower().strip(): h for h in headers}
    def pick(*cands):
        for c in cands:
            if c in hmap: return hmap[c]
        return ""
    return {
        "name": pick("nome do hóspede","hóspede","guest name","reviewer name","name","autor","author"),
        "title": pick("título da avaliação","review title","title","titulo"),
        "text_pos": pick("avaliação positiva","positive","pros","comentario positivo"),
        "text_neg": pick("avaliação negativa","negative","cons","comentario negativo"),
        "rating": pick("nota de avaliação","score","rating","nota","overall score","overall","puntuación","pontuacao"),
        "date": pick("data da avaliação","submission date","date","data","review date","created","created at"),
        "external_id": pick("número da reserva","review id","id","booking id","reviewid"),
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

def _fingerprint(user_id: str, source: str, external_id: Optional[str],
                 author: Optional[str], title: Optional[str],
                 date: Optional[datetime], text: Optional[str]) -> str:
    base = [user_id or "", source or "booking"]
    if external_id:
        base += ["extid:", str(external_id)]
    else:
        base += ["author:", (author or "").strip().lower(),
                 "title:", (title or "").strip().lower(),
                 "date:", date.isoformat() if date else "",
                 "text:", (text or "").strip().lower()[:200]]
    return hashlib.sha256("|".join(base).encode("utf-8")).hexdigest()

def _set_if_attr(obj: Any, field: str, value: Any) -> None:
    if hasattr(obj, field):
        try: setattr(obj, field, value)
        except Exception: pass

def _get_current_user_id() -> Optional[str]:
    info = session.get("user_info") or {}
    return info.get("id")

def _require_login() -> bool:
    return "credentials" in session and bool(_get_current_user_id())

# ======= Views =======
@booking_bp.route("/", methods=["GET"])
def form_upload():
    if not _require_login():
        return ("Não autenticado.", 401)
    return render_template("booking_upload.html")

@booking_bp.route("/upload", methods=["POST"])
def upload_csv():
    if not _require_login():
        return jsonify(success=False, error="Não autenticado."), 401

    if (request.content_length or 0) > MAX_FILE_BYTES:
        return jsonify(success=False, error="Arquivo muito grande."), 413

    f = request.files.get("file")
    if not f:
        return jsonify(success=False, error="Arquivo não enviado."), 400

    if not _filename_ok(f.filename or ""):
        return jsonify(success=False, error="Extensão não suportada (use .csv)."), 400

    try:
        raw = f.read()
        text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
    except Exception:
        return jsonify(success=False, error="Falha ao ler o arquivo."), 400

    # CSV
    try:
        buf = io.StringIO(text)
        sample = text[:2048]
        dialect = csv.Sniffer().sniff(sample)
        buf.seek(0)
        reader = csv.DictReader(buf, dialect=dialect)
        headers = reader.fieldnames or []
    except Exception:
        buf = io.StringIO(text)
        reader = csv.DictReader(buf)
        headers = reader.fieldnames or []

    if not headers:
        return jsonify(success=False, error="CSV sem cabeçalhos."), 400

    fieldmap = _detect_fields(headers)

    inserted = 0
    duplicates = 0
    skipped = 0
    errors: List[str] = []

    user_id = _get_current_user_id() or "anonymous"

    for i, row in enumerate(reader, start=1):
        try:
            name = row.get(fieldmap["name"]) if fieldmap["name"] else None
            title = row.get(fieldmap["title"]) if fieldmap["title"] else None
            pos = row.get(fieldmap["text_pos"]) if fieldmap["text_pos"] else None
            neg = row.get(fieldmap["text_neg"]) if fieldmap["text_neg"] else None

            text_joined = _first_not_empty((pos or ""), (neg or "")) or ""
            if pos and neg:
                text_joined = f"Positivo: {pos}\nNegativo: {neg}".strip()

            rating_10 = _to_float(row.get(fieldmap["rating"])) if fieldmap["rating"] else None
            rating_5 = _convert_to_five_scale(rating_10)

            raw_date = row.get(fieldmap["date"]) if fieldmap["date"] else None
            dt = _parse_date(raw_date) or agora_brt()

            external_id = row.get(fieldmap["external_id"]) if fieldmap["external_id"] else None

            fp = _fingerprint(user_id, "booking", external_id, name, title, dt, text_joined)

            # dedupe
            existing = None
            try:
                if hasattr(Review, "fingerprint"):
                    existing = Review.query.filter_by(user_id=user_id, fingerprint=fp).first()
                elif hasattr(Review, "external_id") and external_id:
                    existing = Review.query.filter_by(user_id=user_id, source="booking", external_id=external_id).first()
                else:
                    existing = Review.query.filter_by(user_id=user_id, source="booking", title=(title or None), date=dt).first()
            except Exception:
                existing = None

            if existing is not None:
                duplicates += 1
                continue

            review = Review()
            _set_if_attr(review, "user_id", user_id)
            _set_if_attr(review, "author_name", name)
            _set_if_attr(review, "reviewer_name", name)
            _set_if_attr(review, "title", title)
            _set_if_attr(review, "text", text_joined)
            _set_if_attr(review, "content", text_joined)
            _set_if_attr(review, "comment", text_joined)
            _set_if_attr(review, "rating", rating_5)
            _set_if_attr(review, "date", dt)

            _set_if_attr(review, "original_rating", rating_10)
            _set_if_attr(review, "original_scale", "0-10")
            _set_if_attr(review, "source", "booking")
            _set_if_attr(review, "external_id", external_id)
            _set_if_attr(review, "fingerprint", fp)

            _set_if_attr(review, "booking_title", title)
            _set_if_attr(review, "booking_positive", pos)
            _set_if_attr(review, "booking_negative", neg)

            db.session.add(review)
            inserted += 1
        except Exception as e:
            errors.append(f"Linha {i}: {e}")
            skipped += 1

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify(success=False, error=f"Falha ao salvar: {e}")

    return jsonify(
        success=True,
        inserted=inserted,
        duplicates=duplicates,
        skipped=skipped,
        errors=errors[:10],
        message="Importação concluída.",
    )

@booking_bp.route("/count", methods=["GET"])
def count_booking_reviews():
    if not _require_login():
        return jsonify(success=False, error="Não autenticado."), 401

    user_id = _get_current_user_id()
    q = Review.query
    try:
        if user_id and hasattr(Review, "user_id"):
            q = q.filter_by(user_id=user_id)
        if hasattr(Review, "source"):
            q = q.filter_by(source="booking")
        count = q.count()
    except Exception:
        count = 0

    return jsonify(success=True, count=count)
