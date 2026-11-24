# POC de Speech Analytics: retención de desafiliaciones en seguro vehicular

Prueba de concepto de punta a punta: desde llamadas de un call center de retención hasta indicadores e insights para el negocio, usando NLP y LLM.

> **Todos los datos son sintéticos.** La empresa ("AutoSegura Perú"), los clientes, los asesores y las conversaciones son ficticios. No se usó información de ninguna empresa real.

## Pregunta de negocio
¿Por qué se van los clientes de Autos, qué hace el equipo de retención cuando llaman y qué cambios aumentarían la prima retenida a 90 días?

## Qué demuestra este proyecto
- Traducir una necesidad de negocio a una taxonomía, KPIs y un modelo de datos (`docs/01_diseno_del_caso.md`).
- Separar KPIs **operativos** (central telefónica, encuestas, finanzas) de KPIs **conversacionales** (Speech Analytics) y cruzarlos.
- Un pipeline audio → texto → extracción estructurada con LLM → validación contra verdad de terreno.
- Un dashboard en Power BI con hallazgos y recomendaciones.

## Método y honestidad sobre los datos
Como no existen grabaciones públicas en español de retención de seguros vehiculares, el proyecto **siembra patrones conocidos** en los datos (sección 5 del diseño) y mide si el pipeline los recupera. El método se valida además sobre transcripciones reales en inglés (CallCenterEN, licencia CC BY-NC 4.0, uso no comercial).

## Estructura
```
docs/01_diseno_del_caso.md     escenario, KPIs, taxonomía, patrones sembrados, modelo de datos
docs/02_bitacora.md            estado, decisiones, limitaciones y cómo retomar
src/generar_datos.py           [1] tablas operativas + verdad de terreno (reproducible)
src/revisar_kpis.py            KPIs de referencia para contrastar con el dashboard
src/generar_dialogos.py        [2] diálogos con LLM condicionados a la verdad de terreno
src/normalizar_dialogos.py     [2b] corrige claves y marcadores sin volver a llamar a la API
src/control_calidad.py         [2c] control automático: fallos duros y alertas blandas
src/preparar_audio.py          [6b] guiones hablables: valores ficticios para [DNI], [PLACA]… (sin API)
src/sintetizar_audio.py        [6c-6d] voz estéreo (asesor izquierdo, cliente derecho) con TTS; reanuda desde caché
src/degradar_audio.py          [6d] versión «telefónica» simulada: 8 kHz, 300-3400 Hz, ruido, mu-law (sin API)
notebooks/01_datos_y_dialogos.ipynb   ejecución en Colab (fases 1 a 5b)
data/raw/                      CSV del modelo estrella
data/dialogos/                 402 diálogos, muestra estratificada, QA, selección de 57 llamadas y sus guiones hablables
data/audio/                    audio de las 57 llamadas (NO versionado, ≈ 1 GB; ver docs/02_bitacora.md)
```

## Avance
| Fase | Estado |
|---|---|
| 1. Diseño del caso y KPIs | ✅ |
| 2. Datos operativos y verdad de terreno | ✅ |
| 3–4. Clave de OpenAI, piloto de diálogos y ajuste del prompt | ✅ |
| 5. Generación de 402 diálogos (≈ US$ 0.55) | ✅ |
| 5b. Normalización y control de calidad | ✅ |
| 6a–6d. Voz sintética estéreo: 57 llamadas, versión limpia y «telefónica» simulada | ✅ |
| 6e. Transcripción por canal (ASR) + WER | ⏳ siguiente |
| 7. Extracción de insights con LLM (salida estructurada) | ⏳ |
| 8. Validación (verdad de terreno + auditoría manual + CallCenterEN) | ⏳ |
| 9. Modelo y dashboard en Power BI + medidas DAX | ⏳ |
| 10. Informe de hallazgos y recomendaciones | ⏳ |

Estado detallado, decisiones, limitaciones conocidas y cómo retomar: `docs/02_bitacora.md`.

## Cómo ejecutar
```bash
pip install -r requirements.txt
python src/generar_datos.py --salida data/raw
python src/revisar_kpis.py --datos data/raw
python src/generar_dialogos.py --n 5 --mock           # prueba sin API (modo piloto: n debe ser ≤ 16, o ≥ 100 para muestra completa)
export OPENAI_API_KEY=...                             # o Secrets en Colab
python src/generar_dialogos.py --n 400 --modelo gpt-6-luna
python src/normalizar_dialogos.py --dialogos data/dialogos/dialogos.jsonl
python src/control_calidad.py --dialogos data/dialogos/dialogos.jsonl --muestra data/dialogos/muestra.csv --salida data/dialogos/qa
python src/preparar_audio.py                          # guiones hablables (sin API); usa data/dialogos/seleccion_audio.csv
python src/sintetizar_audio.py --ids L023691          # una llamada de prueba (API de voz); sin --ids: las 57
python src/degradar_audio.py                          # versión telefónica simulada (sin API, determinista)
```

Los diálogos ya generados están versionados en `data/dialogos/`: no hace falta volver a gastar en la API para seguir con las fases siguientes. El audio no se versiona por tamaño; regenerarlo con `sintetizar_audio.py` usa la API de voz y no es reproducible bit a bit.
