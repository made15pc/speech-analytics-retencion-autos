# Datos de diálogos (sintéticos)

Todo es ficticio: empresa «AutoSegura Perú», clientes y asesores. Los diálogos los escribió un LLM (`gpt-6-luna`) a partir de una ficha con la verdad de terreno de cada llamada (`data/raw/verdad_conversacion.csv`).

| Archivo | Contenido |
|---|---|
| `dialogos.jsonl` | 402 diálogos normalizados. Una línea por llamada: `llamada_id`, `modelo`, `turnos` (lista de `{hablante: asesor\|cliente, texto}`), `tokens_entrada`, `tokens_salida` |
| `muestra.csv` | Muestra estratificada (motivo × aceptación, 16 estratos) con la ficha y el `peso_muestral` de cada llamada |
| `qa/qa_detalle.csv` | Resultado del control de calidad por diálogo (fallos duros y alertas blandas) |
| `qa/qa_final.csv` | Resumen final: `duros`, `blandos`, `alertas_utiles`, `con_alerta` (22 verdaderos, 380 falsos) |
| `seleccion_audio.csv` | Las 57 llamadas elegidas para el audio: `llamada_id`, `motivo_principal`, `nivel`, `cliente_acepta`, `claro`, `palabras`, `min_aprox`, `grupo` (`base_hasta_800` o `complemento_siniestro`) |
| `guiones_audio.jsonl` | Guiones hablables de esas 57: por turno `texto` (con marcadores) y `texto_hablado` (valores ficticios en palabras, referencia del WER), más el cliente ficticio (`genero`, `nombre`) y los `valores` usados |

Marcadores permitidos en el texto: `[NOMBRE_CLIENTE]`, `[DNI]`, `[PLACA]`, `[TARJETA]`, `[CORREO]`. Los números de gestión se reemplazaron por números ficticios de 6 dígitos.

**Reproducibilidad:** las tablas de `data/raw/` salen de `src/generar_datos.py` con semilla 42. Los diálogos **no** son reproducibles bit a bit (el LLM no es determinista); por eso se versionan.
