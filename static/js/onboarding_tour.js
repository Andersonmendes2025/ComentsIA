/**
 * onboarding_tour.js
 * Tour interativo de primeiro acesso usando Driver.js
 */

document.addEventListener("DOMContentLoaded", () => {
    // 1. Verifica cache local para evitar requisição desnecessária se já completou
    if (localStorage.getItem('onboarding_done') === 'true') {
      return;
    }
  
    // 2. Verifica no backend o status real (caso logue em outro dispositivo)
    fetch('/api/onboarding-status')
      .then(res => res.json())
      .then(data => {
        if (!data.done) {
          // Se não concluiu, aguarda 1.5s para carregar a página e inicia o tour
          setTimeout(startOnboardingTour, 1500);
        } else {
          // Já concluiu, salva no storage para não verificar mais
          localStorage.setItem('onboarding_done', 'true');
        }
      })
      .catch(err => console.error("Erro ao verificar onboarding:", err));
  
    function startOnboardingTour() {
      // Injeta o CSS do Driver.js se ainda não existir
      if (!document.getElementById('driver-js-css')) {
        const link = document.createElement('link');
        link.id = 'driver-js-css';
        link.rel = 'stylesheet';
        link.href = 'https://cdn.jsdelivr.net/npm/driver.js@1.0.1/dist/driver.css';
        document.head.appendChild(link);
      }
  
      // Carrega o script do Driver.js e executa
      const script = document.createElement('script');
      script.src = 'https://cdn.jsdelivr.net/npm/driver.js@1.0.1/dist/driver.js.iife.js';
      script.onload = () => {
        const driver = window.driver.js.driver;
        
        const tour = driver({
          showProgress: true,
          animate: true,
          doneBtnText: 'Concluir',
          nextBtnText: 'Próximo →',
          prevBtnText: '← Voltar',
          popoverClass: 'driverjs-theme',
          onDestroyStarted: () => {
            if (!tour.hasNextStep() || confirm("Tem certeza que deseja pular o tour?")) {
              markOnboardingDone();
              tour.destroy();
            }
          },
          steps: [
            {
              element: '.navbar-brand',
              popover: {
                title: 'Boas-vindas ao ComentsIA! 🎉',
                description: 'Ficamos felizes em ter você aqui. Vamos fazer um tour rápido de 1 minuto para te mostrar onde fica cada coisa.',
                side: "bottom", align: 'start'
              }
            },
            {
              element: 'a[href="/auto/locations"]',
              popover: {
                title: 'Conecte o Google',
                description: 'É aqui que você sincroniza suas fichas do Google Business Profile e liga a resposta automática.',
                side: "bottom", align: 'start'
              }
            },
            {
              element: 'a[href="/settings"]',
              popover: {
                title: 'Configure a IA',
                description: 'No menu do seu perfil, acesse Configurações para definir o tom de voz da IA e o contexto do seu negócio.',
                side: "bottom", align: 'end'
              }
            },
            {
              element: 'a[href="/ajuda"]',
              popover: {
                title: 'Central de Ajuda',
                description: 'Se tiver dúvidas técnicas ou sobre as regras do Google (como Grupos de Fichas), nossa documentação está aqui.',
                side: "bottom", align: 'start'
              }
            },
            {
              element: '#chat-float-btn',
              popover: {
                title: 'Chat Inteligente 24h',
                description: 'Precisa de ajuda rápida? Clique aqui para falar com nosso Assistente IA ou abrir um chamado para suporte humano.',
                side: "left", align: 'end'
              }
            }
          ]
        });
  
        tour.drive();
      };
      
      document.body.appendChild(script);
    }
  
    function markOnboardingDone() {
      // Salva no backend
      const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';
      
      fetch('/api/onboarding-done', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken
        }
      }).catch(err => console.error("Erro ao salvar status do onboarding:", err));
      
      // Salva localmente
      localStorage.setItem('onboarding_done', 'true');
    }
  });
