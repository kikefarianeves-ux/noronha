"""Coleta maré e swell de Fernando de Noronha (Open-Meteo Marine, sem chave) e salva data/data.json."""
import json, time, urllib.parse, urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

LAT, LON = -3.854, -32.424
TZ = "America/Noronha"
OUT = Path(__file__).resolve().parent.parent / "data" / "data.json"
URL = "https://marine-api.open-meteo.com/v1/marine"

# ---- Critérios do swell (ajuste à vontade) ----
# Direção = de onde a onda vem, em graus (0 = norte). O swell que faz a temporada em Noronha vem do norte.
H_MIN, H_FULL = 0.8, 2.5     # altura do swell (m): abaixo de H_MIN não conta; em H_FULL vale 100%
T_MIN, T_FULL = 8.0, 14.0    # período (s): onda curta é mar de vento; onda longa é swell de verdade
DIR_FULL = (330, 20)         # setor NNO a NNE: vale 100%
DIR_PARTIAL = (300, 45)      # NO a NE: vale 50%; fora disso, não conta
DOM_FULL = 0.6               # parte da altura total que precisa ser swell (o resto é mar de vento)
SCORE_SWELL = 55             # nota (0-100) a partir da qual é swell
SCORE_FRACO = 30             # entre as duas notas: swell fraco ou se formando
SUAVIZAR_H = 6               # média das últimas 6 horas, para não oscilar
TEMPORADA_MESES = (12, 1, 2, 3)  # janela sazonal, usada só como estimativa quando a previsão não mostra swell

PONTOS = ["N", "NNE", "NE", "ENE", "L", "ESE", "SE", "SSE", "S", "SSO", "SO", "OSO", "O", "ONO", "NO", "NNO"]


def fetch():
    q = urllib.parse.urlencode({
        "latitude": LAT, "longitude": LON, "timezone": TZ, "forecast_days": 16,
        "hourly": "sea_level_height_msl,wave_height,swell_wave_height,swell_wave_period,swell_wave_direction",
    })
    for tentativa in range(3):
        try:
            with urllib.request.urlopen(f"{URL}?{q}", timeout=30) as r:
                return json.load(r)
        except Exception:
            if tentativa == 2:
                raise
            time.sleep(5)


def clamp(x):
    return max(0.0, min(1.0, x))


def no_setor(d, setor):
    a, b = setor  # setor que passa pelo 0 graus
    return d >= a or d <= b


def fatores(h, t, d, total):
    """Cada fator vai de 0 a 1."""
    if None in (h, t, d, total) or total <= 0:
        return {"altura": 0.0, "periodo": 0.0, "direcao": 0.0, "dominancia": 0.0}
    dirf = 1.0 if no_setor(d, DIR_FULL) else 0.5 if no_setor(d, DIR_PARTIAL) else 0.0
    return {
        "altura": clamp((h - H_MIN) / (H_FULL - H_MIN)),
        "periodo": clamp((t - T_MIN) / (T_FULL - T_MIN)),
        "direcao": dirf,
        "dominancia": clamp((h / total) / DOM_FULL),
    }


def nota(f):
    # A direção funciona como porta: swell que não vem do setor certo não conta.
    return round(100 * f["direcao"] * (0.5 * f["altura"] + 0.3 * f["periodo"] + 0.2 * f["dominancia"]), 1)


def build(api, agora):
    h = api["hourly"]
    t = [datetime.fromisoformat(x) for x in h["time"]]
    nivel = h["sea_level_height_msl"]
    i = max(k for k, x in enumerate(t) if x <= agora)

    # ---- Maré ----
    frac = (agora - t[i]).total_seconds() / 3600
    atual = nivel[i] + (nivel[i + 1] - nivel[i]) * frac
    enchendo = nivel[i + 1] > nivel[i]
    janela = [v for v in nivel[max(0, i - 12): i + 13] if v is not None]
    media = sum(janela) / len(janela)
    extremos = []
    for k in range(i + 1, min(i + 49, len(t) - 1)):
        a, b, c = nivel[k - 1], nivel[k], nivel[k + 1]
        if None in (a, b, c):
            continue
        if b > a and b >= c:
            extremos.append({"tipo": "alta", "hora": h["time"][k], "nivel_m": round(b, 2)})
        elif b < a and b <= c:
            extremos.append({"tipo": "baixa", "hora": h["time"][k], "nivel_m": round(b, 2)})

    # ---- Swell: nota de 0 a 100 por hora, suavizada ----
    F = [fatores(h["swell_wave_height"][k], h["swell_wave_period"][k],
                 h["swell_wave_direction"][k], h["wave_height"][k]) for k in range(len(t))]
    notas = [nota(f) for f in F]
    suav = [sum(notas[max(0, k - SUAVIZAR_H + 1): k + 1]) / len(notas[max(0, k - SUAVIZAR_H + 1): k + 1])
            for k in range(len(t))]
    atual_nota = round(suav[i], 1)
    situacao = "swell" if atual_nota >= SCORE_SWELL else "swell fraco" if atual_nota >= SCORE_FRACO else "sem swell"

    inicio = None
    if situacao != "swell":
        for k in range(i + 1, len(t)):
            if suav[k] >= SCORE_SWELL:
                inicio = h["time"][k]
                break
    por_dia = {}
    for k in range(i, len(t)):
        d = h["time"][k][:10]
        por_dia[d] = max(por_dia.get(d, 0), round(suav[k], 1))

    hs, ts, ds = h["swell_wave_height"][i], h["swell_wave_period"][i], h["swell_wave_direction"][i]
    na_temporada = agora.month in TEMPORADA_MESES
    inicio_sazonal = None if na_temporada else str(datetime(agora.year, 12, 1).date())  # meses 4 a 11

    return {
        "atualizado_em": agora.isoformat(timespec="minutes"),
        "fuso": TZ,
        "mare": {
            "nivel_atual_m": round(atual, 2),
            "estado": "alta" if atual > media else "baixa",
            "movimento": "enchendo" if enchendo else "vazando",
            "proximos_extremos": extremos[:4],
            "serie_48h": [{"hora": h["time"][k], "nivel_m": round(nivel[k], 2)}
                          for k in range(i, min(i + 49, len(t))) if nivel[k] is not None],
        },
        "swell": {
            "nota": atual_nota,
            "situacao": situacao,
            "em_epoca": situacao == "swell",
            "altura_m": hs,
            "periodo_s": ts,
            "direcao_graus": ds,
            "direcao_nome": PONTOS[round(ds / 22.5) % 16] if ds is not None else None,
            "energia_kw_por_m": round(0.49 * hs * hs * ts, 1) if hs is not None and ts is not None else None,
            "fatores_pct": {k: round(v * 100) for k, v in F[i].items()},
            "proximo_inicio_previsto": inicio,
            "temporada_sazonal": na_temporada,
            "proximo_inicio_sazonal_estimado": inicio_sazonal,
            "nota_maxima_por_dia": por_dia,
            "criterios": {"nota_swell": SCORE_SWELL, "nota_fraco": SCORE_FRACO},
        },
    }


if __name__ == "__main__":
    dados = build(fetch(), datetime.now(ZoneInfo(TZ)).replace(tzinfo=None))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
    print("ok", dados["atualizado_em"], dados["swell"]["situacao"], dados["swell"]["nota"])
