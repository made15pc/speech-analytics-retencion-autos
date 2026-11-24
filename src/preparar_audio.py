"""
Paso 6b — Guiones hablados para la voz sintética.

Para cada llamada de la selección:
  * asigna un cliente ficticio (nombre y género; el género se detecta por el trato del asesor y,
    si no hay pista, se sortea de forma determinista según el ID de la llamada),
  * reemplaza [DNI], [PLACA], [TARJETA], [CORREO], [NOMBRE_CLIENTE] por valores ficticios que la voz
    pueda leer (dígitos en palabras, letras separadas),
  * convierte "S/ 144" en "144 soles".
El resultado (texto_hablado) es lo que se sintetiza y la REFERENCIA contra la que se calcula el WER.

Uso:
    python src/preparar_audio.py --dialogos data/dialogos/dialogos.jsonl \
        --seleccion data/dialogos/seleccion_audio.csv --salida data/dialogos/guiones_audio.jsonl
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import unicodedata
from pathlib import Path

import pandas as pd

NOMBRES = {
    "F": ["María Quispe", "Rosa Huamán", "Carmen Flores", "Lucía Mamani", "Ana Torres",
          "Patricia Condori", "Elena Ramos", "Sofía Chávez"],
    "M": ["Carlos Quispe", "Luis Huamán", "Jorge Flores", "Miguel Mamani", "José Torres",
          "Pedro Condori", "Juan Ramos", "Diego Chávez"],
}
DIG = ["cero", "uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve"]
RE_F = re.compile(r"\b(señora|señorita|sra|doña)\b", re.I)
RE_M = re.compile(r"\b(señor|sr|don)\b", re.I)
RE_MARCA = re.compile(r"\[([A-Z_]+)\]")
RE_SOLES = re.compile(r"S/\.?\s*(\d+(?:[.,]\d+)*)")


def _rng(llamada_id: str) -> random.Random:
    return random.Random(int(hashlib.md5(str(llamada_id).encode()).hexdigest(), 16))


def _ascii(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def digitos(n: int, rng: random.Random) -> str:
    return " ".join(DIG[rng.randrange(10)] for _ in range(n))


def persona(llamada_id: str, texto_total: str) -> dict:
    rng = _rng(llamada_id)
    f, m = len(RE_F.findall(texto_total)), len(RE_M.findall(texto_total))
    genero = "F" if f > m else "M" if m > f else rng.choice(["F", "M"])
    nombre = rng.choice(NOMBRES[genero])
    nom, ape = [_ascii(x) for x in nombre.split()]
    letras = " ".join(rng.choice("ABCDEFGHJKLMNPRSTUVXYZ") for _ in range(3))
    return dict(
        genero=genero, nombre=nombre,
        valores={
            "NOMBRE_CLIENTE": nombre,
            "DNI": digitos(8, rng),
            "PLACA": f"{letras} {digitos(3, rng)}",
            "TARJETA": digitos(4, rng),
            "CORREO": f"{nom} punto {ape} arroba correo punto com",
        },
    )


def hablar(texto: str, valores: dict) -> str:
    t = RE_MARCA.sub(lambda m: valores.get(m.group(1), m.group(0)), texto)
    t = RE_SOLES.sub(lambda m: f"{m.group(1)} soles", t)
    return re.sub(r"\s{2,}", " ", t).strip()


def preparar(d: dict) -> dict:
    texto_total = " ".join(t["texto"] for t in d["turnos"])
    p = persona(d["llamada_id"], texto_total)
    turnos = [dict(hablante=t["hablante"], texto=t["texto"], texto_hablado=hablar(t["texto"], p["valores"]))
              for t in d["turnos"]]
    return dict(llamada_id=d["llamada_id"], cliente=dict(genero=p["genero"], nombre=p["nombre"]),
                valores=p["valores"], turnos=turnos)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dialogos", default="data/dialogos/dialogos.jsonl")
    ap.add_argument("--seleccion", default="data/dialogos/seleccion_audio.csv")
    ap.add_argument("--salida", default="data/dialogos/guiones_audio.jsonl")
    a = ap.parse_args()
    ids = list(pd.read_csv(a.seleccion).llamada_id)
    dialogos = {}
    for l in open(a.dialogos, encoding="utf-8"):
        d = json.loads(l)
        dialogos[d["llamada_id"]] = d
    faltan = [i for i in ids if i not in dialogos]
    assert not faltan, f"IDs de la selección que no están en los diálogos: {faltan[:5]}"
    guiones = [preparar(dialogos[i]) for i in ids]
    restos = [(g["llamada_id"], m) for g in guiones for t in g["turnos"]
              for m in re.findall(r"\[[^\]]+\]", t["texto_hablado"])]
    assert not restos, f"quedaron marcadores sin reemplazar: {restos[:5]}"
    with open(a.salida, "w", encoding="utf-8") as f:
        for g in guiones:
            f.write(json.dumps(g, ensure_ascii=False) + "\n")
    gen = pd.Series([g["cliente"]["genero"] for g in guiones]).value_counts().to_dict()
    n_turnos = sum(len(g["turnos"]) for g in guiones)
    n_chars = sum(len(t["texto_hablado"]) for g in guiones for t in g["turnos"])
    print(f"Guiones: {len(guiones)} | turnos: {n_turnos} | caracteres: {n_chars:,} | género del cliente: {gen}")
    print(f"Guardado en {a.salida}")


if __name__ == "__main__":
    main()
