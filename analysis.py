"""Multi-method stock analysis (pure Python, no numpy).
Methods: price action, simplified Elliott, data mining (kNN on own history),
money zones (volume profile at support/resistance).
All on split/dividend adjusted OHLCV.
"""
import math

METHODS = ["pa", "elliott", "mining", "money"]
NAMES = {"pa": "پرایس اکشن", "elliott": "الیوت", "mining": "داده‌کاوی", "money": "توده پول"}


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def adjusted_ohlcv(rows):
    """rows: TSETMC daily list (any order). Prices converted rial->toman. Returns oldest-first dict of lists."""
    rows = [r for r in rows if _f(r.get("pClosing")) > 0 and _f(r.get("qTotTran5J")) > 0
            and _f(r.get("priceMax")) > 0 and _f(r.get("priceMin")) > 0]
    rows.sort(key=lambda r: r.get("dEven", 0))
    n = len(rows)
    mult = [1.0] * n
    m = 1.0
    for i in range(n - 1, 0, -1):
        prev_close = _f(rows[i - 1]["pClosing"])
        ref = _f(rows[i].get("priceYesterday"))
        if prev_close > 0 and ref > 0:
            m *= ref / prev_close
        mult[i - 1] = m
    return {
        "day": [r["dEven"] for r in rows],
        "o": [_f(r.get("priceFirst")) * mult[i] / 10 for i, r in enumerate(rows)],
        "h": [_f(r["priceMax"]) * mult[i] / 10 for i, r in enumerate(rows)],
        "l": [_f(r["priceMin"]) * mult[i] / 10 for i, r in enumerate(rows)],
        "c": [_f(r["pClosing"]) * mult[i] / 10 for i, r in enumerate(rows)],
        "v": [_f(r["qTotTran5J"]) for r in rows],
    }


def zigzag(c, pct=0.07):
    """Pivots [(index, price, 'H'|'L')] on closes; last one is the running extreme."""
    if len(c) < 5:
        return []
    piv = []
    hi_i = lo_i = 0
    direction = 0
    for i in range(1, len(c)):
        if c[i] > c[hi_i]:
            hi_i = i
        if c[i] < c[lo_i]:
            lo_i = i
        if direction >= 0 and c[i] <= c[hi_i] * (1 - pct) and hi_i > lo_i - 0:
            if direction == 0 and lo_i < hi_i:
                piv.append((lo_i, c[lo_i], "L"))
            piv.append((hi_i, c[hi_i], "H"))
            direction = -1
            lo_i = i
        elif direction <= 0 and c[i] >= c[lo_i] * (1 + pct):
            if direction == 0 and hi_i < lo_i:
                piv.append((hi_i, c[hi_i], "H"))
            piv.append((lo_i, c[lo_i], "L"))
            direction = 1
            hi_i = i
    if direction == 1:
        piv.append((hi_i, c[hi_i], "H"))
    elif direction == -1:
        piv.append((lo_i, c[lo_i], "L"))
    return piv


# ---------------------------------------------------------------- volume profile
def volume_profile(d, lookback=120, bins=40):
    n = len(d["c"])
    lo_i = max(0, n - lookback)
    lo = min(d["l"][lo_i:])
    hi = max(d["h"][lo_i:])
    if hi <= lo:
        return []
    step = (hi - lo) / bins
    vol = [0.0] * bins
    for i in range(lo_i, n):
        tp = (d["h"][i] + d["l"][i] + d["c"][i]) / 3.0
        b = min(bins - 1, int((tp - lo) / step))
        vol[b] += d["v"][i]
    nz = [x for x in vol if x > 0]
    if not nz:
        return []
    mean = sum(nz) / len(nz)
    nodes = []
    for b in range(bins):
        left = vol[b - 1] if b > 0 else 0
        right = vol[b + 1] if b < bins - 1 else 0
        if vol[b] >= 1.6 * mean and vol[b] >= left and vol[b] >= right:
            nodes.append({"lo": lo + b * step, "hi": lo + (b + 1) * step,
                          "mid": lo + (b + 0.5) * step, "rel": vol[b] / mean})
    return nodes


