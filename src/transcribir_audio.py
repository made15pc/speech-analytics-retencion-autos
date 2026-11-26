"""
Paso 6e — Transcripción por canal con gpt-transcribe (consume créditos de la API).

Para cada llamada y cada versión de audio (limpio / telefónico), separa el estéreo en dos archivos mono
(canal izquierdo = asesor, canal derecho = cliente) y transcribe cada canal POR SEPARADO: así no hace falta
diarización. Cada archivo mono dura lo mismo que la llamada completa, por lo que los minutos facturados son
2 x duración de la llamada por versión.

Línea base: SOLO la pista de idioma (languages = ["es"]). Sin `prompt` y sin `keywords`: darle al ASR los términos
que esperamos oír le regalaría las respuestas y subestimaría el WER. Probar con hints sería otro experimento.

Guarda data/transcripciones/<version>/<llamada>_<canal>.json con el texto, el modelo, los parámetros y la duración.
Reanuda: no repite lo ya transcrito. Precio de referencia: US$ 0.0045 por minuto de audio (página oficial de precios
de OpenAI, consultada el 24-nov-2026); la factura real la da el panel de OpenAI.

Uso:
    python src/transcribir_audio.py --ids L023691                  # una llamada, ambas versiones
    python src/transcribir_audio.py --ids L023691 --versiones limpio
    python src/transcribir_audio.py                                # todas
    python src/transcribir_audio.py --mock --ids L023691           # sin API (solo prueba el flujo)
"""
from __future__ import annotations

import argparse
import json
import random
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pydub import AudioSegment

MODELO_ASR = "gpt-transcribe"
IDIOMAS = ["es"]
USD_POR_MIN = 0.0045
MAX_MB = 25  # límite de archivo de la API de transcripción
CANALES = {"asesor": 0, "cliente": 1}
ENTRADAS = {"limpio": "data/audio/limpio", "telefonico": "data/audio/telefonico"}


def _a_json(o):
    """El SDK devuelve objetos pydantic (p. ej. TranscriptionLanguage): se guardan como diccionarios, nunca se pierde
    una respuesta ya pagada por no poder serializarla."""
    return o.model_dump(mode="json") if hasattr(o, "model_dump") else str(o)


def tareas(ids: list[str] | None, versiones: list[str]) -> list[tuple[str, str, str]]:
    out = []
    for v in versiones:
        carpeta = Path(ENTRADAS[v])
        todos = sorted(p.stem for p in carpeta.glob("*.flac"))
        for lid in (ids or todos):
            assert lid in todos, f"no existe {carpeta / (lid + '.flac')}"
            out += [(v, lid, c) for c in CANALES]
    return out


def transcribir_archivo(client, ruta: Path) -> dict:
    mb = ruta.stat().st_size / 1e6
    assert mb < MAX_MB, f"{ruta.name}: {mb:.1f} MB supera el límite de {MAX_MB} MB"
    with open(ruta, "rb") as f:
        for intento in range(5):
            try:
                f.seek(0)
                r = client.audio.transcriptions.create(model=MODELO_ASR, file=f, extra_body={"languages": IDIOMAS})
                return dict(texto=r.text, languages=getattr(r, "languages", None), usage=getattr(r, "usage", None))
            except Exception as e:  # noqa: BLE001
                espera = 2 ** intento + random.random()
                print(f"  {ruta.name}: error ({type(e).__name__}: {str(e)[:100]}); reintento en {espera:.0f}s")
                time.sleep(espera)
    raise RuntimeError(f"no se pudo transcribir {ruta.name}")


def procesar(tarea, client, salida: Path, mock: bool, forzar: bool):
    version, lid, canal = tarea
    out = salida / version / f"{lid}_{canal}.json"
    if out.exists() and not forzar:
        return None
    est = AudioSegment.from_file(Path(ENTRADAS[version]) / f"{lid}.flac")
    assert est.channels == 2, "se esperaba audio estéreo"
    mono = est.split_to_mono()[CANALES[canal]]
    minutos = len(mono) / 60000
    with tempfile.TemporaryDirectory() as tmp:
        ruta = Path(tmp) / f"{lid}_{canal}.flac"
        mono.export(ruta, format="flac")
        res = dict(texto=f"[mock] {canal} {lid}", languages=IDIOMAS, usage=None) if mock \
            else transcribir_archivo(client, ruta)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(dict(llamada_id=lid, version=version, canal=canal, modelo=MODELO_ASR,
                                   idiomas_pista=IDIOMAS, keywords=None, prompt=None, mock=mock,
                                   duracion_min=round(minutos, 3), **res), ensure_ascii=False, default=_a_json),
                   encoding="utf-8")
    return minutos


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--versiones", nargs="*", default=list(ENTRADAS), choices=list(ENTRADAS))
    ap.add_argument("--ids", nargs="*")
    ap.add_argument("--salida", default="data/transcripciones")
    ap.add_argument("--hilos", type=int, default=4)
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--forzar", action="store_true")
    a = ap.parse_args()
    client = None
    if not a.mock:
        from openai import OpenAI
        client = OpenAI()
    lista = tareas(a.ids, a.versiones)
    with ThreadPoolExecutor(a.hilos) as ex:
        res = list(ex.map(lambda t: procesar(t, client, Path(a.salida), a.mock, a.forzar), lista))
    hechas = [m for m in res if m is not None]
    print(f"Archivos mono nuevos: {len(hechas)} de {len(lista)} | {sum(hechas):.1f} min facturables | "
          f"costo estimado ≈ US$ {sum(hechas) * USD_POR_MIN:.2f} (referencia oficial, no factura)")


if __name__ == "__main__":
    main()
