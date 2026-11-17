"""
Paso 2 — Genera transcripciones de llamadas (diálogos) con un LLM de OpenAI,
condicionadas a la "verdad de terreno" de cada llamada.

Idea clave: el LLM NO decide qué pasa en la llamada. Lo decide generar_datos.py
(motivo, oferta, si acepta, conducta del asesor...). El LLM solo "actúa" la llamada.
Así después podemos medir si el pipeline de extracción recupera lo que sembramos.

Uso:
    # prueba sin gastar (diálogos de plantilla)
    python src/generar_dialogos.py --n 40 --mock
    # real (necesita OPENAI_API_KEY en el entorno)
    python src/generar_dialogos.py --n 400 --modelo gpt-6-luna
"""
from __future__ import annotations

import argparse
import json
import os
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

DESCRIPCION_MOTIVO = {
    "aumento_prima": "le subieron la prima en la renovación y le parece caro",
    "vendio_vehiculo": "vendió su vehículo",
    "mala_experiencia_siniestro": "tuvo un siniestro y la atención fue mala (demora en taller, "
                                  "reembolso o rechazo)",
    "oferta_competencia": "otra aseguradora le ofreció un precio menor",
    "dificultad_economica": "está pasando un momento económico difícil",
    "cobro_no_reconocido": "le hicieron un cargo duplicado o que no reconoce en su tarjeta",
    "doble_cobertura": "ya tiene un seguro vehicular por su banco o su leasing",
    "bajo_uso_vehiculo": "casi no usa el auto (trabaja remoto, lo tiene guardado)",
}
DESCRIPCION_OFERTA = {
    "descuento": "un descuento temporal sobre la prima (10 % a 15 %)",
    "cambio_plan": "pasarse a un plan de menor cobertura y menor precio",
    "suspension_temporal": "suspender la póliza por unos meses sin perder la antigüedad",
    "cuotas_sin_interes": "fraccionar el pago en cuotas sin intereses",
    "traslado_poliza": "trasladar la póliza a su nuevo vehículo",
    "correccion_cobro": "revertir el cobro indebido y corregir la facturación",
    "escalamiento_siniestro": "escalar su caso de siniestro a un supervisor o al área de siniestros "
                              "con un compromiso de respuesta",
}
COMPETIDORES_FICTICIOS = ["Inti Seguros", "Seguros Pacha", "Qhapaq Seguros", "otra aseguradora"]

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]


def fecha_texto(valor) -> str:
    f = pd.to_datetime(valor)
    return f"{f.day} de {MESES[f.month - 1]} de {f.year}"


def motivo_claro(llamada_id) -> bool:
    """60 % de las llamadas: el cliente explica su motivo con claridad. 40 %: lo insinúa.
    Determinista según el ID (reproducible y recalculable al validar)."""
    return int(str(llamada_id)[1:]) % 10 >= 4

SISTEMA = """Eres guionista de llamadas realistas de un call center de seguros vehiculares en Perú.
Escribes transcripciones de llamadas al área de Retención de la empresa ficticia "AutoSegura Perú".
Reglas:
- Español peruano natural y coloquial del cliente; el asesor es cordial pero no perfecto.
- Incluye muletillas y frases cortadas con moderación ("ya", "eh", "o sea", "a ver", "ajá").
- NO uses etiquetas ni nombres técnicos (nunca escribas "motivo:", "aumento_prima", "oferta", etc.).
  El motivo y la conducta deben inferirse de la conversación, como en una llamada real.
- Escribe "DNI" y "placa" como palabras normales y enmascara solo el valor (por ejemplo: "mi DNI es [DNI]", "la placa es [PLACA]").
- Datos personales siempre enmascarados: [NOMBRE_CLIENTE], [DNI], [PLACA], [TARJETA], [CORREO].
  El asesor sí puede decir su propio nombre de pila (inventado).
- Cumple EXACTAMENTE la ficha: lo que la ficha dice que no ocurre, no debe ocurrir.
- No repitas el mismo resumen o la misma confirmación más de una vez. Si la llamada debe ser larga, llénala con búsquedas en el sistema, esperas, dudas del cliente, desvíos de tema y comentarios laterales; nunca con repeticiones.
- Usa únicamente la fecha de la llamada que da la ficha. No inventes otra fecha como "hoy"; cualquier fecha futura que se mencione debe ser coherente con ella.
- Responde solo con JSON: {"turnos": [{"hablante": "asesor"|"cliente", "texto": "..."}]}"""