# ---------------------------------------------------------------- price action
def _candle(d, i):
    o, h, l, c = d["o"][i], d["h"][i], d["l"][i], d["c"][i]
    rng = max(h - l, 1e-9)
    body = abs(c - o)
    return o, h, l, c, rng, body


def price_action(d, support_levels):
    n = len(d["c"])
    if n < 30:
        return None
    price = d["c"][-1]
    near = None
    for s in support_levels:
        if s <= price * 1.01 and (price - s) / price <= 0.04:
            near = s
            break
    # last candle too low-volume or no real range -> ignore
    o, h, l, c, rng, body = _candle(d, n - 1)
    po, ph, pl, pc, prng, pbody = _candle(d, n - 2)
    pats = []
    lower = min(o, c) - l
    upper = h - max(o, c)
    if lower >= 2 * max(body, rng * 0.05) and upper <= rng * 0.25 and (c - l) / rng >= 0.6:
        pats.append("چکش/پین‌بار صعودی")
    if pc < po and c > o and c >= po and o <= pc and body > pbody:
        pats.append("engulfing صعودی")
    if n >= 4:
        o2, h2, l2, c2, r2, b2 = _candle(d, n - 3)
        if c2 < o2 and pbody < b2 * 0.5 and c > o and c > (o2 + c2) / 2:
            pats.append("ستاره صبحگاهی")
    if ph < d["h"][-3] and pl > d["l"][-3] and c > d["h"][-3] and False:
        pass
    # inside bar breakout
    if n >= 3 and d["h"][-2] <= d["h"][-3] and d["l"][-2] >= d["l"][-3] and c > d["h"][-3]:
        pats.append("شکست اینساید‌بار")
    # structure: higher low over last pivots
    piv = zigzag(d["c"], 0.05)
    lows = [p for p in piv if p[2] == "L"]
    hl = len(lows) >= 2 and lows[-1][1] > lows[-2][1]
    vol_ok = d["v"][-1] >= 0.8 * (sum(d["v"][-21:-1]) / 20.0)
    ok = bool(pats) and (near is not None or hl) and vol_ok and c >= o
    if not ok:
        return None
    return {"patterns": pats, "support": near, "higher_low": hl,
            "text": "، ".join(pats) + (" روی حمایت" if near else "") + (" + کف بالاتر" if hl else "")}


# ---------------------------------------------------------------- Elliott (simplified)
def elliott(d):
    c = d["c"]
    if len(c) < 60:
        return None
    price = c[-1]
    piv = zigzag(c, 0.08)
    if len(piv) < 3:
        return None
    # need the last pivot to be a low and price rising off it
    last = piv[-1]
    if last[2] != "L":
        return None
    if price < last[1] * 1.0 or (price / last[1] - 1) > 0.12:
        return None
    # --- end of wave 4 -> wave 5
    if len(piv) >= 5:
        L0, H1, L2, H3, L4 = piv[-5:]
        if (L0[2], H1[2], L2[2], H3[2], L4[2]) == ("L", "H", "L", "H", "L"):
            w1, w3 = H1[1] - L0[1], H3[1] - L2[1]
            ret4 = (H3[1] - L4[1]) / w3 if w3 > 0 else 9
            ret2 = (H1[1] - L2[1]) / w1 if w1 > 0 else 9
            if (L2[1] > L0[1] and H3[1] > H1[1] and L4[1] > H1[1] and w3 >= w1
                    and 0.2 <= ret4 <= 0.55 and ret2 <= 0.8):
                target = L4[1] + w1
                return {"stage": "پایان موج ۴ ← آغاز موج ۵", "stop": L4[1], "target": target,
                        "text": f"موج ۴ تمام شده؛ هدف موج ۵ ≈ {target:,.0f}"}
    # --- end of wave 2 -> wave 3
    if len(piv) >= 3:
        L0, H1, L2 = piv[-3:]
        if (L0[2], H1[2], L2[2]) == ("L", "H", "L"):
            w1 = H1[1] - L0[1]
            ret2 = (H1[1] - L2[1]) / w1 if w1 > 0 else 9
            if L2[1] > L0[1] and 0.382 <= ret2 <= 0.786 and w1 / L0[1] >= 0.15:
                target = L2[1] + 1.618 * w1
                return {"stage": "پایان موج ۲ ← آغاز موج ۳", "stop": L2[1], "target": target,
                        "text": f"اصلاح ۲ تمام شده ({ret2 * 100:.0f}٪)؛ هدف موج ۳ ≈ {target:,.0f}"}
    return None


