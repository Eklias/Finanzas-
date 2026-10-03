// Pruebas del JavaScript real con un DOM mínimo, sin dependencias externas.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../static/js/chatbot.js'), 'utf8');

class Element {
    constructor(tag = 'div') {
        this.tagName = tag;
        this.children = [];
        this.listeners = {};
        this.dataset = {};
        this.value = '';
        this.hidden = false;
        this.disabled = false;
        this.className = '';
        this.attributes = {};
        this.classList = {add: name => { this.className += ` ${name}`; }};
    }
    set textContent(text) { this.text = String(text); this.children = []; }
    get textContent() { return (this.text || '') + this.children.map(c => c.textContent).join(' '); }
    appendChild(child) { this.children.push(child); return child; }
    addEventListener(event, handler) { this.listeners[event] = handler; }
    setAttribute(name, value) { this.attributes[name] = value; }
    focus() { this.focused = true; }
    // Fallar si se intenta interpretar como HTML un mensaje o nombre de cuenta.
    set innerHTML(value) { throw new Error('No debe usarse innerHTML en el chat'); }
}

function descendants(node, tag) {
    return node.children.flatMap(child => [...(child.tagName === tag ? [child] : []), ...descendants(child, tag)]);
}

function setup() {
    const ids = ['container', 'toggle', 'window', 'close', 'form', 'input', 'send', 'messages'];
    const nodes = Object.fromEntries(ids.map(id => [`chatbot-${id}`, new Element()]));
    nodes['chatbot-container'].dataset.url = '/chatbot/';
    nodes['chatbot-container'].querySelector = () => ({value: 'csrf-token'});
    nodes['chatbot-window'].hidden = true;
    const responses = [];
    const calls = [];
    const context = {
        document: {getElementById: id => nodes[id], createElement: tag => new Element(tag)},
        window: {location: {origin: 'http://localhost'}}, URL, URLSearchParams, TypeError,
        fetch: async (url, options) => {
            calls.push({url, options});
            const result = responses.shift();
            if (result instanceof Error) throw result;
            return {ok: result.status === 200, status: result.status, json: async () => result.data};
        },
    };
    vm.runInNewContext(source, context);
    return {
        nodes, calls,
        async send(data, status = 200) {
            responses.push(data instanceof Error ? data : {data, status});
            nodes['chatbot-input'].value = 'Aporte de capital de 100 soles';
            await nodes['chatbot-form'].listeners.submit({preventDefault() {}});
            return nodes['chatbot-messages'].children.at(-1);
        },
    };
}

function proposal() {
    return {
        estado: 'propuesta', revision_url: `/asientos/registrar/?propuesta=${'a'.repeat(32)}`,
        vista_previa: {
            fecha: '2020-07-25', descripcion: 'Aporte de capital', total_debe: '100.00', total_haber: '100.00',
            movimientos: [
                {cuenta_codigo: '10', cuenta_nombre: 'Caja', tipo: 'debe', monto: '100.00'},
                {cuenta_codigo: '50', cuenta_nombre: 'Capital', tipo: 'haber', monto: '100.00'},
            ],
        },
    };
}

test('vista previa con descripción, cuentas, Debe/Haber, montos, totales y enlace sin guardar', async () => {
    const app = setup();
    const message = await app.send(proposal());
    assert.equal(descendants(message, 'table').length, 1);
    for (const text of ['Fecha: 2020-07-25', 'Aporte de capital', '10', 'Caja', '50', 'Capital', 'Debe', 'Haber', '100.00',
                        'Total Debe: S/ 100.00', 'Total Haber: S/ 100.00']) {
        assert.ok(message.textContent.includes(text), text);
    }
    const link = descendants(message, 'a')[0];
    assert.equal(link.textContent, 'Revisar y registrar asiento');
    assert.equal(link.href, `http://localhost/asientos/registrar/?propuesta=${'a'.repeat(32)}`);
    assert.equal(app.calls.length, 1); // Ningún segundo POST para guardar o transferir.
    assert.equal(app.calls[0].url, '/chatbot/');
    assert.equal(app.calls[0].options.headers['X-CSRFToken'], 'csrf-token');
});

