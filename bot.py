# bot.py
import os, requests, math
from datetime import datetime

# ---- JMA endpoints (official) ----
JMA_TABLE = "https://www.jma.go.jp/bosai/amedas/const/amedastable.json"        # station metadata
JMA_LATEST_TIME = "https://www.jma.go.jp/bosai/amedas/data/latest_time.txt"    # ISO8601 JST
JMA_SELECTOR = "https://www.jma.go.jp/bosai/const/selectorinfos/amedas.json"   # element name map

# ---- Notifiers ----
SLACK_WEBHOOK = os.getenv("SLACK_WEBHOOK_URL")              # optional
LINE_TOKEN     = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")     # optional

# ---- Target location (your coords) ----
LAT = float(os.getenv("LAT", "34.8663494"))
LON = float(os.getenv("LON", "137.1739931"))

def haversine(lat1, lon1, lat2, lon2):
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dlmb/2)**2
    return 2 * R * math.atan2(a**0.5, (1 - a)**0.5)

def nearest_amedas(lat, lon):
    meta = requests.get(JMA_TABLE, timeout=20).json()
    best = None
    for sid, v in meta.items():
        plat = v["lat"][0] + v["lat"][1]/60
        plon = v["lon"][0] + v["lon"][1]/60
        d = haversine(lat, lon, plat, plon)
        if not best or d < best[0]:
            best = (d, sid, v.get("kjName", ""), plat, plon)
    return {"station_id": best[1], "name": best[2], "lat": best[3], "lon": best[4], "dist_m": round(best[0])}

def latest_point_json(station_id):
    ttxt = requests.get(JMA_LATEST_TIME, timeout=20).text.strip()
    dt = datetime.fromisoformat(ttxt)  # JST
    ymd = dt.strftime("%Y%m%d")
    h3 = f"{(dt.hour//3)*3:02d}"
    url = f"https://www.jma.go.jp/bosai/amedas/data/point/{station_id}/{ymd}_{h3}.json"
    js = requests.get(url, timeout=20).json()
    k = max(js.keys())
    return k, js[k]

# --- robust element label loader (dict/list both OK) ---
def load_elem_labels():
    mapping = {}
    try:
        sel = requests.get(JMA_SELECTOR, timeout=20).json()
    except Exception:
        sel = None

    if isinstance(sel, dict) and "selectors" in sel:
        blocks = sel["selectors"]
    elif isinstance(sel, list):
        blocks = sel
    else:
        blocks = []

    for block in blocks:
        if not isinstance(block, dict):
            continue
        key = block.get("key")
        if key in ("elem", "elements"):
            for item in block.get("values", []):
                val = item.get("value")
                name = item.get("name") or item.get("ja") or val
                if val:
                    mapping[val] = name

    # fallbacks
    mapping.setdefault("temp", "気温")
    mapping.setdefault("humidity", "湿度")
    mapping.setdefault("wind", "風速")
    mapping.setdefault("windDirection", "風向")
    mapping.setdefault("gust", "最大瞬間風速")
    mapping.setdefault("gustDirection", "最大瞬間風向")
    mapping.setdefault("precipitation10m", "10分間降水量")
    mapping.setdefault("precipitation1h", "1時間降水量")
    mapping.setdefault("precipitation3h", "3時間降水量")
    mapping.setdefault("precipitation24h", "24時間降水量")
    mapping.setdefault("sunshine10m", "10分間日照時間")
    mapping.setdefault("snowDepth", "積雪深")
    mapping.setdefault("pressure", "現地気圧")
    mapping.setdefault("seaLevelPressure", "海面気圧")
    mapping.setdefault("visibility", "視程")
    return mapping

def flatten_values(row: dict):
    def take(v):
        if v is None: return None
        return v[0] if isinstance(v, list) else v
    return {k: take(v) for k, v in row.items()}

# --- 風向を16方位名に ---
DIR16 = ["北","北北東","北東","東北東","東","東南東","南東","南南東",
         "南","南南西","南西","西南西","西","西北西","北西","北北西"]
def dir16_name(code):
    try:
        i = int(code) % 16
        return DIR16[i]
    except Exception:
        return str(code)

def fmt_unit(key):
    units = {
        "temp": "℃",
        "humidity": "%",
        "wind": "m/s",
        "gust": "m/s",
        "windDirection": "",           # 方向は方位名に変換するので単位なし
        "gustDirection": "",
        "precipitation10m": "mm/10m",
        "precipitation1h": "mm/h",
        "precipitation3h": "mm/3h",
        "precipitation24h": "mm",
        "snowDepth": "cm",
        "sunshine10m": "min/10m",
        "pressure": "hPa",
        "seaLevelPressure": "hPa",
        "visibility": "km",
    }
    return units.get(key, "")

def notify_slack(text):
    if not SLACK_WEBHOOK: 
        print("Slack webhook not set; skip"); 
        return
    r = requests.post(SLACK_WEBHOOK, json={"text": text}, timeout=20)
    print
