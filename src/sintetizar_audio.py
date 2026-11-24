"""
Paso 6c — Síntesis de voz estéreo: asesor = canal izquierdo, cliente = canal derecho.

Para cada llamada de data/dialogos/guiones_audio.jsonl:
  * sintetiza cada turno por separado con gpt-4o-mini-tts (voz según rol y género),
  * arma la línea de tiempo: pausa corta entre hablantes distintos; pausa larga (2.5 a 6 s) cuando el
    mismo hablante habla dos turnos seguidos (representa una espera: búsqueda en el sistema, etc.),
  * guarda el estéreo en data/audio/limpio/<id>.flac (sin pérdida: un MP3 puede filtrar un canal en el
    otro) y los tiempos por turno en <id>.json.
Reanuda: no repite los turnos ya sintetizados (caché en data/audio/cache_turnos/) ni las llamadas ya hechas.
Limitación: no modela interrupciones ni solapamiento de voces.
Instrucciones v2: el ánimo del cliente sale de la verdad de terreno (sentimiento_inicio en la primera
mitad de la llamada, sentimiento_fin en la segunda); tras una frase de espera del asesor se inserta
una pausa de 3 a 7 s (tipo_pausa = "espera"); el caché de turnos incluye un hash de voz+instrucción+texto.

Uso:
    python src/sintetizar_audio.py --ids L023691            # una llamada de prueba
    python src/sintetizar_audio.py                           # todas las del guion
    python src/sintetizar_audio.py --mock --ids L023691      # sin API (tonos), para probar el armado
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
from pydub import AudioSegment
from pydub.generators import Sine

MODELO_TTS = "gpt-4o-mini-tts"
VOCES = {("asesor", "F"): "coral", ("asesor", "M"): "echo",
         ("cliente", "F"): "sage", ("cliente", "M"): "cedar"}
BASE = ("Habla en español latinoamericano, con acento peruano neutro, como en una llamada telefónica real: "
        "coloquial, con ritmo irregular, alguna duda y énfasis naturales. No leas ni declames; "
        "no suenes a locutor ni a audiolibro.")
ROL = {
    "asesor": "Eres una persona que atiende el teléfono en un call center de seguros: cordial y clara, "
              "con tono de conversación y no de presentación.",
    "cliente": "Eres un cliente que llama a su aseguradora para consultar o dar de baja su póliza.",
}
ANIMO = {
    "negativo": "Estás molesto y frustrado con la aseguradora: tono tenso, algo cortante e impaciente, "
                "con algún suspiro; hablas con firmeza.",
    "neutro": "Estás tranquilo y práctico, con alguna duda: tono normal, sin emoción marcada.",
    "positivo": "Estás de buen ánimo y colaborador: tono amable y aliviado.",
}
ESPERA_ASESOR = "Lo dices mientras buscas en el sistema, con la atención dividida y la voz algo más baja."
RE_ESPERA = re.compile(r"un momento|un segundito|un instante|unos segundos|permít[ae]me|déjeme|déjame|"
                       r"voy a (revisar|verificar|consultar|validar|buscar)|ya vuelvo|no cuelgue|en línea", re.I)
PAUSA_ESPERA = (3000, 7000)  # ms de silencio tras una frase de espera del asesor
VERSION_INSTR = "v2"


def es_espera(t: dict) -> bool:
    return t["hablante"] == "asesor" and bool(RE_ESPERA.search(t["texto_hablado"]))


def instruccion(hablante: str, animo: str | None, espera: bool) -> str:
    partes = [BASE, ROL[hablante]]
    if hablante == "cliente" and animo:
        partes.append(ANIMO[animo])
    if hablante == "asesor" and espera:
        partes.append(ESPERA_ASESOR)
    return " ".join(partes)


FRAME = 24000
USD_POR_MIN_TTS = 0.015  # referencia de fuentes secundarias; confirmar con el panel de OpenAI


def genero_asesor(asesor_id: str) -> str:
    """Estable por asesor (A01 → F, A02 → M, ...): cada asesor conserva la misma voz en todas sus llamadas."""
    return "F" if int(re.sub(r"\D", "", str(asesor_id)) or 0) % 2 == 1 else "M"


def partir(texto: str, maximo: int = 1200) -> list[str]:
    trozos, actual = [], ""
    for frase in re.split(r"(?<=[.?!…])\s+", texto):
        if actual and len(actual) + len(frase) + 1 > maximo:
            trozos.append(actual); actual = frase
        else:
            actual = f"{actual} {frase}".strip()
    if actual:
        trozos.append(actual)
    return trozos or [texto]


def _normalizar(seg: AudioSegment) -> AudioSegment:
    seg = seg.set_channels(1).set_frame_rate(FRAME).set_sample_width(2)
    return seg.apply_gain(-20.0 - seg.dBFS) if seg.dBFS != float("-inf") else seg


def _tono(texto: str, hablante: str) -> AudioSegment:  # solo para --mock
    dur = max(500, int(len(texto) / 15 * 1000))
    return Sine(300 if hablante == "asesor" else 600).to_audio_segment(duration=dur, volume=-20)


def sintetizar_turno(client, texto, hablante, genero, cache: Path, n: int, instr: str, mock: bool) -> AudioSegment:
    if mock:
        return _normalizar(_tono(texto, hablante))
    voz = VOCES[(hablante, genero)]
    partes = []
    for k, trozo in enumerate(partir(texto)):
        h = hashlib.md5(f"{voz}|{instr}|{trozo}".encode("utf-8")).hexdigest()[:8]
        ruta = cache / f"{n:03d}_{k}_{h}.mp3"
        if not ruta.exists():
            for intento in range(5):
                try:
                    r = client.audio.speech.create(model=MODELO_TTS, voice=voz, input=trozo,
                                                   instructions=instr, response_format="mp3")
                    ruta.write_bytes(r.content)
                    break
                except Exception as e:  # noqa: BLE001
                    espera = 2 ** intento + random.random()
                    print(f"  turno {n}: error ({type(e).__name__}: {str(e)[:80]}); reintento en {espera:.0f}s")
                    time.sleep(espera)
            else:
                raise RuntimeError(f"no se pudo sintetizar el turno {n}")
        partes.append(AudioSegment.from_file(ruta, format="mp3"))
    seg = partes[0]
    for p in partes[1:]:
        seg += p
    return _normalizar(seg)


def armar(g: dict, segs: list[AudioSegment], rng: random.Random):
    izq = der = AudioSegment.silent(duration=0, frame_rate=FRAME).set_sample_width(2)
    tiempos, previo, prev_espera = [], None, False
    for i, (t, seg) in enumerate(zip(g["turnos"], segs)):
        if previo is None:
            gap, tipo = 600, "inicio"
        elif prev_espera and previo != t["hablante"]:
            gap, tipo = int(rng.uniform(*PAUSA_ESPERA)), "espera"
        elif previo == t["hablante"]:
            gap, tipo = int(rng.uniform(2500, 6000)), "mismo_hablante"
        else:
            gap, tipo = int(rng.uniform(250, 800)), "cambio"
        sil = AudioSegment.silent(duration=gap, frame_rate=FRAME).set_sample_width(2)
        izq, der = izq + sil, der + sil
        mudo = seg._spawn(bytes(len(seg.raw_data)))  # silencio con exactamente los mismos fotogramas
        ini = len(izq)
        if t["hablante"] == "asesor":
            izq, der = izq + seg, der + mudo
        else:
            izq, der = izq + mudo, der + seg
        tiempos.append(dict(n=i, hablante=t["hablante"], inicio_ms=ini, fin_ms=ini + len(seg),
                            pausa_previa_ms=gap, tipo_pausa=tipo))
        previo, prev_espera = t["hablante"], es_espera(t)
    cola = AudioSegment.silent(duration=800, frame_rate=FRAME).set_sample_width(2)
    izq, der = izq + cola, der + cola
    return AudioSegment.from_mono_audiosegments(izq, der), tiempos


def procesar(g, asesor_id, animo, client, salida: Path, hilos: int, mock: bool, forzar: bool):
    lid = g["llamada_id"]
    out_audio, out_json = salida / "limpio" / f"{lid}.flac", salida / "limpio" / f"{lid}.json"
    if out_audio.exists() and out_json.exists() and not forzar:
        return None
    cache = salida / "cache_turnos" / lid
    cache.mkdir(parents=True, exist_ok=True)
    gen = {"asesor": genero_asesor(asesor_id), "cliente": g["cliente"]["genero"]}
    n_t = len(g["turnos"])

    def _instr(i, t):  # ánimo del cliente: sentimiento_inicio en la 1.ª mitad, sentimiento_fin en la 2.ª
        return instruccion(t["hablante"], animo[0] if i < n_t / 2 else animo[1], es_espera(t))

    with ThreadPoolExecutor(hilos) as ex:
        segs = list(ex.map(lambda x: sintetizar_turno(client, x[1]["texto_hablado"], x[1]["hablante"],
                                                      gen[x[1]["hablante"]], cache, x[0],
                                                      _instr(x[0], x[1]), mock),
                           enumerate(g["turnos"])))
    rng = random.Random(int(hashlib.md5(lid.encode()).hexdigest(), 16))
    est, tiempos = armar(g, segs, rng)
    out_audio.parent.mkdir(parents=True, exist_ok=True)
    est.export(out_audio, format="flac")
    meta = dict(llamada_id=lid, asesor_id=asesor_id, genero=gen, voces={r: VOCES[(r, gen[r])] for r in gen},
                modelo_tts=MODELO_TTS, version_instrucciones=VERSION_INSTR,
                animo=dict(inicio=animo[0], fin=animo[1]), duracion_ms=len(est), mock=mock, turnos=tiempos)
    out_json.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return (len(est) / 60000, sum(len(t["texto_hablado"]) for t in g["turnos"]),
            sum(t["tipo_pausa"] == "espera" for t in tiempos))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--guiones", default="data/dialogos/guiones_audio.jsonl")
    ap.add_argument("--muestra", default="data/dialogos/muestra.csv")
    ap.add_argument("--verdad", default="data/raw/verdad_conversacion.csv")
    ap.add_argument("--salida", default="data/audio")
    ap.add_argument("--ids", nargs="*", help="solo estas llamadas")
    ap.add_argument("--hilos", type=int, default=4)
    ap.add_argument("--mock", action="store_true", help="no llama a la API: genera tonos")
    ap.add_argument("--forzar", action="store_true", help="rehace llamadas ya generadas")
    a = ap.parse_args()
    guiones = [json.loads(l) for l in open(a.guiones, encoding="utf-8")]
    if a.ids:
        guiones = [g for g in guiones if g["llamada_id"] in set(a.ids)]
    asesores = pd.read_csv(a.muestra).set_index("llamada_id").asesor_id
    verdad = pd.read_csv(a.verdad).set_index("llamada_id")[["sentimiento_inicio", "sentimiento_fin"]]
    faltan = [g["llamada_id"] for g in guiones if g["llamada_id"] not in verdad.index]
    assert not faltan, f"sin verdad de terreno: {faltan[:5]}"
    assert set(verdad.loc[[g["llamada_id"] for g in guiones]].stack()) <= set(ANIMO), "ánimo no reconocido"
    client = None
    if not a.mock:
        from openai import OpenAI
        client = OpenAI()
    tot_min = tot_chars = hechas = tot_esperas = 0
    for g in guiones:
        r = procesar(g, asesores[g["llamada_id"]], tuple(verdad.loc[g["llamada_id"]]), client, Path(a.salida),
                     a.hilos, a.mock, a.forzar)
        if r:
            hechas += 1; tot_min += r[0]; tot_chars += r[1]; tot_esperas += r[2]
            print(f"{g['llamada_id']}: {r[0]:.1f} min | {r[1]:,} caracteres | {r[2]} esperas")
    print(f"\nLlamadas nuevas: {hechas} de {len(guiones)} | {tot_min:.1f} min | {tot_esperas} esperas | "
          f"costo de voz estimado ≈ US$ {tot_min * USD_POR_MIN_TTS:.2f} (referencia, no factura)")


if __name__ == "__main__":
    main()
