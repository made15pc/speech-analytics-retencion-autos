# Diseño del caso: POC de Speech Analytics para retención de desafiliaciones

## 1. Escenario (ficticio)

**AutoSegura Perú** (empresa ficticia) vende seguro vehicular en tres planes: *Todo Riesgo*, *Plus* y *Responsabilidad Civil (RC)*. Los clientes que quieren cancelar su póliza llaman a la cola de **Retención** (entrante) o dejan una solicitud web y reciben una **devolución de llamada** (callback).

- Período analizado: **1 de mayo al 31 de julio de 2026** (13 semanas).
- Ventana de observación de la póliza: **90 días** después de la llamada (cerrada al 29 de octubre), para medir la retención real y no solo la "retención declarada".
- Equipo: 18 asesores, 3 supervisores.

### Pregunta de negocio
> ¿Por qué se van los clientes de Autos, qué hace el equipo de retención cuando llaman y qué cambios aumentarían la prima retenida a 90 días?

### Preguntas derivadas (lo que la POC debe responder)
1. ¿Cuáles son los motivos reales de baja y en qué se diferencian de lo que el asesor registra en el CRM?
2. ¿Qué ofertas funcionan para cada motivo? ¿Se están ofreciendo las correctas?
3. ¿Qué conductas del asesor (indagar el motivo, ofrecer alternativa, confirmar acuerdo) se asocian a mayor retención?
4. ¿Cuánto de lo "retenido en la llamada" sigue vigente a 90 días?
5. ¿Cómo se relacionan la operación (espera, abandono, rellamadas) con la experiencia y el resultado?

## 2. Dos capas de indicadores

| Capa | Fuente en una empresa real | Fuente en este proyecto |
|---|---|---|
| Operativa | Central telefónica (ACD/CTI), planificación (WFM), encuestas, finanzas | `fact_llamada`, `fact_asesor_dia`, `fact_encuesta`, `fact_costos_mes` (simuladas) |
| Conversacional | Grabaciones → audio a texto → NLP/LLM | Diálogos generados con LLM → (muestra) voz sintética → Whisper → extracción con LLM |
| Resultado de negocio | Sistema de pólizas | `fact_poliza_90d` (simulada) |

## 3. Diccionario de KPIs

### Operativos
| KPI | Fórmula | Fuente |
|---|---|---|
| Llamadas ofrecidas | Conteo de llamadas que entran a la cola | ACD |
| Nivel de servicio (80/20) | Atendidas en ≤ 20 s / ofrecidas (excluyendo abandonos < 5 s) | ACD |
| Tasa de abandono | Abandonadas (≥ 5 s de espera) / ofrecidas | ACD |
| ASA (tiempo medio de respuesta) | Promedio de espera de las atendidas | ACD |
| TMO | (conversación + espera en línea + trabajo posterior) / atendidas | ACD |
| Ocupación | Tiempo en llamada (TMO total) / tiempo conectado disponible | ACD + WFM |
| FCR (resolución en primer contacto) | Pólizas con una sola llamada atendida en 7 días / pólizas con llamada atendida | ACD + CRM |
| Tasa de transferencia | Transferidas / atendidas | ACD |
| CSAT | % de respuestas 4–5 sobre total de respuestas (escala 1–5) | Encuesta |
| NPS | % promotores (9–10) − % detractores (0–6) | Encuesta |
| Costo por contacto | Costo total del mes / llamadas atendidas | Finanzas |

### Retención (negocio)
| KPI | Fórmula | Fuente |
|---|---|---|
| Tasa de retención en llamada | Pólizas que aceptan oferta / pólizas con solicitud de baja atendida | CRM |
| Tasa de retención a 90 días | Pólizas vigentes a 90 días / pólizas con solicitud de baja atendida | Pólizas |
| Fuga post-acuerdo | Aceptaron oferta pero cancelaron antes de 90 días / aceptaron oferta | CRM + Pólizas |
| Prima anual retenida | Σ prima mensual × 12 de pólizas vigentes a 90 días | Pólizas |

