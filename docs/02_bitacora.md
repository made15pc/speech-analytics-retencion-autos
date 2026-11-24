# Bitácora del proyecto

Última actualización: 24 de noviembre de 2026.

## 1. Dónde quedamos

| Fase | Estado |
|---|---|
| 1. Diseño del caso y KPIs | ✅ cerrada |
| 2. Datos operativos y verdad de terreno | ✅ cerrada y verificada en Colab (idénticos a la corrida original) |
| 3. Clave de OpenAI y modelo | ✅ cerrada (`gpt-6-luna` responde) |
| 4. Piloto de diálogos y ajuste del prompt (parches 01 a 03) | ✅ cerrada |
| 5. Generación de los 402 diálogos | ✅ cerrada: 0 errores, 267,463 tokens de entrada y 1,048,921 de salida, ≈ US$ 0.55 |
| 5b. Normalización y control de calidad | ✅ cerrada (ver sección 4b) |
| 6a–6d. Voz sintética estéreo: 57 llamadas, versión limpia y «telefónica» simulada | ✅ cerradas (ver sección 4c) |
| **6e. Transcripción por canal (ASR) + WER** | **⏳ siguiente paso** |
| 7. Extracción de insights con LLM (salida estructurada) | ⏳ |
| 8. Validación (verdad de terreno + auditoría manual + CallCenterEN) | ⏳ |
| 9. Modelo y dashboard en Power BI + medidas DAX | ⏳ |
| 10. Informe de hallazgos y recomendaciones (deck de 5 a 7 láminas) | ⏳ |

## 2. Cómo retomar (Colab)

Colab borra `/content` al cerrar la sesión. El código vive en este repositorio; los **datos generados** (`data/dialogos/`) también están versionados, porque regenerarlos cuesta dinero y no es reproducible bit a bit (el LLM no es determinista).

1. Clona el repositorio e instala dependencias:
   ```python
   !git clone https://github.com/made15pc/speech-analytics-retencion-autos.git
   %cd speech-analytics-retencion-autos
   !pip install -q -r requirements.txt
   ```
2. Carga la clave desde *Secrets* (guardada como `OPENAI_API_KEY`) y fija el modelo:
   ```python
   import os
   from google.colab import userdata
   os.environ["OPENAI_API_KEY"] = userdata.get("OPENAI_API_KEY")
   MODELO = "gpt-6-luna"
   ```
3. Los datos ya están en `data/raw/` (tablas operativas) y `data/dialogos/` (402 diálogos normalizados, muestra, QA, selección de audio y guiones hablables). **No hay que regenerar los diálogos.** Para el 6e hace falta además el audio (`data/audio/`, ≈ 1 GB), que **no se versiona**: vive en Drive y se puede regenerar con `preparar_audio.py` → `sintetizar_audio.py` (API de voz, poco más de US$ 3 en la corrida original; no es reproducible bit a bit) → `degradar_audio.py` (sin API, determinista).
4. Si se reinicia el kernel y falla un `import`, ejecutar la celda de recuperación del notebook (fija la ruta de forma absoluta).

## 3. Decisiones tomadas

- **Todo sintético.** No se usa información de ninguna empresa real. Los datos operativos salen de `generar_datos.py` (semilla 42); los diálogos los escribe un LLM a partir de una ficha con la verdad de terreno de cada llamada.
- **El LLM no decide qué pasa en la llamada:** la decisión (motivo, oferta, aceptación, conducta del asesor) viene de la simulación. Así se mide si el extractor recupera lo sembrado.
- **Muestra estratificada con peso muestral** para extrapolar porcentajes de la muestra a toda la operación.
- **CallCenterEN** (inglés, CC BY-NC 4.0, uso no comercial) se usará solo para validar el método, no como fuente del proyecto.

## 4. Cambios al generador de diálogos durante el piloto

| Parche | Problema detectado | Corrección |
|---|---|---|
| 01 | `--n 5` generaba 96 llamadas (mínimo de 6 por estrato × 16 estratos); además la ficha se contradecía cuando el cliente aceptaba sin oferta ("acepta la alternativa" y "no ofrece alternativa") | Modo piloto: con `n < 100` toma 1 llamada de `n` estratos distintos. Ficha con tres casos (acepta con oferta, acepta sin oferta, no acepta) |
| 02 | El modelo inventaba fechas ("16 de noviembre de 2026") fuera del escenario (mayo a julio); repetía el resumen del acuerdo hasta 3 veces; el cliente explicaba el motivo con demasiada claridad | La ficha incluye la fecha real de la llamada y se prohíbe inventar otras; regla anti-repetición (llenar con esperas y desvíos); variable de claridad: 40 % de llamadas con motivo indirecto, asignado por el ID de la llamada (`motivo_claro()`) |
| 03 | En las llamadas indirectas el cliente mencionaba tres motivos con el mismo peso y la etiqueta real no era recuperable; el modelo escribía "mi [DNI] es [DNI]" | El motivo real debe aparecer al menos dos veces con detalle y los demás temas deben quedar descartados por el cliente; solo el valor va enmascarado ("mi DNI es [DNI]") |
| 04 | El generador validaba solo la clave `hablante`: 2 turnos de 402 llegaron con la clave `text` en vez de `texto` | La validación exige además `texto` no vacío. **No se regeneró nada:** la corrida de 402 usó la versión sin este parche (md5 `3728d95d…`); el repositorio contiene la versión con el parche (md5 `e7182cef…`), que solo difiere en esa validación |