# ---------------------------------------------------------------- data mining
def _features(d, i):
    c, v = d["c"], d["v"]
    if i < 60:
        return None
    ret5 = c[i] / c[i - 5] - 1
    ret20 = c[i] / c[i - 20] - 1
    ma20 = sum(c[i - 19:i + 1]) / 20.0
    dist = c[i] / ma20 - 1
    gains = losses = 0.0
    for k in range(i - 13, i + 1):
        ch = c[k] - c[k - 1]
        if ch > 0:
            gains += ch
        else:
            losses -= ch
    rsi = 100.0 if losses == 0 else 100 - 100 / (1 + gains / losses)
    av = sum(v[i - 20:i]) / 20.0
    vr = min(v[i] / av, 5.0) if av > 0 else 1.0
    rng = max(c[i - 59:i + 1]) - min(c[i - 59:i + 1])
    pos = (c[i] - min(c[i - 59:i + 1])) / rng if rng > 0 else 0.5
    return [ret5, ret20, dist, rsi / 100.0, vr, pos]


def mining(d, horizon=10, k=15):
    n = len(d["c"])
    if n < 160:
        return None
    feats = {}
    for i in range(60, n):
        f = _features(d, i)
        if f:
            feats[i] = f
    cur = feats.get(n - 1)
    hist = [i for i in feats if i + horizon < n - 1]
    if cur is None or len(hist) < 60:
        return None
    dims = len(cur)
    mu = [sum(feats[i][j] for i in hist) / len(hist) for j in range(dims)]
    sd = [math.sqrt(sum((feats[i][j] - mu[j]) ** 2 for i in hist) / len(hist)) or 1.0
          for j in range(dims)]
    dist = []
    for i in hist:
        s = 0.0
        for j in range(dims):
            s += ((feats[i][j] - cur[j]) / sd[j]) ** 2
        dist.append((s, i))
    dist.sort()
    nb = [i for _, i in dist[:k]]
    fw = sorted(d["c"][i + horizon] / d["c"][i] - 1 for i in nb)
    win = sum(1 for x in fw if x > 0) / len(fw)
    med = fw[len(fw) // 2]
    # base rate for context
    allf = [d["c"][i + horizon] / d["c"][i] - 1 for i in hist]
    base_win = sum(1 for x in allf if x > 0) / len(allf)
    ok = win >= 0.67 and med >= 0.03 and win >= base_win + 0.10
    if not ok:
        return None
    return {"win": win, "median": med, "base_win": base_win, "k": len(fw), "horizon": horizon,
            "text": f"در {len(fw)} حالت مشابه گذشته‌ی همین سهم، {win * 100:.0f}٪ بار بعد از "
                    f"{horizon} روز مثبت بوده (میانه {med * 100:+.1f}٪؛ نرخ پایه {base_win * 100:.0f}٪)"}


# ---------------------------------------------------------------- money zones
def money_zone(d, nodes, power=None):
    price = d["c"][-1]
    sup = [x for x in nodes if x["lo"] <= price]
    res = [x for x in nodes if x["lo"] > price]
    best = None
    for x in sorted(sup, key=lambda x: -x["mid"]):
        gap = (price - x["hi"]) / price
        touched = min(d["l"][-3:]) <= x["hi"] * 1.01
        if -0.01 <= gap <= 0.05 and (touched or gap <= 0.03):
            best = x
            break
    if not best:
        return None
    nr = min(res, key=lambda x: x["lo"]) if res else None
    room = (nr["lo"] / price - 1) if nr else None
    if room is not None and room < 0.03:
        return None  # مقاومت سنگین بلافاصله بالای سر
    strong = power is not None and power >= 1.3
    txt = f"توده حجمی ({best['rel']:.1f} برابر میانگین) در {best['mid']:,.0f} حمایت است"
    if room is not None:
        txt += f"؛ مقاومت بعدی {room * 100:.0f}٪ بالاتر"
    if strong:
        txt += f"؛ قدرت خریدار حقیقی {power:.2f}"
    return {"support_mid": best["mid"], "rel": best["rel"], "room": room, "strong": strong,
            "text": txt}


# ---------------------------------------------------------------- combine
def analyze_stock(d, power=None, skip=()):
    """d: adjusted ohlcv. Returns dict method->result (only methods that fired)."""
    if not d or len(d["c"]) < 60:
        return {}
    nodes = volume_profile(d)
    piv = zigzag(d["c"], 0.05)
    levels = sorted([p[1] for p in piv if p[2] == "L"] + [x["mid"] for x in nodes], reverse=True)
    out = {}
    for name, fn in (("pa", lambda: price_action(d, levels)),
                     ("elliott", lambda: elliott(d)),
                     ("mining", lambda: mining(d)),
                     ("money", lambda: money_zone(d, nodes, power))):
        if name in skip:
            continue
        try:
            r = fn()
        except Exception:
            r = None
        if r:
            out[name] = r
    return out


# ---------------------------------------------------------------- full report (manual symbol / global)
def full_report(d, power=None):
    """گزارش کامل برای نمایش دستی: روش‌ها + سطوح + روند. فقط توضیح است، نه توصیه."""
    if not d or len(d["c"]) < 60:
        return {"lines": ["داده کافی نیست (کمتر از ۶۰ روز)"], "levels": [], "methods": {}}
    c = d["c"]
    price = c[-1]
    nodes = volume_profile(d)
    res = analyze_stock(d, power)
    lines = []

    def ma(n):
        return sum(c[-n:]) / n if len(c) >= n else None
    m50, m200 = ma(50), ma(200)
    if m50:
        lines.append(f"قیمت {'بالای' if price > m50 else 'زیر'} میانگین ۵۰ روزه ({m50:,.2f})")
    if m200:
        lines.append(f"قیمت {'بالای' if price > m200 else 'زیر'} میانگین ۲۰۰ روزه ({m200:,.2f})")
    hi = max(d["h"][-250:])
    lo = min(d["l"][-250:])
    lines.append(f"سقف یک‌ساله {hi:,.2f} ({(price / hi - 1) * 100:+.1f}٪) | کف یک‌ساله {lo:,.2f} ({(price / lo - 1) * 100:+.1f}٪)")
    names = {"pa": "پرایس اکشن", "elliott": "الیوت (آزمایشی، در بک‌تست ضعیف بود)",
             "mining": "داده‌کاوی", "money": "توده پول"}
    for k in ("pa", "money", "mining", "elliott"):
        if k in res:
            lines.append(f"{names[k]}: {res[k].get('text', '')}")
    if not res:
        lines.append("هیچ‌کدام از روش‌ها الان سیگنال نمی‌دهند")
    levels = []
    for x in nodes:
        levels.append((x["mid"], "res" if x["mid"] > price else "sup"))
    return {"lines": lines, "levels": levels, "methods": res}
