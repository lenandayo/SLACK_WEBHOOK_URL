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
    # ex) 2025-09-17T07:10:00+09:00 -> ymd='20250917', h3='06'
    ttxt = requests.get(JMA_LATEST_TIME, timeout=20).text.strip()
    dt = datetime.fromisoformat(ttxt)
    ymd = dt.strftime("%Y%m%d")
    h3 = f"{(dt.hour//3)*3:02d}"
    url = f"https://www.jma.go.jp/bosai/amedas/data/point/{station_id}/{ymd}_{h3}.json"
    js = requests.get(url, timeout=20).json()
    # pick the latest timestamp key
    k = max(js.keys())
    return k, js[k]


"""
Build a dict like {'precipitation10m': '10分間降水量', 'temp': '気温', ...}
from the official selector info JSON.
"""
def load_elem_labels():
    import requests
    mapping = {}

    try:
        sel = requests.get(JMA_SELECTOR, timeout=20).json()
    except Exception:
        sel = None

    # sel が dictでも list でも対応する
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
        if key in ("elem", "elements"):  # どちらの表記でも
            for item in block.get("values", []):
                val = item.get("value")
                name = item.get("name") or item.get("ja") or val
                if val:
                    mapping[val] = name

    # 取得できなかった要素名はフォールバック（よく出るキー）
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
    """Take first element if value is like [val, quality_flag]. Keep None if missing."""
    def take(v):
        if v is None: return None
        return v[0] if isinstance(v, list) else v
    return {k: take(v) for k, v in row.items()}

def fmt_unit(key):
    units = {
        "temp": "℃",
        "humidity": "%",
        "wind": "m/s",
        "windDirection": "",           # 方位コード（そのまま表示）
        "precipitation10m": "mm/10m",
        "precipitation1h": "mm/h",
        "precipitation3h": "mm/3h",
        "precipitation24h": "mm",
        "snowDepth": "cm",
        "sunshine10m": "min/10m",
    }
    return units.get(key, "")

def notify_slack(text):
    if not SLACK_WEBHOOK: return
    requests.post(SLACK_WEBHOOK, json={"text": text}, timeout=20)

def notify_line(text):
    if not LINE_TOKEN: return
    headers = {"Authorization": f"Bearer {LINE_TOKEN}", "Content-Type": "application/json"}
    payload = {"messages": [{"type": "text", "text": text[:1900]}]}
    requests.post("https://api.line.me/v2/bot/message/broadcast", headers=headers, json=payload, timeout=20)

def main():
    st = nearest_amedas(LAT, LON)
    tkey, row = latest_point_json(st["station_id"])
    labels = load_elem_labels()
    vals = flatten_values(row)

    # Build lines: list only observed (non-None) elements
    lines = [f"観測速報 {tkey[8:10]}:{tkey[10:12]}（JST） / アメダス{st['name']}（{st['dist_m']}m先）"]
    for key in sorted(vals.keys()):
        val = vals[key]
        if val is None: continue
        name = labels.get(key, key)
        unit = fmt_unit(key)
        if unit:
            lines.append(f"- {name}: {val}{unit}")
        else:
            lines.append(f"- {name}: {val}")

    lines.append("出典: 気象庁アメダス（速報値）")
    msg = "\n".join(lines)

    # Send
    notify_slack(msg)
    notify_line(msg)

if __name__ == "__main__":
    main()