Resultado del piloto de 5 diálogos tras el parche 03 (caso revisado a mano): cumple los 5 puntos de la ficha; 944 palabras frente a 952 de objetivo; sin fechas ajenas; sin etiquetas técnicas.

## 4b. Control de calidad de los 402 diálogos (paso 5b)

Primera pasada: 41 fallos duros y 212 alertas blandas. Revisados uno a uno con el contexto, casi todo era ruido del propio control. Hallazgos:

| Marca inicial | Veredicto | Acción |
|---|---|---|
| Marcadores inventados (20 diálogos, 27 apariciones: `[NÚMERO DE SOLICITUD]`, `[CÓDIGO]`…) y 2 `[Pausa breve]` | **Defecto real** (la voz los leería) | `normalizar_dialogos.py`: número ficticio de 6 dígitos estable por diálogo; acotaciones eliminadas. Sin llamar a la API |
| Fuga de etiqueta (15) | Falso positivo: eran la palabra «ficha» (registro del cliente), ninguna etiqueta técnica | «ficha» pasa a alerta blanda `menciona_ficha`; las 15 se leyeron: lenguaje natural del asesor |
| Fecha lejana (9) | Falso positivo: una suspensión de 3 meses proyecta fechas a ~110 días y el umbral era 45 | Umbral a 130 días. Las 9 fechas eran coherentes con la oferta |
| «Hoy» distinto (1) | Falso positivo: «desde hoy, sino desde el 18 de agosto» | Solo cuenta «hoy» pegado a la fecha |
| Etiqueta como palabra (1, L004591) | Excepción aceptada: «la placa que me diste, la [PLACA]» se lee como valor | Documentada, no se toca |
| No debía aceptar (196 → 85 tras el parche) | **Heurística sin precisión.** En los 10 diálogos leídos, 9 eran falsos positivos y 1 dudoso (L023389) | Se descarta como criterio. La aceptación se mide con el extractor LLM contra la verdad de terreno |

Estado final (`data/dialogos/qa/qa_final.csv`): **1 fallo duro aceptado, 22 diálogos con alerta útil (`con_alerta = True`), 380 sin alerta**. Mediana de 1,142 palabras por diálogo (mín 388, máx 2,074). Las alertas útiles son: confirmación de acuerdo ausente, aceptación no detectada, validación de identidad, oferta esperada ausente, saludo y extensión. En la validación (fase 8) se reportará la precisión del extractor **con y sin** esos 22 diálogos (análisis de sensibilidad).

Parche 05 al control (`control_calidad.py`, md5 `d56cea06…`): `ficha` fuera de los fallos duros, umbral de fechas, regla de «hoy», filtro de negaciones y modismos en la aceptación, lectura robusta de la clave `texto`.

Lección de método: se midieron las alertas leyendo contexto, no confiando en el conteo. Un chequeo por palabras clave es útil para decidir qué leer y malo para decidir qué descartar.

## 4c. Fase 6: voz sintética (pasos 6a a 6d)

Diseño final y resultado. Difiere del diseño inicial en tres puntos: se usaron **57 llamadas** (no ~30), la selección fue **≤ 800 palabras más 5 llamadas de siniestro**, y el **modelo de transcripción se confirma en el 6e** (el plan inicial decía Whisper).

**6a. Verificación de modelos y herramientas** (ffmpeg, pydub, modelos de voz y de transcripción disponibles para la clave). Los precios y las fechas de retiro de modelos manejados hasta ahora vienen de fuentes secundarias y **no están confirmados en la página oficial**; se verifican antes del 6e.

