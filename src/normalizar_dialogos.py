"""
Paso 5b — Normalización determinista de diálogos ya generados (sin volver a llamar a la API).

Corrige tres defectos observados en la corrida de 402 diálogos:
  1. Turnos con la clave 'text' en lugar de 'texto'.
  2. Marcadores inventados para números de gestión ([NÚMERO DE SOLICITUD], [CÓDIGO], ...):
     se reemplazan por un número ficticio de 6 dígitos, estable dentro de cada diálogo.
  3. Acotaciones escénicas entre corchetes ([Pausa breve]): se eliminan, porque la voz las leería.

Uso:
    python src/normalizar_dialogos.py --dialogos data/dialogos/dialogos.jsonl
Deja una copia del original en <archivo>.antes_de_normalizar y es idempotente.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path

PERMITIDOS = {"NOMBRE_CLIENTE", "DNI", "PLACA", "TARJETA", "CORREO"}
RE_BRACKET = re.compile(r"\[([^\]]+)\]")
RE_NUMERO = re.compile(r"n[úu]mero|c[óo]digo|gesti[óo]n|solicitud|atenci[óo]n|constancia|tr[áa]mite|nro|ticket|caso", re.I)
RE_ACOTACION = re.compile(r"pausa|silencio|espera|suspiro|risa|tecle", re.I)


def numero_ficticio(llamada_id: str) -> str:
    return str(int(hashlib.md5(str(llamada_id).encode()).hexdigest(), 16) % 900000 + 100000)


def normalizar(d: dict) -> tuple[dict, dict]:
    cambios = {"clave_text": 0, "numero_caso": 0, "acotacion": 0}
    num = numero_ficticio(d["llamada_id"])
    for t in d.get("turnos") or []:
        if "texto" not in t and "text" in t:
            t["texto"] = t.pop("text"); cambios["clave_text"] += 1

        def _sub(m):
            etiqueta = m.group(1)
            if etiqueta in PERMITIDOS:
                return m.group(0)
            if RE_ACOTACION.search(etiqueta):
                cambios["acotacion"] += 1
                return ""
            if RE_NUMERO.search(etiqueta):
                cambios["numero_caso"] += 1
                return num
            return m.group(0)  # desconocido de otro tipo: lo dejamos para que el QA lo marque

        t["texto"] = re.sub(r"\s{2,}", " ", RE_BRACKET.sub(_sub, t.get("texto", ""))).strip()
    return d, cambios


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dialogos", default="data/dialogos/dialogos.jsonl")
    a = ap.parse_args()
    ruta = Path(a.dialogos)
    copia = ruta.with_name(ruta.name + ".antes_de_normalizar")
    if not copia.exists():
        shutil.copy(ruta, copia)
    total = {"clave_text": 0, "numero_caso": 0, "acotacion": 0}
    filas = []
    for l in open(ruta, encoding="utf-8"):
        d, c = normalizar(json.loads(l))
        for k in total:
            total[k] += c[k]
        filas.append(d)
    with open(ruta, "w", encoding="utf-8") as f:
        for d in filas:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    print(f"Diálogos: {len(filas)} | cambios: {total}")


if __name__ == "__main__":
    main()
