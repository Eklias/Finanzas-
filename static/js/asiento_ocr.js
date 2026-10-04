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
    const btnVoz = document.getElementById('btnGrabarVoz');
    const iconoVoz = document.getElementById('iconoMicrofono');
    const textoVoz = document.getElementById('textoBotonVoz');
    const btnGuardarTodas = document.getElementById('btnGuardarTodasLote');
    const btnDescargarExcelCaso = document.getElementById('btnDescargarExcelCaso');
    const btnDescargarExcelDirecto = document.getElementById('btnDescargarExcelDirecto');
    const btnLimpiarCaso = document.getElementById('btnLimpiarCaso');
    const tituloCasoDetectado = document.getElementById('tituloCasoDetectado');

    let ultimasOperaciones = [];
    let tituloCasoActual = 'CASO CICLO CONTABLE';
    let mediaRecorder = null;
    let audioChunks = [];
    let grabacionActiva = false;

    function showFeedback(message, error = false) {
        feedback.textContent = message;
        feedback.className = error ? 'alert alert-error' : 'alert alert-success';
        feedback.style.display = 'block';
    }

    toggle.addEventListener('click', () => {
        const manual = textBox.style.display === 'none';
        textBox.style.display = manual ? 'block' : 'none';
        files.disabled = manual;
        toggle.textContent = manual ? '📷 Subir imagen' : '✍️ Pegar texto';
    });

    // ═══ DICTADO POR VOZ CON GROQ WHISPER ═══
    if (btnVoz) {
        btnVoz.addEventListener('click', async () => {
            if (!grabacionActiva) {
                // Iniciar grabación
                try {
                    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                    audioChunks = [];
                    mediaRecorder = new MediaRecorder(stream);

                    mediaRecorder.ondataavailable = (e) => {
                        if (e.data.size > 0) audioChunks.push(e.data);
                    };

                    mediaRecorder.onstop = async () => {
                        stream.getTracks().forEach(track => track.stop());
                        const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
                        await enviarAudioGroq(audioBlob);
                    };

                    mediaRecorder.start();
                    grabacionActiva = true;
                    btnVoz.style.background = '#fee2e2';
                    btnVoz.style.borderColor = '#ef4444';
                    btnVoz.style.color = '#b91c1c';
                    if (iconoVoz) iconoVoz.textContent = '⏹️';
                    if (textoVoz) textoVoz.textContent = 'Detener grabación';
                    showFeedback('🎙️ Escuchando... Dicta tu operación o hecho contable y haz clic en "Detener grabación".');
                } catch (err) {
                    showFeedback('No se pudo acceder al micrófono. Permita el acceso en el navegador.', true);
                }
            } else {
                // Detener grabación
                if (mediaRecorder && mediaRecorder.state !== 'inactive') {
                    mediaRecorder.stop();
                }
                grabacionActiva = false;
                btnVoz.style.background = '#ffffff';
                btnVoz.style.borderColor = '#cbd5e1';
                btnVoz.style.color = '#1e293b';
                if (iconoVoz) iconoVoz.textContent = '🎙️';
                if (textoVoz) textoVoz.textContent = 'Dictar por Voz';
            }
        });
    }

    async function enviarAudioGroq(audioBlob) {
        showFeedback('⏳ Transcribiendo voz con Whisper AI...');
        const formData = new FormData();
        formData.append('audio', audioBlob, 'grabacion.webm');

        try {
            const token = document.querySelector('#formAsiento [name="csrfmiddlewaretoken"]')?.value || '';
            const resp = await fetch(panel.dataset.audioUrl, {
                method: 'POST',
                body: formData,
                headers: {'X-CSRFToken': token}
            });
            const data = await resp.json();
            if (!resp.ok || data.error) throw new Error(data.error || 'Error al transcribir el audio.');

            textBox.style.display = 'block';
            files.disabled = true;
            toggle.textContent = '📷 Subir imagen';

            const textoActual = text.value.trim();
            text.value = textoActual ? `${textoActual}\n${data.texto}` : data.texto;
            showFeedback(`✅ Dictado transcrito: "${data.texto}". Haz clic en "Procesar Caso" para estructurar con IA.`);
        } catch (error) {
            showFeedback(error.message || 'Error en la transcripción.', true);
        }
    }

    // ═══ DESCARGA DIRECTA DE EXCEL DEL CASO RESUELTO POR IA (HOJA ÚNICA) ═══
    async function descargarExcelDelCaso() {
        const token = document.querySelector('#formAsiento [name="csrfmiddlewaretoken"]')?.value || '';
        const exportUrl = panel.dataset.exportarCasoUrl || panel.dataset.excelUrl;

        if (ultimasOperaciones && ultimasOperaciones.length > 0) {
            showFeedback('⏳ Generando archivo Excel en hoja única para este caso resuelto...');
            try {
                const resp = await fetch(panel.dataset.exportarCasoUrl, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': token
                    },
                    body: JSON.stringify({
                        operaciones: ultimasOperaciones,
                        titulo_caso: tituloCasoActual || 'CASO CICLO CONTABLE'
                    })
                });
                if (!resp.ok) throw new Error('Error al generar el archivo Excel.');
                const blob = await resp.blob();
                const downloadUrl = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = downloadUrl;
                const safeName = (tituloCasoActual || 'Caso_Ciclo_Contable').replace(/[^a-zA-Z0-9_\-]/g, '_');
                a.download = `${safeName}.xlsx`;
                document.body.appendChild(a);
                a.click();
                a.remove();
                window.URL.revokeObjectURL(downloadUrl);
                showFeedback(`✅ ¡Excel de "${tituloCasoActual}" descargado exitosamente!`);
            } catch (err) {
                showFeedback(err.message || 'Error al descargar Excel.', true);
            }
        } else {
            // Si no hay operaciones en memoria de la IA, descargar lo registrado en BD
            window.location.href = panel.dataset.exportarCasoUrl || panel.dataset.excelUrl;
        }
    }

    if (btnDescargarExcelCaso) {
        btnDescargarExcelCaso.addEventListener('click', descargarExcelDelCaso);
    }
    if (btnDescargarExcelDirecto) {
        btnDescargarExcelDirecto.addEventListener('click', descargarExcelDelCaso);
    }

    // ═══ LIMPIAR ASIENTOS ANTERIORES (NUEVO CASO) ═══
    if (btnLimpiarCaso) {
        btnLimpiarCaso.addEventListener('click', async () => {
            if (!confirm('¿Deseas vaciar todos los asientos registrados anteriormente para resolver un caso nuevo desde cero?')) {
                return;
            }
            btnLimpiarCaso.disabled = true;
            btnLimpiarCaso.textContent = '⏳ Limpiando...';
            try {
                const token = document.querySelector('#formAsiento [name="csrfmiddlewaretoken"]')?.value || '';
                const resp = await fetch(panel.dataset.limpiarUrl, {
                    method: 'POST',
                    headers: {'X-CSRFToken': token}
                });
                const resData = await resp.json();
                if (!resp.ok || resData.error) throw new Error(resData.error || 'Error al limpiar asientos.');
                alert(resData.mensaje);
                window.location.reload();
            } catch (err) {
                alert(err.message || 'Error al limpiar la base de datos.');
                btnLimpiarCaso.disabled = false;
                btnLimpiarCaso.textContent = '🗑️ Nuevo Caso (Limpiar Libro)';
            }
        });
    }

    // ═══ GUARDAR TODAS LAS OPERACIONES DETECTADAS EN LOTE ═══
    if (btnGuardarTodas) {
        btnGuardarTodas.addEventListener('click', async () => {
            if (!ultimasOperaciones.length) {
                showFeedback('No hay operaciones detectadas para guardar.', true);
                return;
            }
            if (!confirm(`¿Deseas registrar las ${ultimasOperaciones.length} operaciones de "${tituloCasoActual}" en la base de datos?`)) {
                return;
            }

            btnGuardarTodas.disabled = true;
            btnGuardarTodas.textContent = '⏳ Guardando...';

            try {
                const token = document.querySelector('#formAsiento [name="csrfmiddlewaretoken"]')?.value || '';
                const resp = await fetch(panel.dataset.guardarLoteUrl, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': token
                    },
                    body: JSON.stringify({ operaciones: ultimasOperaciones })
                });
                const resData = await resp.json();
                if (!resp.ok || resData.error) throw new Error(resData.error || 'No se pudieron guardar las operaciones.');

                showFeedback(`🎉 ${resData.mensaje} Puedes descargar el Excel o consultar los reportes.`);
                setTimeout(() => window.location.reload(), 1500);
            } catch (err) {
                showFeedback(err.message || 'Error al guardar en lote.', true);
                btnGuardarTodas.disabled = false;
                btnGuardarTodas.textContent = '⚡ Guardar en BD';
            }
        });
    }

    function loadOperation(operation) {
        if (!operation || !Array.isArray(operation.movimientos) || !operation.movimientos.length ||
            operation.movimientos.some(m => !m || !['debe', 'haber'].includes(m.tipo) ||
                !Number.isFinite(Number(m.monto)) || Number(m.monto) <= 0)) {
            showFeedback('La operación no contiene movimientos válidos.', true);
            return;
        }
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
            ? `Operación cargada. Cuentas pendientes de revisión manual: ${unresolved.join(', ')}. Seleccione sus cuentas antes de guardar.`
            : 'Operación cargada. Revise fecha, cuentas, montos y balance antes de guardar.', unresolved.length > 0);
    }

    button.addEventListener('click', async () => {
        if (button.disabled) return;
        const selected = files.disabled ? [] : Array.from(files.files || []);
        const manual = files.disabled ? text.value.trim() : '';
        if (!selected.length && !manual) {
            showFeedback('Seleccione una imagen, dicte por voz o pegue el enunciado del caso.', true);
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
        ultimasOperaciones = [];

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
            if (!response.ok || data.error) throw new Error(data.error || 'No se pudo procesar el caso.');
            if (Array.isArray(data.operaciones) && data.operaciones.length) {
                ultimasOperaciones = data.operaciones;
                tituloCasoActual = data.titulo_caso || 'CASO CICLO CONTABLE';
                if (tituloCasoDetectado) {
                    tituloCasoDetectado.textContent = `📌 ${tituloCasoActual} (${data.operaciones.length} operaciones resueltas):`;
                }

                data.operaciones.forEach((operation, index) => {
                    const chip = document.createElement('button');
                    chip.type = 'button';
                    chip.className = 'btn btn-secondary btn-sm';
                    chip.textContent = `Cargar #${index + 1}: ${operation.fecha || 'Fecha'} - ${operation.glosa || 'Operación'}`;
                    chip.addEventListener('click', () => loadOperation(operation));
                    operations.appendChild(chip);
                });
                selector.style.display = 'block';
                showFeedback(`✅ Caso resuelto: Se estructuraron ${data.operaciones.length} operaciones contables. Puedes descargar directamente el Excel de este caso o guardarlas en BD.`);
            } else {
                showFeedback('Texto recibido. La IA no identificó operaciones contables en el enunciado.');
            }
        } catch (error) {
            showFeedback(error.message || 'No se pudo conectar con el servidor.', true);
        } finally {
            button.disabled = false;
            loading.style.display = 'none';
        }
    });
})();