def construir_ficha(r: pd.Series) -> str:
    """Traduce la verdad de terreno a instrucciones de guion."""
    pasos = []
    pasos.append("El asesor saluda con el saludo corporativo completo (nombre de la empresa y su nombre)."
                 if r.saludo_corporativo else
                 "El asesor contesta con un saludo informal e incompleto, sin decir el nombre de la empresa.")
    pasos.append("El asesor valida identidad pidiendo [DNI] y [PLACA]." if r.valida_identidad else
                 "El asesor NO valida la identidad del cliente.")
    pasos.append("El asesor pregunta activamente por qué quiere cancelar y repregunta para entender."
                 if r.indaga_motivo else
                 "El asesor NO pregunta el motivo; el cliente lo menciona solo de pasada.")
    if r.ofrece_alternativa:
        pasos.append(f"El asesor ofrece: {DESCRIPCION_OFERTA[r.oferta_tipo]}.")
        if not r.oferta_adecuada:
            pasos.append("La oferta no resuelve realmente lo que le pasa al cliente "
                         "(el cliente puede notarlo).")
    else:
        pasos.append("El asesor NO ofrece ninguna alternativa; solo toma la solicitud de baja.")
    if r.cliente_acepta and r.ofrece_alternativa:
        pasos.append("El cliente ACEPTA quedarse con la alternativa.")
    elif r.cliente_acepta:
        pasos.append("El cliente, sin que el asesor le ofrezca nada, decide por su cuenta no cancelar "
                     "por ahora (por ejemplo, después de desahogarse); el asesor solo toma nota.")
    else:
        pasos.append("El cliente NO acepta y mantiene la cancelación.")
    if r.cliente_acepta and r.ofrece_alternativa:
        pasos.append("Al final el asesor resume las nuevas condiciones (monto, fecha de aplicación) "
                     "y pide confirmación explícita." if r.confirma_acuerdo else
                     "El asesor NO resume ni confirma las condiciones del acuerdo; cierra rápido.")
    if r.escala_supervisor:
        pasos.append("En algún momento se transfiere o deriva al cliente a un supervisor o al área "
                     "de siniestros.")
    if r.menciona_competencia:
        pasos.append(f"El cliente menciona a {random.choice(COMPETIDORES_FICTICIOS)} y su precio.")
    if r.menciona_llamada_previa:
        pasos.append("El cliente se queja de que ya llamó antes por lo mismo.")

    sec = ""
    if isinstance(r.motivo_secundario, str) and r.motivo_secundario:
        sec = f" Además, de forma secundaria, {DESCRIPCION_MOTIVO[r.motivo_secundario]}."

    palabras = int(min(1400, max(250, r.conversacion_seg * 2.2)))
    return f"""FICHA DE LA LLAMADA
- Tipo: {"devolución de llamada (el cliente dejó una solicitud web)" if r.tipo == "callback" else "llamada entrante"}
- Fecha de la llamada: {fecha_texto(r.fecha_hora_ingreso)}
- Claridad del cliente al explicar su motivo: {"explica su motivo con claridad" if motivo_claro(r.get("llamada_id", r.name)) else "NO dice su motivo de forma directa: lo da en partes o lo insinúa, y puede mencionar otros temas de pasada. Aun así, el motivo real debe aparecer al menos dos veces con detalle suficiente para identificarlo como el principal, y los otros temas deben quedar claramente como secundarios o descartados por el propio cliente (no dudes entre motivos)"}
- Cliente: plan {r.plan}, prima S/ {r.prima_mensual_soles:.0f} al mes, región {r.region}
- Motivo real del cliente: {DESCRIPCION_MOTIVO[r.motivo_principal]}.{sec}
- Ánimo del cliente al inicio: {r.sentimiento_inicio}. Ánimo al final: {r.sentimiento_fin}.
- Nivel del asesor: {r.nivel}.
- Lo que ocurre, en orden:
""" + "\n".join(f"  {i+1}. {p}" for i, p in enumerate(pasos)) + f"""
- Extensión aproximada: {palabras} palabras en total."""


def muestra_estratificada(datos: Path, n: int, semilla: int) -> pd.DataFrame:
    V = pd.read_csv(datos / "verdad_conversacion.csv")
    L = pd.read_csv(datos / "fact_llamada.csv")
    D = pd.read_csv(datos / "dim_asesor.csv")
    df = (V.merge(L[["llamada_id", "tipo", "fecha_hora_ingreso", "espera_seg"]], on="llamada_id")
           .merge(D[["asesor_id", "nivel"]], on="asesor_id"))
    df["estrato"] = df.motivo_principal + "|" + df.cliente_acepta.astype(str)
    if n < 100:  # modo piloto: n llamadas de n estratos distintos
        m = df.groupby("estrato").sample(1, random_state=semilla).sample(n, random_state=semilla)
        m["peso_muestral"] = 1.0
        return m.reset_index(drop=True)
    # asignación proporcional con piso de 6 por estrato
    prop = df.estrato.value_counts(normalize=True)
    cuota = (prop * n).round().clip(lower=6).astype(int)
    partes = [g.sample(min(len(g), cuota[e]), random_state=semilla) for e, g in df.groupby("estrato")]
    m = pd.concat(partes).sample(frac=1, random_state=semilla).reset_index(drop=True)
    # peso = cuántas llamadas de la población representa cada llamada de la muestra.
    # Úsalo para extrapolar porcentajes de la muestra a toda la operación.
    tam_pob = df.estrato.value_counts()
    tam_mue = m.estrato.value_counts()
    m["peso_muestral"] = m.estrato.map(tam_pob / tam_mue).round(3)
    return m


