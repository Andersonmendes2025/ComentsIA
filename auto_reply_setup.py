from flask import Blueprint, render_template, session, redirect, url_for, flash
from datetime import datetime
from selenium_script import iniciar_bot_google, executar_robo_com_google_login

auto_reply_bp = Blueprint('auto_reply', __name__)

@auto_reply_bp.route('/auto_reply_setup')
def auto_reply_setup():
    if 'credentials' not in session:
        flash('Você precisa estar logado para configurar o robô.', 'warning')
        return redirect(url_for('authorize'))

    user_info = session.get('user_info', {})
    return render_template(
        'auto_reply_setup.html',
        user=user_info,
        now=datetime.now()
    )

@auto_reply_bp.route('/start_auto_bot')
def start_auto_bot():
    if 'credentials' not in session:
        flash('Você precisa estar logado para iniciar o robô.', 'warning')
        return redirect(url_for('authorize'))

    user_info = session.get('user_info', {})
    email = user_info.get('email')

    try:
        executar_robo_com_google_login(email)
        flash('Robô foi iniciado com sucesso!', 'success')
    except Exception as e:
        flash(f'Erro ao iniciar o robô: {str(e)}', 'danger')

    return redirect(url_for('auto_reply.auto_reply_setup'))

@auto_reply_bp.route('/run_bot_now')
def run_bot_now():
    if 'credentials' not in session:
        flash('Você precisa estar logado para rodar o robô.', 'warning')
        return redirect(url_for('authorize'))

    user_info = session.get('user_info', {})
    iniciar_bot_google(user_info)

    flash('✅ Robô iniciado manualmente. A janela foi aberta para varredura.', 'success')
    return redirect(url_for('auto_reply.auto_reply_setup'))
