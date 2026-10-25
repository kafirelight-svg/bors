# -*- coding: utf-8 -*-
"""ذخیره‌ی تاریخچه ۱۰ ساله در SQLite و تحلیل بر پایه آن (بدون Qt/Kivy)."""
import os, re, sqlite3, datetime, statistics
import requests

H = {"User-Agent": "Mozilla/5.0", "Referer": "https://tsetmc.com/"}
YEARS = 10
TGJU = "https://api.tgju.org/v1/market/indicator/summary-table-data/{}"
TSE_IDX = "https://cdn.tsetmc.com/api/Index/GetIndexB2History/{}"
YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/{}?range=10y&interval=1d"
# سری‌ها: usd_toman, gold18_toman, sekee_toman, tse_total, tse_equal, gold_ounce, btc_usd, fng
SERIES = ["usd_toman", "gold18_toman", "sekee_toman", "tse_total", "tse_equal",
          "gold_ounce", "btc_usd", "fng"]


def db_path(base_dir):
    os.makedirs(base_dir, exist_ok=True)
    return os.path.join(base_dir, "history.db")


def connect(base_dir):
    c = sqlite3.connect(db_path(base_dir))
    c.execute("CREATE TABLE IF NOT EXISTS daily(series TEXT, day TEXT, value REAL, "
              "PRIMARY KEY(series, day))")
    c.execute("CREATE TABLE IF NOT EXISTS snap(ts TEXT PRIMARY KEY, data TEXT)")
    return c


def _put(conn, series, rows):
    conn.executemany("INSERT OR REPLACE INTO daily VALUES(?,?,?)",
                     [(series, d, float(v)) for d, v in rows if v and v > 0])
    conn.commit()
    return len(rows)


def _cutoff():
    return (datetime.date.today() - datetime.timedelta(days=365 * YEARS + 5)).isoformat()


def _tgju(name, divisor):
    r = requests.get(TGJU.format(name), headers=H, timeout=40)
    out = []
    for row in r.json()["data"]:
        try:
            day = row[6].replace("/", "-")
            v = float(row[3].replace(",", "")) / divisor
            if day >= _cutoff():
                out.append((day, v))
        except Exception:
            pass
    return out


def _tse(code):
    r = requests.get(TSE_IDX.format(code), headers=H, timeout=40)
    out = []
    for x in r.json().get("indexB2", []):
        s = str(x.get("dEven"))
        day = f"{s[:4]}-{s[4:6]}-{s[6:]}"
        if day >= _cutoff():
            out.append((day, x.get("xNivInuClMresIbs")))
    return out


def _yahoo(sym):
    r = requests.get(YAHOO.format(sym), headers=H, timeout=40)
    res = r.json()["chart"]["result"][0]
    ts, cl = res["timestamp"], res["indicators"]["quote"][0]["close"]
    return [(datetime.datetime.utcfromtimestamp(t).strftime("%Y-%m-%d"), c)
            for t, c in zip(ts, cl) if c]


def _fng():
    r = requests.get("https://api.alternative.me/fng/?limit=0", timeout=40)
    return [(datetime.datetime.utcfromtimestamp(int(x["timestamp"])).strftime("%Y-%m-%d"),
             float(x["value"])) for x in r.json()["data"]]


def download_all(base_dir, progress=None):
    """دانلود/به‌روزرسانی تمام سری‌ها. خروجی: دیکشنری تعداد ردیف یا پیام خطا."""
    jobs = [("usd_toman", lambda: _tgju("price_dollar_rl", 10)),
            ("gold18_toman", lambda: _tgju("geram18", 10)),
            ("sekee_toman", lambda: _tgju("sekee", 10)),
            ("tse_total", lambda: _tse("32097828799138957")),
            ("tse_equal", lambda: _tse("67130298613737946")),
            ("gold_ounce", lambda: _yahoo("GC=F")),
            ("btc_usd", lambda: _yahoo("BTC-USD")),
            ("fng", _fng)]
    conn = connect(base_dir)
    report = {}
    for i, (name, fn) in enumerate(jobs):
        try:
            report[name] = _put(conn, name, fn())
        except Exception as e:
            report[name] = f"خطا: {str(e)[:60]}"
        if progress:
            progress(i + 1, len(jobs))
    conn.close()
    return report


def save_snapshot(base_dir, d):
    """ذخیره‌ی داده‌ی زنده‌ی امروز (هر بار که به‌روزرسانی می‌شود)."""
    import json
    conn = connect(base_dir)
    today = datetime.date.today().isoformat()
    conn.execute("INSERT OR REPLACE INTO snap VALUES(?,?)",
                 (datetime.datetime.now().isoformat(timespec="seconds"),
                  json.dumps(d, ensure_ascii=False, default=str)))
    for key, ser in (("usdt_toman", "usd_toman"), ("gold_ounce", "gold_ounce")):
        v = d.get(key)
        if v and v > 0 and ser != "usd_toman":
            conn.execute("INSERT OR REPLACE INTO daily VALUES(?,?,?)", (ser, today, v))
    if d.get("m2_auto"):
        conn.execute("INSERT OR REPLACE INTO daily VALUES(?,?,?)", ("m2_hemat", today, d["m2_auto"]))
    conn.commit(); conn.close()


def load(base_dir, series):
    conn = connect(base_dir)
    rows = conn.execute("SELECT day,value FROM daily WHERE series=? ORDER BY day", (series,)).fetchall()
    conn.close()
    return rows


def count_rows(base_dir):
    conn = connect(base_dir)
    n = conn.execute("SELECT COUNT(*) FROM daily").fetchone()[0]
    conn.close()
    return n


def _pct_rank(values, x):
    if not values:
        return None
    return 100.0 * sum(1 for v in values if v <= x) / len(values)


