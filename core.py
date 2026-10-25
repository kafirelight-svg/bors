"""منطق شبکه و محاسبات (بدون وابستگی به Qt)."""
import math, re
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

# ---------------- ثابت‌ها و سرآیندها ----------------

API_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Referer": "https://tsetmc.com/",
    "Accept": "application/json, text/plain, */*",
}

URL_TETHERLAND = "https://api.tetherland.com/currencies"
URL_WALLEX = "https://api.wallex.ir/v1/markets"
URL_GOLD = "https://data-asg.goldprice.org/dbXRates/USD"
URL_GOLD_CG = "https://api.coingecko.com/api/v3/simple/price?ids=pax-gold&vs_currencies=usd"
URL_CG_GLOBAL = "https://api.coingecko.com/api/v3/global"
URL_FNG = "https://api.alternative.me/fng/?limit=1"
URL_ICE = "https://www.ice.ir/"
URL_TSE_OVERVIEW = "https://cdn.tsetmc.com/api/MarketData/GetMarketOverview/{}"
URL_MARKET_WATCH_PE = ("https://cdn.tsetmc.com/api/ClosingPrice/GetMarketWatch"
                       "?market=0&paperTypes[0]=1")
URL_MARKET_WATCH_PLUS = [
    "https://old.tsetmc.com/tsev2/data/MarketWatchPlus.aspx",
    "https://main.tsetmc.com/tsev2/data/MarketWatchPlus.aspx",
]
URL_DAILY = "https://cdn.tsetmc.com/api/ClosingPrice/GetClosingPriceDailyList/{}/{}"
URL_TGJU = "https://api.tgju.org/v1/market/indicator/summary-table-data/{}"
URL_CLIENT_TYPE = "https://cdn.tsetmc.com/api/ClientType/GetClientType/{}/1/0"

HEMAT_RIAL = 10_000_000_000_000  # ۱۰^۱۳ ریال
ATH_MARKET_CAP_USD_BILLION = 425.0
ATH_MARKET_CAP_HEMAT = 27_500.0

# ثابت‌های سنجهٔ جاماندگی بازار نسبت به دلار
BASE_MARKET_CAP = 6700.0
BASE_USD = 26200.0

# ---------- ثوابت محاسبات تعادل ----------
USD_OFFICIAL_WEIGHT = 0.70        # نرخ مرکز مبادله/رسمی: ۷۰٪؛ بازار آزاد: ۳۰٪
M2_JUMP_GUARD_MIN = 0.85          # کران محافظ جهش ناشی از M2، نه مدل پیش‌بینی
M2_JUMP_GUARD_MAX = 1.15
M2_JUMP_GUARD_NEUTRAL = 1.0
EMAMI_GOLD_GRAMS = 8.133          # وزن سکه امامی (گرم)
EMAMI_FINENESS = 0.900            # عیار سکه امامی
EMAMI_OFFICIAL_MINT_PREMIUM_TOMAN = 50_000.0  # حق ضرب رسمی تقریبی؛ جدا از حباب بازار
TEDPIX_FAIR_CAP_LOW_BUSD = 110.0
TEDPIX_FAIR_CAP_HIGH_BUSD = 130.0
TEDPIX_FAIR_INDEX_LOW = 2_800_000.0
TEDPIX_FAIR_INDEX_HIGH = 3_200_000.0

MAX_CLIENT_WORKERS = 12
DEFAULT_TIMEOUT = 8



def make_session():
    s = requests.Session()
    s.headers.update(API_HEADERS)
    return s


def to_float(val, default=0.0):
    try:
        return float(str(val).replace(",", "").strip())
    except (TypeError, ValueError):
        return default


def parse_tedpix(text):
    """استخراج عدد شاخص کل از رشته‌هایی مثل '2,850,000 (+12,000)' -> 2850000.0"""
    if not text:
        return 0.0
    s = str(text).split("(")[0]
    s = s.replace(",", "").replace("،", "").strip()
    try:
        return float(s)
    except (TypeError, ValueError):
        return 0.0


def estimate_iran_gold_quotes(d, usdt_toman=None, ounce=None):
    """Populate the display-only 18k spot quote when no local quote exists.

    Emami market price is never synthesized here: without a valid live quote,
    its equilibrium card must show intrinsic value only and no market bubble.
    """
    d = d if isinstance(d, dict) else {}
    fx = to_float(usdt_toman) or to_float(d.get("usdt_toman"))
    xau = to_float(ounce) or to_float(d.get("gold_ounce"))
    gold18 = to_float(d.get("gold18_market_toman")) or to_float(d.get("gold_18k_toman"))
    if gold18 <= 0 and fx > 0 and xau > 0:
        gold18 = xau * fx * 0.750 / 31.1035
        d["gold18_market_source"] = "estimated_spot_melt"
    d["gold18_market_toman"] = gold18 if gold18 > 0 else 0.0
    d["gold_18k_toman"] = gold18 if gold18 > 0 else 0.0
    # Keep only an independently supplied, valid live coin quote.
    emami = to_float(d.get("emami_market_toman"))
    d["emami_market_toman"] = emami if emami > 0 else 0.0
    return d


