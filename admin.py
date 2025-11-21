# admin.py
from __future__ import annotations

import calendar
import math
from datetime import date, datetime, timedelta
from functools import lru_cache, wraps
from typing import Dict, List, Optional

import pytz
from flask import (
    Blueprint,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from sqlalchemy import and_, func, or_

# ====== EMAILS (usa teu utilitário existente) ======
from email_utils import enviar_email  # usa SMTP configurado no projeto

# ====== MODELOS EXISTENTES DO PROJETO ======
# (integra com seu app)
# admin.py — imports (substitua seu bloco atual de models por este)
from models import (
    Activity,
    AdminActionLog,
    BillingEvent,
    Company,
    Contact,
    Coupon,
    EmailTemplate,
    FinanceItem,
    MessageLog,
    PaymentTransaction,
    PlanPrice,
    RelatorioHistorico,
    Review,
    Role,
    RolePermission,
    Ticket,
    User,
    UserPermissionOverride,
    UserRole,
    UserSettings,
    HistoricalSyncPrice,
    db,
)


# -----------------------------------------------------------------------------
# Helpers de tempo (BRT)
# -----------------------------------------------------------------------------
def agora_brt():
    return datetime.now(pytz.timezone("America/Sao_Paulo"))


# -----------------------------------------------------------------------------
# Blueprint
# -----------------------------------------------------------------------------
admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

# -----------------------------------------------------------------------------
# RBAC: Papéis + Permissões granulares (ler/editar por recurso)
# -----------------------------------------------------------------------------


# Helpers de permissão
def _get_current_user_id():
    info = session.get("user_info") or {}
    return info.get("id")


def _get_current_user():
    uid = _get_current_user_id()
    if not uid:
        return None
    try:
        return User.query.get(uid)
    except Exception:
        return None


def _user_role_key(user_id: str) -> Optional[str]:
    r = (
        db.session.query(Role.key)
        .join(UserRole, UserRole.role_id == Role.id)
        .filter(UserRole.user_id == user_id)
        .first()
    )
    return r[0] if r else None


def _perm_level_to_int(level: str) -> int:
    return {"none": 0, "read": 1, "write": 2}.get((level or "none").lower(), 0)


def _best_level(level_a: str, level_b: str) -> str:
    # retorna o "maior" nível
    la, lb = _perm_level_to_int(level_a), _perm_level_to_int(level_b)
    return level_a if la >= lb else level_b


def permission_level_for(user_id: str, perm: str) -> str:
    # Admin sempre full
    role_key = _user_role_key(user_id) or ""
    if role_key == "admin":
        return "write"

    # Override por usuário?
    uo = UserPermissionOverride.query.filter_by(user_id=user_id, perm=perm).first()
    if uo:
        return uo.level

    # Nível do papel
    rp = (
        db.session.query(RolePermission.level)
        .join(Role, Role.id == RolePermission.role_id)
        .join(UserRole, UserRole.role_id == Role.id)
        .filter(UserRole.user_id == user_id, RolePermission.perm == perm)
        .first()
    )
    return rp[0] if rp else "none"


def user_can(user_id: str, perm: str, mode: str = "read") -> bool:
    level = permission_level_for(user_id, perm)
    if mode == "read":
        return _perm_level_to_int(level) >= 1
    return _perm_level_to_int(level) >= 2


def require_perm(perm: str, mode: str = "read"):
    def deco(fn):
        @wraps(fn)
        def _wrap(*a, **k):
            uid = _get_current_user_id()
            if not uid:
                flash("Faça login para continuar.", "warning")
                return redirect(url_for("authorize"))
            if not user_can(uid, perm, mode):
                abort(403)
            return fn(*a, **k)

        return _wrap

    return deco


# -----------------------------------------------------------------------------
# Modelos Financeiros / CRM-Lite
# -----------------------------------------------------------------------------

# -----------------------------------------------------------------------------
# Pricing centralizado + cache
# -----------------------------------------------------------------------------
PLAN_KEYS = ["free", "pro", "pro_anual", "business", "business_anual"]


@lru_cache(maxsize=1)
def get_plan_prices() -> Dict[str, Dict[str, int | str]]:
    defaults = {
        "free": {"price_cents": 0, "currency": "BRL"},
        "pro": {"price_cents": 4999, "currency": "BRL"},
        "pro_anual": {"price_cents": 49900, "currency": "BRL"},
        "business": {"price_cents": 7999, "currency": "BRL"},
        "business_anual": {"price_cents": 79900, "currency": "BRL"},
    }
    rows = PlanPrice.query.all()
    if not rows:
        return defaults
    out = {}
    for r in rows:
        out[r.plan_key] = {
            "price_cents": int(r.price_cents),
            "currency": r.currency or "BRL",
        }
    for k, v in defaults.items():
        out.setdefault(k, v)
    return out


def invalidate_price_cache():
    get_plan_prices.cache_clear()


def format_brl_cents(cents: int) -> str:
    try:
        return (
            f"R$ {cents/100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        )
    except Exception:
        return f"R$ {cents/100:.2f}"


# -----------------------------------------------------------------------------
# Métricas (Dia / MTD / YTD + por plano + séries 12m)
# -----------------------------------------------------------------------------
def month_floor(dt: datetime) -> datetime:
    return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def month_end(dt: datetime) -> datetime:
    last = calendar.monthrange(dt.year, dt.month)[1]
    return dt.replace(day=last, hour=23, minute=59, second=59, microsecond=999999)


def last_n_month_starts(n: int, ref: datetime) -> List[date]:
    d0 = month_floor(ref).date()
    out = []
    y, m = d0.year, d0.month
    for _ in range(n):
        out.append(date(y, m, 1))
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    return list(reversed(out))


def period_paid_sum(start: datetime, end: datetime) -> int:
    q = (
        db.session.query(func.coalesce(func.sum(PaymentTransaction.amount_cents), 0))
        .filter(PaymentTransaction.status == "paid")
        .filter(PaymentTransaction.paid_at >= start)
        .filter(PaymentTransaction.paid_at <= end)
    )
    return int(q.scalar() or 0)


def period_paid_by_plan(start: datetime, end: datetime) -> Dict[str, int]:
    rows = (
        db.session.query(
            PaymentTransaction.plan_key,
            func.coalesce(func.sum(PaymentTransaction.amount_cents), 0),
        )
        .filter(
            PaymentTransaction.status == "paid",
            PaymentTransaction.paid_at >= start,
            PaymentTransaction.paid_at <= end,
        )
        .group_by(PaymentTransaction.plan_key)
        .all()
    )
    return {k or "": int(v) for k, v in rows}


def _active_clients_at(end: datetime) -> int:
    # ativos = plano != 'free' e plano_ate >= end
    try:
        return (
            UserSettings.query.filter(UserSettings.plano != "free")
            .filter(UserSettings.plano_ate != None)
            .filter(UserSettings.plano_ate >= end)
            .count()
        )  # noqa
    except Exception:
        return 0


def _applicable_finance_items(start: datetime, end: datetime) -> List[FinanceItem]:
    sm = month_floor(start).date()
    em = month_floor(end).date()
    return (
        FinanceItem.query.filter(
            FinanceItem.active == True, FinanceItem.start_month <= em
        )
        .filter(or_(FinanceItem.end_month == None, FinanceItem.end_month >= sm))
        .all()
    )


def calc_adjustments(start: datetime, end: datetime, gross_cents: int):
    tax_cents = 0
    cost_cents = 0
    items = _applicable_finance_items(start, end)
    for it in items:
        try:
            if it.method == "percent" and it.percent:
                part = int(round(gross_cents * (float(it.percent) / 100.0)))
                if it.kind == "tax":
                    tax_cents += part
                else:
                    cost_cents += part
            elif it.method == "fixed" and it.amount_cents:
                # alocar em 1 mês (recorrência mensal — soma integral)
                if it.kind == "tax":
                    tax_cents += int(it.amount_cents)
                else:
                    cost_cents += int(it.amount_cents)
        except Exception:
            continue
    net_cents = max(0, gross_cents - (tax_cents + cost_cents))
    return {
        "tax_cents": tax_cents,
        "cost_cents": cost_cents,
        "net_cents": net_cents,
        "gross_fmt": format_brl_cents(gross_cents),
        "tax_fmt": format_brl_cents(tax_cents),
        "cost_fmt": format_brl_cents(cost_cents),
        "net_fmt": format_brl_cents(net_cents),
    }


def avg_ticket(start: datetime, end: datetime) -> int:
    # média por transação (bruto / n_transações)
    total = period_paid_sum(start, end)
    n = (
        db.session.query(func.count(PaymentTransaction.id))
        .filter(
            PaymentTransaction.status == "paid",
            PaymentTransaction.paid_at >= start,
            PaymentTransaction.paid_at <= end,
        )
        .scalar()
        or 0
    )
    return int(total / n) if n else 0


def arpu_mtd(end: datetime) -> int:
    # ARPU do mês corrente até agora
    start_m = month_floor(end)
    total = period_paid_sum(start_m, end)
    ativos = _active_clients_at(end)
    return int(total / ativos) if ativos else 0


def cost_per_customer(start: datetime, end: datetime) -> int:
    # custo médio por cliente (impostos + custos / ativos)
    total = calc_adjustments(start, end, period_paid_sum(start, end))
    ativos = _active_clients_at(end)
    return int((total["tax_cents"] + total["cost_cents"]) / ativos) if ativos else 0


# -----------------------------------------------------------------------------
# ROTAS: Dashboard
# -----------------------------------------------------------------------------
@admin_bp.route("/", methods=["GET"])
@require_perm("dashboard.view", "read")
def dashboard():
    # KPIs simples (ativos, inadimplentes) + tabelas no template
    now = agora_brt()
    try:
        ativos = UserSettings.query.filter(
            UserSettings.plano != "free", UserSettings.plano_ate >= now
        ).count()
        inad = (
            UserSettings.query.filter(UserSettings.plano != "free")
            .filter(or_(UserSettings.plano_ate == None, UserSettings.plano_ate < now))
            .count()
        )
    except Exception:
        ativos = inad = 0
    return render_template(
        "admin_dashboard.html",
        ativos=ativos,
        inadimplentes=inad,
        prices=get_plan_prices(),
        planos=get_pricing_catalog(),
        fmt=format_brl_cents,
    )


@admin_bp.route("/dashboard/metrics.json", methods=["GET"])
@require_perm("dashboard.view", "read")
def metrics_json():
    now = agora_brt()
    start_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start_m = month_floor(now)
    start_y = datetime(now.year, 1, 1, 0, 0, 0, 0, tzinfo=now.tzinfo)

    gross_day = period_paid_sum(start_day, now)
    gross_mtd = period_paid_sum(start_m, now)
    gross_ytd = period_paid_sum(start_y, now)

    by_plan_mtd = period_paid_by_plan(start_m, now)
    adj_day = calc_adjustments(start_day, now, gross_day)
    adj_mtd = calc_adjustments(start_m, now, gross_mtd)
    adj_ytd = calc_adjustments(start_y, now, gross_ytd)

    # séries 12 meses (bruto x líquido)
    months = last_n_month_starts(12, now)
    series = []
    for m0 in months:
        m0_dt = datetime(m0.year, m0.month, 1, 0, 0, 0, 0, tzinfo=now.tzinfo)
        m1_dt = month_end(m0_dt)
        g = period_paid_sum(m0_dt, m1_dt)
        a = calc_adjustments(m0_dt, m1_dt, g)
        series.append(
            {
                "month": f"{m0.month:02d}/{m0.year}",
                "gross_cents": g,
                "net_cents": a["net_cents"],
            }
        )

    data = {
        "clients": {
            "active": _active_clients_at(now),
            "delinquent": UserSettings.query.filter(UserSettings.plano != "free")
            .filter(or_(UserSettings.plano_ate == None, UserSettings.plano_ate < now))
            .count(),
        },
        "revenue": {
            "day": adj_day,
            "mtd": adj_mtd,
            "ytd": adj_ytd,
            "by_plan_mtd": by_plan_mtd,
        },
        "kpis": {
            "avg_ticket": {
                "day": format_brl_cents(avg_ticket(start_day, now)),
                "mtd": format_brl_cents(avg_ticket(start_m, now)),
                "ytd": format_brl_cents(avg_ticket(start_y, now)),
            },
            "arpu": {"mtd": format_brl_cents(arpu_mtd(now))},
            "cost_per_customer": {
                "day": format_brl_cents(cost_per_customer(start_day, now)),
                "mtd": format_brl_cents(cost_per_customer(start_m, now)),
                "ytd": format_brl_cents(cost_per_customer(start_y, now)),
            },
        },
        "series_last12": series,
    }
    return jsonify(data)


# -----------------------------------------------------------------------------
# Pricing editor
# -----------------------------------------------------------------------------
@admin_bp.route("/pricing", methods=["GET", "POST"])
@require_perm("pricing.view", "read")
def pricing():
    if request.method == "POST":
        if not user_can(_get_current_user_id(), "pricing.edit", "write"):
            abort(403)
        for plan_key in PLAN_KEYS:
            cents_str = request.form.get(f"{plan_key}_cents")
            if cents_str is None:
                continue
            try:
                cents = int(cents_str)
            except ValueError:
                continue
            row = PlanPrice.query.filter_by(plan_key=plan_key).first()
            if not row:
                row = PlanPrice(plan_key=plan_key, price_cents=cents)
                db.session.add(row)
            else:
                row.price_cents = cents
        db.session.add(
            AdminActionLog(
                admin_user_id=_get_current_user_id(),
                action="pricing_update",
                meta={"source": "admin_pricing"},
            )
        )
        db.session.commit()
        invalidate_price_cache()
        flash("Preços atualizados.", "success")
        return redirect(url_for("admin.pricing"))
    # adicionando os preços históricos no HTML
    return render_template(
        "admin_pricing.html",
        prices=get_plan_prices(),
        planos=get_pricing_catalog(),
        historical=get_historical_sync_prices(),   # ⭐ ADICIONADO
        fmt=format_brl_cents,
    )


@admin_bp.route("/coupons/create", methods=["POST"])
@admin_bp.route("/coupons", methods=["POST"])  # compat: POST direto na list
@require_perm("coupons.edit", "write")
def coupon_create():
    code = (request.form.get("code") or "").upper().strip()
    discount_type = (request.form.get("discount_type") or "").strip()
    discount_value = int(request.form.get("discount_value") or 0)
    description = (request.form.get("description") or "").strip()
    max_uses_raw = request.form.get("max_uses")
    recurring = _as_bool(request.form.get("recurring"))
    valid_from = request.form.get("valid_from")
    valid_until = request.form.get("valid_until")

    if not (code and discount_type and discount_value > 0):
        flash("Preencha código/tipo/valor.", "danger")
        return redirect(url_for("admin.coupons"))

    c = Coupon(
        code=code,
        description=description or None,
        discount_type=discount_type,  # 'percent' | 'fixed'
        discount_value=discount_value,
        recurring=recurring,
        active=True,
    )

    try:
        if max_uses_raw not in (None, ""):
            mu = int(max_uses_raw)
            c.max_uses = None if mu == 0 else mu
    except Exception:
        c.max_uses = None

    try:
        if valid_from:
            c.valid_from = datetime.fromisoformat(valid_from)
        if valid_until:
            c.valid_until = datetime.fromisoformat(valid_until)
    except Exception:
        pass

    db.session.add(c)
    db.session.add(
        AdminActionLog(
            admin_user_id=_get_current_user_id(),
            action="coupon_create",
            meta={"code": code},
        )
    )
    db.session.commit()
    flash("Cupom criado.", "success")
    return redirect(url_for("admin.coupons"))


# -----------------------------------------------------------------------------
# Finance: impostos/custos (CRUD)
# -----------------------------------------------------------------------------
@admin_bp.route("/finance", methods=["GET", "POST"])
@require_perm("finance.view", "read")
def finance_items():
    if request.method == "POST":
        if not user_can(_get_current_user_id(), "finance.edit", "write"):
            abort(403)
        kind = request.form.get("kind")
        name = request.form.get("name")
        method = request.form.get("method")
        percent = request.form.get("percent")
        amount_cents = request.form.get("amount_cents")
        recurrence = request.form.get("recurrence") or "monthly"
        start_month = request.form.get("start_month")
        end_month = request.form.get("end_month") or None
        active = True if request.form.get("active") == "on" else False
        allocation_method = request.form.get("allocation_method") or "per_user_equal"
        cost_center = request.form.get("cost_center") or None
        if not (kind and name and method and start_month):
            flash("Preencha os campos obrigatórios.", "danger")
            return redirect(url_for("admin.finance_items"))
        sm_y, sm_m = map(int, start_month.split("-"))
        em_date = None
        if end_month:
            em_y, em_m = map(int, end_month.split("-"))
            em_date = datetime(em_y, em_m, 1).date()
        it = FinanceItem(
            kind=kind,
            name=name,
            method=method,
            recurrence=recurrence,
            start_month=datetime(sm_y, sm_m, 1).date(),
            end_month=em_date,
            active=active,
            allocation_method=allocation_method,
            cost_center=cost_center,
        )
        if method == "percent":
            it.percent = float(percent or 0)
        else:
            it.amount_cents = int(amount_cents or 0)
        db.session.add(it)
        db.session.add(
            AdminActionLog(
                admin_user_id=_get_current_user_id(),
                action="finance_edit",
                meta={"item": name},
            )
        )
        db.session.commit()
        flash("Item salvo.", "success")
        return redirect(url_for("admin.finance_items"))
    items = FinanceItem.query.order_by(
        FinanceItem.active.desc(), FinanceItem.start_month.desc()
    ).all()
    return render_template("admin_finance.html", items=items)


@admin_bp.route("/finance/<int:item_id>/toggle", methods=["POST"])
@require_perm("finance.edit", "write")
def finance_toggle(item_id):
    it = FinanceItem.query.get_or_404(item_id)
    it.active = not it.active
    db.session.add(
        AdminActionLog(
            admin_user_id=_get_current_user_id(),
            action="finance_toggle",
            meta={"item_id": item_id, "active": it.active},
        )
    )
    db.session.commit()
    flash("Item atualizado.", "success")
    return redirect(url_for("admin.finance_items"))


@admin_bp.route("/finance/<int:item_id>/delete", methods=["POST"])
@require_perm("finance.edit", "write")
def finance_delete(item_id):
    it = FinanceItem.query.get_or_404(item_id)
    db.session.delete(it)
    db.session.add(
        AdminActionLog(
            admin_user_id=_get_current_user_id(),
            action="finance_delete",
            meta={"item_id": item_id},
        )
    )
    db.session.commit()
    flash("Item removido.", "success")
    return redirect(url_for("admin.finance_items"))


# -----------------------------------------------------------------------------
# Cupons (CRUD)
# -----------------------------------------------------------------------------
def _as_bool(v) -> bool:
    return str(v).strip().lower() in ("on", "1", "true", "yes", "y")


@admin_bp.route("/coupons", methods=["GET"])
@require_perm("coupons.view", "read")
def coupons():
    coupons = Coupon.query.order_by(Coupon.code).all()
    return render_template("admin_coupons.html", coupons=coupons)


@admin_bp.route("/coupons/<int:coupon_id>/edit", methods=["GET", "POST"])
@require_perm("coupons.edit", "write")
def coupon_edit(coupon_id):
    c = Coupon.query.get_or_404(coupon_id)
    if request.method == "POST":
        c.description = (request.form.get("description") or "").strip() or None
        c.discount_type = (request.form.get("discount_type") or "").strip()
        c.discount_value = int(request.form.get("discount_value") or 0)

        max_uses_raw = request.form.get("max_uses")
        try:
            max_uses = (
                int(max_uses_raw)
                if max_uses_raw
                not in (
                    None,
                    "",
                )
                else None
            )
            c.max_uses = None if (max_uses is None or max_uses == 0) else max_uses
        except Exception:
            c.max_uses = None

        c.recurring = _as_bool(request.form.get("recurring"))
        c.active = _as_bool(request.form.get("active"))

        vf = request.form.get("valid_from")
        vu = request.form.get("valid_until")
        try:
            c.valid_from = datetime.fromisoformat(vf) if vf else None
            c.valid_until = datetime.fromisoformat(vu) if vu else None
        except Exception:
            pass

        db.session.add(
            AdminActionLog(
                admin_user_id=_get_current_user_id(),
                action="coupon_edit",
                meta={"coupon_id": coupon_id},
            )
        )
        db.session.commit()
        flash("Cupom atualizado.", "success")
        return redirect(url_for("admin.coupons"))

    # GET -> renderizar um template simples de edição
    return render_template("admin_coupon_edit.html", c=c)


@admin_bp.route("/coupons/<int:coupon_id>/toggle", methods=["POST"])
@require_perm("coupons.edit", "write")
def coupon_toggle(coupon_id):
    c = Coupon.query.get_or_404(coupon_id)
    c.active = not c.active
    db.session.add(
        AdminActionLog(
            admin_user_id=_get_current_user_id(),
            action="coupon_toggle",
            meta={"coupon_id": coupon_id, "active": c.active},
        )
    )
    db.session.commit()
    flash("Cupom atualizado.", "success")
    return redirect(url_for("admin.coupons"))


@admin_bp.route("/coupons/<int:coupon_id>/delete", methods=["POST"])
@require_perm("coupons.edit", "write")
def coupon_delete(coupon_id):
    c = Coupon.query.get_or_404(coupon_id)
    db.session.delete(c)
    db.session.add(
        AdminActionLog(
            admin_user_id=_get_current_user_id(),
            action="coupon_delete",
            meta={"coupon_id": coupon_id},
        )
    )
    db.session.commit()
    flash("Cupom removido.", "success")
    return redirect(url_for("admin.coupons"))


# -----------------------------------------------------------------------------
# Campanhas/E-mails (segmentos simples + template HTML)
# -----------------------------------------------------------------------------
def _resolve_segment(segment: str):
    q = UserSettings.query
    now = agora_brt()
    if segment == "pro":
        return q.filter(UserSettings.plano.in_(["pro", "pro_anual"]))
    if segment == "business":
        return q.filter(UserSettings.plano.in_(["business", "business_anual"]))
    if segment == "trial_expiring":
        # aqui, como o projeto atual não tem trial explícito, exemplo: planos pagos vencendo em 7 dias
        return q.filter(
            UserSettings.plano != "free",
            UserSettings.plano_ate != None,
            UserSettings.plano_ate <= (now + timedelta(days=7)),
        )
    return q  # all


def _render_template_html(html: str, vars_dict: Dict[str, str]) -> str:
    out = html or ""
    for k, v in (vars_dict or {}).items():
        out = out.replace(f"{{{{{k}}}}}", str(v))
    return out
@lru_cache(maxsize=1)
def get_historical_sync_prices():
    defaults = {
        "30": {"price_cents": 990, "currency": "BRL"},
        "60": {"price_cents": 1490, "currency": "BRL"},
        "90": {"price_cents": 1990, "currency": "BRL"},
        "180": {"price_cents": 3490, "currency": "BRL"},
    }

    rows = HistoricalSyncPrice.query.all()
    if not rows:
        return defaults

    out = {}
    for r in rows:
        out[r.period] = {
            "price_cents": r.price_cents,
            "currency": r.currency or "BRL"
        }

    # Garante defaults para períodos não criados no banco
    for p, v in defaults.items():
        out.setdefault(p, v)

    return out
def invalidate_historical_cache():
    get_historical_sync_prices.cache_clear()

@admin_bp.route("/pricing/historical", methods=["GET", "POST"])
def admin_historical_pricing():
    prices = get_historical_sync_prices()

    if request.method == "POST":
        for period in ["30", "60", "90", "180"]:
            field_name = f"price_{period}"
            value = request.form.get(field_name)
            if not value:
                continue

            # converte "9.90" para cents
            value_cents = int(float(value.replace(",", ".")) * 100)

            row = HistoricalSyncPrice.query.filter_by(period=period).first()
            if not row:
                row = HistoricalSyncPrice(period=period)

            row.price_cents = value_cents
            db.session.add(row)

        db.session.commit()
        invalidate_historical_cache()
        flash("Preços atualizados!", "success")

        # 🔥 CORREÇÃO AQUI — volta para /admin/pricing
        return redirect(url_for("admin.pricing"))

    return render_template("admin_historical_pricing.html", prices=prices)



@admin_bp.route("/broadcast", methods=["GET", "POST"])
@require_perm("emails.view", "read")
def broadcast():
    if request.method == "POST":
        if not user_can(_get_current_user_id(), "emails.send", "write"):
            abort(403)
        segment = request.form.get("segment") or "all"
        template_key = request.form.get("template_key")
        t = EmailTemplate.query.filter_by(key=template_key).first()
        if not t:
            flash("Template não encontrado.", "danger")
            return redirect(url_for("admin.broadcast"))
        users = _resolve_segment(segment)
        sent = 0
        for s in users.all():
            # Email do contato: decrypt no teu settings (se vier criptografado)
            email = (
                User.query.get(s.user_id).email if User.query.get(s.user_id) else None
            )
            if not email:
                continue
            html = _render_template_html(
                t.html, {"nome_empresa": s.business_name or "Cliente"}
            )
            try:
                enviar_email(destinatario=email, assunto=t.subject, corpo_html=html)
                sent += 1
            except Exception:
                continue
        db.session.add(
            AdminActionLog(
                admin_user_id=_get_current_user_id(),
                action="broadcast",
                meta={"template": template_key, "segment": segment, "count": sent},
            )
        )
        db.session.commit()
        flash(f"E-mail enviado para {sent} contas.", "success")
        return redirect(url_for("admin.broadcast"))
    templates = EmailTemplate.query.order_by(EmailTemplate.key).all()
    return render_template("admin_broadcast.html", templates=templates)


# -----------------------------------------------------------------------------
# Cobrança automática: webhook de falha + D+1/D+2 + manual
# -----------------------------------------------------------------------------
def _send_billing_email(user_id: str, template_key: str, event_id: int):
    # Usa EmailTemplate (tabela) + enviar_email
    u = User.query.get(user_id)
    if not u or not u.email:
        return
    exists = MessageLog.query.filter_by(
        user_id=user_id,
        channel="email",
        template_key=template_key,
        event_ref_id=event_id,
    ).first()
    if exists:
        return
    t = EmailTemplate.query.filter_by(key=template_key).first()
    if not t:
        return
    html = _render_template_html(
        t.html,
        {
            "nome_empresa": (
                UserSettings.query.filter_by(user_id=user_id).first() or UserSettings()
            ).business_name
            or "Cliente"
        },
    )
    enviar_email(destinatario=u.email, assunto=t.subject, corpo_html=html)
    db.session.add(
        MessageLog(
            user_id=user_id,
            channel="email",
            template_key=template_key,
            event_ref_id=event_id,
        )
    )
    db.session.commit()


@admin_bp.route("/webhooks/payment_failed", methods=["POST"])
def payment_failed_webhook():
    data = request.get_json(silent=True) or {}
    ext_id = (data.get("event_id") or data.get("charge_id") or "")[:128]
    user_id = (data.get("user_id") or "").strip()
    if not user_id:
        return jsonify({"ok": False, "error": "missing user_id"}), 400
    ev = BillingEvent.query.filter_by(
        event="payment_failed", external_id=ext_id
    ).first()
    if not ev:
        ev = BillingEvent(user_id=user_id, event="payment_failed", external_id=ext_id)
        db.session.add(ev)
        db.session.commit()
    if not ev.handled_immediate:
        _send_billing_email(user_id, "billing_failed_immediate", ev.id)
        ev.handled_immediate = True
        db.session.commit()
    return jsonify({"ok": True})


def run_daily_billing_followups():
    now = agora_brt()
    events = BillingEvent.query.filter_by(event="payment_failed").all()
    for ev in events:
        if (
            ev.handled_immediate
            and not ev.sent_day1
            and (now - ev.occurred_at) >= timedelta(days=1)
        ):
            _send_billing_email(ev.user_id, "billing_failed_day1", ev.id)
            ev.sent_day1 = True
        if (
            ev.handled_immediate
            and not ev.sent_day2
            and (now - ev.occurred_at) >= timedelta(days=2)
        ):
            _send_billing_email(ev.user_id, "billing_failed_day2", ev.id)
            ev.sent_day2 = True
    db.session.commit()


@admin_bp.route("/overdue/send_now", methods=["POST"])
@require_perm("delinquent.contact", "write")
def overdue_send_now():
    template = EmailTemplate.query.filter_by(key="billing_overdue_manual").first()
    uid = request.form.get("user_id")
    if not (template and uid):
        abort(400)
    u = User.query.get(uid)
    if u and u.email:
        html = _render_template_html(
            template.html,
            {
                "nome_empresa": (
                    UserSettings.query.filter_by(user_id=uid).first() or UserSettings()
                ).business_name
                or "Cliente"
            },
        )
        enviar_email(destinatario=u.email, assunto=template.subject, corpo_html=html)
        db.session.add(
            AdminActionLog(
                admin_user_id=_get_current_user_id(),
                action="overdue_send_now",
                target_user_id=uid,
            )
        )
        db.session.commit()
    flash("Cobrança enviada.", "success")
    return redirect(url_for("admin.dashboard"))


# -----------------------------------------------------------------------------
# Inadimplentes (lista simples)
# -----------------------------------------------------------------------------
@admin_bp.route("/delinquent", methods=["GET"])
@require_perm("delinquent.view", "read")
def delinquent_list():
    now = agora_brt()
    rows = (
        UserSettings.query.filter(UserSettings.plano != "free")
        .filter(or_(UserSettings.plano_ate == None, UserSettings.plano_ate < now))
        .all()
    )
    return render_template("admin_delinquent.html", rows=rows)


# -----------------------------------------------------------------------------
# Acesso (convites, papéis e overrides)
# -----------------------------------------------------------------------------
@admin_bp.route("/access", methods=["GET", "POST"])
@require_perm("access.manage_roles", "write")
def access():
    if request.method == "POST":
        action = request.form.get("action")
        target_email = (request.form.get("user_email") or "").strip().lower()
        target = User.query.filter_by(email=target_email).first()
        if not target:
            flash(
                "Usuário não encontrado (ele precisa logar com Google ao menos 1x).",
                "warning",
            )
            return redirect(url_for("admin.access"))

        if action == "set_role":
            role_key = request.form.get("role_key")
            role = Role.query.filter_by(key=role_key).first()
            if not role:
                flash("Papel inválido.", "danger")
                return redirect(url_for("admin.access"))
            current = UserRole.query.filter_by(user_id=target.id).first()
            if not current:
                db.session.add(UserRole(user_id=target.id, role_id=role.id))
            else:
                current.role_id = role.id
            db.session.add(
                AdminActionLog(
                    admin_user_id=_get_current_user_id(),
                    target_user_id=target.id,
                    action="change_role",
                    meta={"role": role_key},
                )
            )
            db.session.commit()
            flash("Papel atualizado.", "success")
            return redirect(url_for("admin.access"))

        if action == "set_perm":
            perm = request.form.get("perm")
            level = request.form.get("level")  # none|read|write
            if perm not in PERMISSIONS_ALL:
                flash("Permissão inválida.", "danger")
                return redirect(url_for("admin.access"))
            up = UserPermissionOverride.query.filter_by(
                user_id=target.id, perm=perm
            ).first()
            if not up:
                db.session.add(
                    UserPermissionOverride(user_id=target.id, perm=perm, level=level)
                )
            else:
                up.level = level
            db.session.add(
                AdminActionLog(
                    admin_user_id=_get_current_user_id(),
                    target_user_id=target.id,
                    action="change_perm",
                    meta={"perm": perm, "level": level},
                )
            )
            db.session.commit()
            flash("Permissão atualizada.", "success")
            return redirect(url_for("admin.access"))

        if action == "reset_overrides":
            UserPermissionOverride.query.filter_by(user_id=target.id).delete()
            db.session.add(
                AdminActionLog(
                    admin_user_id=_get_current_user_id(),
                    target_user_id=target.id,
                    action="change_perm",
                    meta={"reset": True},
                )
            )
            db.session.commit()
            flash("Overrides resetados.", "success")
            return redirect(url_for("admin.access"))

    roles = Role.query.order_by(Role.name).all()
    users = User.query.order_by(User.email).all()
    role_map = {ur.user_id: ur.role_id for ur in UserRole.query.all()}
    overrides = UserPermissionOverride.query.all()
    return render_template(
        "admin_access.html",
        roles=roles,
        users=users,
        role_map=role_map,
        overrides=overrides,
        PERMISSIONS_ALL=PERMISSIONS_ALL,
    )


# -----------------------------------------------------------------------------
# Permissões padrão por papel (seeds sugeridos)
# -----------------------------------------------------------------------------
PERMISSIONS_ALL = [
    "dashboard.view",
    "finance.view",
    "finance.edit",
    "pricing.view",
    "pricing.edit",
    "transactions.view",
    "transactions.export",
    "coupons.view",
    "coupons.edit",
    "emails.view",
    "emails.send",
    "templates.edit",
    "delinquent.view",
    "delinquent.contact",
    "tickets.view",
    "tickets.edit",
    "access.manage_roles",
]


def seed_roles_permissions():
    # Cria papéis e permissões padrão se não existirem
    defaults = {
        "admin": {
            "name": "Administrador",
            "perms": {p: "write" for p in PERMISSIONS_ALL},
        },
        "financeiro": {
            "name": "Financeiro",
            "perms": {
                "dashboard.view": "read",
                "finance.view": "write",
                "finance.edit": "write",
                "transactions.view": "read",
                "transactions.export": "write",
                "delinquent.view": "read",
                "delinquent.contact": "write",
            },
        },
        "diretoria": {
            "name": "Diretoria",
            "perms": {
                "dashboard.view": "read",
                "finance.view": "read",
                "transactions.view": "read",
                "delinquent.view": "read",
            },
        },
        "marketing_email": {
            "name": "Marketing (E-mail)",
            "perms": {
                "emails.view": "read",
                "emails.send": "write",
                "templates.edit": "write",
            },
        },
        "suporte": {
            "name": "Suporte",
            "perms": {
                "tickets.view": "write",
                "tickets.edit": "write",
                "delinquent.view": "read",
            },
        },
    }
    for key, cfg in defaults.items():
        role = Role.query.filter_by(key=key).first()
        if not role:
            role = Role(key=key, name=cfg["name"])
            db.session.add(role)
            db.session.commit()
        # Upsert de permissões
        for perm, level in cfg["perms"].items():
            rp = RolePermission.query.filter_by(role_id=role.id, perm=perm).first()
            if not rp:
                db.session.add(RolePermission(role_id=role.id, perm=perm, level=level))
            else:
                rp.level = level
    db.session.commit()


# -----------------------------------------------------------------------------
# TICKETS / ATIVIDADES (CRM-Lite) – rotas básicas de exemplo
# -----------------------------------------------------------------------------
@admin_bp.route("/tickets", methods=["GET", "POST"])
@require_perm("tickets.view", "read")
def tickets_board():
    if request.method == "POST":
        if not user_can(_get_current_user_id(), "tickets.edit", "write"):
            abort(403)
        company_id = request.form.get("company_id")
        assunto = request.form.get("assunto")
        prioridade = request.form.get("prioridade") or "normal"
        if not (company_id and assunto):
            flash("Informe empresa e assunto.", "danger")
            return redirect(url_for("admin.tickets_board"))
        t = Ticket(
            company_id=int(company_id),
            assunto=assunto,
            prioridade=prioridade,
            owner_id=_get_current_user_id(),
        )
        db.session.add(t)
        db.session.commit()
        flash("Ticket criado.", "success")
        return redirect(url_for("admin.tickets_board"))
    tickets = Ticket.query.order_by(Ticket.status, Ticket.updated_at.desc()).all()
    companies = Company.query.order_by(Company.name).all()
    return render_template("admin_tickets.html", tickets=tickets, companies=companies)


@admin_bp.route("/tickets/<int:tid>/move", methods=["POST"])
@require_perm("tickets.edit", "write")
def tickets_move(tid):
    t = Ticket.query.get_or_404(tid)
    new_status = request.form.get("status")  # aberto|pendente|resolvido
    if new_status not in ("aberto", "pendente", "resolvido"):
        abort(400)
    t.status = new_status
    db.session.commit()
    return redirect(url_for("admin.tickets_board"))


# --- Helpers de catálogo de planos ---
PLAN_META = {
    "free": {"nome": "Free", "duration_days": 0},
    "pro": {"nome": "Pro", "duration_days": 30},
    "pro_anual": {"nome": "Pro Anual", "duration_days": 365},
    "business": {"nome": "Business", "duration_days": 30},
    "business_anual": {"nome": "Business Anual", "duration_days": 365},
}


def get_plan_display_name(plan_key: str) -> str:
    return (PLAN_META.get(plan_key) or {}).get("nome", plan_key)


def get_plan_duration_days(plan_key: str) -> int:
    return int((PLAN_META.get(plan_key) or {}).get("duration_days", 0))


def get_pricing_catalog() -> dict:
    prices = get_plan_prices()
    out = {}
    for k in PLAN_KEYS:
        meta = PLAN_META.get(k, {})
        price = prices.get(k, {"price_cents": 0, "currency": "BRL"})
        out[k] = {
            "nome": meta.get("nome", k),
            "duration_days": meta.get("duration_days", 0),
            "price_cents": price["price_cents"],
            "currency": price.get("currency", "BRL"),
        }
    return out


@admin_bp.route("/access/logs", methods=["GET"])
@require_perm("access.manage_roles", "write")
def access_logs():
    # Aceita ?user_id=<id> OU ?email=<email>. Se vier user_id com "@", trata como e-mail.
    raw_uid = (request.args.get("user_id") or "").strip()
    raw_email = (request.args.get("email") or "").strip().lower()

    uid = None
    if raw_email:
        u = User.query.filter_by(email=raw_email).first()
        if not u:
            return jsonify({"ok": True, "logs": []})
        uid = str(u.id)
    elif raw_uid:
        if "@" in raw_uid:
            u = User.query.filter_by(email=raw_uid.lower()).first()
            if not u:
                return jsonify({"ok": True, "logs": []})
            uid = str(u.id)
        else:
            uid = raw_uid
    else:
        return jsonify({"ok": False, "error": "missing user_id or email"}), 400

    # Admin actions (preços, impostos/custos, cupons, acessos, broadcasts etc.)
    admin_rows = (
        AdminActionLog.query.filter(
            or_(
                AdminActionLog.target_user_id == uid,
                AdminActionLog.admin_user_id == uid,
            )
        )
        .order_by(AdminActionLog.id.desc())
        .limit(200)
        .all()
    )

    # Envios de e-mail (templates de cobrança, broadcast, etc.)
    email_rows = (
        MessageLog.query.filter_by(user_id=uid)
        .order_by(MessageLog.id.desc())
        .limit(200)
        .all()
    )

    # Eventos de cobrança (falhas e follow-ups)
    billing_rows = (
        BillingEvent.query.filter_by(user_id=uid)
        .order_by(BillingEvent.id.desc())
        .limit(200)
        .all()
    )

    def ts_or_none(obj):
        for attr in ("created_at", "occurred_at"):
            if getattr(obj, attr, None):
                return getattr(obj, attr).isoformat()
        return None

    def as_admin(l):
        return {
            "kind": "admin",
            "id": l.id,
            "ts": ts_or_none(l),
            "action": l.action,  # ex.: pricing_update, finance_edit, finance_toggle, finance_delete, coupon_create...
            "meta": l.meta or {},
            "actor_id": l.admin_user_id,
            "target_id": l.target_user_id,
        }

    def as_email(m):
        return {
            "kind": "email",
            "id": m.id,
            "ts": ts_or_none(m),
            "action": f"email:{m.template_key}",
            "meta": {
                "channel": m.channel,
                "template_key": m.template_key,
                "event_ref_id": m.event_ref_id,
            },
            "actor_id": None,
            "target_id": m.user_id,
        }

    def as_billing(b):
        return {
            "kind": "billing",
            "id": b.id,
            "ts": ts_or_none(b),
            "action": b.event,  # ex.: payment_failed
            "meta": {
                "external_id": b.external_id,
                "handled_immediate": getattr(b, "handled_immediate", None),
                "sent_day1": getattr(b, "sent_day1", None),
                "sent_day2": getattr(b, "sent_day2", None),
            },
            "actor_id": None,
            "target_id": b.user_id,
        }

    logs = [
        *map(as_admin, admin_rows),
        *map(as_email, email_rows),
        *map(as_billing, billing_rows),
    ]
    logs.sort(key=lambda x: (x["ts"] or "", x["id"]), reverse=True)

    return jsonify({"ok": True, "logs": logs})


@admin_bp.route("/companies/create", methods=["POST"])
@require_perm("tickets.edit", "write")
def company_create():
    name = (request.form.get("name") or "").strip()
    email = (request.form.get("email") or "").strip() or None
    phone = (request.form.get("phone") or "").strip() or None

    if not name:
        flash("Informe o nome da empresa.", "danger")
        return redirect(url_for("admin.tickets_board"))

    # Só passa atributos que o model realmente tem
    attrs = {"name": name}
    if hasattr(Company, "email") and email:
        attrs["email"] = email
    if hasattr(Company, "phone") and phone:
        attrs["phone"] = phone

    c = Company(**attrs)
    db.session.add(c)
    db.session.commit()
    flash("Empresa criada.", "success")
    return redirect(url_for("admin.tickets_board"))
import os

STRIPE_PRICE_IDS = {
    # planos recorrentes
    "pro_mensal": os.getenv("STRIPE_PRICE_PRO_MENSAL"),
    "pro_anual": os.getenv("STRIPE_PRICE_PRO_ANUAL"),
    "business_mensal": os.getenv("STRIPE_PRICE_BUSINESS_MENSAL"),
    "business_anual": os.getenv("STRIPE_PRICE_BUSINESS_ANUAL"),

    # add-ons de sincronização retroativa
    "retro_30": os.getenv("STRIPE_PRICE_RETRO_30"),
    "retro_60": os.getenv("STRIPE_PRICE_RETRO_60"),
    "retro_90": os.getenv("STRIPE_PRICE_RETRO_90"),
    "retro_180": os.getenv("STRIPE_PRICE_RETRO_180"),
}
