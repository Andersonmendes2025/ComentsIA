# routes_metrics.py
from flask import Blueprint, jsonify, session
from sqlalchemy import case, func

from models import Review, db

# ---------- Decoradores e limiter (fallbacks p/ não quebrar) ----------
try:
    # ajuste o caminho se seus decoradores NÃO estão no main.py
    from main import limiter, require_plano_ativo, require_terms_accepted  # noqa: F401
except Exception:

    def require_terms_accepted(f):  # no-op
        return f

    def require_plano_ativo(f):  # no-op
        return f

    class _NoLimiter:
        def limit(self, *args, **kwargs):
            def _wrap(f):
                return f

            return _wrap

    limiter = _NoLimiter()
# ---------------------------------------------------------------------

metrics_bp = Blueprint("metrics", __name__)


@metrics_bp.get("/api/dashboard_metrics")
@require_terms_accepted
@require_plano_ativo
@limiter.limit("20/minute")
def api_dashboard_metrics():
    user_info = session.get("user_info") or {}
    user_id = user_info.get("id")
    if not user_id:
        return jsonify(error="Sessão inválida."), 401

    total, respondidas, media = (
        db.session.query(
            func.count(Review.id),
            func.coalesce(func.sum(case((Review.replied.is_(True), 1), else_=0)), 0),
            func.avg(Review.rating),  # AVG ignora NULL
        )
        .filter(Review.user_id == user_id)
        .one()
    )

    total = int(total or 0)
    respondidas = int(respondidas or 0)
    media = float(media) if media is not None else 0.0
    pendentes = max(total - respondidas, 0)
    respondidas_pct = (respondidas / total * 100.0) if total > 0 else 0.0

    return jsonify(
        total=total,
        respondidas=respondidas,
        respondidas_pct=round(respondidas_pct, 1),
        media=round(media, 1),
        pendentes=pendentes,
    )