def analyze(base_dir):
    """تحلیل تاریخی: شاخص کل به دلار (آزاد) نسبت به ۱۰ سال گذشته و ..."""
    out = {"ok": False}
    usd = dict(load(base_dir, "usd_toman"))
    idx = load(base_dir, "tse_total")
    if len(usd) < 100 or len(idx) < 100:
        out["msg"] = "تاریخچه کافی نیست؛ اول «دانلود تاریخچه» را بزنید."
        return out
    # شاخص به دلار: برای روزهایی که نرخ دلار نیست، آخرین نرخ قبلی
    usd_days = sorted(usd)
    ratio, j, last = [], 0, None
    for day, v in idx:
        while j < len(usd_days) and usd_days[j] <= day:
            last = usd[usd_days[j]]; j += 1
        if last:
            ratio.append((day, v / last * 1000.0))   # شاخص به ازای هر ۱۰۰۰ تومان
    vals = [r for _, r in ratio]
    cur = vals[-1]
    out.update(ok=True, last_day=ratio[-1][0], n_days=len(vals),
               idx_usd_now=cur, idx_usd_median=statistics.median(vals),
               idx_usd_min=min(vals), idx_usd_max=max(vals),
               idx_usd_pct=_pct_rank(vals, cur),
               idx_usd_dev=(cur / statistics.median(vals) - 1) * 100)
    # قیمت ۱۰ سال پیش تا حالا: رشد سالانه ترکیبی
    def cagr(rows):
        if len(rows) < 200:
            return None
        d0 = datetime.date.fromisoformat(rows[0][0]); d1 = datetime.date.fromisoformat(rows[-1][0])
        yrs = max((d1 - d0).days / 365.25, 0.1)
        return ((rows[-1][1] / rows[0][1]) ** (1 / yrs) - 1) * 100
    out["cagr"] = {n: cagr(load(base_dir, n)) for n in
                   ("usd_toman", "gold18_toman", "sekee_toman", "tse_total", "tse_equal")}
    # بیشینه افت شاخص کل
    peak, mdd = 0, 0
    for _, v in idx:
        peak = max(peak, v); mdd = min(mdd, v / peak - 1)
    out["tse_max_dd"] = mdd * 100
    out["tse_from_peak"] = (idx[-1][1] / peak - 1) * 100
    # شاخص منصفانه بر پایه میانه تاریخی نسبت به دلار
    last_usd = usd[usd_days[-1]]
    out["tse_fair_hist"] = statistics.median(vals) * last_usd / 1000.0
    out["tse_now"] = idx[-1][1]
    # طلا به دلار: میانه نسبت طلای ۱۸ تومانی به (اونس × دلار)
    g = dict(load(base_dir, "gold18_toman")); o = dict(load(base_dir, "gold_ounce"))
    pr = []
    for day in sorted(g):
        if day in o and day in usd and o[day] > 0:
            pr.append(g[day] / (o[day] * usd[day] * 0.75 / 31.1035))
    if len(pr) > 100:
        out["gold_premium_now"] = (pr[-1] - 1) * 100
        out["gold_premium_median"] = (statistics.median(pr) - 1) * 100
    return out


def seed(base_dir, app_dir):
    """اولین اجرا: تاریخچه‌ی همراه برنامه را کپی می‌کند تا دانلود لازم نباشد."""
    import shutil
    dst = db_path(base_dir)
    src = os.path.join(app_dir, "data", "history.db")
    try:
        if os.path.exists(src):
            n = 0
            if os.path.exists(dst):
                c = sqlite3.connect(dst)
                try:
                    n = c.execute("SELECT COUNT(*) FROM daily").fetchone()[0]
                except Exception:
                    n = 0
                c.close()
            if n < 1000:
                shutil.copyfile(src, dst)
    except Exception:
        pass


def _before(rows, day):
    """آخرین مقدار در تاریخ day یا قبل از آن -> (day, value) یا None."""
    best = None
    for dd, v in rows:
        if dd <= day:
            best = (dd, v)
        else:
            break
    return best


def compare(base_dir, liq=None, infl=None):
    """مقایسه نقطه‌به‌نقطه‌ی دلار و شاخص کل با نقدینگی و تورم (ورودی دستی، درصد). مقدار نامعلوم = None."""
    import datetime as dt
    out = {}
    try:
        usd, idx = load(base_dir, "usd_toman"), load(base_dir, "tse_total")
        if not usd or not idx:
            return out
        day = min(usd[-1][0], idx[-1][0])
        t = dt.date.fromisoformat(day)
        try:
            ly = t.replace(year=t.year - 1)
        except ValueError:
            ly = t.replace(year=t.year - 1, day=28)
        ys = dt.date(t.year if (t.month, t.day) >= (3, 21) else t.year - 1, 3, 21)  # ۱ فروردین (تقریبی)
        out["day"], out["ly_day"] = day, ly.isoformat()
        for name, rows in (("usd", usd), ("idx", idx)):
            now = _before(rows, day)
            a = _before(rows, ly.isoformat())
            s = _before(rows, (ys - dt.timedelta(days=1)).isoformat())
            out[name + "_now"] = now[1]
            if a:
                out[name + "_ly"] = a[1]
                out[name + "_yoy"] = (now[1] / a[1] - 1) * 100
            if s:
                out[name + "_ys"] = s[1]
                out[name + "_ytd"] = (now[1] / s[1] - 1) * 100
        for key, g in (("liq", liq), ("infl", infl)):
            if g is not None and "usd_ly" in out:
                eq = out["usd_ly"] * (1 + g / 100)
                out[key + "_eq"] = eq
                out[key + "_gap"] = (out["usd_now"] / eq - 1) * 100  # مثبت = حباب، منفی = عقب‌ماندگی
    except Exception:
        pass
    return out
