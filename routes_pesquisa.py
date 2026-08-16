import re
import json
import base64
import io
import csv
import qrcode
from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, jsonify, redirect, flash, url_for, session, Response, send_file
from models import db, Company
from models_pesquisa import PesquisaConfig, PesquisaPergunta, PesquisaEnvio, PesquisaRespostaItem
from flask_wtf.csrf import generate_csrf

pesquisa_bp = Blueprint("pesquisa", __name__)

@pesquisa_bp.route("/p/<string:slug>", methods=["GET"])
def renderizar_pesquisa(slug):
    """Página pública para o cliente final responder à pesquisa."""
    config = PesquisaConfig.query.filter_by(slug=slug, is_active=True).first_or_404()
    return render_template("pesquisa_publica.html", config=config)


@pesquisa_bp.route("/p/<string:slug>/enviar", methods=["POST"])
def enviar_resposta(slug):
    """Processa a resposta do formulário com suporte a AJAX e Booster Google."""
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.is_json or request.form.get("is_ajax") == "true"
    
    # --- 🛡️ CAMADA 1: BLINDAGEM DE SESSÃO (EVITAR DUPLICAÇÃO) ---
    session_key = f"pesquisa_enviada_{slug}"
    ultimo_envio_str = session.get(session_key)
    
    if ultimo_envio_str:
        try:
            ultimo_envio = datetime.fromisoformat(ultimo_envio_str)
            if datetime.now() < ultimo_envio + timedelta(minutes=5):
                if is_ajax:
                    return jsonify({
                        "success": True,
                        "already_submitted": True,
                        "message": "Pesquisa já enviada recentemente."
                    })
                return redirect(url_for("pesquisa.renderizar_pesquisa", slug=slug, sucesso="true"))
        except ValueError:
            pass

    config = PesquisaConfig.query.filter_by(slug=slug, is_active=True).first_or_404()
    
    nome = (request.form.get("nome") or "").strip()
    email = (request.form.get("email") or "").strip()
    whatsapp = (request.form.get("whatsapp") or "").strip()

    envio = PesquisaEnvio(
        pesquisa_config_id=config.id,
        cliente_nome=nome if nome else None,
        cliente_email=email if email else None,
        cliente_whatsapp=whatsapp if whatsapp else None
    )
    db.session.add(envio)
    db.session.flush()

    redirecionar_valido = False
    primeiro_elogio_texto = ""
    
    for pergunta in config.perguntas:
        valor = request.form.get(f"pergunta_{pergunta.id}")
        
        if pergunta.is_obrigatoria and not valor:
            db.session.rollback()
            if is_ajax:
                return jsonify({
                    "success": False,
                    "error": f"A pergunta '{pergunta.texto_pergunta}' é obrigatória."
                }), 400
            flash(f"A pergunta '{pergunta.texto_pergunta}' é obrigatória.", "danger")
            return redirect(url_for("pesquisa.renderizar_pesquisa", slug=slug))
        
        if valor:
            valor_str = str(valor).strip()
            item = PesquisaRespostaItem(
                pesquisa_envio_id=envio.id,
                pesquisa_pergunta_id=pergunta.id,
                valor_resposta=valor_str
            )
            db.session.add(item)
            
            # Se for texto aberto e tiver mais de 10 caracteres, guarda para o Google Booster
            if pergunta.tipo_resposta == "texto" and len(valor_str) >= 5 and not primeiro_elogio_texto:
                primeiro_elogio_texto = valor_str

            # Verifica o gatilho configurado ou nota 5 estrelas / NPS 9-10 / Emoji 5
            if config.pergunta_gatilho_id and pergunta.id == config.pergunta_gatilho_id:
                if valor_str in ["5", "9", "10", "5_estrelas", "excelente"]:
                    redirecionar_valido = True
            elif not config.pergunta_gatilho_id and pergunta.tipo_resposta in ["estrelas", "stars"]:
                if valor_str == "5":
                    redirecionar_valido = True

    db.session.commit()

    # Registra data de envio na sessão
    session[session_key] = datetime.now().isoformat()

    tem_google_booster = bool(config.link_google_feedback and (config.redirecionar_positivo_auto or True))
    elegivel_google = bool(redirecionar_valido and tem_google_booster)

    if is_ajax:
        return jsonify({
            "success": True,
            "elegivel_google": elegivel_google,
            "link_google": config.link_google_feedback if elegivel_google else None,
            "comentario_cliente": primeiro_elogio_texto,
            "cliente_nome": nome
        })

    if elegivel_google and config.redirecionar_positivo_auto:
        return redirect(config.link_google_feedback)

    return redirect(url_for("pesquisa.renderizar_pesquisa", slug=slug, sucesso="true"))


