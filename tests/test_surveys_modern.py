# -*- coding: utf-8 -*-
import json
import pytest
from werkzeug.datastructures import MultiDict
from main import app, db, User, UserSettings
from models import Company
from models_pesquisa import PesquisaConfig, PesquisaPergunta, PesquisaEnvio, PesquisaRespostaItem

def test_survey_creation_and_booster_flow():
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    client = app.test_client()

    with app.app_context():
        # Setup company and user
        user = User.query.filter_by(id="test_survey_user").first()
        if not user:
            user = User(id="test_survey_user", email="survey_tester@example.com")
            db.session.add(user)
        
        settings = UserSettings.query.filter_by(user_id="test_survey_user").first()
        if not settings:
            settings = UserSettings(user_id="test_survey_user", plano="pro")
            db.session.add(settings)
        else:
            settings.plano = "pro"
            
        company = Company.query.filter_by(owner_user_id="test_survey_user").first()
        if not company:
            company = Company(owner_user_id="test_survey_user", name="Empresa Teste", segmento="Restaurante")
            db.session.add(company)
            
        db.session.commit()

        # 1. Test Survey Creation POST with MultiDict
        slug_teste = "pesquisa-teste-moderna"
        p_old = PesquisaConfig.query.filter_by(slug=slug_teste).first()
        if p_old:
            db.session.delete(p_old)
            db.session.commit()

        with client.session_transaction() as sess:
            sess['user_id'] = 'test_survey_user'
            sess['user_info'] = {'id': 'test_survey_user', 'email': 'survey_tester@example.com'}
            sess['plano'] = 'pro'

        post_data = MultiDict([
            ("titulo", "Pesquisa de Satisfação VIP"),
            ("subtitulo", "Queremos saber como foi sua experiência"),
            ("slug", slug_teste),
            ("link_google_feedback", "https://g.page/r/teste/review"),
            ("redirecionar_positivo_auto", "true"),
            ("pergunta_gatilho_idx", "0"),
            ("pergunta_texto[]", "Qual a sua nota para o nosso atendimento?"),
            ("pergunta_tipo[]", "estrelas"),
            ("pergunta_obrigatoria_raw[]", "true"),
            ("pergunta_opcoes[]", ""),
            
            ("pergunta_texto[]", "Em uma escala de 0 a 10, você nos recomendaria?"),
            ("pergunta_tipo[]", "nps"),
            ("pergunta_obrigatoria_raw[]", "false"),
            ("pergunta_opcoes[]", ""),
            
            ("pergunta_texto[]", "Como você avalia nosso ambiente?"),
            ("pergunta_tipo[]", "emojis"),
            ("pergunta_obrigatoria_raw[]", "false"),
            ("pergunta_opcoes[]", ""),

            ("pergunta_texto[]", "O que você mais gostou?"),
            ("pergunta_tipo[]", "multipla_escolha"),
            ("pergunta_obrigatoria_raw[]", "false"),
            ("pergunta_opcoes[]", "Comida, Atendimento, Ambiente, Rapidez"),

            ("pergunta_texto[]", "Deixe seu comentário:"),
            ("pergunta_tipo[]", "texto"),
            ("pergunta_obrigatoria_raw[]", "false"),
            ("pergunta_opcoes[]", "")
        ])

        res_criar = client.post("/dashboard/pesquisa/criar", data=post_data, follow_redirects=True)
        assert res_criar.status_code == 200

        pesquisa = PesquisaConfig.query.filter_by(slug=slug_teste).first()
        assert pesquisa is not None
        assert len(pesquisa.perguntas) == 5
        assert pesquisa.link_google_feedback == "https://g.page/r/teste/review"

        # 2. Test Public Survey Rendering
        res_pub = client.get(f"/p/{slug_teste}")
        assert res_pub.status_code == 200
        html_pub = res_pub.data.decode("utf-8")
        assert "Pesquisa de Satisfação VIP" in html_pub
        assert "modalGoogleBooster" in html_pub

        # 3. Test 5-Star AJAX Submission (Triggering Google Booster)
        p_stars = pesquisa.perguntas[0]
        p_nps = pesquisa.perguntas[1]
        p_emoji = pesquisa.perguntas[2]
        p_mc = pesquisa.perguntas[3]
        p_text = pesquisa.perguntas[4]

        envio_5star = {
            "is_ajax": "true",
            "nome": "Carlos Silva",
            "email": "carlos@example.com",
            "whatsapp": "11999998888",
            f"pergunta_{p_stars.id}": "5",
            f"pergunta_{p_nps.id}": "10",
            f"pergunta_{p_emoji.id}": "5",
            f"pergunta_{p_mc.id}": "Comida",
            f"pergunta_{p_text.id}": "O atendimento foi sensacional e a comida maravilhosa!"
        }

        res_env_5 = client.post(
            f"/p/{slug_teste}/enviar",
            data=envio_5star,
            headers={"X-Requested-With": "XMLHttpRequest"}
        )
        assert res_env_5.status_code == 200
        data_5 = res_env_5.get_json()
        assert data_5["success"] is True
        assert data_5["elegivel_google"] is True
        assert data_5["link_google"] == "https://g.page/r/teste/review"
        assert "O atendimento foi sensacional" in data_5["comentario_cliente"]

        # 4. Test 2-Star AJAX Submission (Internal retention, no Google redirect)
        with client.session_transaction() as sess:
            sess[f"pesquisa_enviada_{slug_teste}"] = None # Reset session lock for test

        envio_2star = {
            "is_ajax": "true",
            "nome": "Mariana Souza",
            "email": "mariana@example.com",
            "whatsapp": "21988887777",
            f"pergunta_{p_stars.id}": "2",
            f"pergunta_{p_nps.id}": "3",
            f"pergunta_{p_emoji.id}": "2",
            f"pergunta_{p_mc.id}": "Rapidez",
            f"pergunta_{p_text.id}": "Demorou bastante para chegar a conta."
        }

        res_env_2 = client.post(
            f"/p/{slug_teste}/enviar",
            data=envio_2star,
            headers={"X-Requested-With": "XMLHttpRequest"}
        )
        assert res_env_2.status_code == 200
        data_2 = res_env_2.get_json()
        assert data_2["success"] is True
        assert data_2["elegivel_google"] is False

        # 5. Test Executive Results Dashboard & Metrics
        res_resp = client.get(f"/dashboard/pesquisa/{pesquisa.id}/respostas")
        assert res_resp.status_code == 200
        html_resp = res_resp.data.decode("utf-8")
        assert "Carlos Silva" in html_resp
        assert "Mariana Souza" in html_resp
        assert "sentimentDonutChart" in html_resp
        assert "WhatsApp" in html_resp

        # 6. Test CSV Export
        res_csv = client.get(f"/dashboard/pesquisa/{pesquisa.id}/exportar_csv")
        assert res_csv.status_code == 200
        assert "attachment;filename=" in res_csv.headers.get("Content-Disposition", "")
        csv_content = res_csv.data.decode("utf-8-sig")
        assert "Carlos Silva" in csv_content
        assert "Mariana Souza" in csv_content

        print("=== ALL SURVEY TESTS PASSED WITH 100% SUCCESS! ===")