def compute_triple_equilibrium(d, params):
    """Compute fair USD, 18k gold, Emami and TEDPIX; monetary values are toman."""
    d = d if isinstance(d, dict) else {}
    params = params if isinstance(params, dict) else {}
    res = {"usd_fair": None, "usd_gap": None, "gold18_fair": None,
           "gold18_bubble": None, "emami_fair": None, "emami_live": None,
           "emami_bubble": None, "emami_state": "ارزش ذاتی خالص؛ قیمت زنده موجود نیست",
           "tedpix_fair": None, "tedpix_gap": None, "effective_usd": None,
           "m2_jump_guard": M2_JUMP_GUARD_NEUTRAL, "signal": "داده ناکافی"}

    def positive(*values):
        for value in values:
            number = to_float(value)
            if number > 0 and math.isfinite(number):
                return number
        return 0.0

    free_fx = positive(params.get("free_market_toman"), params.get("usdt_toman"),
                       d.get("free_market_toman"), d.get("usdt_toman"))
    official_fx = positive(params.get("official_fx_toman"), params.get("center_exchange_toman"),
                           params.get("nima_toman"), d.get("official_fx_toman"),
                           d.get("center_exchange_toman"), d.get("nima_toman"))
    ounce = positive(params.get("gold_ounce"), d.get("gold_ounce"))
    current_index = parse_tedpix(params.get("index_total") or d.get("index_total"))
    effective_usd = 0.0
    weight = to_float(params.get("usd_official_weight"))
    if not (0.0 < weight < 1.0) or not math.isfinite(weight):
        weight = USD_OFFICIAL_WEIGHT
    if official_fx > 0 and free_fx > 0:
        effective_usd = weight * official_fx + (1.0 - weight) * free_fx
    else:
        # If either rate is invalid, fall back to whichever valid rate exists.
        effective_usd = official_fx or free_fx

    if effective_usd > 0:
        # Optional M2 jump guard: ratio is capped narrowly and is never a forecast.
        m2_now = positive(params.get("m2_current"), d.get("m2_current"))
        m2_base = positive(params.get("m2_base"), d.get("m2_base"))
        if m2_now and m2_base:
            guard = min(max(m2_now / m2_base, M2_JUMP_GUARD_MIN + 1e-9), M2_JUMP_GUARD_MAX - 1e-9)
        else:
            guard = M2_JUMP_GUARD_NEUTRAL
        usd_fair = effective_usd * guard
        if math.isfinite(usd_fair) and usd_fair > 0:
            res.update({"effective_usd": effective_usd, "usd_fair": usd_fair,
                        "effective_usd_toman": effective_usd, "m2_jump_guard": guard})
            if free_fx > 0:
                res["usd_gap"] = (free_fx / usd_fair - 1.0) * 100.0

    usd_fair = res["usd_fair"]
    if ounce > 0 and usd_fair and usd_fair > 0:
        gold18_fair = ounce * usd_fair * 0.750 / 31.1035
        if math.isfinite(gold18_fair) and gold18_fair > 0:
            res["gold18_fair"] = gold18_fair
            quote_data = dict(d)
            for key in ("gold18_market_toman", "emami_market_toman"):
                candidate = positive(params.get(key))
                if candidate:
                    quote_data[key] = candidate
            # Only pass actual available live quotes; coin quote is never estimated.
            estimate_iran_gold_quotes(quote_data, None, None)
            gold_market = positive(quote_data.get("gold18_market_toman"))
            if gold_market:
                res["gold18_bubble"] = (gold_market - gold18_fair) / gold18_fair * 100.0
            pure_gold_grams = EMAMI_GOLD_GRAMS * EMAMI_FINENESS
            emami_fair = (ounce * usd_fair * pure_gold_grams / 31.1035
                          + EMAMI_OFFICIAL_MINT_PREMIUM_TOMAN)
            if math.isfinite(emami_fair) and emami_fair > 0:
                res["emami_fair"] = emami_fair
                emami_market = positive(quote_data.get("emami_market_toman"))
                if emami_market:
                    res["emami_live"] = emami_market
                    res["emami_bubble"] = (emami_market - emami_fair) / emami_fair * 100.0
                    res["emami_state"] = "حباب واقعی بر مبنای قیمت زنده"

    # Linear USD market-cap corridor mapping: $110B -> 2.8M, $130B -> 3.2M.
    # Current cap/index remain untouched in the incoming data.
    cap_usd_b = positive(params.get("market_cap_usd_b"), d.get("market_cap_usd_b"))
    if cap_usd_b <= 0:
        cap_toman = positive(params.get("market_cap_toman"), d.get("market_cap_toman"))
        if cap_toman <= 0:
            cap_toman = positive(d.get("current_hemat")) * 1e12
        fx_for_cap = positive(effective_usd, free_fx, official_fx)
        if cap_toman > 0 and fx_for_cap > 0:
            cap_usd_b = cap_toman / fx_for_cap / 1e9
    if cap_usd_b > 0:
        corridor_cap = min(max(cap_usd_b, TEDPIX_FAIR_CAP_LOW_BUSD), TEDPIX_FAIR_CAP_HIGH_BUSD)
        ratio = ((corridor_cap - TEDPIX_FAIR_CAP_LOW_BUSD) /
                 (TEDPIX_FAIR_CAP_HIGH_BUSD - TEDPIX_FAIR_CAP_LOW_BUSD))
        tedpix_fair = TEDPIX_FAIR_INDEX_LOW + ratio * (TEDPIX_FAIR_INDEX_HIGH - TEDPIX_FAIR_INDEX_LOW)
        res["tedpix_fair"] = min(max(tedpix_fair, TEDPIX_FAIR_INDEX_LOW), TEDPIX_FAIR_INDEX_HIGH)
        if current_index > 0:
            res["tedpix_gap"] = (current_index / res["tedpix_fair"] - 1.0) * 100.0

    gaps = [g for g in (res["usd_gap"], res["gold18_bubble"], res["emami_bubble"], res["tedpix_gap"])
            if g is not None and math.isfinite(g)]
    if gaps:
        avg_gap = sum(gaps) / len(gaps)
        if avg_gap <= -15:
            res["signal"] = f"شوک مثبت تعادل (بازار عمیقاً زیر تعادل) | میانگین شکاف: {avg_gap:+.1f}٪"
        elif avg_gap <= -5:
            res["signal"] = f"ارزش بیش از تعادل (فرصت خرید) | میانگین شکاف: {avg_gap:+.1f}٪"
        elif avg_gap < 5:
            res["signal"] = f"نزدیک تعادل کلان | میانگین شکاف: {avg_gap:+.1f}٪"
        elif avg_gap < 15:
            res["signal"] = f"حباب خفیف چنددارایی | میانگین شکاف: {avg_gap:+.1f}٪"
        else:
            res["signal"] = f"حباب سنگین چنددارایی (ریسک اصلاح) | میانگین شکاف: {avg_gap:+.1f}٪"
    return res