@pesquisa_bp.route("/dashboard/pesquisa/qrcode/<string:slug>", methods=["GET"])
def gerar_qrcode_backend(slug):
    """Gera o QR Code da pesquisa em formato Base64 para exibição e impressão."""
    try:
        url_base = request.host_url.rstrip('/')
        url_publica = f"{url_base}/p/{slug}"
        
        qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=10, border=4)
        qr.add_data(url_publica)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        
        img_buffer = io.BytesIO()
        img.save(img_buffer, format="PNG")
        img_b64 = base64.b64encode(img_buffer.getvalue()).decode('utf-8')
        img_data_uri = f"data:image/png;base64,{img_b64}"
        
        return jsonify({"success": True, "qr_code": img_data_uri, "url": url_publica})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@pesquisa_bp.route("/dashboard/pesquisa", methods=["GET"])
def listar_pesquisas():
    """Painel de listagem de todas as pesquisas da empresa."""
    user_info = session.get("user_info") or {}
    user_id = user_info.get("id")
    
    if not user_id:
        return redirect(url_for("authorize"))

    company = Company.query.filter_by(owner_user_id=user_id).first()
    if not company:
        company = Company(owner_user_id=user_id, name="Minha Empresa", segmento="Geral")
        db.session.add(company)
        db.session.commit()

    pesquisas = PesquisaConfig.query.filter_by(company_id=company.id, is_active=True).order_by(PesquisaConfig.id.desc()).all()
    
    lista_metricas = []
    for p in pesquisas:
        total_respostas = p.envios.count()
        lista_metricas.append({
            "id": p.id,
            "titulo": p.titulo,
            "subtitulo": p.subtitulo,
            "slug": p.slug,
            "link_google": p.link_google_feedback,
            "booster_ativo": bool(p.link_google_feedback and p.redirecionar_positivo_auto),
            "perguntas_count": len(p.perguntas),
            "respostas_count": total_respostas,
            "created_at": p.created_at
        })

    return render_template("dashboard_pesquisa_lista.html", pesquisas=lista_metricas, csrf_token=generate_csrf)


