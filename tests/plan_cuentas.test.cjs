const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../static/js/plan_cuentas.js'), 'utf8');

class Element {
    constructor(value = '', dataset = {}) {
        this.value = value;
        this.dataset = dataset;
        this.hidden = false;
        this.disabled = false;
        this.events = {};
        this.attributes = {};
        this.count = {textContent: ''};
    }
    addEventListener(type, callback) { this.events[type] = callback; }
    fire(type, event = {}) { this.events[type](event); }
    querySelector() { return this.count; }
    setAttribute(name, value) { this.attributes[name] = value; }
    focus() { this.focused = true; }
    get selectedOptions() { return this.options.filter(option => option.value === this.value); }
}

function setup(data = [
    {codigo: '10', nombre: 'Efectivo y equivalentes', tipo: 'activo', subcategoria: 'activo_corriente'},
    {codigo: '20', nombre: 'Mercaderías', tipo: 'activo', subcategoria: 'existencias'},
    {codigo: '50', nombre: 'Capital', tipo: 'patrimonio', subcategoria: ''},
    {codigo: '67', nombre: 'Gastos financieros', tipo: 'gasto', subcategoria: 'gasto_financiero'},
]) {
    const ids = ['subcategorias-por-tipo', 'id_tipo', 'id_subcategoria', 'subcategoria_group',
        'cuentas-busqueda', 'cuentas-subcategoria', 'cuentas-limpiar', 'cuentas-resultados',
        'cuentas-filtros', 'id_codigo', 'cuentas-sin-resultados'];
    const nodes = Object.fromEntries(ids.map(id => [id, new Element()]));
    nodes['subcategorias-por-tipo'].textContent = JSON.stringify({
        activo: ['activo_corriente', 'existencias'], gasto: ['gasto_financiero'], patrimonio: ['patrimonio'],
    });
    const options = ['', 'activo_corriente', 'existencias', 'patrimonio', 'gasto_financiero'];
    nodes.id_subcategoria.options = options.map(value => new Element(value));
    nodes['cuentas-subcategoria'].options = ['*', ...options].map(value => new Element(value));
    nodes['cuentas-subcategoria'].value = '*';
    const rows = data.map(cuenta => new Element('', cuenta));
    const buttons = ['', 'activo', 'patrimonio', 'gasto'].map(tipo => new Element('', {tipo}));
    const reset = new Element();
    const newLink = new Element();
    const deleteLink = new Element('', {eliminar: '10 - Cuenta "especial" <script>'});
    const confirmations = [];
    const table = {scrollTop: 120};
    const selectors = {'[data-cuenta]': rows, '.cuentas-tipo': buttons, '[data-limpiar]': [reset],
        '.cuentas-new-link': [newLink], '[data-eliminar]': [deleteLink]};
    vm.runInNewContext(source, {
        document: {getElementById: id => nodes[id], querySelectorAll: selector => selectors[selector],
            querySelector: () => table},
        window: {confirm: message => { confirmations.push(message); return false; }},
    });
    return {nodes, rows, buttons, reset, newLink, deleteLink, confirmations, table};
}

test('busca sin tildes, combina palabras y cuenta resultados', () => {
    const app = setup();
    assert.equal(app.buttons[1].count.textContent, 2);
    app.nodes['cuentas-busqueda'].value = '  MERCADERIAS 20  ';
    app.nodes['cuentas-busqueda'].fire('input');
    assert.deepEqual(app.rows.map(row => row.hidden), [true, false, true, true]);
    assert.equal(app.nodes['cuentas-resultados'].textContent, 'Mostrando 1 de 4 cuentas');
    assert.equal(app.table.scrollTop, 0);
});

test('combina búsqueda, tipo y subcategoría y limpia selecciones incompatibles', () => {
    const app = setup();
    app.buttons[1].fire('click');
    app.nodes['cuentas-subcategoria'].value = 'existencias';
    app.nodes['cuentas-subcategoria'].fire('change');
    assert.deepEqual(app.rows.map(row => row.hidden), [true, false, true, true]);
    app.nodes['cuentas-busqueda'].value = 'efectivo';
    app.nodes['cuentas-busqueda'].fire('input');
    assert.ok(app.rows.every(row => row.hidden));
    assert.equal(app.nodes['cuentas-sin-resultados'].hidden, false);
    app.buttons[3].fire('click');
    assert.equal(app.nodes['cuentas-subcategoria'].value, '*');
    assert.equal(app.buttons[3].attributes['aria-pressed'], 'true');
    app.reset.fire('click');
    assert.ok(app.rows.every(row => !row.hidden));
    assert.equal(app.nodes['cuentas-limpiar'].hidden, true);
    assert.equal(app.nodes['cuentas-sin-resultados'].hidden, true);
    assert.equal(app.nodes['cuentas-busqueda'].focused, true);
});

test('General filtra cuentas sin subcategoría y el catálogo vacío inicia sin errores', () => {
    const app = setup();
    app.nodes['cuentas-subcategoria'].value = '';
    app.nodes['cuentas-subcategoria'].fire('change');
    assert.deepEqual(app.rows.map(row => row.hidden), [true, true, false, true]);
    const empty = setup([]);
    assert.equal(empty.nodes['cuentas-resultados'].textContent, 'Mostrando 0 de 0 cuentas');
});

test('el formulario ofrece solo subcategorías compatibles y reinicia al cambiar de tipo', () => {
    const app = setup();
    assert.equal(app.nodes.subcategoria_group.hidden, true);
    app.nodes.id_tipo.value = 'activo';
    app.nodes.id_tipo.fire('change');
    assert.equal(app.nodes.subcategoria_group.hidden, false);
    app.nodes.id_subcategoria.value = 'existencias';
    app.nodes.id_tipo.value = 'gasto';
    app.nodes.id_tipo.fire('change');
    assert.equal(app.nodes.id_subcategoria.value, '');
    assert.equal(app.nodes.id_subcategoria.options.find(option => option.value === 'existencias').disabled, true);
    assert.equal(app.nodes.id_subcategoria.options.find(option => option.value === 'gasto_financiero').disabled, false);
});

test('confirmación trata nombres como texto y permite cancelar; nueva cuenta enfoca el código', () => {
    const app = setup();
    let prevented = false;
    app.deleteLink.fire('click', {preventDefault: () => { prevented = true; }});
    assert.equal(prevented, true);
    assert.equal(app.confirmations[0], '¿Eliminar la cuenta 10 - Cuenta "especial" <script>?');
    app.newLink.fire('click');
    assert.equal(app.nodes.id_codigo.focused, true);
});
