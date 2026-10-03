const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../static/js/asiento_ocr.js'), 'utf8');

function setup(response = {}, ok = true, cuentas = [{id: 71, codigo: '10', nombre: 'Caja'}]) {
    const ids = ['ocr-panel', 'btnProcesarOcr', 'inputImagenOcr', 'inputTextoManual',
        'contenedorModoTexto', 'btnToggleModoTexto', 'ocrFeedback', 'ocrLoading',
        'selectorOperaciones', 'listaOperacionesChips', 'ocrResultado', 'ocrTextoDetectado',
        'movimientos-container', 'id_fecha', 'id_descripcion'];
    function element() {
        return {style: {}, value: '', children: [], listeners: {},
            addEventListener(event, callback) { this.listeners[event] = callback; },
            appendChild(child) { this.children.push(child); },
            replaceChildren() { this.children = []; }};
    }
    const nodes = Object.fromEntries(ids.map(id => [id, element()]));
    nodes['ocr-panel'].dataset = {url: '/procesar_imagen_asiento/'};
    nodes.contenedorModoTexto.style.display = 'none';
    const calls = [];
    const rows = [];
    const context = {
        document: {getElementById: id => nodes[id], createElement: element,
            querySelector: () => ({value: 'csrf-token'})},
        FormData: class { constructor() { this.entries = []; }
            append(...entry) { this.entries.push(entry); } },
        fetch: async (...args) => { calls.push(args); return {ok, json: async () => response}; },
        CUENTAS: cuentas, contadorMovimientos: 2,
        agregarMovimiento: (...row) => rows.push(row),
    };
    vm.runInNewContext(source, context);
    return {nodes, calls, rows, context,
        click: () => nodes.btnProcesarOcr.listeners.click()};
}

test('envía imágenes como multipart con CSRF y muestra OCR sin cambiar el asiento', async () => {
    const app = setup({texto_ocr_detectado: '<img src=x onerror=alert(1)>',
        operaciones: [{fecha: '2026-10-03', glosa: '<script>texto</script>',
            movimientos: [{codigo_cuenta: '10', tipo: 'debe', monto: 100}]}]});
    const file = {name: 'comprobante.png'};
    app.nodes.inputImagenOcr.files = [file];
    await app.click();
    assert.equal(app.calls[0][0], '/procesar_imagen_asiento/');
    const request = app.calls[0][1];
    assert.equal(request.headers['X-CSRFToken'], 'csrf-token');
    assert.equal(request.body.entries[0][0], 'imagenes');
    assert.equal(request.body.entries[0][1], file);
    assert.equal(app.nodes.ocrTextoDetectado.value, '<img src=x onerror=alert(1)>');
    assert.equal(app.nodes.ocrResultado.hidden, false);
    assert.equal(app.rows.length, 0);
    const chip = app.nodes.listaOperacionesChips.children[0];
    assert.ok(chip.textContent.includes('<script>texto</script>'));
    chip.listeners.click();
    assert.equal(app.rows[0][0], 71);
    assert.equal(app.nodes.id_fecha.value, '2026-10-03');
    assert.equal(app.nodes.btnProcesarOcr.disabled, false);
});

test('conserva OCR cuando la IA falla y libera el botón', async () => {
    const app = setup({error: 'Sin clave IA', texto_ocr_detectado: 'Texto legible'}, false);
    app.nodes.inputImagenOcr.files = [{}];
    await app.click();
    assert.equal(app.nodes.ocrTextoDetectado.value, 'Texto legible');
    assert.equal(app.nodes.ocrFeedback.textContent, 'Sin clave IA');
    assert.equal(app.nodes.btnProcesarOcr.disabled, false);
    assert.equal(app.nodes.ocrLoading.style.display, 'none');
});

test('modo texto ignora imágenes seleccionadas previamente', async () => {
    const app = setup({texto_ocr_detectado: 'Aporte', operaciones: []});
    app.nodes.inputImagenOcr.files = [{}];
    app.nodes.btnToggleModoTexto.listeners.click();
    app.nodes.inputTextoManual.value = 'Aporte';
    await app.click();
    assert.equal(app.calls[0][1].body.entries.length, 1);
    assert.equal(app.calls[0][1].body.entries[0][0], 'texto');
});