@pesquisa_bp.route("/dashboard/pesquisa/criar", methods=["GET", "POST"])
def criar_pesquisa():
    """Construtor moderno de pesquisas com suporte a Estrelas, NPS, Emojis, Texto e Múltipla Escolha."""
    user_info = session.get("user_info") or {}
    user_id = user_info.get("id")
    
    if not user_id:
        return redirect(url_for("authorize"))

    company = Company.query.filter_by(owner_user_id=user_id).first()
    if not company:
        company = Company(owner_user_id=user_id, name="Minha Empresa", segmento="Geral")
        db.session.add(company)
        db.session.commit()

    if request.method == "POST":
        titulo = (request.form.get("titulo") or "Como foi sua experiência conosco?").strip()
        subtitulo = (request.form.get("subtitulo") or "Leva menos de 1 minuto para responder.").strip()
        slug_raw = (request.form.get("slug") or "").strip().lower()
        link_google = (request.form.get("link_google_feedback") or "").strip()
        redirecionar = request.form.get("redirecionar_positivo_auto") == "on" or request.form.get("redirecionar_positivo_auto") == "true"
        pergunta_gatilho_idx = request.form.get("pergunta_gatilho_idx")

        slug_limpo = re.sub(r'[^a-zA-Z0-9-]', '', slug_raw)
        if not slug_limpo or PesquisaConfig.query.filter_by(slug=slug_limpo).first():
            flash("Este endereço de link já está em uso. Por favor, escolha outro nome.", "danger")
            return redirect(url_for("pesquisa.criar_pesquisa"))

        nova_pesquisa = PesquisaConfig(
            company_id=company.id,
            titulo=titulo,
            subtitulo=subtitulo,
            slug=slug_limpo,
            link_google_feedback=link_google if link_google else None,
            redirecionar_positivo_auto=redirecionar
        )
        db.session.add(nova_pesquisa)
        db.session.flush()

        perguntas_texto = request.form.getlist("pergunta_texto[]")
        perguntas_tipo = request.form.getlist("pergunta_tipo[]")
        perguntas_obrigatoria = request.form.getlist("pergunta_obrigatoria_raw[]")
        perguntas_opcoes = request.form.getlist("pergunta_opcoes[]")

        for idx, texto in enumerate(perguntas_texto):
            if not texto:
                continue
            
            tipo = perguntas_tipo[idx] if idx < len(perguntas_tipo) else "texto"
            opcoes_raw = perguntas_opcoes[idx] if idx < len(perguntas_opcoes) else ""
            opcoes_lista = [o.strip() for o in opcoes_raw.split(",") if o.strip()] if opcoes_raw else []
            obrigatoria = perguntas_obrigatoria[idx] == "true" if idx < len(perguntas_obrigatoria) else False

            p = PesquisaPergunta(
                pesquisa_config_id=nova_pesquisa.id,
                texto_pergunta=texto.strip(),
                tipo_resposta=tipo,
                is_obrigatoria=obrigatoria,
                ordem=idx,
                opcoes_json=json.dumps(opcoes_lista) if opcoes_lista else None
            )
            db.session.add(p)
            db.session.flush() 
            
            if redirecionar and str(idx) == str(pergunta_gatilho_idx):
                nova_pesquisa.pergunta_gatilho_id = p.id

        # Se o booster foi ativado mas nenhuma pergunta específica foi marcada, vincula à primeira de estrelas/nps
        if redirecionar and not nova_pesquisa.pergunta_gatilho_id:
            primeira_rating = PesquisaPergunta.query.filter_by(pesquisa_config_id=nova_pesquisa.id).filter(
                PesquisaPergunta.tipo_resposta.in_(["estrelas", "stars", "nps", "emojis"])
            ).first()
            if primeira_rating:
                nova_pesquisa.pergunta_gatilho_id = primeira_rating.id

        db.session.commit()
        flash("Pesquisa de satisfação publicada com sucesso!", "success")
        return redirect(url_for("pesquisa.listar_pesquisas"))

    return render_template("dashboard_pesquisa_criar.html", csrf_token=generate_csrf)


@pesquisa_bp.route("/dashboard/pesquisa/deletar/<int:id>", methods=["POST"])
def deletar_pesquisa(id):
    """Exclui uma pesquisa e todas as suas respostas com segurança."""
    user_info = session.get("user_info") or {}
    user_id = user_info.get("id")

    p = PesquisaConfig.query.get_or_404(id)
    company = Company.query.filter_by(owner_user_id=user_id).first()
    
    if not company or p.company_id != company.id:
        flash("Acesso negado.", "danger")
        return redirect(url_for("pesquisa.listar_pesquisas"))

    db.session.delete(p)
    db.session.commit()
    flash("Pesquisa apagada com sucesso.", "success")
    return redirect(url_for("pesquisa.listar_pesquisas"))


