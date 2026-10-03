(() => {
    'use strict';
    const panel = document.getElementById('ocr-panel');
    if (!panel) return;
    const button = document.getElementById('btnProcesarOcr');
    const files = document.getElementById('inputImagenOcr');
    const text = document.getElementById('inputTextoManual');
    const textBox = document.getElementById('contenedorModoTexto');
    const toggle = document.getElementById('btnToggleModoTexto');
    const feedback = document.getElementById('ocrFeedback');
    const loading = document.getElementById('ocrLoading');
    const selector = document.getElementById('selectorOperaciones');
    const operations = document.getElementById('listaOperacionesChips');
    const result = document.getElementById('ocrResultado');
    const detectedText = document.getElementById('ocrTextoDetectado');

    function showFeedback(message, error = false) {
        feedback.textContent = message;
        feedback.className = error ? 'alert alert-error' : 'alert alert-success';
        feedback.style.display = 'block';
    }

    toggle.addEventListener('click', () => {
        const manual = textBox.style.display === 'none';
        textBox.style.display = manual ? 'block' : 'none';
        files.disabled = manual;
        toggle.textContent = manual ? 'Subir imagen' : 'Pegar texto';
    });

    function loadOperation(operation) {
        if (!operation || !Array.isArray(operation.movimientos) || !operation.movimientos.length ||
            operation.movimientos.some(m => !m || !['debe', 'haber'].includes(m.tipo) ||
                !Number.isFinite(Number(m.monto)) || Number(m.monto) <= 0)) {
            showFeedback('La operación no contiene movimientos válidos.', true);
            return;
        }
        // Reutilizar las filas y el cálculo de balance del formulario actual.
        document.getElementById('movimientos-container').replaceChildren();
        contadorMovimientos = 0;
        document.getElementById('id_fecha').value = operation.fecha || '';
        document.getElementById('id_descripcion').value = operation.glosa || '';
        const unresolved = [];
        operation.movimientos.forEach((m, index) => {
            const code = String(m.codigo_cuenta ?? '').trim();
            const matches = code ? CUENTAS.filter(c => String(c.codigo ?? '').trim() === code) : [];
            const account = matches.length === 1 &&
                (m.pendiente_revision === undefined || m.pendiente_revision === false) ? matches[0] : null;
            if (!account) unresolved.push(`movimiento ${index + 1}${code ? ` (código ${code})` : ''}`);
            agregarMovimiento(account ? account.id : '', m.tipo, m.monto);
        });
        showFeedback(unresolved.length
            ? `Operación cargada. Cuentas pendientes de revisión manual: ${unresolved.join(', ')}. No hay una coincidencia exacta y segura en el catálogo. Seleccione sus cuentas antes de guardar.`
            : 'Operación cargada. Revise fecha, cuentas, montos y balance antes de guardar.', unresolved.length > 0);
    }

    button.addEventListener('click', async () => {
        if (button.disabled) return;
        const selected = files.disabled ? [] : Array.from(files.files || []);
        const manual = files.disabled ? text.value.trim() : '';
        if (!selected.length && !manual) {
            showFeedback('Seleccione una imagen o pegue un texto contable.', true);
            return;
        }
        const body = new FormData();
        selected.forEach(file => body.append('imagenes', file));
        if (manual) body.append('texto', manual);
        button.disabled = true;
        loading.style.display = 'flex';
        feedback.style.display = 'none';
        selector.style.display = 'none';
        operations.replaceChildren();
        result.hidden = true;
        detectedText.value = '';
        try {
            const token = document.querySelector('#formAsiento [name="csrfmiddlewaretoken"]').value;
            const response = await fetch(panel.dataset.url, {
                method: 'POST', body, headers: {'X-CSRFToken': token},
            });
            const data = await response.json();
            if (data.texto_ocr_detectado) {
                detectedText.value = data.texto_ocr_detectado;
                result.hidden = false;
            }
            if (!response.ok || data.error) throw new Error(data.error || 'No se pudo procesar la imagen.');
            if (Array.isArray(data.operaciones) && data.operaciones.length) {
                data.operaciones.forEach((operation, index) => {
                    const chip = document.createElement('button');
                    chip.type = 'button';
                    chip.className = 'btn btn-secondary btn-sm';
                    chip.textContent = `Cargar #${index + 1}: ${operation.fecha || 'Sin fecha'} - ${operation.glosa || 'Operación'}`;
                    chip.addEventListener('click', () => loadOperation(operation));
                    operations.appendChild(chip);
                });
                selector.style.display = 'block';
                showFeedback('Texto procesado. Seleccione una operación para cargarla en el formulario.');
            } else {
                showFeedback('Texto OCR disponible. La IA no identificó operaciones para cargar.');
            }
        } catch (error) {
            showFeedback(error.message || 'No se pudo conectar con el servidor.', true);
        } finally {
            button.disabled = false;
            loading.style.display = 'none';
        }
    });
})();