test('no inventa una cuenta si el código OCR no existe en el catálogo', async () => {
    const app = setup({operaciones: [{movimientos: [{codigo_cuenta: '999', tipo: 'debe', monto: 20}]}]});
    app.nodes.inputImagenOcr.files = [{}];
    await app.click();
    app.nodes.listaOperacionesChips.children[0].listeners.click();
    assert.equal(app.rows[0][0], '');
    assert.ok(app.nodes.ocrFeedback.textContent.includes('pendientes de revisión manual'));
});

test('normaliza números y espacios y carga múltiples movimientos por ID exacto', async () => {
    const app = setup({operaciones: [{fecha: '2020-07-08', glosa: 'Creación de empresa',
        movimientos: [{codigo_cuenta: 10, tipo: 'debe', monto: 100000},
            {codigo_cuenta: ' 50 ', tipo: 'haber', monto: 100000}]}]}, true,
        [{id: 71, codigo: ' 10 ', nombre: 'Caja'}, {id: 82, codigo: 50, nombre: 'Capital'}]);
    app.nodes.inputImagenOcr.files = [{}];
    await app.click();
    assert.equal(app.rows.length, 0);
    app.nodes.listaOperacionesChips.children[0].listeners.click();
    assert.deepEqual(app.rows, [[71, 'debe', 100000], [82, 'haber', 100000]]);
    assert.equal(app.nodes.id_fecha.value, '2020-07-08');
    assert.equal(app.nodes.id_descripcion.value, 'Creación de empresa');
    assert.equal(app.nodes.ocrFeedback.className, 'alert alert-success');
});

test('no selecciona por prefijo, nombre parecido, código vacío o marca pendiente', async () => {
    const movimientos = [
        {codigo_cuenta: '10', nombre_cuenta: 'Caja', tipo: 'debe', monto: 20},
        {codigo_cuenta: null, nombre_cuenta: 'Caja general', tipo: 'haber', monto: 20},
        {codigo_cuenta: '101', pendiente_revision: true, tipo: 'debe', monto: 20},
        {codigo_cuenta: '', tipo: 'haber', monto: 20},
        {codigo_cuenta: '0101', tipo: 'haber', monto: 20},
    ];
    const app = setup({operaciones: [{movimientos}]}, true,
        [{id: 71, codigo: '101', nombre: 'Caja general'},
            {id: 82, codigo: '102', nombre: 'Caja chica'}]);
    app.nodes.inputImagenOcr.files = [{}];
    await app.click();
    app.nodes.listaOperacionesChips.children[0].listeners.click();
    assert.equal(app.rows.length, 5);
    app.rows.forEach(row => assert.equal(row[0], ''));
    assert.ok(app.nodes.ocrFeedback.textContent.includes('movimiento 1 (código 10)'));
    assert.equal(app.nodes.ocrFeedback.className, 'alert alert-error');
});

test('códigos ambiguos tras quitar espacios quedan sin selección', async () => {
    const app = setup({operaciones: [{movimientos: [{codigo_cuenta: '10', tipo: 'debe', monto: 20}]}]},
        true, [{id: 71, codigo: '10'}, {id: 82, codigo: ' 10 '}]);
    app.nodes.inputImagenOcr.files = [{}];
    await app.click();
    app.nodes.listaOperacionesChips.children[0].listeners.click();
    assert.equal(app.rows[0][0], '');
});

test('sin archivos no realiza solicitudes y un error de red permite reintentar', async () => {
    const app = setup();
    await app.click();
    assert.equal(app.calls.length, 0);
    app.nodes.inputImagenOcr.files = [{}];
    app.context.fetch = async () => { throw new Error('Sin conexión'); };
    await app.click();
    assert.equal(app.nodes.ocrFeedback.textContent, 'Sin conexión');
    assert.equal(app.nodes.btnProcesarOcr.disabled, false);
});
