"""داده‌ی جهانی از Yahoo Finance (روزانه، بدون تعدیل لازم)."""
import time

GLOBAL = [
    ("GC=F", "انس طلا"),
    ("SI=F", "انس نقره"),
    ("HG=F", "مس"),
    ("ALI=F", "آلومینیوم"),
]
URL = "https://query1.finance.yahoo.com/v8/finance/chart/{}?period1={}&period2={}&interval=1d"


def fetch_yahoo(session, sym, years=20):
    p2 = int(time.time())
    p1 = p2 - years * 366 * 86400
    r = session.get(URL.format(sym, max(p1, 0), p2), headers={"User-Agent": "Mozilla/5.0"}, timeout=25)
    r.raise_for_status()
    j = r.json()["chart"]["result"][0]
    q = j["indicators"]["quote"][0]
    d = {"day": [], "o": [], "h": [], "l": [], "c": [], "v": []}
    for i, t in enumerate(j["timestamp"]):
        o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
        if None in (o, h, l, c) or c <= 0:
            continue
        d["day"].append(int(time.strftime("%Y%m%d", time.gmtime(t))))
        d["o"].append(float(o)); d["h"].append(float(h)); d["l"].append(float(l)); d["c"].append(float(c))
        d["v"].append(float(q["volume"][i] or 0))
    return d
