import re
import json
from flask import Blueprint, render_template, request, jsonify, redirect, flash, url_for, session
from models import db, Company
from models_pesquisa import PesquisaConfig, PesquisaPergunta, PesquisaEnvio, PesquisaRespostaItem
from flask_wtf.csrf import generate_csrf
import io  
import qrcode  
from flask import send_file  

pesquisa_bp = Blueprint("pesquisa", __name__)

@pesquisa_bp.route("/p/<string:slug>", methods=["GET"])
def renderizar_pesquisa(slug):
    config = PesquisaConfig.query.filter_by(slug=slug, is_active=True).first_or_404()
    return render_template("pesquisa_publica.html", config=config)


@pesquisa_bp.route("/p/<string:slug>/enviar", methods=["POST"])
def enviar_resposta(slug):
    config = PesquisaConfig.query.filter_by(slug=slug, is_active=True).first_or_404()
    
    nome = request.form.get("nome")
    email = request.form.get("email")
    whatsapp = request.form.get("whatsapp")

    # Instancia o registro mestre de envio
    envio = PesquisaEnvio(
        pesquisa_config_id=config.id,
        cliente_nome=nome,
        cliente_email=email,
        cliente_whatsapp=whatsapp
    )
    db.session.add(envio)
    db.session.flush() # Pega o ID sem commitar de fato ainda

    redirecionar_valido = False
    
    # Itera sobre as perguntas do formulário para salvar as respostas individuais
    for pergunta in config.perguntas:
        valor = request.form.get(f"pergunta_{pergunta.id}")
        
        # Validação de segurança no backend caso um campo obrigatório venha vazio
        if pergunta.is_obrigatoria and not valor:
            db.session.rollback()
            flash(f"A pergunta '{pergunta.texto_pergunta}' é obrigatória.", "danger")
            return redirect(url_for("pesquisa.renderizar_pesquisa", slug=slug))
        
        if valor:
            item = PesquisaRespostaItem(
                pesquisa_envio_id=envio.id,
                pesquisa_pergunta_id=pergunta.id,
                valor_resposta=str(valor).strip()
            )
            db.session.add(item)
            
            # 🚀 LÓGICA DE GATILHO: Se a pergunta for a eleita pelo dono E o cliente der exatamente 5 estrelas
            if config.pergunta_gatilho_id and pergunta.id == config.pergunta_gatilho_id:
                if str(valor).strip() == "5":
                    redirecionar_valido = True

    db.session.commit()

    # 🚀 RECONHECE PROMOTORES: Manda direto para a ficha do Google Business Profile
    if redirecionar_valido and config.link_google_feedback and config.redirecionar_positivo_auto:
        return redirect(config.link_google_feedback)

    # 🚀 RETENÇÃO / FEEDBACK CONCLUÍDO: Redireciona para a tela de sucesso nativa do formulário
    return redirect(url_for("pesquisa.renderizar_pesquisa", slug=slug, sucesso="true"))


@pesquisa_bp.route("/dashboard/pesquisa/qrcode/<string:slug>", methods=["GET"])
def gerar_qrcode_backend(slug):
    try:
        url_publica = url_for("pesquisa.renderizar_pesquisa", slug=slug, _external=True)
        qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=10, border=4)
        qr.add_data(url_publica)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        
        img_buffer = io.BytesIO()
        img.save(img_buffer, format="PNG")
        img_buffer.seek(0)
        return send_file(img_buffer, mimetype="image/png", as_attachment=False)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    

@pesquisa_bp.route("/dashboard/pesquisa", methods=["GET"])
def listar_pesquisas():
    user_info = session.get("user_info") or {}
    user_id = user_info.get("id") or "admin_local"
    company = Company.query.filter_by(owner_user_id=user_id).first() or Company.query.first()

    if not company:
        company = Company(owner_user_id=user_id, name="Hotel Front Comfort", segmento="Hotelaria")
        db.session.add(company)
        db.session.commit()

    pesquisas = PesquisaConfig.query.filter_by(company_id=company.id, is_active=True).all()
    
    lista_metricas = []
    for p in pesquisas:
        total_respostas = p.envios.count()
        lista_metricas.append({
            "id": p.id,
            "titulo": p.titulo,
            "slug": p.slug,
            "respostas_count": total_respostas
        })

    return render_template("dashboard_pesquisa_lista.html", pesquisas=lista_metricas, csrf_token=generate_csrf)