test('aclaración sigue como mensaje normal sin botón ni tabla', async () => {
    const app = setup();
    const message = await app.send({estado: 'requiere_aclaracion', pregunta: '¿Cuál es el importe?'});
    assert.equal(message.textContent, '¿Cuál es el importe?');
    assert.equal(descendants(message, 'table').length, 0);
    assert.equal(descendants(message, 'a').length, 0);
});

test('gastos operativos ambiguos muestran la pregunta sin error de Groq', async () => {
    const app = setup();
    const pregunta = '¿Qué tipo de gasto operativo se pagó: Gastos de Personal (62), Gastos por Tributos (64) u otro?';
    const message = await app.send({
        estado: 'requiere_aclaracion', status: 'success', pregunta,
        motivo: 'Falta identificar la naturaleza del gasto.',
        datos_detectados: {fecha: '2020-07-31', importe: '20000.00', forma_pago: 'al contado'},
        datos_faltantes: ['tipo_gasto_operativo'],
    });
    assert.equal(message.textContent, pregunta);
    assert.equal(message.className.includes('chatbot-message-error'), false);
    assert.equal(descendants(message, 'table').length, 0);
    assert.equal(descendants(message, 'a').length, 0);
    assert.equal(app.nodes['chatbot-send'].disabled, false);
});

for (const status of [422, 502]) {
    test(`HTTP ${status} muestra error y permite continuar conversando`, async () => {
        const app = setup();
        const message = await app.send({error: 'No se pudo validar la propuesta.'}, status);
        assert.equal(message.textContent, 'No se pudo validar la propuesta.');
        assert.ok(message.className.includes('chatbot-message-error'));
        assert.equal(descendants(message, 'a').length, 0);
        assert.equal(app.nodes['chatbot-send'].disabled, false);
        const siguiente = await app.send({estado: 'requiere_aclaracion', pregunta: '¿Forma de pago?'});
        assert.equal(siguiente.textContent, '¿Forma de pago?');
    });
}

test('descripciones y nombres maliciosos se muestran como texto', async () => {
    const app = setup();
    const data = proposal();
    const hostile = '<img src=x onerror=alert(1)>';
    data.vista_previa.descripcion = hostile;
    data.vista_previa.movimientos[0].cuenta_nombre = hostile;
    const message = await app.send(data);
    assert.ok(message.textContent.includes(hostile));
    assert.equal(descendants(message, 'img').length, 0);
});

test('rechaza enlaces de revisión externos y propuestas incompletas', async () => {
    const app = setup();
    const data = proposal();
    data.revision_url = 'https://evil.example/asientos/registrar/';
    let message = await app.send(data);
    assert.ok(message.className.includes('chatbot-message-error'));
    assert.equal(descendants(message, 'a').length, 0);
    message = await app.send({estado: 'propuesta'});
    assert.ok(message.className.includes('chatbot-message-error'));
});

test('error de red libera el botón de envío', async () => {
    const app = setup();
    const message = await app.send(new TypeError('Failed to fetch'));
    assert.ok(message.textContent.includes('Error de conexión'));
    assert.equal(app.nodes['chatbot-send'].disabled, false);
});

test('abrir y cerrar el chat conserva controles accesibles', () => {
    const app = setup();
    app.nodes['chatbot-toggle'].listeners.click();
    assert.equal(app.nodes['chatbot-window'].hidden, false);
    assert.equal(app.nodes['chatbot-toggle'].attributes['aria-expanded'], 'true');
    assert.equal(app.nodes['chatbot-input'].focused, true);
    app.nodes['chatbot-close'].listeners.click();
    assert.equal(app.nodes['chatbot-window'].hidden, true);
});
