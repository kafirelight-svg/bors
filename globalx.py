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


def key_levels(d, k=5, lookback=250, recent=60, n=3):
    """سه مقاومت و سه حمایت ساده از قله/دره‌های روزانه.
    هر سطح: قیمت، تاریخ، بازه (۳ ماهه یا ۱ ساله). فقط توضیح است، نه توصیه."""
    if not d or len(d["c"]) < 2 * k + 2:
        return {"price": None, "res": [], "sup": []}
    H, L, C, D = d["h"], d["l"], d["c"], d["day"]
    price = C[-1]
    n_all = len(C)
    start = max(k, n_all - lookback)
    highs, lows = [], []
    for i in range(start, n_all - k):
        if H[i] == max(H[i - k:i + k + 1]):
            highs.append((H[i], i))
        if L[i] == min(L[i - k:i + k + 1]):
            lows.append((L[i], i))

    def label(i):
        age = n_all - 1 - i
        return ("۳ ماهه" if age <= recent else "۱ ساله"), D[i]

    def pick(cands, above):
        # حذف سطوح نزدیک به هم (کمتر از ۱٪)
        cands = sorted(cands, key=lambda x: abs(x[0] - price))
        out = []
        for p, i in cands:
            if above and p <= price or (not above and p >= price):
                continue
            if any(abs(p - q["price"]) / price < 0.01 for q in out):
                continue
            tf, day = label(i)
            out.append({"price": p, "tf": tf, "day": day})
            if len(out) == n:
                break
        return out

    return {"price": price, "day": D[-1], "res": pick(highs, True), "sup": pick(lows, False)}
