(() => {
    'use strict';
    const container = document.getElementById('chatbot-container');
    if (!container) return;
    const toggle = document.getElementById('chatbot-toggle');
    const windowChat = document.getElementById('chatbot-window');
    const close = document.getElementById('chatbot-close');
    const form = document.getElementById('chatbot-form');
    const input = document.getElementById('chatbot-input');
    const send = document.getElementById('chatbot-send');
    const messages = document.getElementById('chatbot-messages');

    function element(tag, text, className) {
        const node = document.createElement(tag);
        if (text !== undefined) node.textContent = text;
        if (className) node.className = className;
        return node;
    }

    function setOpen(open) {
        windowChat.hidden = !open;
        toggle.setAttribute('aria-expanded', String(open));
        if (open) input.focus();
    }
    toggle.addEventListener('click', () => setOpen(windowChat.hidden));
    close.addEventListener('click', () => setOpen(false));

    function preview(message, data) {
        const proposal = data.vista_previa;
        if (!proposal || !Array.isArray(proposal.movimientos)) {
            throw new Error('No se pudo mostrar la propuesta. Intenta nuevamente.');
        }
        // La URL únicamente puede llevar a nuestro formulario, dentro del mismo origen.
        const url = new URL(data.revision_url, window.location.origin);
        if (url.origin !== window.location.origin || url.pathname !== '/asientos/registrar/' ||
            !/^[a-f0-9]{32}$/.test(url.searchParams.get('propuesta') || '')) {
            throw new Error('El enlace de revisión no es válido. Intenta nuevamente.');
        }
        message.textContent = '';
        message.classList.add('chatbot-proposal');
        message.appendChild(element('strong', 'Propuesta de asiento'));
        message.appendChild(element('p', proposal.descripcion));
        message.appendChild(element('p', `Fecha: ${proposal.fecha}`));
        const wrapper = element('div', undefined, 'chatbot-table-wrapper');
        const table = element('table', undefined, 'chatbot-table');
        table.appendChild(element('caption', 'Movimientos propuestos', 'chatbot-sr-only'));
        const head = element('thead');
        const headings = element('tr');
        ['Código', 'Cuenta', 'Tipo', 'Monto (S/)'].forEach(text => {
            const th = element('th', text);
            th.setAttribute('scope', 'col');
            headings.appendChild(th);
        });
        head.appendChild(headings);
        table.appendChild(head);
        const body = element('tbody');
        proposal.movimientos.forEach(m => {
            const row = element('tr');
            [m.cuenta_codigo, m.cuenta_nombre, m.tipo === 'debe' ? 'Debe' : 'Haber', m.monto]
                .forEach(text => row.appendChild(element('td', text)));
            body.appendChild(row);
        });
        table.appendChild(body);
        wrapper.appendChild(table);
        message.appendChild(wrapper);
        const totals = element('div', undefined, 'chatbot-totals');
        totals.appendChild(element('div', `Total Debe: S/ ${proposal.total_debe}`));
        totals.appendChild(element('div', `Total Haber: S/ ${proposal.total_haber}`));
        message.appendChild(totals);
        message.appendChild(element('p', 'Revisa los datos y la fecha antes de guardar. Debe = Haber no garantiza que el tratamiento contable sea correcto.', 'chatbot-note'));
        const review = element('a', 'Revisar y registrar asiento', 'btn btn-success chatbot-review');
        review.href = url.href;
        message.appendChild(review);
    }

    form.addEventListener('submit', async event => {
        event.preventDefault();
        const text = input.value.trim();
        if (!text || send.disabled) return;
        messages.appendChild(element('div', text, 'chatbot-message chatbot-message-user'));
        input.value = '';
        const message = element('div', 'Pensando...', 'chatbot-message chatbot-message-bot');
        messages.appendChild(message);
        send.disabled = true;
        messages.scrollTop = messages.scrollHeight;
        try {
            const token = container.querySelector('[name="csrfmiddlewaretoken"]').value;
            const response = await fetch(container.dataset.url, {
                method: 'POST',
                headers: {'Content-Type': 'application/x-www-form-urlencoded', 'X-CSRFToken': token},
                body: new URLSearchParams({message: text}).toString(),
                credentials: 'same-origin',
            });
            let data;
            try {
                data = await response.json();
            } catch {
                throw new Error('El servidor no pudo responder. Recarga la página e intenta nuevamente.');
            }
            if (!response.ok) {
                const fallback = response.status === 422
                    ? 'La propuesta no es válida. Revisa el hecho contable e intenta nuevamente.'
                    : response.status === 502
                        ? 'El servicio de IA no pudo generar una propuesta válida. Intenta nuevamente.'
                        : 'No se pudo procesar el mensaje. Intenta nuevamente.';
                throw new Error(data.error || fallback);
            }
            if (data.estado === 'propuesta') {
                preview(message, data);
            } else {
                message.textContent = data.pregunta || data.response || 'No se recibió una respuesta válida.';
            }
        } catch (error) {
            message.classList.add('chatbot-message-error');
            message.textContent = error instanceof TypeError
                ? 'Error de conexión. Comprueba tu conexión e intenta nuevamente.'
                : error.message;
        } finally {
            send.disabled = false;
            messages.scrollTop = messages.scrollHeight;
        }
    });
})();
