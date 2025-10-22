# -*- coding: utf-8 -*-
"""
Worker web service (Render) para processar uploads do Booking em background.
Start command no Render:  gunicorn worker:app --workers 1
"""

from __future__ import annotations

from flask import jsonify

from booking import _get_scheduler
from main import app  # reaproveita a app e config/DB do seu projeto

# liga o scheduler do booking
_get_scheduler()


# healthcheck simples para Render
@app.get("/health")
def health():
    return jsonify(ok=True)