@pesquisa_bp.route("/dashboard/pesquisa/criar", methods=["GET", "POST"])
def criar_pesquisa():
    user_info = session.get("user_info") or {}
    user_id = user_info.get("id") or "admin_local"
    company = Company.query.filter_by(owner_user_id=user_id).first() or Company.query.first()

    if request.method == "POST":
        titulo = request.form.get("titulo")
        subtitulo = request.form.get("subtitulo")
        slug_raw = request.form.get("slug", "").strip().lower()
        link_google = request.form.get("link_google_feedback", "").strip()
        redirecionar = request.form.get("redirecionar_positivo_auto") == "on"
        pergunta_gatilho_idx = request.form.get("pergunta_gatilho_idx") # Pega o índice da pergunta escolhida como gatilho

        slug_limpo = re.sub(r'[^a-zA-Z0-9-]', '', slug_raw)
        if not slug_limpo or PesquisaConfig.query.filter_by(slug=slug_limpo, is_active=True).first():
            flash("Endereço de acesso inválido ou já em uso.", "danger")
            return redirect(url_for("pesquisa.criar_pesquisa"))

        # 🚀 PROTEÇÃO BACKEND: Impede de salvar se ativou o redirecionamento mas não selecionou o gatilho
        if redirecionar and not pergunta_gatilho_idx:
            flash("Erro: Você ativou o redirecionamento automático mas não selecionou nenhuma pergunta de estrelas como parâmetro.", "danger")
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

        # Captura as perguntas dinâmicas enviadas
        perguntas_texto = request.form.getlist("pergunta_texto[]")
        perguntas_tipo = request.form.getlist("pergunta_tipo[]")
        perguntas_obrigatoria = request.form.getlist("pergunta_obrigatoria_raw[]")
        perguntas_opcoes = request.form.getlist("pergunta_opcoes[]")

        for idx, texto in enumerate(perguntas_texto):
            if not texto: continue
            
            opcoes_lista = [o.strip() for o in perguntas_opcoes[idx].split(",") if o.strip()] if idx < len(perguntas_opcoes) else []
            obrigatoria = perguntas_obrigatoria[idx] == "true" if idx < len(perguntas_obrigatoria) else False

            p = PesquisaPergunta(
                pesquisa_config_id=nova_pesquisa.id,
                texto_pergunta=texto,
                tipo_resposta=perguntas_tipo[idx],
                is_obrigatoria=obrigatoria,
                ordem=idx,
                opcoes_json=json.dumps(opcoes_lista) if opcoes_lista else None
            )
            db.session.add(p)
            db.session.flush() 
            
            if redirecionar and str(idx) == str(pergunta_gatilho_idx):
                nova_pesquisa.pergunta_gatilho_id = p.id

        db.session.commit()
        flash("Nova pesquisa estilo Forms criada com sucesso!", "success")
        return redirect(url_for("pesquisa.listar_pesquisas"))

    return render_template("dashboard_pesquisa_criar.html", csrf_token=generate_csrf)


@pesquisa_bp.route("/dashboard/pesquisa/deletar/<int:id>", methods=["POST"])
def deletar_pesquisa(id):
    p = PesquisaConfig.query.get_or_404(id)
    p.is_active = False # Soft delete limpo
    db.session.commit()
    flash("Pesquisa removida com sucesso.", "success")
    return redirect(url_for("pesquisa.listar_pesquisas"))


@pesquisa_bp.route("/dashboard/pesquisa/<int:id>/respostas", methods=["GET"])
def ver_respostas(id):
    config = PesquisaConfig.query.get_or_404(id)
    envios = PesquisaEnvio.query.filter_by(pesquisa_config_id=config.id).order_by(PesquisaEnvio.id.desc()).all()
    
    estatisticas = {}
    for p in config.perguntas:
        itens = PesquisaRespostaItem.query.filter_by(pesquisa_pergunta_id=p.id).all()
        total_respostas = len(itens)
        
        if p.tipo_resposta in ['estrelas', 'stars', 'multipla_escolha']:
            contagem = {}
            for item in itens:
                val = item.valor_resposta
                contagem[val] = contagem.get(val, 0) + 1
            
            opcoes = ["5", "4", "3", "2", "1"] if p.tipo_resposta in ['estrelas', 'stars'] else json.loads(p.opcoes_json or '[]')
            
            detalhes = []
            for op in opcoes:
                qtd = contagem.get(str(op), 0)
                pct = (qtd / total_respostas * 100) if total_respostas > 0 else 0
                detalhes.append({"opcao": op, "qtd": qtd, "pct": round(pct, 1)})
            
            estatisticas[p.id] = {"tipo": p.tipo_resposta, "total": total_respostas, "detalhes": detalhes}
        else:
            textos = [{"texto": item.valor_resposta, "envio_id": item.pesquisa_envio_id} for item in itens if item.valor_resposta]
            estatisticas[p.id] = {"tipo": 'texto', "total": len(textos), "textos": textos}
            
    return render_template("dashboard_pesquisa_respostas.html", config=config, envios=envios, estatisticas=estatisticas)