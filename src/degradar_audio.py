"""
Paso 6d — Versión "telefónica" SIMULADA a partir del audio limpio (sin API, sin costo).

Por cada canal (asesor = izquierdo, cliente = derecho) de data/audio/limpio/<id>.flac:
  1. 24 kHz -> 8 kHz (resample_poly, con filtro antialias),
  2. pasa-banda 300-3400 Hz (Butterworth de orden 4), como una línea telefónica,
  3. ruido blanco filtrado en la misma banda, a una SNR objetivo (20 dB por defecto) respecto del RMS del habla activa
     de ESE canal (se usan los tiempos de los turnos del JSON),
  4. compresión mu-law con cuantización de 8 bits (aproximación de G.711, no el códec exacto).
Guarda data/audio/telefonico/<id>.flac (estéreo, 8 kHz) y <id>.json con los parámetros y la SNR medida por canal.
Determinista: la semilla del ruido sale de md5(llamada_id|canal). Los tiempos de los turnos no cambian.

Limitaciones: es una SIMULACIÓN (no hay pérdida de paquetes, eco, cortes ni códecs de bajo bitrate como G.729/GSM);
el ruido es estacionario e independiente por canal; la voz de partida sigue siendo TTS limpio.

Uso:
    python src/degradar_audio.py --ids L023691
    python src/degradar_audio.py                     # todas las llamadas de data/audio/limpio
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from pydub import AudioSegment
from scipy.signal import butter, resample_poly, sosfilt

FS_IN, FS_OUT = 24000, 8000
BANDA = (300, 3400)
SNR_DB = 20.0
MU = 255.0
MARGEN_MS = 50  # se excluye el borde de cada turno al medir habla / ruido
SOS = butter(4, BANDA, btype="bandpass", fs=FS_OUT, output="sos")


def mulaw(x: np.ndarray) -> np.ndarray:
    """Compresión mu-law (mu = 255) con cuantización a 8 bits (255 niveles) y expansión posterior."""
    x = np.clip(x, -1.0, 1.0)
    y = np.sign(x) * np.log1p(MU * np.abs(x)) / np.log1p(MU)
    y = np.round(y * 127) / 127
    return np.sign(y) * np.expm1(np.abs(y) * np.log1p(MU)) / MU


def _mascara(n: int, tramos_ms: list[tuple[int, int]], margen_ms: int) -> np.ndarray:
    """True dentro de los tramos; margen_ms > 0 los encoge (habla segura), < 0 los ensancha (para aislar el ruido)."""
    m = np.zeros(n, dtype=bool)
    k = FS_OUT // 1000
    for a, b in tramos_ms:
        m[max(0, (a + margen_ms) * k):max(0, (b - margen_ms) * k)] = True
    return m


def degradar_canal(x: np.ndarray, tramos_ms, rng, snr_db: float = SNR_DB):
    """x: señal 24 kHz en [-1, 1]. Devuelve (señal 8 kHz degradada, SNR medida en dB)."""
    x = sosfilt(SOS, resample_poly(x, 1, FS_IN // FS_OUT))
    activo = _mascara(len(x), tramos_ms, MARGEN_MS)
    solo_ruido = ~_mascara(len(x), tramos_ms, -MARGEN_MS)
    rms_habla = np.sqrt(np.mean(x[activo] ** 2))
    ruido = sosfilt(SOS, rng.standard_normal(len(x)))
    ruido *= rms_habla / 10 ** (snr_db / 20) / np.sqrt(np.mean(ruido ** 2))
    y = mulaw(x + ruido)
    # SNR medida sobre la señal final: potencia en habla activa (habla+ruido) vs potencia en tramos sin habla (solo ruido)
    pa, pn = np.mean(y[activo] ** 2), np.mean(y[solo_ruido] ** 2)
    medida = 10 * np.log10(max(pa - pn, 1e-12) / pn)
    return y, float(medida)


def procesar(lid: str, entrada: Path, salida: Path, snr_db: float, forzar: bool):
    out_a, out_j = salida / f"{lid}.flac", salida / f"{lid}.json"
    if out_a.exists() and out_j.exists() and not forzar:
        return None
    meta = json.loads((entrada / f"{lid}.json").read_text(encoding="utf-8"))
    est = AudioSegment.from_file(entrada / f"{lid}.flac")
    assert est.channels == 2 and est.frame_rate == FS_IN, "se esperaba estéreo a 24 kHz"
    canales = {"asesor": 0, "cliente": 1}
    chs, medidas = [], {}
    for rol, i in canales.items():
        x = np.array(est.split_to_mono()[i].get_array_of_samples(), dtype=np.float64) / 32768.0
        tramos = [(t["inicio_ms"], t["fin_ms"]) for t in meta["turnos"] if t["hablante"] == rol]
        seed = int(hashlib.md5(f"{lid}|{rol}".encode()).hexdigest()[:8], 16)
        y, medidas[rol] = degradar_canal(x, tramos, np.random.default_rng(seed), snr_db)
        chs.append(y)
    n = min(len(c) for c in chs)
    est8 = np.column_stack([c[:n] for c in chs])
    pcm = np.round(np.clip(est8, -1, 1) * 32767).astype("<i2")
    salida.mkdir(parents=True, exist_ok=True)
    AudioSegment(pcm.tobytes(), frame_rate=FS_OUT, sample_width=2, channels=2).export(out_a, format="flac")
    out_j.write_text(json.dumps(dict(
        llamada_id=lid, origen="limpio", frame_rate=FS_OUT, banda_hz=list(BANDA), snr_objetivo_db=snr_db,
        snr_medida_db={r: round(v, 2) for r, v in medidas.items()}, codec="mu-law 255, 8 bits (aprox. G.711)",
        duracion_ms=round(n / FS_OUT * 1000), duracion_limpio_ms=meta["duracion_ms"]), ensure_ascii=False), encoding="utf-8")
    return medidas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--entrada", default="data/audio/limpio")
    ap.add_argument("--salida", default="data/audio/telefonico")
    ap.add_argument("--snr", type=float, default=SNR_DB)
    ap.add_argument("--ids", nargs="*")
    ap.add_argument("--forzar", action="store_true")
    a = ap.parse_args()
    entrada, salida = Path(a.entrada), Path(a.salida)
    ids = a.ids or sorted(p.stem for p in entrada.glob("*.json"))
    hechas, fuera = 0, []
    for lid in ids:
        r = procesar(lid, entrada, salida, a.snr, a.forzar)
        if r:
            hechas += 1
            if any(abs(v - a.snr) > 1.5 for v in r.values()):
                fuera.append((lid, {k: round(v, 1) for k, v in r.items()}))
    print(f"Llamadas nuevas: {hechas} de {len(ids)} | SNR objetivo {a.snr} dB | fuera de ±1.5 dB: {fuera or 'ninguna'}")


if __name__ == "__main__":
    main()
