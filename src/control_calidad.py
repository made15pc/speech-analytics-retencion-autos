"""
Paso 5b — Control automático de calidad de los diálogos generados.

Compara cada diálogo con su ficha (la verdad de terreno) y separa dos niveles:
  * FALLOS DUROS: el diálogo es inservible o contamina el estudio (etiquetas técnicas filtradas,
    enmascarado mal hecho, fechas fuera del escenario, estructura rota).
  * ALERTAS BLANDAS: heurísticas por palabras clave sobre la conducta pedida en la ficha.
    Pueden dar falsos positivos: sirven para elegir qué leer, no para descartar.

Uso:
    python src/control_calidad.py --dialogos data/dialogos/dialogos.jsonl \
        --muestra data/dialogos/muestra.csv --salida data/dialogos/qa
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

MESES = {m: i + 1 for i, m in enumerate(
    ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
     "septiembre", "octubre", "noviembre", "diciembre"])}
PERMITIDOS = {"NOMBRE_CLIENTE", "DNI", "PLACA", "TARJETA", "CORREO"}
CLAVES = ["aumento_prima", "vendio_vehiculo", "mala_experiencia_siniestro", "oferta_competencia",
          "dificultad_economica", "cobro_no_reconocido", "doble_cobertura", "bajo_uso_vehiculo",
          "cambio_plan", "suspension_temporal", "cuotas_sin_interes", "traslado_poliza",
          "correccion_cobro", "escalamiento_siniestro"]
RE_CLAVE = re.compile(r"\b(" + "|".join(CLAVES) + r")\b|taxonom|verdad de terreno|motivo_", re.I)
RE_FICHA = re.compile(r"\bficha\b", re.I)
RE_SNAKE = re.compile(r"\b[a-záéíóú]+_[a-záéíóú_]+\b")  # sensible a mayúsculas: solo minúsculas
RE_BRACKET = re.compile(r"\[([^\]]+)\]")
RE_TAG_COMO_PALABRA = re.compile(r"\b(mi|su|tu|el|la|del|me)\s+\[(DNI|PLACA)\]", re.I)
RE_FECHA = re.compile(r"(\d{1,2})\s+de\s+(" + "|".join(MESES) + r")(?:\s+de\s+(\d{4}))?", re.I)
OFERTA_PALABRAS = {
    "descuento": r"descuento", "cambio_plan": r"plan", "suspension_temporal": r"suspen",
    "cuotas_sin_interes": r"cuota", "traslado_poliza": r"traslad",
    "correccion_cobro": r"revert|devol|corrig|reembols", "escalamiento_siniestro": r"supervisor|escal|siniestros",
}
RE_CUALQUIER_OFERTA = re.compile(
    r"(ofrec\w*|puedo|podemos|podría|podriamos|le propongo|propongo)[^.?!]{0,70}"
    r"(descuento|cambio de plan|cambiar de plan|plan de menor|suspend|suspensi|sin intereses|fraccion"
    r"|traslad|revert|reversi|escal)", re.I)
RE_PIDE_CONFIRMAR = re.compile(
    r"confirm\w*[^.?!]{0,80}(expres|explícit|de acuerdo|acepta|condiciones|continuar)"
    r"|(expres|explícit)\w*[^.?!]{0,40}confirm", re.I)
RE_COMPETENCIA = re.compile(r"aseguradora|competencia|otra compañía|otra empresa|Inti|Pacha|Qhapaq", re.I)
RE_ACEPTA = re.compile(r"me quedo|acepto|no cancel|quedarme|continuar|mantener|sigo con|prefiero seguir", re.I)


RE_NO_ACEPTA = [
    re.compile(r"\bno\s+(?:\w+\s+){0,3}?(?:acepto|aceptando|aceptar|mantener|continuar|quedarme|seguir)\b(?:\s+(?:con\s+)?(?:continuar|seguir|mantener|quedarme)\b)*", re.I),
    re.compile(r"\bme quedo (?:más |mas )?tranquil\w*", re.I),
    re.compile(r"\b(?:continuar|seguir|mantener|mantengo|sigo)\s+(?:con\s+)?(?:la|mi|esa|esta)\s+(?:cancelaci[oó]n|decisi[oó]n|baja)", re.I),
]


def acepta_texto(txt):
    for r_ in RE_NO_ACEPTA:
        txt = r_.sub(" ", txt)
    return bool(RE_ACEPTA.search(txt))


def _tx(t):
    return t.get("texto", t.get("text", "")) or ""


def textos(turnos, quien):
    return [_tx(t) for t in turnos if t["hablante"] == quien]


def revisar(d: dict, r: pd.Series) -> dict:
    duros, blandos = [], []
    turnos = d.get("turnos")
    if not turnos or len(turnos) < 8 or {t["hablante"] for t in turnos} != {"asesor", "cliente"} \
            or any(not str(_tx(t)).strip() for t in turnos):
        return dict(llamada_id=d["llamada_id"], palabras=0, turnos=len(turnos or []),
                    duros="sin_dialogo_o_estructura_rota", blandos="")
    todo = " ".join(_tx(t) for t in turnos)
    asesor, cliente = textos(turnos, "asesor"), textos(turnos, "cliente")
    n = len(turnos)
    tercio = max(1, int(n * 0.35))
    cola_asesor = " ".join(_tx(t) for t in turnos[-tercio:] if t["hablante"] == "asesor")
    cola_cliente = " ".join(_tx(t) for t in turnos[-tercio:] if t["hablante"] == "cliente")

    # ---------------- fallos duros ----------------
    sin_marcadores = RE_BRACKET.sub("", todo)
    if RE_CLAVE.search(sin_marcadores) or RE_SNAKE.search(sin_marcadores):
        duros.append("fuga_de_etiqueta")
    if any(b not in PERMITIDOS for b in RE_BRACKET.findall(todo)):
        duros.append("placeholder_desconocido")
    if RE_TAG_COMO_PALABRA.search(todo) or re.search(r"\[DNI\]\s+es\s+\[DNI\]|\[PLACA\]\s+es\s+\[PLACA\]", todo):
        duros.append("etiqueta_usada_como_palabra")
    f_llamada = pd.to_datetime(r.fecha_hora_ingreso).normalize()
    for m in RE_FECHA.finditer(todo):
        dia, mes, anio = int(m.group(1)), MESES[m.group(2).lower()], int(m.group(3) or f_llamada.year)
        try:
            f = datetime(anio, mes, dia)
        except ValueError:
            duros.append("fecha_invalida"); continue
        antes = todo[max(0, m.start() - 20):m.start()].lower()
        if re.search(r"hoy,?\s*(es\s+|estamos\s+(a|al)\s+)?(el\s+)?$", antes) and f != f_llamada:
            duros.append("hoy_distinto_a_fecha_llamada")
        if f > f_llamada + timedelta(days=130):
            duros.append("fecha_lejana")

    # ---------------- alertas blandas ----------------
    if RE_FICHA.search(sin_marcadores):
        blandos.append("menciona_ficha")
    inicio = " ".join(asesor[:2])
    if r.saludo_corporativo and "autosegura" not in inicio.lower():
        blandos.append("saludo_sin_empresa_pero_debia_tenerla")
    if not r.saludo_corporativo and "autosegura" in inicio.lower():
        blandos.append("saludo_con_empresa_pero_debia_ser_informal")
    primeros = " ".join(asesor[:6]).lower()
    if r.valida_identidad and not re.search(r"dni|placa", primeros):
        blandos.append("no_valida_identidad_pero_debia")
    if not r.valida_identidad and re.search(r"dni|placa", primeros):
        blandos.append("valida_identidad_pero_no_debia")
    asesor_txt = " ".join(asesor)
    if r.ofrece_alternativa:
        if not re.search(OFERTA_PALABRAS[r.oferta_tipo], asesor_txt, re.I):
            blandos.append("oferta_esperada_no_aparece")
    elif RE_CUALQUIER_OFERTA.search(asesor_txt) and not r.escala_supervisor:
        blandos.append("hay_oferta_pero_no_debia")
    if r.cliente_acepta and not acepta_texto(" ".join(cliente)):
        blandos.append("debia_aceptar_pero_no_se_detecta")
    if not r.cliente_acepta and acepta_texto(cola_cliente):
        blandos.append("no_debia_aceptar_pero_parece_aceptar")
    if r.cliente_acepta and r.confirma_acuerdo and not RE_PIDE_CONFIRMAR.search(cola_asesor):
        blandos.append("debia_confirmar_acuerdo_y_no_aparece")
    if r.cliente_acepta and r.ofrece_alternativa and not r.confirma_acuerdo and RE_PIDE_CONFIRMAR.search(cola_asesor):
        blandos.append("no_debia_confirmar_acuerdo_pero_confirma")
    if r.menciona_competencia and not RE_COMPETENCIA.search(" ".join(cliente)):
        blandos.append("competencia_esperada_no_aparece")
    if not r.menciona_competencia and re.search(r"Inti Seguros|Seguros Pacha|Qhapaq", todo):
        blandos.append("competencia_aparece_pero_no_debia")
    palabras = len(todo.split())
    objetivo = int(min(1400, max(250, r.conversacion_seg * 2.2)))
    if not 0.6 <= palabras / objetivo <= 1.5:
        blandos.append("extension_fuera_de_rango")
    return dict(llamada_id=d["llamada_id"], palabras=palabras, objetivo=objetivo, turnos=n,
                duros=";".join(sorted(set(duros))), blandos=";".join(blandos))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dialogos", default="data/dialogos/dialogos.jsonl")
    ap.add_argument("--muestra", default="data/dialogos/muestra.csv")
    ap.add_argument("--salida", default="data/dialogos/qa")
    a = ap.parse_args()
    out = Path(a.salida); out.mkdir(parents=True, exist_ok=True)

    muestra = pd.read_csv(a.muestra).set_index("llamada_id", drop=False)
    dialogos = [json.loads(l) for l in open(a.dialogos, encoding="utf-8")]
    # si un ID quedó repetido (reintentos), nos quedamos con el último
    dialogos = list({d["llamada_id"]: d for d in dialogos}.values())
    filas = [revisar(d, muestra.loc[d["llamada_id"]]) for d in dialogos if d["llamada_id"] in muestra.index]
    df = pd.DataFrame(filas).merge(muestra[["motivo_principal", "oferta_tipo", "cliente_acepta", "nivel"]],
                                   left_on="llamada_id", right_index=True, how="left")
    df.to_csv(out / "qa_detalle.csv", index=False, encoding="utf-8")

    n = len(df)
    print(f"Diálogos revisados: {n} de {len(muestra)} en la muestra")
    print(f"Palabras: mediana {df.palabras.median():.0f} | mín {df.palabras.min()} | máx {df.palabras.max()}")
    for titulo, col in (("FALLOS DUROS", "duros"), ("ALERTAS BLANDAS", "blandos")):
        c = df[col].fillna("").str.split(";").explode()
        c = c[c != ""].value_counts()
        print(f"\n== {titulo}: {int((df[col].fillna('') != '').sum())} diálogos con al menos uno ==")
        print(c.to_string() if len(c) else "(ninguno)")
    limpios = ((df.duros.fillna("") == "") & (df.blandos.fillna("") == "")).sum()
    print(f"\nSin ninguna marca: {limpios} ({limpios / n:.0%}) | sin fallos duros: "
          f"{int((df.duros.fillna('') == '').sum())} ({(df.duros.fillna('') == '').mean():.0%})")
    revisar_df = df[(df.duros.fillna("") != "") | (df.blandos.fillna("") != "")]
    revisar_df.to_csv(out / "qa_revisar.csv", index=False, encoding="utf-8")
    print(f"\nArchivos: {out / 'qa_detalle.csv'} y {out / 'qa_revisar.csv'} ({len(revisar_df)} filas)")


if __name__ == "__main__":
    main()