@pesquisa_bp.route("/dashboard/pesquisa/<int:id>/respostas", methods=["GET"])
def ver_respostas(id):
    """Painel Executivo de Análise de Métricas, NPS, Gráficos e Linha do Tempo."""
    user_info = session.get("user_info") or {}
    user_id = user_info.get("id")
    
    config = PesquisaConfig.query.get_or_404(id)
    company = Company.query.filter_by(owner_user_id=user_id).first()
    
    if not company or config.company_id != company.id:
        flash("Acesso negado.", "danger")
        return redirect(url_for("pesquisa.listar_pesquisas"))

    envios = PesquisaEnvio.query.filter_by(pesquisa_config_id=config.id).order_by(PesquisaEnvio.id.desc()).all()
    total_envios = len(envios)

    # Coleta de métricas consolidadas
    notas_totais = []
    promotores_count = 0
    neutros_count = 0
    detratores_count = 0
    estrelas_dist = {"5": 0, "4": 0, "3": 0, "2": 0, "1": 0}

    estatisticas = {}
    for p in config.perguntas:
        itens = PesquisaRespostaItem.query.filter_by(pesquisa_pergunta_id=p.id).all()
        total_respostas_pergunta = len(itens)
        
        tipo_normalizado = p.tipo_resposta
        if tipo_normalizado in ['estrelas', 'stars']:
            contagem = {"5": 0, "4": 0, "3": 0, "2": 0, "1": 0}
            soma_notas = 0
            for item in itens:
                v = str(item.valor_resposta).strip()
                if v in contagem:
                    contagem[v] += 1
                    nota_num = int(v)
                    soma_notas += nota_num
                    notas_totais.append(nota_num)
                    estrelas_dist[v] += 1
                    if nota_num == 5:
                        promotores_count += 1
                    elif nota_num == 4:
                        neutros_count += 1
                    else:
                        detratores_count += 1
            
            media_p = round(soma_notas / total_respostas_pergunta, 2) if total_respostas_pergunta > 0 else 0
            detalhes = []
            for op in ["5", "4", "3", "2", "1"]:
                qtd = contagem[op]
                pct = round((qtd / total_respostas_pergunta * 100), 1) if total_respostas_pergunta > 0 else 0
                detalhes.append({"opcao": op, "qtd": qtd, "pct": pct})
            
            estatisticas[p.id] = {
                "tipo": "estrelas",
                "total": total_respostas_pergunta,
                "media": media_p,
                "detalhes": detalhes
            }

        elif tipo_normalizado == 'nps':
            contagem_nps = {str(i): 0 for i in range(11)}
            soma_nps = 0
            for item in itens:
                v = str(item.valor_resposta).strip()
                if v in contagem_nps:
                    contagem_nps[v] += 1
                    val_num = int(v)
                    soma_nps += val_num
                    # Mapeia NPS para nota 1-5
                    notas_totais.append(round(1 + (val_num / 10 * 4), 2))
                    if val_num >= 9:
                        promotores_count += 1
                    elif val_num >= 7:
                        neutros_count += 1
                    else:
                        detratores_count += 1

            media_nps = round(soma_nps / total_respostas_pergunta, 1) if total_respostas_pergunta > 0 else 0
            detalhes = []
            for i in range(10, -1, -1):
                op = str(i)
                qtd = contagem_nps[op]
                pct = round((qtd / total_respostas_pergunta * 100), 1) if total_respostas_pergunta > 0 else 0
                detalhes.append({"opcao": op, "qtd": qtd, "pct": pct})
            
            estatisticas[p.id] = {
                "tipo": "nps",
                "total": total_respostas_pergunta,
                "media": media_nps,
                "detalhes": detalhes
            }

        elif tipo_normalizado == 'emojis':
            contagem_emo = {"5": 0, "4": 0, "3": 0, "2": 0, "1": 0}
            labels_emo = {"5": "🤩 Incrível", "4": "🙂 Bom", "3": "😐 Regular", "2": "🙁 Ruim", "1": "😡 Péssimo"}
            for item in itens:
                v = str(item.valor_resposta).strip()
                if v in contagem_emo:
                    contagem_emo[v] += 1
                    nota_num = int(v)
                    notas_totais.append(nota_num)
                    if nota_num == 5:
                        promotores_count += 1
                    elif nota_num == 4:
                        neutros_count += 1
                    else:
                        detratores_count += 1
            
            detalhes = []
            for op in ["5", "4", "3", "2", "1"]:
                qtd = contagem_emo[op]
                pct = round((qtd / total_respostas_pergunta * 100), 1) if total_respostas_pergunta > 0 else 0
                detalhes.append({"opcao": labels_emo[op], "val": op, "qtd": qtd, "pct": pct})
            
            estatisticas[p.id] = {
                "tipo": "emojis",
                "total": total_respostas_pergunta,
                "detalhes": detalhes
            }

        elif tipo_normalizado == 'multipla_escolha':
            contagem_op = {}
            for item in itens:
                val = item.valor_resposta
                contagem_op[val] = contagem_op.get(val, 0) + 1
            
            opcoes = json.loads(p.opcoes_json or '[]')
            detalhes = []
            for op in opcoes:
                qtd = contagem_op.get(str(op), 0)
                pct = round((qtd / total_respostas_pergunta * 100), 1) if total_respostas_pergunta > 0 else 0
                detalhes.append({"opcao": op, "qtd": qtd, "pct": pct})
            
            estatisticas[p.id] = {
                "tipo": "multipla_escolha",
                "total": total_respostas_pergunta,
                "detalhes": detalhes
            }
        else:
            textos = []
            for item in itens:
                if item.valor_resposta:
                    textos.append({
                        "texto": item.valor_resposta,
                        "envio_id": item.pesquisa_envio_id,
                        "cliente_nome": item.envio.cliente_nome if item.envio else None,
                        "created_at": item.envio.created_at if item.envio else None
                    })
            estatisticas[p.id] = {"tipo": "texto", "total": len(textos), "textos": textos}

    # Cálculo da Média Geral e NPS Score
    media_geral = round(sum(notas_totais) / len(notas_totais), 1) if notas_totais else 5.0
    total_avaliacoes = promotores_count + neutros_count + detratores_count
    
    if total_avaliacoes > 0:
        pct_promotores = (promotores_count / total_avaliacoes) * 100
        pct_detratores = (detratores_count / total_avaliacoes) * 100
        nps_score = round(pct_promotores - pct_detratores)
    else:
        nps_score = 100
        pct_promotores = 100
        pct_detratores = 0

    if nps_score >= 75:
        nps_zona = "surveys.nps_zone_excellence"
        nps_cor = "success"
    elif nps_score >= 50:
        nps_zona = "surveys.nps_zone_quality"
        nps_cor = "primary"
    elif nps_score >= 0:
        nps_zona = "surveys.nps_zone_improvement"
        nps_cor = "warning"
    else:
        nps_zona = "surveys.nps_zone_critical"
        nps_cor = "danger"

    taxa_google_conversao = round((promotores_count / total_envios * 100), 1) if total_envios > 0 else 0

    kpis = {
        "total_envios": total_envios,
        "media_geral": media_geral,
        "nps_score": nps_score,
        "nps_zona": nps_zona,
        "nps_cor": nps_cor,
        "promotores_count": promotores_count,
        "neutros_count": neutros_count,
        "detratores_count": detratores_count,
        "taxa_google": taxa_google_conversao,
        "estrelas_dist": estrelas_dist
    }

    return render_template(
        "dashboard_pesquisa_respostas.html",
        config=config,
        company=company,
        envios=envios,
        estatisticas=estatisticas,
        kpis=kpis
    )


