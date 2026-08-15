/**
 * support_chat.js
 * Lógica do Widget de Chat Flutuante Inteligente (Integração com Gemini)
 */

document.addEventListener("DOMContentLoaded", () => {
    // 1. Injetar o HTML do Chat no body
    const chatHtml = `
      <style>
        /* Botão flutuante */
        #chat-float-btn {
          position: fixed;
          bottom: 24px;
          right: 24px;
          width: 60px;
          height: 60px;
          border-radius: 50%;
          background: linear-gradient(135deg, #0d6efd 0%, #4f46e5 100%);
          color: white;
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 28px;
          box-shadow: 0 4px 15px rgba(13, 110, 253, 0.4);
          cursor: pointer;
          z-index: 1040;
          transition: transform 0.2s, box-shadow 0.2s;
        }
        #chat-float-btn:hover {
          transform: scale(1.05);
          box-shadow: 0 6px 20px rgba(13, 110, 253, 0.6);
        }
        
        /* Indicador de notificação (ponto vermelho) */
        #chat-badge {
          position: absolute;
          top: 0;
          right: 0;
          width: 14px;
          height: 14px;
          background-color: #ef4444;
          border: 2px solid white;
          border-radius: 50%;
          display: none;
        }
  
        /* Painel deslizante do Chat */
        #chat-panel {
          position: fixed;
          top: 0;
          right: -400px;
          width: 380px;
          max-width: 100vw;
          height: 100vh;
          background: white;
          box-shadow: -5px 0 25px rgba(0,0,0,0.1);
          z-index: 1050;
          transition: right 0.3s cubic-bezier(0.4, 0, 0.2, 1);
          display: flex;
          flex-direction: column;
        }
        #chat-panel.open {
          right: 0;
        }
  
        /* Header do Chat */
        .chat-header {
          background: linear-gradient(135deg, #0d6efd 0%, #4f46e5 100%);
          color: white;
          padding: 16px 20px;
          display: flex;
          justify-content: space-between;
          align-items: center;
        }
        .chat-header h5 { margin: 0; font-size: 1.1rem; font-weight: 600; display: flex; align-items: center; gap: 8px;}
        .chat-close { background: none; border: none; color: white; font-size: 1.5rem; cursor: pointer; opacity: 0.8; transition: opacity 0.2s; }
        .chat-close:hover { opacity: 1; }
  
        /* Área de Mensagens */
        .chat-messages {
          flex: 1;
          overflow-y: auto;
          padding: 20px;
          background: #f8fafc;
          display: flex;
          flex-direction: column;
          gap: 16px;
        }
        
        /* Balões de Mensagem */
        .chat-bubble {
          max-width: 85%;
          padding: 12px 16px;
          border-radius: 16px;
          font-size: 0.95rem;
          line-height: 1.5;
          word-wrap: break-word;
        }
        .bubble-bot {
          background: white;
          color: #334155;
          align-self: flex-start;
          border-bottom-left-radius: 4px;
          box-shadow: 0 2px 8px rgba(0,0,0,0.04);
        }
        .bubble-user {
          background: #0d6efd;
          color: white;
          align-self: flex-end;
          border-bottom-right-radius: 4px;
          box-shadow: 0 2px 8px rgba(13, 110, 253, 0.2);
        }
        
        /* Input Area */
        .chat-input-area {
          padding: 16px;
          background: white;
          border-top: 1px solid #e2e8f0;
          display: flex;
          gap: 8px;
        }
        .chat-input-area input {
          flex: 1;
          padding: 10px 16px;
          border: 1px solid #cbd5e1;
          border-radius: 50px;
          outline: none;
          transition: border-color 0.2s;
        }
        .chat-input-area input:focus { border-color: #0d6efd; }
        .chat-input-area button {
          width: 44px;
          height: 44px;
          border-radius: 50%;
          background: #0d6efd;
          color: white;
          border: none;
          display: flex;
          align-items: center;
          justify-content: center;
          cursor: pointer;
          transition: background 0.2s;
        }
        .chat-input-area button:hover { background: #0b5ed7; }
        .chat-input-area button:disabled { background: #94a3b8; cursor: not-allowed; }
  
        /* Typing Indicator */
        .typing-indicator {
          display: flex;
          gap: 4px;
          padding: 12px 16px;
          background: white;
          border-radius: 16px;
          border-bottom-left-radius: 4px;
          align-self: flex-start;
          box-shadow: 0 2px 8px rgba(0,0,0,0.04);
          display: none;
        }
        .typing-dot {
          width: 6px;
          height: 6px;
          background: #94a3b8;
          border-radius: 50%;
          animation: typing 1.4s infinite ease-in-out both;
        }
        .typing-dot:nth-child(1) { animation-delay: -0.32s; }
        .typing-dot:nth-child(2) { animation-delay: -0.16s; }
        @keyframes typing {
          0%, 80%, 100% { transform: scale(0); }
          40% { transform: scale(1); }
        }
        
        /* Backdrop mobile */
        #chat-backdrop {
          position: fixed;
          top: 0; left: 0; right: 0; bottom: 0;
          background: rgba(0,0,0,0.4);
          z-index: 1045;
          display: none;
          opacity: 0;
          transition: opacity 0.3s;
        }
        #chat-backdrop.open { display: block; opacity: 1; }
        
        @media (max-width: 576px) {
          #chat-panel { width: 100%; right: -100%; }
        }
      </style>
  
      <div id="chat-float-btn" onclick="toggleChat()">
        <i class="bi bi-chat-dots-fill"></i>
        <div id="chat-badge"></div>
      </div>
      
      <div id="chat-backdrop" onclick="toggleChat()"></div>
  
      <div id="chat-panel">
        <div class="chat-header">
          <h5><i class="bi bi-robot"></i> Suporte IA</h5>
          <button class="chat-close" onclick="toggleChat()"><i class="bi bi-x-lg"></i></button>
        </div>
        
        <div class="chat-messages" id="chat-messages-container">
          <div class="chat-bubble bubble-bot">
            Olá! Sou o assistente virtual do ComentsIA. Posso ajudar você a configurar o sistema, tirar dúvidas sobre planos, relatórios ou resolver problemas com o Google Business Profile.<br><br>Como posso ajudar hoje?
          </div>
        </div>
        
        <div class="typing-indicator" id="chat-typing">
          <div class="typing-dot"></div>
          <div class="typing-dot"></div>
          <div class="typing-dot"></div>
        </div>
  
        <form class="chat-input-area" id="chat-form">
          <input type="text" id="chat-input" placeholder="Digite sua mensagem..." autocomplete="off">
          <button type="submit" id="chat-send-btn"><i class="bi bi-send-fill"></i></button>
        </form>
      </div>
    `;
  
    document.body.insertAdjacentHTML('beforeend', chatHtml);
  
    // 2. Lógica do Chat
    const chatForm = document.getElementById('chat-form');
    const chatInput = document.getElementById('chat-input');
    const msgContainer = document.getElementById('chat-messages-container');
    const typingIndicator = document.getElementById('chat-typing');
    const sendBtn = document.getElementById('chat-send-btn');
    
    // Histórico em memória
    let messageHistory = [];
  
    chatForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const text = chatInput.value.trim();
      if (!text) return;
  
      // Adiciona MSG do usuário
      appendMessage('user', text);
      chatInput.value = '';
      
      messageHistory.push({ role: 'user', content: text });
  
      // Mostra typing
      typingIndicator.style.display = 'flex';
      msgContainer.appendChild(typingIndicator); // move pro final
      msgContainer.scrollTop = msgContainer.scrollHeight;
      sendBtn.disabled = true;
      chatInput.disabled = true;
  
      try {
        const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';
        
        const response = await fetch('/api/support-chat', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
          },
          body: JSON.stringify({ messages: messageHistory })
        });
  
        const data = await response.json();
        
        if (response.ok && data.reply) {
          // Formata Markdown básico da resposta
          let formattedReply = data.reply
            .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
            .replace(/\*(.*?)\*/g, '<em>$1</em>')
            .replace(/\n/g, '<br>');
            
          appendMessage('bot', formattedReply);
          messageHistory.push({ role: 'model', content: data.reply });
        } else {
          appendMessage('bot', 'Desculpe, ocorreu um erro ao processar sua solicitação.');
        }
      } catch (err) {
        console.error('Chat Error:', err);
        appendMessage('bot', 'Erro de conexão. Verifique sua internet ou tente novamente mais tarde.');
      } finally {
        typingIndicator.style.display = 'none';
        sendBtn.disabled = false;
        chatInput.disabled = false;
        chatInput.focus();
      }
    });
  
    function appendMessage(role, htmlContent) {
      const div = document.createElement('div');
      div.className = `chat-bubble bubble-${role}`;
      div.innerHTML = htmlContent;
      msgContainer.appendChild(div);
      
      // Move typing indicator pra baixo
      if (typingIndicator.style.display === 'flex') {
        msgContainer.appendChild(typingIndicator);
      }
      
      msgContainer.scrollTop = msgContainer.scrollHeight;
    }
  });
  
  // Função global para abrir/fechar chat (usada também em outros botões do site)
  window.toggleChat = function() {
    const panel = document.getElementById('chat-panel');
    const backdrop = document.getElementById('chat-backdrop');
    
    if (panel.classList.contains('open')) {
      panel.classList.remove('open');
      backdrop.classList.remove('open');
      setTimeout(() => backdrop.style.display = 'none', 300);
    } else {
      backdrop.style.display = 'block';
      // Reflow for transition
      void backdrop.offsetWidth;
      panel.classList.add('open');
      backdrop.classList.add('open');
      document.getElementById('chat-input').focus();
    }
  };
