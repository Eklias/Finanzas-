(() => {
    'use strict';

    const subcategoriasPorTipo = JSON.parse(document.getElementById('subcategorias-por-tipo').textContent);
    const tipoCuenta = document.getElementById('id_tipo');
    const subcategoriaCuenta = document.getElementById('id_subcategoria');

    function actualizarSubcategorias() {
        const permitidas = subcategoriasPorTipo[tipoCuenta.value] || [];
        document.getElementById('subcategoria_group').hidden = !permitidas.length;
        if (!permitidas.includes(subcategoriaCuenta.value)) subcategoriaCuenta.value = '';
        Array.from(subcategoriaCuenta.options).forEach(opcion => {
            opcion.hidden = opcion.value !== '' && !permitidas.includes(opcion.value);
            opcion.disabled = opcion.hidden;
        });
    }

    tipoCuenta.addEventListener('change', actualizarSubcategorias);
    actualizarSubcategorias();

    const normalizar = valor => valor.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('es').trim();
    const cuentas = Array.from(document.querySelectorAll('[data-cuenta]')).map(fila => ({
        fila,
        texto: normalizar(`${fila.dataset.codigo} ${fila.dataset.nombre}`),
        tipo: fila.dataset.tipo,
        subcategoria: fila.dataset.subcategoria,
    }));
    const busqueda = document.getElementById('cuentas-busqueda');
    const subcategoria = document.getElementById('cuentas-subcategoria');
    const botonesTipo = Array.from(document.querySelectorAll('.cuentas-tipo'));
    const limpiar = document.getElementById('cuentas-limpiar');
    const sinResultados = document.getElementById('cuentas-sin-resultados');
    const tabla = document.querySelector('.cuentas-table-scroll');
    let tipoSeleccionado = '';

    botonesTipo.forEach(boton => {
        boton.querySelector('[data-count]').textContent = boton.dataset.tipo
            ? cuentas.filter(cuenta => cuenta.tipo === boton.dataset.tipo).length
            : cuentas.length;
        boton.addEventListener('click', () => {
            tipoSeleccionado = boton.dataset.tipo;
            actualizarFiltroSubcategoria();
            filtrar();
        });
    });

    function actualizarFiltroSubcategoria() {
        const permitidas = subcategoriasPorTipo[tipoSeleccionado] || [];
        Array.from(subcategoria.options).forEach(opcion => {
            opcion.hidden = Boolean(tipoSeleccionado) && !['*', ''].includes(opcion.value) && !permitidas.includes(opcion.value);
            opcion.disabled = opcion.hidden;
        });
        if (subcategoria.selectedOptions[0].disabled) subcategoria.value = '*';
    }

    function filtrar() {
        const palabras = normalizar(busqueda.value).split(/\s+/).filter(Boolean);
        let visibles = 0;
        cuentas.forEach(cuenta => {
            const coincide = palabras.every(palabra => cuenta.texto.includes(palabra))
                && (!tipoSeleccionado || cuenta.tipo === tipoSeleccionado)
                && (subcategoria.value === '*' || cuenta.subcategoria === subcategoria.value);
            cuenta.fila.hidden = !coincide;
            if (coincide) visibles += 1;
        });
        botonesTipo.forEach(boton => boton.setAttribute('aria-pressed', String(boton.dataset.tipo === tipoSeleccionado)));
        document.getElementById('cuentas-resultados').textContent = `Mostrando ${visibles} de ${cuentas.length} cuentas`;
        limpiar.hidden = !palabras.length && !tipoSeleccionado && subcategoria.value === '*';
        if (sinResultados) sinResultados.hidden = visibles !== 0;
        if (tabla) tabla.scrollTop = 0;
    }

    function limpiarFiltros() {
        busqueda.value = '';
        tipoSeleccionado = '';
        subcategoria.value = '*';
        actualizarFiltroSubcategoria();
        filtrar();
        busqueda.focus();
    }

    busqueda.addEventListener('input', filtrar);
    subcategoria.addEventListener('change', filtrar);
    limpiar.addEventListener('click', limpiarFiltros);
    document.querySelectorAll('[data-limpiar]').forEach(boton => boton.addEventListener('click', limpiarFiltros));
    if (cuentas.length) document.getElementById('cuentas-filtros').hidden = false;
    filtrar();

    document.querySelectorAll('.cuentas-new-link').forEach(enlace => {
        enlace.addEventListener('click', () => document.getElementById('id_codigo').focus());
    });
    document.querySelectorAll('[data-eliminar]').forEach(enlace => {
        enlace.addEventListener('click', evento => {
            if (!window.confirm(`¿Eliminar la cuenta ${enlace.dataset.eliminar}?`)) evento.preventDefault();
        });
    });
})();
