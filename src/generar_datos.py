"""
Paso 1 — Genera las tablas operativas y la "verdad de terreno" de cada llamada.

Todo es sintético y reproducible (semilla fija). La lógica de negocio que produce
los datos está explícita aquí para que se pueda auditar qué patrones fueron sembrados
(ver docs/01_diseno_del_caso.md, sección 5).

Uso:
    python src/generar_datos.py --salida data/raw --semilla 42
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Parámetros del escenario
# ---------------------------------------------------------------------------
INICIO = date(2026, 5, 1)
FIN = date(2026, 7, 31)
N_POLIZAS_BASE = 17_000         # solicitudes de baja "normales" en el trimestre
N_POLIZAS_ALZA_JULIO = 2_700    # patrón 1: alza de tarifa Todo Riesgo en julio
UMBRAL_NS_SEG = 20              # nivel de servicio 80/20
ABANDONO_MIN_SEG = 5            # abandonos más cortos no se cuentan

MOTIVOS = [
    "aumento_prima", "vendio_vehiculo", "mala_experiencia_siniestro",
    "oferta_competencia", "dificultad_economica", "cobro_no_reconocido",
    "doble_cobertura", "bajo_uso_vehiculo",
]
PESO_MOTIVO_BASE = np.array([0.17, 0.14, 0.10, 0.15, 0.13, 0.08, 0.10, 0.13])

OFERTAS_ADECUADAS = {
    "aumento_prima": ["descuento", "cambio_plan"],
    "vendio_vehiculo": ["traslado_poliza"],
    "mala_experiencia_siniestro": ["escalamiento_siniestro"],
    "oferta_competencia": ["descuento", "cambio_plan"],
    "dificultad_economica": ["suspension_temporal", "cuotas_sin_interes", "cambio_plan"],
    "cobro_no_reconocido": ["correccion_cobro"],
    "doble_cobertura": ["cambio_plan"],
    "bajo_uso_vehiculo": ["suspension_temporal", "cambio_plan"],
}
TODAS_OFERTAS = ["descuento", "cambio_plan", "suspension_temporal", "cuotas_sin_interes",
                 "traslado_poliza", "correccion_cobro", "escalamiento_siniestro"]

# Probabilidad de aceptar cuando la oferta ES adecuada al motivo
P_ACEPTA_ADECUADA = {
    "aumento_prima": 0.55, "vendio_vehiculo": 0.30, "mala_experiencia_siniestro": 0.40,
    "oferta_competencia": 0.45, "dificultad_economica": 0.45, "cobro_no_reconocido": 0.85,
    "doble_cobertura": 0.22, "bajo_uso_vehiculo": 0.45,
}
# Probabilidad de seguir vigente a 90 días si aceptó (patrón 5: el descuento "no dura")
P_VIGENTE_90D = {
    "descuento": 0.70, "cambio_plan": 0.90, "suspension_temporal": 0.85,
    "cuotas_sin_interes": 0.80, "traslado_poliza": 0.92, "correccion_cobro": 0.95,
    "escalamiento_siniestro": 0.76,
}

REGIONES = ["Lima", "Arequipa", "La Libertad", "Piura", "Cusco", "Lambayeque"]
P_REGION = [0.60, 0.12, 0.09, 0.07, 0.06, 0.06]
PLANES = ["Todo Riesgo", "Plus", "RC"]
P_PLAN = [0.45, 0.30, 0.25]
PRIMA_MEDIA = {"Todo Riesgo": 265, "Plus": 170, "RC": 62}  # soles por mes

# Horario de la cola de retención: lunes a sábado, 8:00–20:00
PESO_HORA = {8: 13.6, 9: 13.6, 10: 34, 11: 34, 12: 42, 13: 40, 14: 42, 15: 42,
             16: 33, 17: 33, 18: 13.6, 19: 13.6}

# Asesores: (id, nivel, supervisor, turno)
ASESORES = [
    ("A01", "senior", "S1", "manana"), ("A02", "semi", "S1", "intermedio"),
    ("A03", "junior", "S1", "tarde"), ("A04", "semi", "S1", "intermedio"),
    ("A05", "senior", "S2", "intermedio"), ("A06", "junior", "S2", "tarde"),
    ("A07", "semi", "S2", "manana"), ("A08", "junior", "S2", "medio"),
    ("A09", "senior", "S3", "tarde"), ("A10", "semi", "S3", "manana"),
    ("A11", "junior", "S3", "medio"), ("A12", "semi", "S3", "medio"),
]
TURNO_HORAS = {"manana": range(8, 16), "intermedio": range(10, 18),
               "medio": range(11, 19), "tarde": range(12, 20)}
HAB = {  # habilidades por nivel
    "junior": dict(saludo=0.88, valida=0.85, indaga=0.55, ofrece=0.55, adecuada=0.50,
                   confirma=0.50, crm_ok=0.58, costo_hora=21.0, tmo_extra=45, acw=85),
    "semi":   dict(saludo=0.94, valida=0.92, indaga=0.75, ofrece=0.75, adecuada=0.70,
                   confirma=0.70, crm_ok=0.75, costo_hora=25.0, tmo_extra=15, acw=65),
    "senior": dict(saludo=0.97, valida=0.96, indaga=0.90, ofrece=0.88, adecuada=0.85,
                   confirma=0.86, crm_ok=0.86, costo_hora=30.0, tmo_extra=0, acw=55),
}


def dias_habiles() -> list[date]:
    d, out = INICIO, []
    while d <= FIN:
        if d.weekday() < 6:  # lunes(0) a sábado(5)
            out.append(d)
        d += timedelta(days=1)
    return out


def asesor_trabaja(asesor_idx: int, d: date) -> bool:
    # cada asesor descansa un día fijo de lunes a sábado
    return d.weekday() != (asesor_idx % 6)


# ---------------------------------------------------------------------------
# Generación
# ---------------------------------------------------------------------------
def generar(semilla: int) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(semilla)
    dias = dias_habiles()

    # ---------------- dim_asesor ----------------
    dim_asesor = pd.DataFrame([
        dict(asesor_id=a, nivel=n, supervisor_id=s, turno=t,
             antiguedad_meses=int(rng.integers(*{"junior": (1, 7), "semi": (7, 25),
                                                  "senior": (25, 72)}[n])),
             costo_hora_soles=HAB[n]["costo_hora"])
        for a, n, s, t in ASESORES
    ])

    # ---------------- dim_poliza + motivo verdadero ----------------
    n_total = N_POLIZAS_BASE + N_POLIZAS_ALZA_JULIO
    region = rng.choice(REGIONES, n_total, p=P_REGION)
    plan = rng.choice(PLANES, n_total, p=P_PLAN)
    canal = rng.choice(["web", "corredor", "banca"], n_total, p=[0.35, 0.40, 0.25])
    antig = np.clip(rng.gamma(2.0, 14, n_total).astype(int) + 1, 1, 120)

    # fecha de primer contacto
    peso_dia = np.array([0.5 if d.weekday() == 5 else 1.0 for d in dias])
    idx_dia = rng.choice(len(dias), N_POLIZAS_BASE, p=peso_dia / peso_dia.sum())
    dias_julio = [i for i, d in enumerate(dias) if d.month == 7]
    pj = peso_dia[dias_julio] / peso_dia[dias_julio].sum()
    idx_dia_alza = rng.choice(dias_julio, N_POLIZAS_ALZA_JULIO, p=pj)
    fecha1 = [dias[i] for i in np.concatenate([idx_dia, idx_dia_alza])]

    motivo = []
    for i in range(n_total):
        if i >= N_POLIZAS_BASE:          # patrón 1
            plan[i] = "Todo Riesgo"
            motivo.append("aumento_prima")
            continue
        w = PESO_MOTIVO_BASE.copy()
        if region[i] == "Arequipa":      # patrón 2
            w[2] *= 3.2
        if plan[i] == "RC":
            w[0] *= 0.6; w[4] *= 1.5
        if canal[i] == "banca":
            w[6] *= 2.2
        if antig[i] <= 6:
            w[3] *= 1.6
        motivo.append(rng.choice(MOTIVOS, p=w / w.sum()))
    motivo = np.array(motivo)

    prima = np.array([max(35, rng.normal(PRIMA_MEDIA[p], PRIMA_MEDIA[p] * 0.22)) for p in plan])
    dim_poliza = pd.DataFrame(dict(
        poliza_id=[f"P{100000 + i}" for i in range(n_total)],
        cliente_id=[f"C{500000 + i}" for i in range(n_total)],
        plan=plan, prima_mensual_soles=prima.round(2), antiguedad_meses=antig,
        canal_venta=canal, region=region,
        segmento_vehiculo=rng.choice(["sedan", "SUV", "hatchback", "pickup"], n_total,
                                     p=[0.35, 0.33, 0.20, 0.12]),
        anio_vehiculo=rng.integers(2012, 2027, n_total),
    ))

    # motivo secundario (30 %)
    motivo_sec = np.where(rng.random(n_total) < 0.30,
                          [rng.choice([m for m in MOTIVOS if m != x]) for x in motivo], None)

    # ---------------- carga por hora -> nivel de ocupación de la cola ----------------
    horas = np.array(list(PESO_HORA.keys()))
    ph = np.array(list(PESO_HORA.values())); ph = ph / ph.sum()
    hora1 = rng.choice(horas, n_total, p=ph)
    es_callback = rng.random(n_total) < 0.20

    carga = pd.Series(1.18, index=pd.MultiIndex.from_arrays(
        [pd.Series(fecha1), hora1])).groupby(level=[0, 1]).sum()  # 1.18 ≈ rellamadas
    tmo_ref = 615.0

    def agentes_en_hora(d: date, h: int) -> list[str]:
        return [a for i, (a, _, _, t) in enumerate(ASESORES)
                if asesor_trabaja(i, d) and h in TURNO_HORAS[t]]

    def rho(d: date, h: int) -> float:
        n_ag = max(1, len(agentes_en_hora(d, h)))
        return float(carga.get((d, h), 0) * tmo_ref / 3600 / n_ag)

    # ---------------- simulación de llamadas ----------------
    nivel_de = dict(zip(dim_asesor.asesor_id, dim_asesor.nivel))
    llamadas, verdad, crm = [], [], []
    estado_poliza = []
    seq = 0

    for i in range(n_total):
        pid = dim_poliza.poliza_id[i]
        mot = motivo[i]
        fecha, hora = fecha1[i], int(hora1[i])
        callback = bool(es_callback[i])
        resuelto, intento = False, 0
        acepto_final, oferta_final, confirma_final = False, "ninguna", False
        atendido_alguna = False

        while not resuelto and intento < 3:
            intento += 1
            seq += 1
            lid = f"L{seq:06d}"
            ts = datetime(fecha.year, fecha.month, fecha.day, hora,
                          int(rng.integers(0, 60)), int(rng.integers(0, 60)))
            ag_disp = agentes_en_hora(fecha, hora)

            # --- espera y abandono (cola entrante) ---
            if callback:
                espera, abandona = 0.0, False
            else:
                r = min(rho(fecha, hora), 0.97)
                espera = 0.0 if rng.random() > r ** 4 else rng.exponential(14 / (1 - r))
                paciencia = rng.exponential(300)
                abandona = espera > paciencia
                if abandona:
                    espera = paciencia

            fila = dict(llamada_id=lid, poliza_id=pid, fecha_hora_ingreso=ts,
                        tipo="callback" if callback else "entrante", intento=intento,
                        espera_seg=round(espera, 1), abandonada=abandona,
                        asesor_id=None, conversacion_seg=0, hold_seg=0, acw_seg=0,
                        transferida=False)

            if abandona:
                llamadas.append(fila)
                # 80 % reintenta en 0–2 días
                if rng.random() < 0.80:
                    fecha, hora = _siguiente(fecha, hora, rng, dias)
                    continue
                break

            atendido_alguna = True
            ag = rng.choice(ag_disp) if ag_disp else rng.choice(dim_asesor.asesor_id)
            h = HAB[nivel_de[ag]]

            # --- conducta del asesor (verdad de terreno) ---
            saludo = rng.random() < h["saludo"]
            valida = rng.random() < h["valida"]
            indaga = rng.random() < h["indaga"]
            ofrece = rng.random() < (h["ofrece"] if indaga else h["ofrece"] * 0.7)
            if mot == "vendio_vehiculo" and not indaga:
                ofrece = ofrece and rng.random() < 0.5
            if ofrece:
                p_adec = min(0.97, h["adecuada"] + (0.10 if indaga else -0.15))
                if rng.random() < p_adec:
                    oferta = rng.choice(OFERTAS_ADECUADAS[mot]); adecuada = True
                else:  # la oferta "por defecto" suele ser descuento
                    no_adec = [o for o in TODAS_OFERTAS if o not in OFERTAS_ADECUADAS[mot]]
                    oferta = "descuento" if ("descuento" in no_adec and rng.random() < 0.6) \
                        else rng.choice(no_adec)
                    adecuada = False
            else:
                oferta, adecuada = "ninguna", False

            # --- sentimiento inicial (patrón 6: esperas largas) ---
            p_neg = 0.72 if mot in ("mala_experiencia_siniestro", "cobro_no_reconocido") else 0.38
            p_neg += 0.15 if espera > 120 else 0
            p_neg += 0.10 if intento > 1 else 0
            p_neg = min(p_neg, 0.95)
            sent_ini = rng.choice(["negativo", "neutro", "positivo"],
                                  p=[p_neg, (1 - p_neg) * 0.85, (1 - p_neg) * 0.15])

            # --- aceptación ---
            if oferta == "ninguna":
                p_ac = 0.03
            else:
                p_ac = P_ACEPTA_ADECUADA[mot] * (1 if adecuada else 0.35)
                if oferta == "descuento" and mot in ("aumento_prima", "oferta_competencia"):
                    p_ac += 0.10
                p_ac += 0.05 if nivel_de[ag] == "senior" else 0
                p_ac -= 0.08 if sent_ini == "negativo" else 0
            acepta = rng.random() < max(0.01, min(p_ac, 0.95))
            confirma = acepta and (rng.random() < h["confirma"])

            escala = (mot == "mala_experiencia_siniestro" and sent_ini == "negativo"
                      and rng.random() < 0.25) or rng.random() < 0.03
            if oferta == "escalamiento_siniestro":
                escala = True
            competencia = rng.random() < (0.9 if mot == "oferta_competencia" else 0.08)

            if acepta:
                sent_fin = rng.choice(["negativo", "neutro", "positivo"], p=[0.05, 0.40, 0.55])
            elif adecuada and indaga:
                sent_fin = rng.choice(["negativo", "neutro", "positivo"], p=[0.25, 0.60, 0.15])
            else:
                sent_fin = rng.choice(["negativo", "neutro", "positivo"], p=[0.55, 0.40, 0.05])

            # --- tiempos ---
            conv = rng.lognormal(np.log(400), 0.35) + h["tmo_extra"]
            conv += 90 if ofrece else 0
            conv += 110 if mot == "mala_experiencia_siniestro" else 0
            conv += 60 if escala else 0
            hold = 0.0 if rng.random() < 0.5 else rng.exponential(
                70 if mot in ("mala_experiencia_siniestro", "cobro_no_reconocido") else 40)
            acw = max(15, rng.normal(h["acw"], 18))

            fila.update(asesor_id=ag, conversacion_seg=round(conv), hold_seg=round(hold),
                        acw_seg=round(acw), transferida=bool(escala))
            llamadas.append(fila)

            # --- código de cierre en CRM (patrón 3) ---
            if rng.random() < h["crm_ok"]:
                mot_crm = mot
            else:
                mot_crm = "otros" if rng.random() < 0.6 else rng.choice(
                    [m for m in MOTIVOS if m != mot])
            crm.append(dict(llamada_id=lid, motivo_crm=mot_crm,
                            resultado_crm="retenido" if acepta else
                            ("pendiente" if escala and not acepta else "baja_procesada")))

            rellama_menciona = intento > 1 and rng.random() < 0.7
            verdad.append(dict(
                llamada_id=lid, poliza_id=pid, asesor_id=ag,
                motivo_principal=mot, motivo_secundario=motivo_sec[i],
                saludo_corporativo=saludo, valida_identidad=valida,
                indaga_motivo=indaga, ofrece_alternativa=ofrece,
                oferta_tipo=oferta, oferta_adecuada=adecuada,
                cliente_acepta=acepta, confirma_acuerdo=confirma,
                escala_supervisor=bool(escala), menciona_competencia=competencia,
                menciona_llamada_previa=rellama_menciona,
                sentimiento_inicio=sent_ini, sentimiento_fin=sent_fin,
                conversacion_seg=round(conv), plan=plan[i], region=region[i],
                prima_mensual_soles=round(float(prima[i]), 2),
            ))

            acepto_final, oferta_final, confirma_final = acepta, oferta, confirma
            # ¿vuelve a llamar? (rompe FCR)
            p_rellamar = 0.06
            if escala and not acepta:
                p_rellamar = 0.40
            elif acepta and not confirma:
                p_rellamar = 0.25
            elif mot == "cobro_no_reconocido" and acepta:
                p_rellamar = 0.18
            if rng.random() < p_rellamar:
                fecha, hora = _siguiente(fecha, hora, rng, dias)
                callback = False
                continue
            resuelto = True

        # --- estado de la póliza a 90 días ---
        if acepto_final and oferta_final != "ninguna":
            p_v = P_VIGENTE_90D.get(oferta_final, 0.7)
            p_v -= 0.15 if not confirma_final else 0
            p_v -= 0.10 if oferta_final not in OFERTAS_ADECUADAS[mot] else 0
        elif acepto_final:
            p_v = 0.6
        elif not atendido_alguna:   # nunca lo atendieron: la baja no se procesó por este canal
            p_v = 0.45
        else:
            p_v = 0.04
        vigente = rng.random() < p_v
        f_ult = fecha
        estado_poliza.append(dict(
            poliza_id=pid, fecha_ultima_llamada=f_ult,
            atendida_alguna_vez=atendido_alguna, vigente_90d=vigente,
            fecha_cancelacion=None if vigente else f_ult + timedelta(
                days=int(rng.integers(0, 3) if not acepto_final else rng.integers(20, 90))),
        ))

    fact_llamada = pd.DataFrame(llamadas)
    fact_llamada["tmo_seg"] = fact_llamada[["conversacion_seg", "hold_seg", "acw_seg"]].sum(axis=1)
    fact_llamada["atendida"] = ~fact_llamada.abandonada
    fact_llamada["atendida_en_umbral"] = fact_llamada.atendida & (fact_llamada.espera_seg <= UMBRAL_NS_SEG)
    fact_llamada["abandono_contable"] = fact_llamada.abandonada & (fact_llamada.espera_seg >= ABANDONO_MIN_SEG)

    verdad = pd.DataFrame(verdad)
    fact_resultado_crm = pd.DataFrame(crm)
    fact_poliza_90d = pd.DataFrame(estado_poliza)

    # ---------------- encuestas ----------------
    enc = verdad[["llamada_id", "sentimiento_fin", "cliente_acepta"]].merge(
        fact_llamada[["llamada_id", "espera_seg"]], on="llamada_id")
    p_resp = 0.18 + np.where(enc.sentimiento_fin == "negativo", 0.10, 0)
    responde = rng.random(len(enc)) < p_resp
    media = enc.sentimiento_fin.map({"negativo": 2.2, "neutro": 3.7, "positivo": 4.6}).values
    media = media - np.where(enc.espera_seg > 120, 0.3, 0)
    csat = np.clip(np.round(media + rng.normal(0, 0.7, len(enc))), 1, 5).astype(int)
    nps = np.clip(np.round(csat * 2 - 0.5 + rng.normal(0, 1.3, len(enc))
                           + np.where(enc.cliente_acepta, 0.8, 0)), 0, 10).astype(int)
    fact_encuesta = pd.DataFrame(dict(llamada_id=enc.llamada_id[responde].values,
                                      csat=csat[responde], nps=nps[responde]))

    # ---------------- asesor por día (para ocupación) ----------------
    filas = []
    tmo_dia = (fact_llamada.dropna(subset=["asesor_id"])
               .assign(fecha=lambda x: x.fecha_hora_ingreso.dt.date)
               .groupby(["fecha", "asesor_id"]).tmo_seg.sum())
    for d in dias:
        for i, (a, _, _, t) in enumerate(ASESORES):
            if not asesor_trabaja(i, d):
                continue
            conectado = 8 * 3600 - 45 * 60 - 2 * 15 * 60      # 8 h menos almuerzo y pausas
            filas.append(dict(fecha=d, asesor_id=a, conectado_seg=conectado,
                              en_llamada_seg=int(tmo_dia.get((d, a), 0))))
    fact_asesor_dia = pd.DataFrame(filas)

    # ---------------- costos mensuales ----------------
    costo = []
    for mes in [5, 6, 7]:
        fa = fact_asesor_dia[pd.to_datetime(fact_asesor_dia.fecha).dt.month == mes]
        horas_pagadas = len(fa) * 8
        personal = (fa.merge(dim_asesor, on="asesor_id").costo_hora_soles * 8).sum()
        costo.append(dict(mes=f"2026-{mes:02d}", costo_asesores_soles=round(personal, 2),
                          costo_supervision_soles=3 * 7500.0,
                          costo_licencias_soles=12 * 180.0,
                          costo_infraestructura_soles=12000.0,
                          horas_pagadas_asesores=horas_pagadas))
    fact_costos_mes = pd.DataFrame(costo)

    return dict(dim_asesor=dim_asesor, dim_poliza=dim_poliza, fact_llamada=fact_llamada,
                fact_resultado_crm=fact_resultado_crm, fact_poliza_90d=fact_poliza_90d,
                fact_encuesta=fact_encuesta, fact_asesor_dia=fact_asesor_dia,
                fact_costos_mes=fact_costos_mes, verdad_conversacion=verdad)


def _siguiente(fecha: date, hora: int, rng, dias: list[date]) -> tuple[date, int]:
    salto = int(rng.choice([0, 1, 2], p=[0.45, 0.4, 0.15]))
    idx = min(dias.index(fecha) + salto, len(dias) - 1)
    nueva_hora = int(rng.choice(list(PESO_HORA.keys())))
    if salto == 0 and nueva_hora <= hora:
        nueva_hora = min(19, hora + 1)
    return dias[idx], nueva_hora


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--salida", default="data/raw")
    ap.add_argument("--semilla", type=int, default=42)
    args = ap.parse_args()
    out = Path(args.salida); out.mkdir(parents=True, exist_ok=True)
    tablas = generar(args.semilla)
    for nombre, df in tablas.items():
        df.to_csv(out / f"{nombre}.csv", index=False, encoding="utf-8")
        print(f"{nombre:<22} {len(df):>7,} filas")


if __name__ == "__main__":
    main()