def parse_usdt_toman(value):
    """Normalize a USDT quote from Toman or Rial to Toman; reject implausible values."""
    if value is None:
        return 0.0
    text = str(value).translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))
    text = text.replace(",", "").replace("٬", "").strip()
    val = to_float(text)
    if not math.isfinite(val) or val <= 0:
        return 0.0
    # Quotes around 30k-300k are Toman; quotes around 300k-3m are Rial.
    if 30_000 <= val <= 300_000:
        return val
    if 300_000 < val <= 3_000_000:
        return val / 10.0
    return 0.0


def fetch_usdt_toman(session):
    """Try Tetherland -> Nobitex -> Wallex, returning a validated Toman quote.

    Providers can report either Toman or Rial. Each candidate is normalized and
    sanity-checked here, so downstream code never parses or divides it again.
    """
    def first_quote(obj, keys):
        if isinstance(obj, dict):
            for key in keys:
                value = obj.get(key)
                if value not in (None, "", 0, "0"):
                    return value
        return None

    # 1) Tetherland (field naming differs between API versions).
    try:
        response = session.get(URL_TETHERLAND, timeout=DEFAULT_TIMEOUT)
        if response.status_code == 200:
            root = response.json()
            data = root.get("data", {}) if isinstance(root, dict) else {}
            currencies = data.get("currencies", {}) if isinstance(data, dict) else {}
            entry = currencies.get("USDT", {}) if isinstance(currencies, dict) else {}
            raw = first_quote(entry, ("price", "last_price", "sell_price", "buy_price"))
            if raw is None and isinstance(data, dict):
                raw = first_quote(data, ("last_price", "price"))
            if raw is None and isinstance(root, dict):
                raw = first_quote(root.get("USDT", {}), ("price", "last_price"))
            rate = parse_usdt_toman(raw)
            if rate >= 30_000:
                return rate
    except Exception:
        pass

    # 2) Nobitex: market/stats is explicitly requested in Rial (rls).
    try:
        response = session.get(
            "https://api.nobitex.ir/market/stats",
            params={"srcCurrency": "usdt", "dstCurrency": "rls"},
            timeout=DEFAULT_TIMEOUT,
        )
        if response.status_code == 200:
            payload = response.json()
            stats = payload.get("stats", {}) if isinstance(payload, dict) else {}
            pair = stats.get("usdt-rls", {}) if isinstance(stats, dict) else {}
            raw = first_quote(pair, ("latest", "bestSell", "bestBuy", "lastPrice"))
            rate = parse_usdt_toman(raw)
            if rate >= 30_000:
                return rate
    except Exception:
        pass
    # Some Nobitex deployments expose USDT/IRT orderbook prices in Toman.
    try:
        response = session.get("https://api.nobitex.ir/v2/orderbook/USDTIRT",
                              timeout=DEFAULT_TIMEOUT)
        if response.status_code == 200:
            book = response.json()
            raw = first_quote(book, ("lastTradePrice", "last", "price"))
            if raw is None:
                asks = book.get("asks", []) if isinstance(book, dict) else []
                bids = book.get("bids", []) if isinstance(book, dict) else []
                side = asks or bids
                if side:
                    raw = side[0].get("price") if isinstance(side[0], dict) else side[0][0]
            rate = parse_usdt_toman(raw)
            if rate >= 30_000:
                return rate
    except Exception:
        pass

    # 3) Wallex USDTTMN is quoted in Toman (normalizer also tolerates Rial).
    try:
        response = session.get(URL_WALLEX, timeout=DEFAULT_TIMEOUT)
        if response.status_code == 200:
            payload = response.json()
            raw = (payload.get("result", {}).get("symbols", {}).get("USDTTMN", {})
                   .get("stats", {}).get("lastPrice"))
            rate = parse_usdt_toman(raw)
            if rate >= 30_000:
                return rate
    except Exception:
        pass

    # Fail safe rather than propagate a corrupted/low exchange rate.
    return 0.0