def dialogo_mock(r: pd.Series) -> list[dict]:
    """Diálogo de plantilla para probar el pipeline sin llamar a la API."""
    t = [("asesor", "Buenos días, AutoSegura Perú, le saluda Carla." if r.saludo_corporativo
          else "Aló, buenos días."),
         ("cliente", "Hola, quiero cancelar mi seguro del carro.")]
    if r.valida_identidad:
        t += [("asesor", "Claro, ¿me confirma su [DNI] y la [PLACA]?"), ("cliente", "Sí, [DNI], placa [PLACA].")]
    if r.indaga_motivo:
        t += [("asesor", "¿Me podría contar por qué desea cancelar?")]
    t += [("cliente", f"Es que {DESCRIPCION_MOTIVO[r.motivo_principal]}.")]
    if r.ofrece_alternativa:
        t += [("asesor", f"Le puedo ofrecer {DESCRIPCION_OFERTA[r.oferta_tipo]}.")]
        t += [("cliente", "Ya, está bien, me quedo." if r.cliente_acepta else "No, gracias, prefiero cancelar.")]
    if r.cliente_acepta and r.confirma_acuerdo:
        t += [("asesor", "Le confirmo: el cambio aplica desde su próxima cuota. ¿Está de acuerdo?"),
              ("cliente", "Sí, de acuerdo.")]
    t += [("asesor", "Gracias por llamar, que tenga buen día.")]
    return [{"hablante": h, "texto": x} for h, x in t]


def generar_uno(cliente, modelo: str, r: pd.Series, reintentos: int = 4) -> dict:
    ficha = construir_ficha(r)
    for intento in range(reintentos):
        try:
            resp = cliente.chat.completions.create(
                model=modelo,
                messages=[{"role": "system", "content": SISTEMA},
                          {"role": "user", "content": ficha}],
                response_format={"type": "json_object"},
            )
            turnos = json.loads(resp.choices[0].message.content)["turnos"]
            assert turnos and all(t["hablante"] in ("asesor", "cliente") and str(t.get("texto", "")).strip() for t in turnos)
            uso = resp.usage
            return dict(llamada_id=r.llamada_id, modelo=modelo, turnos=turnos,
                        tokens_entrada=uso.prompt_tokens, tokens_salida=uso.completion_tokens)
        except Exception as e:  # noqa: BLE001
            espera = 2 ** intento + random.random()
            print(f"  {r.llamada_id}: error ({type(e).__name__}: {e}); reintento en {espera:.0f}s")
            time.sleep(espera)
    return dict(llamada_id=r.llamada_id, modelo=modelo, turnos=None, error=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--datos", default="data/raw")
    ap.add_argument("--salida", default="data/dialogos")
    ap.add_argument("--n", type=int, default=400)
    ap.add_argument("--modelo", default="gpt-6-luna")
    ap.add_argument("--hilos", type=int, default=6)
    ap.add_argument("--semilla", type=int, default=7)
    ap.add_argument("--mock", action="store_true", help="no llama a la API")
    a = ap.parse_args()
    random.seed(a.semilla)

    out = Path(a.salida); out.mkdir(parents=True, exist_ok=True)
    muestra = muestra_estratificada(Path(a.datos), a.n, a.semilla)
    muestra.to_csv(out / "muestra.csv", index=False)
    print(f"Muestra estratificada: {len(muestra)} llamadas en {muestra.estrato.nunique()} estratos")

    archivo = out / ("dialogos_mock.jsonl" if a.mock else "dialogos.jsonl")
    hechos = set()
    if archivo.exists():  # permite reanudar si se corta
        hechos = {json.loads(l)["llamada_id"] for l in archivo.open(encoding="utf-8")
                  if json.loads(l).get("turnos")}
    pendientes = muestra[~muestra.llamada_id.isin(hechos)]
    print(f"Pendientes: {len(pendientes)} (ya generadas: {len(hechos)})")

    if a.mock:
        with archivo.open("a", encoding="utf-8") as f:
            for _, r in pendientes.iterrows():
                f.write(json.dumps(dict(llamada_id=r.llamada_id, modelo="mock",
                                        turnos=dialogo_mock(r)), ensure_ascii=False) + "\n")
        print(f"Listo (mock): {archivo}")
        return

    from openai import OpenAI
    cliente = OpenAI()  # lee OPENAI_API_KEY
    tok_in = tok_out = errores = 0
    with archivo.open("a", encoding="utf-8") as f, ThreadPoolExecutor(a.hilos) as ex:
        futuros = [ex.submit(generar_uno, cliente, a.modelo, r) for _, r in pendientes.iterrows()]
        for i, fu in enumerate(as_completed(futuros), 1):
            res = fu.result()
            f.write(json.dumps(res, ensure_ascii=False) + "\n"); f.flush()
            tok_in += res.get("tokens_entrada", 0); tok_out += res.get("tokens_salida", 0)
            errores += bool(res.get("error"))
            if i % 25 == 0:
                print(f"  {i}/{len(futuros)}  tokens entrada={tok_in:,} salida={tok_out:,}")
    print(f"Listo: {archivo} | errores={errores} | tokens entrada={tok_in:,} salida={tok_out:,}")


if __name__ == "__main__":
    main()