**6b. Selección y guiones hablables** (`seleccion_audio.csv`, `guiones_audio.jsonl`, `src/preparar_audio.py`, md5 `946964d3…`)
- 57 llamadas: 52 del grupo `base_hasta_800` (≤ 800 palabras, elegidas entre las 379 llamadas limpias, sin alertas ni fallos duros) y 5 del grupo `complemento_siniestro` (L012751, L009107, L002739, L006451, L017717). Las llamadas de siniestro tienen al menos 947 palabras, por eso el corte de 800 dejaba fuera el motivo `mala_experiencia_siniestro`; las 5 de complemento tienen `cliente_acepta = False` y ninguna es de asesor senior. De las 52 base, aceptan 14 y no aceptan 38.
- 57 guiones, 1,455 turnos, 229,479 caracteres; clientes ficticios: 31 hombres y 26 mujeres (género detectado por el trato del asesor; si no hay pista, sorteo determinista por ID).
- `[DNI]` → 8 dígitos en palabras; `[PLACA]` → 3 letras separadas y 3 dígitos en palabras; `[TARJETA]` → 4 dígitos; `[CORREO]` → «nombre punto apellido arroba correo punto com»; `S/ 249` → «249 soles». Se modificaron 191 turnos. El texto de referencia del WER es `texto_hablado`.

**6c. Voz: piloto y ajuste** (`src/sintetizar_audio.py`)
- TTS `gpt-4o-mini-tts`, una petición por turno. Voces: asesora `coral`, asesor `echo`, clienta `sage`, cliente `cedar`. El género del asesor es estable por ID (impar = mujer, par = hombre): cada asesor conserva su voz.
- Estéreo: asesor en el canal izquierdo, cliente en el derecho, cada canal con silencio mientras habla el otro. Master en **FLAC**: un MP3 estéreo puede filtrar un canal en el otro y contaminar la transcripción por canal. Pausas de 250 a 800 ms entre hablantes distintos.
- **Piloto L023691 (sentimiento negativo → negativo), versión 1:** se entendía, pero (a) el cliente sonaba plano y (b) las esperas no se distinguían. La causa de (b) estaba en el diseño: la espera solo se modelaba cuando el mismo hablante tenía dos turnos seguidos, y esa llamada no los tenía. Un diagnóstico sobre los 57 guiones mostró que 55 tienen frases de espera del asesor (160 en total) y que **siempre** habla el cliente justo después.
- **Versión 2 (parche 06, md5 `e552cb0c…`):** (1) la instrucción de voz del cliente depende de `sentimiento_inicio` (primera mitad de la llamada) y `sentimiento_fin` (segunda mitad), tomados de la verdad de terreno; (2) tras una frase de espera del asesor se inserta un silencio de 3 a 7 s (decisión de diseño, no un dato); (3) el caché de turnos incluye un hash de voz + instrucción + texto: sin eso, cambiar las instrucciones habría reutilizado los mp3 viejos sin avisar. Evaluación **por oído, una sola persona**: en el piloto la v2 fue mejor en las esperas y en el tono del cliente, sin regresiones; otras dos llamadas (neutro → neutro y negativo → positivo) se reportaron «ok» sin más detalle.

**6d. Voz completa y versión telefónica** (`src/degradar_audio.py`, md5 `454f0254…`)
- **Voz limpia, 57 llamadas:** 314.4 min y 1,455 turnos. 0 turnos con filtración entre canales (en cada turno: nivel propio > −40 dBFS y nivel del otro canal < −60 dBFS). 160 esperas; L014609 y L012563 no tienen ninguna. Hay 2 turnos seguidos del mismo hablante que recibieron una pausa de 2.5 a 6 s sin ser esperas: efecto pequeño y no buscado. Las 56 llamadas restantes tardaron 17.7 min con 4 hilos.
- **Costo de la voz:** poco más de US$ 3 según el panel de OpenAI (cifra exacta pendiente de anotar). La referencia de fuentes secundarias (≈ US$ 4.7) sobrestimó ≈ 35 %. La duración total también superó la estimación inicial (≈ 268 min): salió 314.4.
- **Versión telefónica (simulada), 57 llamadas:** 24 → 8 kHz; pasa-banda Butterworth de orden 4 de 300 a 3400 Hz; ruido blanco filtrado en la misma banda, a una SNR de 20 dB respecto del RMS del habla activa de cada canal (ruido independiente por canal); compresión mu-law (mu = 255, 8 bits; aproximación de G.711, no el códec exacto). Determinista (semilla por llamada y canal); duración idéntica al audio limpio. SNR medida: 19.99 a 20.01 dB, que coincide con el objetivo por construcción: valida el código, **no** el realismo. Los 20 dB son un escenario moderado elegido por la autora, no un valor medido en llamadas reales; en la escucha del piloto la voz seguía entendiéndose.
- Respaldo: audio limpio, caché de turnos, versión telefónica y scripts en Drive. El audio no está en GitHub.