def format_hemat(val_hemat):
    if abs(val_hemat) >= 0.01:
        return f"{val_hemat:+.2f} همت"
    return f"{round(val_hemat * 1000, 1):+.1f} م.ت"



def market_lag(d):
    base_m, base_u = BASE_MARKET_CAP, BASE_USD
    cm, cu = to_float(d.get("current_hemat")), to_float(d.get("usdt_toman"))
    if min(base_m, base_u, cm, cu) <= 0:
        return None
    return (1.0 - (cm / base_m) / (cu / base_u)) * 100.0


def _fetch_ice_rate(session):
    """نرخ رسمی ICE (۵۵–۷۰ هزار تومان)؛ در صورت نبود 0 (بدون عدد جعلی)."""
    try:
        r = session.get(URL_ICE, timeout=DEFAULT_TIMEOUT)
        if r.status_code != 200:
            return 0.0
        text = re.sub(r"<[^>]+>", " ", r.text)
        text = text.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))
        number = r"([0-9][0-9,٬٫.]{3,})"
        lab = re.compile(r"(?:دلار|usd|نرخ ارز|نرخ فروش|مرکز مبادله)[^0-9]{0,100}" + number, re.I)
        cands = [m.group(1) for m in lab.finditer(text)] or re.findall(number, text)
        for raw in cands:
            raw = raw.replace(",", "").replace("٬", "").replace("٫", "").replace(".", "")
            if 55_000 <= to_float(raw) <= 70_000:
                return to_float(raw)
    except Exception:
        pass
    return 0.0


def fetch_tgju_latest(session, name):
    """Latest daily row from tgju (rial) -> (toman, jalali_date) or (0, '')."""
    try:
        r = session.get(URL_TGJU.format(name), timeout=10, headers={"Referer": "https://www.tgju.org/"})
        row = r.json()["data"][0]
        return to_float(str(row[3]).replace(",", "")) / 10.0, str(row[7])
    except Exception:
        return 0.0, ""


def fetch_usd_year_end(session=None):
    """Last tgju free-market dollar close of the previous Jalali year -> (toman, date) or (0, '')."""
    try:
        import requests
        s = session or requests.Session()
        r = s.get(URL_TGJU.format("price_dollar_rl"), timeout=15,
                  headers={"Referer": "https://www.tgju.org/", "User-Agent": "Mozilla/5.0"})
        rows = r.json()["data"]
        cur_year = int(str(rows[0][7]).split("/")[0])
        for row in rows:  # newest first
            if int(str(row[7]).split("/")[0]) < cur_year:
                return to_float(str(row[3]).replace(",", "")) / 10.0, str(row[7])
    except Exception:
        pass
    return 0.0, ""