@pesquisa_bp.route("/dashboard/pesquisa/<int:id>/exportar_csv", methods=["GET"])
def exportar_csv(id):
    """Exporta todos os feedbacks e respostas da pesquisa em formato CSV com UTF-8 BOM."""
    user_info = session.get("user_info") or {}
    user_id = user_info.get("id")
    
    config = PesquisaConfig.query.get_or_404(id)
    company = Company.query.filter_by(owner_user_id=user_id).first()
    
    if not company or config.company_id != company.id:
        flash("Acesso negado.", "danger")
        return redirect(url_for("pesquisa.listar_pesquisas"))

    envios = PesquisaEnvio.query.filter_by(pesquisa_config_id=config.id).order_by(PesquisaEnvio.id.asc()).all()
    
    output = io.StringIO()
    # Adiciona UTF-8 BOM para compatibilidade com Microsoft Excel
    output.write('\ufeff')
    writer = csv.writer(output, delimiter=';')
    
    # Cabeçalho do CSV
    headers = ["ID", "Data / Hora", "Nome do Cliente", "E-mail", "WhatsApp"]
    for p in config.perguntas:
        headers.append(p.texto_pergunta)
    writer.writerow(headers)

    # Linhas de dados
    for envio in envios:
        mapa_respostas = {item.pesquisa_pergunta_id: item.valor_resposta for item in envio.respostas}
        data_str = envio.created_at.strftime("%d/%m/%Y %H:%M") if envio.created_at else ""
        row = [
            envio.id,
            data_str,
            envio.cliente_nome or "Anônimo",
            envio.cliente_email or "",
            envio.cliente_whatsapp or ""
        ]
        for p in config.perguntas:
            row.append(mapa_respostas.get(p.id, ""))
        writer.writerow(row)

    output.seek(0)
    filename = f"feedbacks_{config.slug}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment;filename={filename}"}
    )