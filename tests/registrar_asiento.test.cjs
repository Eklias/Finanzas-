const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const template = fs.readFileSync(path.join(__dirname, '../templates/registrar_asiento.html'), 'utf8');
const source = template.match(/<script>([\s\S]*?)<\/script>/)[1];

class Element {
    constructor(tag = 'div') { this.tag = tag; this.children = []; this.className = ''; }
    set value(value) { this.currentValue = String(value); }
    get value() { return this.currentValue || ''; }
    appendChild(child) { this.children.push(child); child.parent = this; }
    remove() { this.parent.children = this.parent.children.filter(c => c !== this); }
    // Sólo interpretar los controles del marcado fijo de la fila; los nombres de
    // cuentas se añaden por textContent en el código real.
    set innerHTML(html) {
        this.children = [...html.matchAll(/<(select|input)\b[^>]*name="([^"]+)"/g)]
            .map(match => { const child = new Element(match[1]); child.name = match[2]; return child; });
    }
    querySelector(selector) {
        if (selector.startsWith('input')) return this.children.find(c => c.tag === 'input');
        const prefix = selector.match(/name\^="([^"]+)"/)[1];
        return this.children.find(c => c.tag === 'select' && c.name.startsWith(prefix));
    }
    querySelectorAll(tag) { return this.children.filter(c => c.tag === tag); }
}

function setup(movimientos) {
    const ids = ['movimientos-container', 'numMovimientos', 'totalDebe', 'totalHaber',
                 'balanceStatus', 'cuentas-data', 'asiento-inicial'];
    const nodes = Object.fromEntries(ids.map(id => [id, new Element()]));
    nodes['cuentas-data'].textContent = JSON.stringify([
        {id: 11, text: '10 - Caja'}, {id: 20, text: '50 - Capital'},
        {id: 30, text: '<script>alert(1)</script>'},
    ]);
    nodes['asiento-inicial'].textContent = JSON.stringify({descripcion: 'Aporte', movimientos});
    const context = {
        document: {
            getElementById: id => nodes[id] || nodes['movimientos-container'].children.find(c => c.id === id),
            createElement: tag => new Element(tag),
            querySelectorAll: () => nodes['movimientos-container'].children,
        },
    };
    vm.createContext(context);
    vm.runInContext(source, context);
    return {nodes, context, rows: () => nodes['movimientos-container'].children};
}

const inicial = [
    {cuenta_id: 11, tipo: 'debe', monto: '100.00'},
    {cuenta_id: 20, tipo: 'haber', monto: '100.00'},
];

test('formulario precarga cuentas, tipos e importes y calcula totales', () => {
    const app = setup(inicial);
    assert.equal(app.rows().length, 2);
    assert.equal(app.rows()[0].children[0].value, '11');
    assert.equal(app.rows()[0].children[1].value, 'debe');
    assert.equal(app.rows()[1].children[0].value, '20');
    assert.equal(app.rows()[1].children[2].value, '100.00');
    assert.equal(app.nodes.totalDebe.textContent, 'S/ 100.00');
    assert.equal(app.nodes.totalHaber.textContent, 'S/ 100.00');
    assert.equal(app.nodes.numMovimientos.value, '2');
});

test('los controles precargados siguen siendo editables', () => {
    const app = setup(inicial);
    app.rows()[0].children[0].value = 20;
    app.rows()[0].children[1].value = 'haber';
    app.rows()[0].children[2].value = '150.00';
    app.rows()[1].children[0].value = 11;
    app.rows()[1].children[1].value = 'debe';
    app.rows()[1].children[2].value = '150.00';
    app.context.actualizarBalance();
    assert.equal(app.nodes.totalDebe.textContent, 'S/ 150.00');
    assert.equal(app.nodes.totalHaber.textContent, 'S/ 150.00');
    assert.ok(app.nodes.balanceStatus.textContent.includes('Balanceado'));
    app.context.agregarMovimiento(11, 'debe', '10.00');
    assert.equal(app.nodes.numMovimientos.value, '3');
    assert.ok(app.nodes.balanceStatus.textContent.includes('Diferencia'));
    app.context.eliminarMovimiento(2);
    assert.equal(app.nodes.numMovimientos.value, '2');
    assert.equal(app.rows()[1].children[2].name, 'monto_1');
});

test('sin propuesta el formulario conserva sus dos filas vacías', () => {
    const app = setup([]);
    assert.equal(app.rows().length, 2);
    assert.equal(app.rows()[0].children[0].value, '');
    assert.equal(app.rows()[0].children[2].value, '');
    assert.equal(app.nodes.totalDebe.textContent, 'S/ 0.00');
});

test('nombres de cuentas con HTML sólo se insertan como texto de opciones', () => {
    const app = setup(inicial);
    const options = app.rows()[0].children[0].children;
    assert.equal(options[2].textContent, '<script>alert(1)</script>');
    assert.equal(options[2].tag, 'option');
    assert.equal(options[2].children.length, 0);
});
