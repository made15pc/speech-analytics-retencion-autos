"""
Calcula los KPIs operativos, de retención y los patrones sembrados a partir de data/raw.
Sirve para dos cosas: (1) revisar que la simulación es verosímil y (2) tener una
"respuesta esperada" contra la cual comparar el dashboard de Power BI.

Uso:
    python src/revisar_kpis.py --datos data/raw
"""
import argparse

import pandas as pd


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--datos", default="data/raw")
    r = ap.parse_args().datos.rstrip("/") + "/"

    L = pd.read_csv(r + "fact_llamada.csv", parse_dates=["fecha_hora_ingreso"])
    V = pd.read_csv(r + "verdad_conversacion.csv")
    C = pd.read_csv(r + "fact_resultado_crm.csv")
    P = pd.read_csv(r + "fact_poliza_90d.csv")
    E = pd.read_csv(r + "fact_encuesta.csv")
    A = pd.read_csv(r + "fact_asesor_dia.csv")
    K = pd.read_csv(r + "fact_costos_mes.csv")
    D = pd.read_csv(r + "dim_asesor.csv")

    ent = L[L.tipo == "entrante"].copy()
    ent["hora"] = ent.fecha_hora_ingreso.dt.hour
    ofrecidas = len(ent) - (ent.abandonada & (ent.espera_seg < 5)).sum()
    at = L[L.atendida]

    print("== OPERATIVOS ==")
    print(f"Llamadas totales           {len(L):,}  (entrantes {len(ent):,})")
    print(f"Nivel de servicio 80/20    {ent.atendida_en_umbral.sum() / ofrecidas:.1%}")
    print(f"Abandono                   {ent.abandono_contable.sum() / ofrecidas:.1%}")
    print(f"ASA (seg)                  {ent[ent.atendida].espera_seg.mean():.0f}")
    print(f"TMO (min)                  {at.tmo_seg.mean() / 60:.2f}")
    print(f"Ocupación                  {A.en_llamada_seg.sum() / A.conectado_seg.sum():.1%}")
    print(f"Transferencia              {at.transferida.mean():.1%}")
    n = at.groupby("poliza_id").size()
    print(f"FCR (pólizas 1 llamada)    {(n == 1).mean():.1%}")
    print(f"CSAT (% 4-5)               {(E.csat >= 4).mean():.1%}   tasa respuesta {len(E) / len(at):.1%}")
    print(f"NPS                        {((E.nps >= 9).mean() - (E.nps <= 6).mean()) * 100:.0f}")
    costo = K[["costo_asesores_soles", "costo_supervision_soles",
               "costo_licencias_soles", "costo_infraestructura_soles"]].sum().sum()
    print(f"Costo por contacto (S/)    {costo / len(at):.2f}")
    print("NS por hora:", ent.groupby("hora").atendida_en_umbral.mean().round(2).to_dict())
    oc = A.merge(D, on="asesor_id").groupby("turno")[["en_llamada_seg", "conectado_seg"]].sum()
    print("Ocupación por turno:", (oc.en_llamada_seg / oc.conectado_seg).round(2).to_dict())

    print("\n== RETENCIÓN ==")
    ult = V.groupby("poliza_id").last().join(P.set_index("poliza_id"))
    print(f"Retención en llamada       {ult.cliente_acepta.mean():.1%}")
    print(f"Retención a 90 días        {ult.vigente_90d.mean():.1%}")
    print(f"Fuga post-acuerdo          {1 - ult[ult.cliente_acepta].vigente_90d.mean():.1%}")
    ret = ult[ult.vigente_90d]
    print(f"Prima anual retenida (S/)  {ret.prima_mensual_soles.sum() * 12:,.0f}")

    print("\n== PATRONES SEMBRADOS ==")
    V2 = V.merge(L[["llamada_id", "fecha_hora_ingreso"]], on="llamada_id")
    V2["mes"] = V2.fecha_hora_ingreso.dt.strftime("%Y-%m")
    print("1) % aumento_prima por mes:",
          pd.crosstab(V2.mes, V2.motivo_principal, normalize="index")["aumento_prima"].round(2).to_dict())
    print("2) % siniestro por región:",
          pd.crosstab(V2.region, V2.motivo_principal, normalize="index")
          ["mala_experiencia_siniestro"].round(2).to_dict())
    ok = C.merge(V, on="llamada_id").eval("motivo_crm == motivo_principal").mean()
    print(f"3) Precisión del código de cierre CRM: {ok:.1%}")
    print("4) Conducta por nivel de asesor:")
    print(V.merge(D, on="asesor_id").groupby("nivel")
          [["indaga_motivo", "ofrece_alternativa", "oferta_adecuada", "cliente_acepta"]].mean().round(2))
    print("5) Vigencia a 90 días entre quienes aceptaron, por oferta:")
    print(ult[ult.cliente_acepta].groupby("oferta_tipo").vigente_90d.agg(["mean", "size"]).round(2))
    print("6) Sentimiento inicial negativo según espera > 120 s:")
    se = V.merge(L[["llamada_id", "espera_seg"]], on="llamada_id")
    print(se.assign(espera_larga=se.espera_seg > 120).groupby("espera_larga")
          .sentimiento_inicio.apply(lambda s: (s == "negativo").mean()).round(2).to_dict())
    print("\nMix de motivos:", V.motivo_principal.value_counts(normalize=True).round(3).to_dict())


if __name__ == "__main__":
    main()