## 5. Limitaciones conocidas (hay que declararlas en el informe)

1. **Los hallazgos están sembrados.** El alza de tarifa de julio, el problema de siniestros en Arequipa, el CRM con ~28 % de errores y las diferencias por nivel de asesor se programaron a propósito. El valor del proyecto es probar que el método los recupera, no "descubrirlos".
2. **FCR de 90 % es optimista.** Resulta de cómo se simularon las rellamadas (~6 %); en operaciones reales suele ser menor.
3. **CSAT bajo (39 % de notas 4–5) y NPS de −39.** Decisión discutible (quien llama a cancelar suele estar molesto); es ajustable en `generar_datos.py`.
4. **La indirección del motivo quedó suave.** Con el parche 03, el motivo real aparece hacia el primer tercio de la llamada. La brecha de precisión entre llamadas claras e indirectas probablemente será pequeña: no presentarla como "robustez ante ambigüedad".
5. **Los diálogos son más limpios que los reales.** El cliente tiende a repetir el motivo (en el piloto, en 7 de 16 turnos). La precisión del extractor sobre datos sintéticos sobreestima el rendimiento real; por eso se contrasta con CallCenterEN.
6. **El ánimo inicial negativo sale flojo** en algunas llamadas (impaciencia en vez de enojo). Vigilarlo en la precisión de sentimiento.
7. **Estos números los decidió el simulador:** no son referencias del mercado.
8. **El audio es más limpio que el real.** El TTS no tiene disfluencias ni ruido: el WER de la versión limpia es optimista. La versión telefónica es una simulación (sin pérdida de paquetes, eco, cortes ni códecs de bajo bitrate; ruido estacionario).
9. **La selección de audio sesga hacia llamadas cortas.** `aumento_prima` pesa 38 % en el subconjunto frente a 26 % en la población y hay menos clientes que aceptan. El subconjunto sirve para comparar la degradación audio → texto, no para estimar prevalencias. `mala_experiencia_siniestro` entra solo con 5 llamadas largas, todas sin aceptación y sin asesor senior.
10. **Poca variedad de voces y de dinámica.** Cuatro voces (dos de asesor, dos de cliente); sin interrupciones ni solapamiento. Las esperas son silencios artificiales de 3 a 7 s tras una frase de espera, no un dato.
11. **La emoción de la voz es aproximada.** El ánimo viene de la verdad de terreno por llamada (inicio en la primera mitad, fin en la segunda), no por turno, y su efecto en la voz se verificó solo por oído en 3 llamadas.
12. **Transcripción por canal:** cada canal tiene tramos largos en los que solo hay silencio (versión limpia) o ruido (telefónica). Un ASR puede inventar texto ahí; hay que vigilarlo al contar errores.

## 6. Pendientes y cosas a recordar

- **Fase 6e (transcripción y WER), plan.** El audio y el texto de referencia ya están hechos (sección 4c):
  - Verificar en la fuente oficial el modelo de transcripción, su precio y las fechas de retiro (lo manejado hasta ahora es de fuentes secundarias). Probar primero con **una** llamada.
  - Transcribir **cada canal por separado** (asesor izquierdo, cliente derecho): así no hace falta diarización. Cada archivo mono dura lo mismo que la llamada, de modo que los minutos facturados se duplican (314 min × 2 canales por versión).
  - WER por hablante, en la versión limpia y en la telefónica, contra `texto_hablado`. Hace falta un normalizador de números y entidades (dígitos frente a palabras; «ABC 123» frente a «A B C uno dos tres»).
  - Comparación pareada: extractor sobre `texto_hablado` (control) frente al extractor sobre la transcripción (tratamiento), ambos contra la verdad de terreno. Con 57 llamadas los intervalos son anchos: reportar **cuántas llamadas cambian de respuesta**, no diferencias porcentuales.
  - Vigilar texto inventado por el ASR en los tramos de un canal donde solo hay ruido o silencio.
- **Auditoría manual de ~20 diálogos indirectos**, a ciegas respecto de la etiqueta, para estimar el techo de precisión por ambigüedad del propio diálogo.
- **Para el dashboard:** hallazgo operativo a mostrar: ocupación de 68 % con nivel de servicio de 70 % (mala distribución de asesores por hora: a las 10 h el nivel de servicio es 37 %, a las 18 h es 97 %). Mayo y junio rondan 83 % de nivel de servicio y 6–7 % de abandono; julio cae a 55 % y 21 %.
- **Seguridad:** la clave de OpenAI vive solo en *Secrets* de Colab. No se escribe en el código, en el notebook ni en el repositorio. Tampoco el token de GitHub. Conviene tener un límite mensual bajo en el panel de facturación de OpenAI.