### Conversacionales (los produce Speech Analytics)
| KPI | Definición | Cómo se obtiene |
|---|---|---|
| Motivo de baja | Motivo principal (+ secundario) | LLM con taxonomía cerrada |
| Precisión del código de cierre | % de llamadas en que el motivo del CRM coincide con el detectado | Cruce LLM vs CRM |
| Tasa de oferta | % de llamadas con al menos una alternativa ofrecida | LLM |
| Adecuación de la oferta | % de ofertas que corresponden al motivo (matriz motivo → oferta) | LLM + regla de negocio |
| Cumplimiento de guion | % de pasos clave cumplidos (saludo, validación, indagación, alternativa, confirmación) | LLM |
| Sentimiento inicio / fin | Negativo / neutro / positivo | LLM |
| Mención de competencia | % de llamadas que mencionan otra aseguradora | LLM |
| Proporción de habla y silencios | % del tiempo que habla el asesor; silencios > 5 s | Marcas de tiempo de Whisper (muestra con audio) |
| CSAT estimado | Predicción a partir del sentimiento final y el desenlace | Modelo calibrado con las encuestas reales |

## 4. Taxonomía cerrada

**Motivos de baja**
1. `aumento_prima` — subió el precio en la renovación
2. `vendio_vehiculo`
3. `mala_experiencia_siniestro` — demora o rechazo en un siniestro
4. `oferta_competencia`
5. `dificultad_economica`
6. `cobro_no_reconocido` — cargo duplicado o no reconocido
7. `doble_cobertura` — ya tiene seguro por banco o leasing
8. `bajo_uso_vehiculo`

**Ofertas de retención**
`descuento`, `cambio_plan`, `suspension_temporal`, `cuotas_sin_interes`, `traslado_poliza` (al nuevo vehículo), `correccion_cobro`, `escalamiento_siniestro`, `ninguna`.

**Matriz de adecuación motivo → oferta** (regla de negocio usada para evaluar)
| Motivo | Ofertas adecuadas |
|---|---|
| aumento_prima | descuento, cambio_plan |
| vendio_vehiculo | traslado_poliza |
| mala_experiencia_siniestro | escalamiento_siniestro |
| oferta_competencia | descuento, cambio_plan |
| dificultad_economica | suspension_temporal, cuotas_sin_interes, cambio_plan |
| cobro_no_reconocido | correccion_cobro |
| doble_cobertura | cambio_plan |
| bajo_uso_vehiculo | suspension_temporal, cambio_plan |

## 5. Patrones sembrados (para validar el método)

Como los datos son sintéticos, **sembramos patrones conocidos** y medimos si el pipeline los recupera. Esto se declara en el informe: el objetivo es probar que el método funciona, no "descubrir" algo real.

1. **Alza de tarifa de Todo Riesgo en julio (+12 %)** → sube el motivo `aumento_prima` en julio.
2. **Problema con la red de talleres en Arequipa** → `mala_experiencia_siniestro` sobrerrepresentado en Arequipa.
3. **Código de cierre poco confiable** → ~28 % de las llamadas tienen mal registrado el motivo en el CRM (muchas como "otros").
4. **Asesores junior ofrecen menos y peor** → menor tasa de oferta y menor adecuación.
5. **Descuento sin cambio de fondo** → alta aceptación en llamada pero mayor fuga a 90 días que `cambio_plan`.
6. **Esperas largas** → más abandono, más rellamadas y peor sentimiento inicial.

## 6. Modelo de datos (estrella para Power BI)

```
dim_fecha ─┐
dim_asesor ─┼── fact_llamada ── fact_encuesta
dim_poliza ─┘        │
                     ├── fact_resultado_crm
                     ├── fact_speech (salida del pipeline LLM)
                     └── verdad_conversacion (solo para validar, no va al dashboard final)
dim_poliza ── fact_poliza_90d
dim_asesor ── fact_asesor_dia
fact_costos_mes (por mes)
```

## 7. Arquitectura del pipeline

```
[1] generar_datos.py        → tablas operativas + verdad de terreno
[2] generar_dialogos.py     → diálogos (OpenAI) para una muestra estratificada
[3] sintetizar_audio.py     → voz sintética en estéreo (asesor izq., cliente der.) para ~10 llamadas
[4] transcribir.py          → Whisper por canal + unión por marcas de tiempo + WER
[5] extraer_insights.py     → LLM con salida estructurada (taxonomía cerrada)
[6] validar.py              → precisión vs verdad de terreno + prueba en CallCenterEN
[7] exportar_powerbi.py     → CSV del modelo estrella + medidas DAX
```