def fetch_yahoo_last(session, sym):
    try:
        r = session.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=5d&interval=1d",
                        timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        return float(r.json()["chart"]["result"][0]["meta"]["regularMarketPrice"])
    except Exception:
        return 0.0


def _tgju_raw(session, name):
    """آخرین ردیف tgju بدون تبدیل واحد -> (عدد خام, تاریخ شمسی)."""
    try:
        r = session.get(URL_TGJU.format(name), timeout=10,
                        headers={"Referer": "https://www.tgju.org/", "User-Agent": "Mozilla/5.0"})
        row = r.json()["data"][0]
        return to_float(str(row[3]).replace(",", "")), str(row[7])
    except Exception:
        return 0.0, ""


EMAMI_PURE_G = 8.133 * 0.900  # گرم طلای خالص سکه‌ی امامی
OZ = 31.1035


def fetch_gold_tab():
    """داده‌ی تب طلا. مقدار نامعلوم = 0 (نمایش «نامشخص»). قیمت‌های ریالی tgju تقسیم بر ۱۰."""
    s = make_session()
    o = {}
    usd, o["date"] = _tgju_raw(s, "price_dollar_rl")
    o["usd"] = usd / 10
    for k, n in (("g24", "geram24"), ("g18", "geram18"), ("s999", "silver_999"), ("emami", "sekee")):
        o[k] = _tgju_raw(s, n)[0] / 10
    o["xau"] = _tgju_raw(s, "ons")[0] / 10 * 10 or 0.0
    o["xag"] = _tgju_raw(s, "silver")[0]
    # اونس‌ها در tgju به دلار و بدون ضریب ریال هستند؛ اگر نامعقول بود از یاهو
    if not (500 < o["xau"] < 20000):
        o["xau"] = fetch_yahoo_last(s, "GC=F")
    if not (3 < o["xag"] < 500):
        o["xag"] = fetch_yahoo_last(s, "SI=F")
    out = dict(o)
    u = o["usd"]
    if o["xau"] > 0 and u > 0:
        f24 = o["xau"] * u / OZ
        out["f24"] = f24
        out["f18"] = f24 * 0.75
        out["femami"] = f24 * EMAMI_PURE_G
        if o["g18"] > 0:
            out["b18"] = (o["g18"] / out["f18"] - 1) * 100
        if o["emami"] > 0:
            out["bemami"] = (o["emami"] / out["femami"] - 1) * 100
    if o["xau"] > 0 and o["xag"] > 0:
        out["r_glob"] = o["xau"] / o["xag"]
        if u > 0:
            out["fs999"] = o["xag"] * u / OZ
            if o["s999"] > 0:
                out["bsilver"] = (o["s999"] / out["fs999"] - 1) * 100
    if o["g24"] > 0 and o["s999"] > 0:
        out["r_dom"] = o["g24"] / o["s999"]
    if out.get("r_glob") and out.get("r_dom"):
        out["r_gap"] = (out["r_dom"] / out["r_glob"] - 1) * 100
    return out


