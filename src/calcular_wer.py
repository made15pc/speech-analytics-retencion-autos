"""
Paso 6e — WER (tasa de error de palabras) de la transcripción, en tres niveles de normalización. Sin API, sin costo.

Compara el texto hablado del guion (referencia) con la transcripción de cada canal (asesor / cliente) y versión
(limpio / telefónico). Se reportan SIEMPRE los tres niveles, para que se vea cuánto pesa cada normalización:
  1) crudo      : minúsculas, sin puntuación, DNI/placa deletreados unidos en una sola palabra.
  2) +números   : además, números escritos con palabras o con cifras quedan en dígitos en ambos textos
                  ("ciento setenta y ocho" = "178"; "1,250" = "1250"). "uno" se deja sin convertir (suele ser pronombre).
  3) +equiv.    : además, "auto segura" = "autosegura", "chao" = "chau" y se ignoran las tildes.
La normalización es fija: se definió antes de calcular el nivel 3 y no se ajusta a los resultados.
Las reglas del nivel 3 salieron de revisar las diferencias más repetidas (como en los archivos GLM del NIST).

Salida: data/resultados/wer_transcripcion.csv y data/resultados/diferencias_frecuentes.csv

Uso:  python src/calcular_wer.py
"""
from __future__ import annotations

import csv
import difflib
import glob
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

import jiwer
from text_to_num import alpha2digit

DIG = {"cero": "0", "uno": "1", "dos": "2", "tres": "3", "cuatro": "4", "cinco": "5", "seis": "6", "siete": "7",
       "ocho": "8", "nueve": "9"}
CONJ = {"y", "a", "o", "e", "u"}
DIG_PAL = {k: v for k, v in DIG.items() if k != "uno"}
EVENTO = ("L012170", "cliente")  # repetición de 52 palabras en el telefónico (ver bitácora)


def toks(s: str) -> list[str]:
    s = unicodedata.normalize("NFC", s.lower())
    return re.sub(r"[^\w\s]", " ", s).split()


def es_ent(t: str) -> bool:
    return t in DIG or (len(t) == 1 and t.isalpha()) or t.isdigit()


def colapsa(ts: list[str]) -> list[str]:
    """Junta rachas de >=3 dígitos o letras sueltas (DNI, placa deletreados) en una sola palabra."""
    out, i = [], 0
    while i < len(ts):
        if not es_ent(ts[i]):
            out.append(ts[i]); i += 1; continue
        j = i
        while j < len(ts) and es_ent(ts[j]): j += 1
        k = j
        while k > i and ts[k - 1] in CONJ: k -= 1
        if k - i >= 3:
            out.append("".join(DIG.get(t, t) for t in ts[i:k])); out.extend(ts[k:j])
        else:
            out.extend(ts[i:j])
        i = j
    return out


def norm_crudo(s: str) -> list[str]:
    return colapsa(toks(s))


def norm_num(s: str) -> list[str]:
    s = unicodedata.normalize("NFC", s.lower())
    s = re.sub(r"(?<=\d)[.,](?=\d{3}(?!\d))", "", s)  # 1,250 o 1.250 -> 1250
    ts = colapsa(re.sub(r"[^\w\s]", " ", s).split())
    ts = alpha2digit(" ".join(ts), "es").split()
    return [DIG_PAL.get(t, t) for t in ts]


def sin_tildes(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")


def norm_final(s: str) -> list[str]:
    s = re.sub(r"auto\s+segura", "autosegura", s.lower())
    s = re.sub(r"\bchao\b", "chau", s)
    return [sin_tildes(t) for t in norm_num(s)]


def cargar_guion(ruta: str = "data/dialogos/guiones_audio.jsonl") -> dict:
    guion = {}
    for linea in open(ruta, encoding="utf-8"):
        j = json.loads(linea)
        for r in ("asesor", "cliente"):
            guion[(j["llamada_id"], r)] = " ".join(t["texto_hablado"] for t in j["turnos"] if t["hablante"] == r)
    return guion


def cargar(version: str) -> dict:
    return {(d["llamada_id"], d["canal"]): d
            for d in (json.load(open(p, encoding="utf-8")) for p in glob.glob(f"data/transcripciones/{version}/*.json"))}


def wer(guion, V, norm, canal=None, excluir=()):
    refs, hyps = [], []
    for (lid, c), d in V.items():
        if (canal and c != canal) or (lid, c) in excluir: continue
        refs.append(" ".join(norm(guion[(lid, c)]))); hyps.append(" ".join(norm(d["texto"])))
    o = jiwer.process_words(refs, hyps)
    return dict(wer=o.wer * 100, sust=o.substitutions, omit=o.deletions, inser=o.insertions,
                n_ref=o.hits + o.substitutions + o.deletions)


def main():
    guion = cargar_guion()
    L, T = cargar("limpio"), cargar("telefonico")
    filas = []
    casos = [("limpio", L, None, ()), ("limpio", L, "asesor", ()), ("limpio", L, "cliente", ()),
             (f"limpio sin {EVENTO[0]} {EVENTO[1]}", L, None, (EVENTO,)),
             ("telefonico", T, None, ()), ("telefonico", T, "asesor", ()), ("telefonico", T, "cliente", ()),
             (f"telefonico sin {EVENTO[0]} {EVENTO[1]}", T, None, (EVENTO,))]
    print(f"{'versión':34s} {'canal':8s} {'1) crudo':>9s} {'2) +números':>12s} {'3) +equiv.':>11s} {'sust':>5s} {'omit':>5s} {'inser':>5s}")
    for nombre, V, canal, exc in casos:
        w0, w1, w2 = (wer(guion, V, n, canal, exc) for n in (norm_crudo, norm_num, norm_final))
        filas.append(dict(version=nombre, canal=canal or "ambos", wer_crudo=round(w0["wer"], 3),
                          wer_numeros=round(w1["wer"], 3), wer_final=round(w2["wer"], 3), sust=w2["sust"],
                          omit=w2["omit"], inser=w2["inser"], palabras_ref=w2["n_ref"]))
        print(f"{nombre:34s} {canal or 'ambos':8s} {w0['wer']:8.2f}% {w1['wer']:11.2f}% {w2['wer']:10.2f}% "
              f"{w2['sust']:5d} {w2['omit']:5d} {w2['inser']:5d}")

    pares = Counter()
    for V in (L, T):
        for (lid, c), d in V.items():
            a, b = norm_final(guion[(lid, c)]), norm_final(d["texto"])
            for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
                if tag == "replace" and max(i2 - i1, j2 - j1) <= 4:
                    pares[(" ".join(a[i1:i2]), " ".join(b[j1:j2]))] += 1

    salida = Path("data/resultados"); salida.mkdir(parents=True, exist_ok=True)
    with open(salida / "wer_transcripcion.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0])); w.writeheader(); w.writerows(filas)
    with open(salida / "diferencias_frecuentes.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["veces", "referencia", "transcripcion"])
        for (r, h), n in pares.most_common(40): w.writerow([n, r, h])
    print(f"\nGuardado: {salida / 'wer_transcripcion.csv'} y {salida / 'diferencias_frecuentes.csv'}")


if __name__ == "__main__":
    main()
