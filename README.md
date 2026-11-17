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
notebooks/01_datos_y_dialogos.ipynb   ejecución en Colab (fases 1 a 5b)
data/raw/                      CSV del modelo estrella
data/dialogos/                 402 diálogos, muestra estratificada y resultado del QA (ver LEEME.md)
```

## Avance
| Fase | Estado |
|---|---|
| 1. Diseño del caso y KPIs | ✅ |
| 2. Datos operativos y verdad de terreno | ✅ |
| 3–4. Clave de OpenAI, piloto de diálogos y ajuste del prompt | ✅ |
| 5. Generación de 402 diálogos (≈ US$ 0.55) | ✅ |
| 5b. Normalización y control de calidad | ✅ |
| 6. Voz sintética estéreo + transcripción (Whisper) + WER | ⏳ siguiente |
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
```

Los diálogos ya generados están versionados en `data/dialogos/`: no hace falta volver a gastar en la API para seguir con las fases siguientes.