def fetch_macro():
    out = {"usdt_toman": 0.0, "free_market_toman": 0.0, "gold_ounce": 0.0, "silver_ounce": 0.0,
           "gold_ratio": 0.0, "btc_dominance": 0.0, "fng_val": 0, "fng_class": "",
           "gold_18k_toman": 0.0, "gold18_market_toman": 0.0, "emami_market_toman": 0.0,
           "official_fx_toman": 0.0, "market_cap_usd_b": 0.0, "current_hemat": 0.0,
           "index_total": "—", "index_equal": "—", "market_pe": "—", "errors": []}
    err = out["errors"]
    s = make_session()
    usdt = fetch_usdt_toman(s)
    if usdt <= 0:
        err.append("نرخ تتر دریافت نشد")
    out["usdt_toman"] = out["free_market_toman"] = usdt
    out["official_fx_toman"] = _fetch_ice_rate(s)
    if out["official_fx_toman"] <= 0:
        err.append("نرخ رسمی ICE دریافت نشد")
    try:
        r = s.get(URL_GOLD, timeout=6)
        if r.status_code == 200:
            it = r.json().get("items", [{}])[0]
            out["gold_ounce"] = to_float(it.get("xauPrice"))
            out["silver_ounce"] = to_float(it.get("xagPrice"))
    except Exception as e:
        err.append(f"طلا: {e}")
    if out["gold_ounce"] <= 0:
        try:
            r = s.get(URL_GOLD_CG, timeout=6)
            if r.status_code == 200:
                out["gold_ounce"] = to_float(r.json().get("pax-gold", {}).get("usd"))
        except Exception as e:
            err.append(f"طلا (۲): {e}")
    if out["gold_ounce"] <= 0 or out["silver_ounce"] <= 0:
        for k, sym in (("gold_ounce", "GC=F"), ("silver_ounce", "SI=F")):
            if out[k] <= 0:
                out[k] = fetch_yahoo_last(s, sym)
    if out["gold_ounce"] > 0 and out["silver_ounce"] > 0:
        out["gold_ratio"] = out["gold_ounce"] / out["silver_ounce"]
    try:
        r = s.get(URL_CG_GLOBAL, timeout=6)
        if r.status_code == 200:
            out["btc_dominance"] = to_float(r.json()["data"]["market_cap_percentage"]["btc"])
    except Exception as e:
        err.append(f"دامیننس: {e}")
    try:
        r = s.get(URL_FNG, timeout=6)
        if r.status_code == 200:
            d = r.json()["data"][0]
            out["fng_val"] = int(to_float(d.get("value")))
            out["fng_class"] = d.get("value_classification", "")
    except Exception as e:
        err.append(f"ترس/طمع: {e}")
    cap = 0.0
    try:
        for mkt in (1, 2):
            r = s.get(URL_TSE_OVERVIEW.format(mkt), timeout=8)
            if r.status_code == 200:
                d = r.json().get("marketOverview", {})
                cap += to_float(d.get("marketValue"))
                if mkt == 1:
                    i, ic = to_float(d.get("indexLastValue")), to_float(d.get("indexChange"))
                    e_, ec = (to_float(d.get("indexEqualWeightedLastValue")),
                              to_float(d.get("indexEqualWeightedChange")))
                    out["index_total"] = f"{int(i):,} ({'+' if ic >= 0 else ''}{int(ic):,})"
                    out["index_equal"] = f"{int(e_):,} ({'+' if ec >= 0 else ''}{int(ec):,})"
    except Exception as e:
        err.append(f"ارزش بازار: {e}")
    if cap > 0:
        out["current_hemat"] = cap / HEMAT_RIAL
        if usdt > 0:
            out["market_cap_usd_b"] = cap / (usdt * 10.0) / 1e9
    if out["gold_ounce"] > 0 and usdt > 0:
        out["gold_18k_toman"] = out["gold_ounce"] * usdt * 0.75 / 31.1035
    g18, g18d = fetch_tgju_latest(s, "geram18")
    if g18 > 0:
        out["gold18_market_toman"] = out["gold_18k_toman"] = g18
        out["gold18_market_source"] = "tgju " + g18d
    else:
        err.append("طلای ۱۸ از tgju دریافت نشد؛ تخمینی نمایش داده می‌شود")
    sk, skd = fetch_tgju_latest(s, "sekee")
    if sk > 0:
        out["emami_market_toman"] = sk
        out["emami_source"] = "tgju " + skd
    else:
        err.append("سکه از tgju دریافت نشد")
    estimate_iran_gold_quotes(out, usdt, out["gold_ounce"])
    try:
        r = s.get(URL_MARKET_WATCH_PE, timeout=8)
        if r.status_code == 200:
            pes = sorted(to_float(x.get("pe")) for x in r.json().get("marketwatch", [])
                         if 1.0 < to_float(x.get("pe")) < 70.0)
            if pes:
                out["market_pe"] = f"{pes[len(pes) // 2]:.2f}"
    except Exception as e:
        err.append(f"P/E: {e}")
    return out


def get_market_watch(session, min_value=20_000_000_000):
    for url in URL_MARKET_WATCH_PLUS:
        try:
            r = session.get(url, timeout=12)
            if r.status_code != 200:
                continue
            parts = r.text.split("@")
            if len(parts) < 3:
                continue
            stocks = []
            for row in parts[2].split(";"):
                cols = row.split(",")
                if len(cols) < 23:
                    continue
                code, sym, title = cols[0].strip(), cols[2].strip(), cols[3].strip()
                price = to_float(cols[7])
                if not code or not sym or price <= 0:
                    continue
                if sym.endswith("ح") or "صندوق" in title or "اوراق" in title:
                    continue
                if to_float(cols[10]) >= min_value:
                    stocks.append({"ins_code": code, "symbol": sym, "title": title,
                                   "last_price": price, "pe": cols[15].strip() or "-"})
            if stocks:
                return stocks
        except Exception:
            continue
    raise ConnectionError("اتصال به سرور دیده‌بان TSETMC برقرار نشد.")


