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
        "dominancia": clamp((h / total) / DOM_F
