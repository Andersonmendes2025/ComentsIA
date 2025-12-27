import os
import time
import base64
from typing import Any, Dict, List, Optional

import requests
from flask import Blueprint, jsonify, request, current_app

# ============================================================
# CONFIGURAÇÃO BÁSICA
# ============================================================

RA_BASE_URL = os.getenv("RA_BASE_URL", "https://app.hugme.com.br")
# Valor recomendado: "client_id:client_secret" da aplicação RA API
RA_CLIENT_ID = os.getenv("RA_CLIENT_ID", "")
RA_CLIENT_SECRET = os.getenv("RA_CLIENT_SECRET", "")

# Se quiser, pode já setar o Authorization Basic pronto:
# export RA_BASIC_AUTH="Basic dXNlcjpwYXNz"
RA_BASIC_AUTH = os.getenv("RA_BASIC_AUTH")

# Limite padrão da API RA: 10 chamadas por minuto
RA_RATE_LIMIT_PER_MIN = int(os.getenv("RA_RATE_LIMIT_PER_MIN", "10"))


class ReclameAquiError(Exception):
    """Erro genérico da integração com Reclame Aqui."""
    pass


# ============================================================
# CLIENTE PRINCIPAL DA API RA
# ============================================================

class ReclameAquiClient:
    def __init__(self):
        self.base_url = RA_BASE_URL.rstrip("/")
        self.client_id = RA_CLIENT_ID
        self.client_secret = RA_CLIENT_SECRET
        self.basic_auth = RA_BASIC_AUTH or self._build_basic_auth()

        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0.0

        # Rate limit simples em memória
        self._call_timestamps: List[float] = []

    # --------------------------
    # Autenticação
    # --------------------------
    def _build_basic_auth(self) -> str:
        if not self.client_id or not self.client_secret:
            raise ReclameAquiError(
                "RA_CLIENT_ID e RA_CLIENT_SECRET não configurados e RA_BASIC_AUTH não informado."
            )
        raw = f"{self.client_id}:{self.client_secret}".encode("utf-8")
        return "Basic " + base64.b64encode(raw).decode("utf-8")

    def _check_rate_limit(self):
        """Aplica um rate limit simples de 10 req/min (por processo)."""
        now = time.time()
        # remove chamadas com mais de 60s
        self._call_timestamps = [t for t in self._call_timestamps if now - t < 60]

        if len(self._call_timestamps) >= RA_RATE_LIMIT_PER_MIN:
            raise ReclameAquiError(
                "Limite de 10 chamadas por minuto para RA API atingido neste processo."
            )

        self._call_timestamps.append(now)

    def get_auth_availability(self) -> Dict[str, Any]:
        """GET /api/auth/availability"""
        url = f"{self.base_url}/api/auth/availability"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def _refresh_access_token(self):
        """POST /api/auth/oauth/token?grant_type=client_credentials"""
        url = f"{self.base_url}/api/auth/oauth/token"
        params = {"grant_type": "client_credentials"}
        headers = {"Authorization": self.basic_auth}

        self._check_rate_limit()
        resp = requests.post(url, params=params, headers=headers, timeout=15)
        if resp.status_code != 200:
            raise ReclameAquiError(
                f"Erro ao obter access_token RA: {resp.status_code} - {resp.text}"
            )

        data = resp.json()
        self._access_token = data.get("access_token")
        expires_in = data.get("expires_in", 300)
        # guarda com uma folga de 30s
        self._token_expires_at = time.time() + expires_in - 30

    def _get_access_token(self) -> str:
        if not self._access_token or time.time() >= self._token_expires_at:
            self._refresh_access_token()
        return self._access_token

    # --------------------------
    # Helper HTTP
    # --------------------------
    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        files: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        expected_status: Optional[List[int]] = None,
    ) -> requests.Response:
        """
        Envia uma requisição autenticada para a API do RA.
        """
        self._check_rate_limit()
        token = self._get_access_token()

        url = f"{self.base_url}{path}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

        if json_body is not None and files is None:
            headers["Content-Type"] = "application/json"

        resp = requests.request(
            method,
            url,
            params=params,
            json=json_body,
            data=data,
            files=files,
            headers=headers,
            timeout=30,
        )

        if expected_status is None:
            expected_status = [200]

        if resp.status_code not in expected_status:
            # tenta tratar erros no padrão novo da RA API
            try:
                err = resp.json()
            except Exception:
                err = {"raw": resp.text}

            raise ReclameAquiError(
                f"Erro RA API [{resp.status_code}] em {path}: {err}"
            )

        return resp

    # ========================================================
    # ENDPOINTS: TICKETS
    # ========================================================

    def get_ticket_availability(self) -> Dict[str, Any]:
        """GET /api/ticket/availability"""
        resp = self._request("GET", "/api/ticket/availability")
        return resp.json()

    def get_tickets(
        self,
        source_name: Optional[str] = None,
        page_size: int = 20,
        page_number: int = 1,
        sort_creation_date: str = "desc",
    ) -> Dict[str, Any]:
        """
        GET /api/ticket/v1/tickets
        """
        params: Dict[str, Any] = {
            "page[size]": page_size,
            "page[number]": page_number,
            "sort[creation_date]": sort_creation_date,
        }

        if source_name is not None:
            params["source.name[eq]"] = source_name

        resp = self._request("GET", "/api/ticket/v1/tickets", params=params)
        return resp.json()

    def get_ticket_by_id(self, ticket_id: int) -> Dict[str, Any]:
        """
        GET /api/ticket/v1/tickets?id[eq]=<ticket_id>
        """
        params = {"id[eq]": ticket_id}
        resp = self._request("GET", "/api/ticket/v1/tickets", params=params)
        return resp.json()

    def get_ticket_count(self) -> int:
        """
        GET /api/ticket/v1/tickets/count
        """
        resp = self._request("GET", "/api/ticket/v1/tickets/count")
        data = resp.json()
        return int(data.get("data", 0))

    def get_ticket_attachment_link(self, type_detail_id: int) -> Dict[str, Any]:
        """
        GET /api/ticket/v1/tickets/attachment/{typeDetailId}
        """
        path = f"/api/ticket/v1/tickets/attachment/{type_detail_id}"
        resp = self._request("GET", path)
        return resp.json()

    # ========================================================
    # ENDPOINTS: EMPRESAS / REPUTAÇÃO / WHATSAPP
    # ========================================================

    def get_organization_companies(self) -> List[Dict[str, Any]]:
        """
        GET /api/companies/v1/companies/organization
        """
        resp = self._request("GET", "/api/companies/v1/companies/organization")
        return resp.json()

    def search_companies(
        self, company_name: str, page: int = 1, limit: int = 15
    ) -> List[Dict[str, Any]]:
        """
        GET /api/ticket/v1/tickets/moderation/companies?companyName=Reclame&page=1&limit=15
        """
        params = {"companyName": company_name, "page": page, "limit": limit}
        resp = self._request(
            "GET", "/api/ticket/v1/tickets/moderation/companies", params=params
        )
        return resp.json()

    def get_company_reputation(self, company_id: int) -> List[Dict[str, Any]]:
        """
        GET /api/companies/v1/companies/{companyId}/reputation
        """
        path = f"/api/companies/v1/companies/{company_id}/reputation"
        resp = self._request("GET", path)
        return resp.json()

    def get_whatsapp_consumption(self) -> Dict[str, Any]:
        """
        GET /api/companies/v1/companies/organization/whatsapp/consumption
        """
        resp = self._request(
            "GET", "/api/companies/v1/companies/organization/whatsapp/consumption"
        )
        return resp.json()

    # ========================================================
    # ENDPOINTS: AVALIAÇÃO, MODERAÇÃO E MENSAGENS
    # ========================================================

    def request_ticket_evaluation(self, ticket_id: int) -> Dict[str, Any]:
        """
        POST /api/ticket/v1/tickets/evaluation
        body: { "id": "2856434" }
        """
        payload = {"id": str(ticket_id)}
        resp = self._request(
            "POST",
            "/api/ticket/v1/tickets/evaluation",
            json_body=payload,
            expected_status=[200],
        )
        return resp.json()

    def request_ticket_moderation(
        self,
        ticket_id: int,
        message: str,
        reason: str,
        file_path: Optional[str] = None,
        migrate_to: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        POST /api/ticket/v1/tickets/moderation (multipart/form-data)
        """
        data = {
            "id": str(ticket_id),
            "message": message,
            "reason": reason,
        }

        if migrate_to:
            data["migrateTO"] = migrate_to

        files = None
        if file_path:
            files = {
                "file": (
                    os.path.basename(file_path),
                    open(file_path, "rb"),
                    "application/octet-stream",
                )
            }

        resp = self._request(
            "POST",
            "/api/ticket/v1/tickets/moderation",
            data=data,
            files=files,
            expected_status=[200],
        )
        return resp.json()

    def send_private_message(
        self,
        ticket_id: int,
        message: str,
        email: str,
        file_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        POST /api/ticket/v1/tickets/message/private (multipart/form-data)
        """
        data = {
            "id": str(ticket_id),
            "message": message,
            "email": email,
        }

        files = None
        if file_path:
            files = {
                "file": (
                    os.path.basename(file_path),
                    open(file_path, "rb"),
                    "application/octet-stream",
                )
            }

        resp = self._request(
            "POST",
            "/api/ticket/v1/tickets/message/private",
            data=data,
            files=files,
            expected_status=[200],
        )
        return resp.json()

    def send_public_message(self, ticket_id: int, message: str) -> Dict[str, Any]:
        """
        POST /api/ticket/v1/tickets/message/public (multipart/form-data)
        """
        data = {
            "id": str(ticket_id),
            "message": message,
        }

        resp = self._request(
            "POST",
            "/api/ticket/v1/tickets/message/public",
            data=data,
            expected_status=[200],
        )
        return resp.json()

    def finish_private_message(self, ticket_id: int) -> Dict[str, Any]:
        """
        POST /api/ticket/v1/tickets/message/private/{ticketId}/end
        """
        path = f"/api/ticket/v1/tickets/message/private/{ticket_id}/end"
        resp = self._request("POST", path, expected_status=[200])
        return resp.json()


# ============================================================
# SINGLETON DO CLIENTE
# ============================================================

ra_client = ReclameAquiClient()

# ============================================================
# BLUEPRINT FLASK
# ============================================================

reclame_bp = Blueprint("reclame", __name__, url_prefix="/reclame")


@reclame_bp.route("/auth/test", methods=["GET"])
def test_auth():
    """
    Testa disponibilidade da autenticação RA.
    GET /reclame/auth/test
    """
    try:
        data = ra_client.get_auth_availability()
        return jsonify({"ok": True, "data": data})
    except Exception as e:
        current_app.logger.exception("Erro test_auth RA")
        return jsonify({"ok": False, "error": str(e)}), 500

@reclame_bp.route("/auth/token", methods=["GET"])
def ra_generate_token():
    """
    Gera um access_token usando o grant_type=client_credentials
    e as credenciais fornecidas pelo Reclame Aqui.
    """
    client_id = os.getenv("RA_CLIENT_ID")
    client_secret = os.getenv("RA_CLIENT_SECRET")

    if not client_id or not client_secret:
        return jsonify({
            "ok": False,
            "error": "Credenciais RA_CLIENT_ID ou RA_CLIENT_SECRET não definidas no .env"
        }), 500

    # Basic Auth codificado em base64 (user:pass)
    auth_string = f"{client_id}:{client_secret}"
    auth_b64 = base64.b64encode(auth_string.encode()).decode()

    url = "https://app.hugme.com.br/api/auth/oauth/token?grant_type=client_credentials"

    headers = {
        "Authorization": f"Basic {auth_b64}",
        "Content-Type": "application/json"
    }

    try:
        res = requests.post(url, headers=headers)
        data = res.json()
        return jsonify({
            "ok": res.status_code == 200,
            "status_code": res.status_code,
            "data": data
        })
    except Exception as e:
        return jsonify({
            "ok": False,
            "error": str(e)
        }), 500
 
@reclame_bp.route("/ticket/availability", methods=["GET"])
def ticket_availability():
    """
    Testa disponibilidade da Ticket API RA.
    GET /reclame/ticket/availability
    """
    try:
        data = ra_client.get_ticket_availability()
        return jsonify({"ok": True, "data": data})
    except Exception as e:
        current_app.logger.exception("Erro ticket_availability RA")
        return jsonify({"ok": False, "error": str(e)}), 500


@reclame_bp.route("/tickets", methods=["GET"])
def list_tickets():
    """
    Lista tickets do Reclame Aqui.
    GET /reclame/tickets?page=1&size=20
    """
    page = int(request.args.get("page", 1))
    size = int(request.args.get("size", 20))

    try:
        data = ra_client.get_tickets(page_size=size, page_number=page)
        return jsonify({"ok": True, "data": data})
    except Exception as e:
        current_app.logger.exception("Erro list_tickets RA")
        return jsonify({"ok": False, "error": str(e)}), 500


@reclame_bp.route("/tickets/<int:ticket_id>", methods=["GET"])
def get_ticket(ticket_id: int):
    """
    Recupera ticket pelo ID.
    GET /reclame/tickets/<ticket_id>
    """
    try:
        data = ra_client.get_ticket_by_id(ticket_id)
        return jsonify({"ok": True, "data": data})
    except Exception as e:
        current_app.logger.exception("Erro get_ticket RA")
        return jsonify({"ok": False, "error": str(e)}), 500


@reclame_bp.route("/tickets/<int:ticket_id>/respond", methods=["POST"])
def respond_ticket(ticket_id: int):
    """
    Envia UMA resposta pública simples para um ticket.
    POST /reclame/tickets/<ticket_id>/respond
    body: { "message": "texto da resposta" }
    """
    body = request.get_json(silent=True) or {}
    message = body.get("message")

    if not message:
        return jsonify({"ok": False, "error": "Campo 'message' é obrigatório."}), 400

    try:
        result = ra_client.send_public_message(ticket_id, message)
        # Aqui você pode:
        # - salvar resposta no banco Review
        # - marcar como respondido
        # - disparar e-mail pro gerente
        return jsonify({"ok": True, "result": result})
    except Exception as e:
        current_app.logger.exception("Erro respond_ticket RA")
        return jsonify({"ok": False, "error": str(e)}), 500


@reclame_bp.route("/companies", methods=["GET"])
def list_companies():
    """
    Lista empresas da organização vinculada à conta RA.
    GET /reclame/companies
    """
    try:
        data = ra_client.get_organization_companies()
        return jsonify({"ok": True, "data": data})
    except Exception as e:
        current_app.logger.exception("Erro list_companies RA")
        return jsonify({"ok": False, "error": str(e)}), 500


@reclame_bp.route("/companies/search", methods=["GET"])
def search_companies_route():
    """
    Busca empresas por nome para uso em moderação (migrateTO).
    GET /reclame/companies/search?name=Reclame&page=1&limit=15
    """
    name = request.args.get("name", "")
    page = int(request.args.get("page", 1))
    limit = int(request.args.get("limit", 15))

    if not name:
        return jsonify({"ok": False, "error": "Parâmetro 'name' é obrigatório."}), 400

    try:
        data = ra_client.search_companies(name, page=page, limit=limit)
        return jsonify({"ok": True, "data": data})
    except Exception as e:
        current_app.logger.exception("Erro search_companies RA")
        return jsonify({"ok": False, "error": str(e)}), 500


@reclame_bp.route("/reputation/<int:company_id>", methods=["GET"])
def company_reputation(company_id: int):
    """
    Recupera reputação da empresa.
    GET /reclame/reputation/<company_id>
    """
    try:
        data = ra_client.get_company_reputation(company_id)
        return jsonify({"ok": True, "data": data})
    except Exception as e:
        current_app.logger.exception("Erro company_reputation RA")
        return jsonify({"ok": False, "error": str(e)}), 500


@reclame_bp.route("/whatsapp/consumption", methods=["GET"])
def whatsapp_consumption():
    """
    Recupera consumo de WhatsApp do RA.
    GET /reclame/whatsapp/consumption
    """
    try:
        data = ra_client.get_whatsapp_consumption()
        return jsonify({"ok": True, "data": data})
    except Exception as e:
        current_app.logger.exception("Erro whatsapp_consumption RA")
        return jsonify({"ok": False, "error": str(e)}), 500


@reclame_bp.route("/tickets/<int:ticket_id>/evaluation", methods=["POST"])
def ticket_evaluation(ticket_id: int):
    """
    Solicita avaliação de ticket (RA pedir para o consumidor avaliar).
    POST /reclame/tickets/<ticket_id>/evaluation
    """
    try:
        data = ra_client.request_ticket_evaluation(ticket_id)
        return jsonify({"ok": True, "data": data})
    except Exception as e:
        current_app.logger.exception("Erro ticket_evaluation RA")
        return jsonify({"ok": False, "error": str(e)}), 500