def get_client_type(session, stock):
    res = dict(stock)
    res.setdefault("power", 0.0)
    res.setdefault("net_hemat", 0.0)
    try:
        r = session.get(URL_CLIENT_TYPE.format(res["ins_code"]), timeout=8)
        if r.status_code != 200:
            return res
        ct = r.json().get("clientType", {})
        bv, sv = max(0.0, to_float(ct.get("buy_I_Volume"))), max(0.0, to_float(ct.get("sell_I_Volume")))
        bc, sc = max(to_float(ct.get("buy_CountI"), 1), 1), max(to_float(ct.get("sell_CountI"), 1), 1)
        price = res["last_price"]
        bcap, scap = bv / bc, sv / sc
        res["power"] = round(bcap / scap, 2) if scap > 0 else 0.0
        res["net_hemat"] = round((bv - sv) * price / HEMAT_RIAL, 4)
    except Exception:
        pass
    return res


def scan_market(min_power, progress=None, should_stop=lambda: False):
    s = make_session()
    stocks = get_market_watch(s)
    total, done, results = len(stocks), 0, []
    with ThreadPoolExecutor(max_workers=MAX_CLIENT_WORKERS) as pool:
        futs = [pool.submit(get_client_type, s, st) for st in stocks]
        for f in as_completed(futs):
            if should_stop():
                for g in futs:
                    g.cancel()
                break
            try:
                r = f.result()
                if r["power"] >= min_power and r["net_hemat"] > 0:
                    results.append(r)
            except Exception:
                pass
            done += 1
            if progress and (done % 10 == 0 or done == total):
                progress(done, total)
    results.sort(key=lambda x: x["power"], reverse=True)
    return results


# ---------------- اسکنر مقاومت (قیمت تعدیل‌شده) ----------------
BRK_LOOKBACK = 60      # روز برای تعیین مقاومت
BRK_VOL_MULT = 1.5     # حجم شکست نسبت به میانگین ۲۰ روز
BRK_RECENT = 15        # شکست در چند روز اخیر بررسی شود
BRK_AFTER = 3          # روز بعد از شکست


def adjusted_series(rows):
    """rows: newest-first TSETMC daily list. Returns oldest-first list of
    (day, adj_close, volume), adjusted for capital increases/dividends using
    the reference price (priceYesterday) jump between consecutive days."""
    rows = [r for r in rows if to_float(r.get("pClosing")) > 0 and to_float(r.get("qTotTran5J")) > 0]
    rows.sort(key=lambda r: r.get("dEven", 0))
    n = len(rows)
    mult = [1.0] * n
    m = 1.0
    for i in range(n - 1, 0, -1):
        prev_close = to_float(rows[i - 1]["pClosing"])
        ref = to_float(rows[i].get("priceYesterday"))
        if prev_close > 0 and ref > 0:
            m *= ref / prev_close
        mult[i - 1] = m
    return [(rows[i]["dEven"], to_float(rows[i]["pClosing"]) * mult[i],
             to_float(rows[i]["qTotTran5J"])) for i in range(n)]


def analyze_breakout(series):
    """Returns (breakout_today, pullback) dicts or None for each."""
    n = len(series)
    if n < BRK_LOOKBACK // 2 + 25:
        return None, None
    closes = [x[1] for x in series]
    vols = [x[2] for x in series]

    def broke(k):
        lo = max(0, k - BRK_LOOKBACK)
        if k - lo < 25 or k < 20:
            return None
        res = max(closes[lo:k])
        avgv = sum(vols[k - 20:k]) / 20.0
        if avgv <= 0 or closes[k] <= res or vols[k] < BRK_VOL_MULT * avgv:
            return None
        return res, vols[k] / avgv

    last = n - 1
    today = None
    b = broke(last)
    if b:
        today = {"resistance": b[0], "vol_ratio": b[1], "close": closes[last],
                 "over_pct": (closes[last] / b[0] - 1) * 100}
    pull = None
    for k in range(last - BRK_AFTER, max(last - BRK_RECENT, 0) - 1, -1):
        b = broke(k)
        if b and closes[k + BRK_AFTER] < closes[k]:
            pull = {"resistance": b[0], "vol_ratio": b[1], "break_day": series[k][0],
                    "break_close": closes[k], "after_close": closes[k + BRK_AFTER],
                    "after_pct": (closes[k + BRK_AFTER] / closes[k] - 1) * 100,
                    "close": closes[last],
                    "vs_res_pct": (closes[last] / b[0] - 1) * 100}
            break
    return today, pull


def _breakout_one(session, st):
    try:
        r = session.get(URL_DAILY.format(st["ins_code"], 130), timeout=10)
        if r.status_code != 200:
            return None
        series = adjusted_series(r.json().get("closingPriceDaily", []))
        today, pull = analyze_breakout(series)
        if today or pull:
            return dict(st, today=today, pull=pull)
    except Exception:
        pass
    return None


def scan_breakouts(progress=None, should_stop=lambda: False):
    """Returns (breakouts, pullbacks) using split/dividend-adjusted closes."""
    s = make_session()
    stocks = [x for x in get_market_watch(s) if not any(c.isdigit() for c in x["symbol"])]
    total, done = len(stocks), 0
    brk, pul = [], []
    with ThreadPoolExecutor(max_workers=MAX_CLIENT_WORKERS) as pool:
        futs = [pool.submit(_breakout_one, s, st) for st in stocks]
        for f in as_completed(futs):
            if should_stop():
                for g in futs:
                    g.cancel()
                break
            r = f.result()
            if r:
                if r["today"]:
                    brk.append(r)
                if r["pull"]:
                    pul.append(r)
            done += 1
            if progress and (done % 10 == 0 or done == total):
                progress(done, total)
    brk.sort(key=lambda x: x["today"]["vol_ratio"], reverse=True)
    pul.sort(key=lambda x: x["pull"]["after_pct"])
    return brk, pul


# ---------------- اسکنر چندروشی ----------------
def _multi_one(session, st, days=420):
    import analysis
    try:
        r = session.get(URL_DAILY.format(st["ins_code"], days), timeout=12)
        if r.status_code != 200:
            return None
        d = analysis.adjusted_ohlcv(r.json().get("closingPriceDaily", []))
        res = analysis.analyze_stock(d, skip=("elliott",))
        if "pa" not in res:
            return None
        ct = get_client_type(session, st)  # قدرت خریدار حقیقی
        power = ct.get("power") or None
        if power and "money" not in res:
            res2 = analysis.analyze_stock(d, power, skip=("elliott",))
            if "money" in res2:
                res["money"] = res2["money"]
        elif power and "money" in res:
            nodes = analysis.volume_profile(d)
            m = analysis.money_zone(d, nodes, power)
            if m:
                res["money"] = m
        return dict(st, methods=res, power=power or 0.0, net_hemat=ct.get("net_hemat", 0.0),
                    score=len(res))
    except Exception:
        return None


def scan_multi(progress=None, should_stop=lambda: False):
    s = make_session()
    stocks = [x for x in get_market_watch(s) if not any(c.isdigit() for c in x["symbol"])]
    total, done, out = len(stocks), 0, []
    with ThreadPoolExecutor(max_workers=MAX_CLIENT_WORKERS) as pool:
        futs = [pool.submit(_multi_one, s, st) for st in stocks]
        for f in as_completed(futs):
            if should_stop():
                for g in futs:
                    g.cancel()
                break
            r = f.result()
            if r:
                out.append(r)
            done += 1
            if progress and (done % 10 == 0 or done == total):
                progress(done, total)
    out.sort(key=lambda x: (x["score"], x["power"]), reverse=True)
    a = [x for x in out if "money" in x["methods"]]
    b = [x for x in out if "mining" in x["methods"] and "money" not in x["methods"]]
    return a, b


def analyze_tse_symbol(query):
    """نماد دستی: جستجو در دیده‌بان، دانلود تاریخچه تعدیل‌شده، تحلیل کامل."""
    import analysis
    q = query.strip().replace("ي", "ی").replace("ك", "ک")
    s = make_session()
    ws = get_market_watch(s, min_value=0)
    nz = lambda t: t.replace("ي", "ی").replace("ك", "ک").replace("\u200c", "").strip()
    st = next((x for x in ws if nz(x["symbol"]) == nz(q)), None) or \
        next((x for x in ws if q and nz(q) in nz(x["symbol"])), None)
    if not st:
        raise ValueError("نماد پیدا نشد")
    r = s.get(URL_DAILY.format(st["ins_code"], 1500), timeout=20).json().get("closingPriceDaily", [])
    d = analysis.adjusted_ohlcv(r)
    ct = get_client_type(s, st)
    power = ct.get("power") or None
    rep = analysis.full_report(d, power)
    if power:
        rep["lines"].append(f"قدرت خریدار حقیقی: {power:.2f}")
    return dict(rep, name=f"{st['symbol']} - {st['title']}", d=d)


def analyze_global(sym, name):
    import analysis, globalx
    d = globalx.fetch_yahoo(make_session(), sym)
    rep = analysis.full_report(d)
    return dict(rep, name=name, d=d)
