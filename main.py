import os, csv, threading, sys, traceback
from kivy.config import Config
from kivy.app import App
from kivy.clock import Clock, mainthread
from kivy.core.text import LabelBase
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.properties import StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.widget import Widget
from kivy.utils import platform
import arabic_reshaper
from bidi.algorithm import get_display
import core
import history

HERE = os.path.dirname(os.path.abspath(__file__))
LabelBase.register("Vazir", os.path.join(HERE, "fonts", "Vazirmatn-Regular.ttf"))
_rs = arabic_reshaper.ArabicReshaper()


def fa(t):
    return get_display(_rs.reshape(str(t)))


class RButton(Button):
    """دکمه‌ی گرد؛ رنگ از background_color خوانده و خودش رسم می‌شود."""
    def __init__(self, **kw):
        super().__init__(**kw)
        from kivy.graphics import Color, RoundedRectangle
        self._bg = list(self.background_color)
        self.background_color = (0, 0, 0, 0)
        with self.canvas.before:
            self._c = Color(*self._bg)
            self._r = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(12)])
        self.bind(pos=self._upd, size=self._upd, state=self._upd, disabled=self._upd)

    def _upd(self, *_):
        r, g, b, a = self._bg
        k = 0.7 if self.state == "down" else 1
        self._c.rgba = (r * k, g * k, b * k, 0.35 if self.disabled else a)
        self._r.pos, self._r.size = self.pos, self.size


class ValueRow(BoxLayout):
    """ردیف عنوان/مقدار با پس‌زمینه‌ی گرد."""
    def __init__(self, title, val, **kw):
        super().__init__(size_hint_y=None, height=dp(42), padding=(dp(10), dp(2)), **kw)
        from kivy.graphics import Color, RoundedRectangle
        with self.canvas.before:
            Color(0.1, 0.14, 0.2, 1)
            self._r = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(10)])
            Color(0.95, 0.72, 0.2, 1)
            self._bar = RoundedRectangle(pos=self.pos, size=(dp(3), self.height), radius=[dp(2)])
        self.bind(pos=self._upd, size=self._upd)
        v = Label(text=fa(val), font_name="Vazir", font_size="15sp", halign="left", valign="middle",
                  color=(0.4, 0.85, 1, 1))
        t = Label(text=fa(title), font_name="Vazir", font_size="13sp", halign="right", valign="middle",
                  color=(0.8, 0.85, 0.9, 1))
        for w in (v, t):
            w.bind(size=lambda i, s: setattr(i, "text_size", s))
        self.add_widget(v)
        self.add_widget(t)

    def _upd(self, *_):
        self._r.pos, self._r.size = self.pos, self.size
        self._bar.pos, self._bar.size = (self.x + dp(2), self.y + dp(6)), (dp(3), self.height - dp(12))


class FaLabel(Label):
    """برچسب فارسی با reshape و bidi."""
    raw = StringProperty("")

    def on_raw(self, *_):
        self.text = fa(self.raw)


KV = """
#:import dp kivy.metrics.dp
<FaLabel>:
    font_name: 'Vazir'
    color: 0.9, 0.93, 0.95, 1
    halign: 'right'
    valign: 'middle'
    text_size: self.width, None
    size_hint_y: None
    height: self.texture_size[1] + dp(6)
<Card@BoxLayout>:
    orientation: 'vertical'
    size_hint_y: None
    height: dp(64)
    padding: dp(8)
    canvas.before:
        Color:
            rgba: 0.1, 0.13, 0.18, 1
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(8)]
<Btn@RButton>:
    font_name: 'Vazir'
    size_hint_y: None
    height: dp(46)
    background_normal: ''
    background_color: 0.15, 0.4, 0.8, 1
    font_size: '14sp'
BoxLayout:
    orientation: 'vertical'
    spacing: dp(4)
    padding: dp(4)
    canvas.before:
        Color:
            rgba: 0.04, 0.055, 0.08, 1
        Rectangle:
            pos: self.pos
            size: self.size
    BoxLayout:
        size_hint_y: None
        height: dp(44)
        spacing: dp(8)
        padding: dp(6), 0
        canvas.before:
            Color:
                rgba: 0.09, 0.12, 0.18, 1
            RoundedRectangle:
                pos: self.pos
                size: self.size
                radius: [dp(14)]
        Image:
            source: app.icon_path
            size_hint_x: None
            width: dp(36)
        Label:
            text: 'TSE Market Hunter'
            font_size: '17sp'
            bold: True
            color: 0.97, 0.78, 0.25, 1
    BoxLayout:
        size_hint_y: None
        height: dp(46)
        spacing: dp(4)
        Btn:
            id: tab1
            text: app.t_macro
            on_release: app.show('macro')
        Btn:
            id: tab2
            text: app.t_scan
            on_release: app.show('scan')
        Btn:
            text: app.t_my
            on_release: app.show('my')
        Btn:
            text: app.t_glob
            on_release: app.show('glob')
    FaLabel:
        id: status
        raw: ''
        font_size: '12sp'
    BoxLayout:
        id: body
"""


class ChartWidget(Widget):
    """نمودار کندل ساده با خطوط حمایت (سبز) و مقاومت (قرمز) و میانگین ۵۰ روزه."""
    def __init__(self, **kw):
        super().__init__(**kw)
        self.d = None
        self.levels = []
        self.bind(pos=self.redraw, size=self.redraw)

    def set_data(self, d, levels, n=110):
        self.d, self.levels, self.n = d, levels, n
        self.redraw()

    def redraw(self, *_):
        from kivy.graphics import Color, Line, Rectangle
        self.canvas.clear()
        d = self.d
        if not d or len(d["c"]) < 5:
            return
        n = min(self.n, len(d["c"]))
        o, h, l, c = (d[k][-n:] for k in ("o", "h", "l", "c"))
        full = d["c"]
        lv = [(p, k) for p, k in self.levels if min(l) * 0.9 <= p <= max(h) * 1.1]
        lo, hi = min(l), max(h)
        for p, _k in lv:
            lo, hi = min(lo, p), max(hi, p)
        rng = max(hi - lo, 1e-9)
        X, Y, W, H = self.x + dp(4), self.y + dp(4), self.width - dp(8), self.height - dp(8)
        sy = lambda p: Y + (p - lo) / rng * H
        step = W / n
        with self.canvas:
            Color(0.07, 0.09, 0.13, 1)
            Rectangle(pos=self.pos, size=self.size)
            for p, k in lv:
                Color(0.2, 0.8, 0.4, 0.55) if k == "sup" else Color(0.9, 0.3, 0.3, 0.55)
                Line(points=[X, sy(p), X + W, sy(p)], width=1)
            for i in range(n):
                x = X + i * step + step / 2
                up = c[i] >= o[i]
                Color(0.2, 0.8, 0.4, 1) if up else Color(0.9, 0.3, 0.3, 1)
                Line(points=[x, sy(l[i]), x, sy(h[i])], width=1)
                top, bot = sy(max(o[i], c[i])), sy(min(o[i], c[i]))
                Rectangle(pos=(x - step * 0.35, bot), size=(step * 0.7, max(top - bot, 1)))
            if len(full) >= 50 + n:
                Color(1, 0.8, 0.2, 1)
                pts = []
                for i in range(n):
                    j = len(full) - n + i
                    pts += [X + i * step + step / 2, sy(sum(full[j - 49:j + 1]) / 50)]
                Line(points=pts, width=1.2)


class TseApp(App):
    icon_path = os.path.join(HERE, "icon.png")
    icon = icon_path
    t_macro = StringProperty(fa("کلان"))
    t_scan = StringProperty(fa("اسکنر بورس"))
    t_my = StringProperty(fa("نماد من"))
    t_glob = StringProperty(fa("جهانی"))

    def build(self):
        self.title = "TSE Market Hunter"
        history.seed(self.user_data_dir, HERE)
        self.root_w = Builder.load_string(KV)
        self.data = None
        self.results = []
        self.stop = False
        self._build_macro()
        self._build_scan()
        self._build_my()
        self._build_glob()
        self.show("macro")
        self.refresh()
        return self.root_w

    # ---------- ساخت صفحات ----------
    def _scroll(self):
        from kivy.uix.scrollview import ScrollView
        sv = ScrollView()
        box = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(6), padding=dp(8))
        box.bind(minimum_height=box.setter("height"))
        sv.add_widget(box)
        return sv, box

    def _build_macro(self):
        from kivy.uix.button import Button
        self.macro_sv, self.macro_box = self._scroll()
        self.macro_btn = RButton(text=fa("به‌روزرسانی"), font_name="Vazir", size_hint_y=None,
                                height=dp(46), background_normal="",
                                background_color=(.15, .4, .8, 1))
        self.macro_btn.bind(on_release=lambda *_: self.refresh())
        self.hist_btn = RButton(text=fa("به‌روزرسانی تاریخچه (اختیاری)"), font_name="Vazir",
                               size_hint_y=None, height=dp(46), background_normal="",
                               background_color=(.5, .3, .7, 1))
        self.hist_btn.bind(on_release=lambda *_: self.dl_history())
        from kivy.uix.textinput import TextInput
        self.ice_in = TextInput(hint_text="ICE", multiline=False, input_filter="float",
                                size_hint_y=None, height=dp(44))
        try:
            with open(os.path.join(self.user_data_dir, "ice_manual.txt")) as f:
                self.ice_in.text = f.read().strip()
        except Exception:
            pass
        self.liq_in = TextInput(hint_text="%", multiline=False, input_filter="float",
                                size_hint_y=None, height=dp(44))
        try:
            with open(os.path.join(self.user_data_dir, "liq_manual.txt")) as f:
                self.liq_in.text = f.read().strip()
        except Exception:
            pass

    def _build_scan(self):
        from kivy.uix.button import Button
        from kivy.uix.textinput import TextInput
        self.scan_page = BoxLayout(orientation="vertical", spacing=dp(6), padding=dp(6))
        self.scan_page.add_widget(FaLabel(raw="حداقل قدرت خریدار (مثلاً 1.6)"))
        self.power_in = TextInput(text="1.6", multiline=False, input_filter="float",
                                  size_hint_y=None, height=dp(44))
        self.scan_page.add_widget(self.power_in)
        self.filter_in = TextInput(hint_text="filter", multiline=False, size_hint_y=None,
                                   height=dp(44), font_name="Vazir")
        self.filter_in.bind(text=lambda *_: self.render_scan())
        self.scan_page.add_widget(self.filter_in)
        row = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(6))
        self.scan_btn = RButton(text=fa("اسکن بازار"), font_name="Vazir", background_normal="",
                               background_color=(.1, .6, .4, 1))
        self.scan_btn.bind(on_release=lambda *_: self.start_scan())
        csv_btn = RButton(text="CSV", font_name="Vazir", background_normal="",
                         background_color=(.3, .3, .4, 1))
        csv_btn.bind(on_release=lambda *_: self.export_csv())
        row.add_widget(self.scan_btn)
        row.add_widget(csv_btn)
        self.scan_page.add_widget(row)
        row2 = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(6))
        self.brk_btn = RButton(text=fa("مقاومت + شکست (تعدیل‌شده)"), font_name="Vazir",
                              background_normal="", background_color=(.7, .4, .1, 1))
        self.brk_btn.bind(on_release=lambda *_: self.start_brk())
        row2.add_widget(self.brk_btn)
        self.multi_btn = RButton(text=fa("اسکن چندروشی"), font_name="Vazir",
                                background_normal="", background_color=(.4, .3, .7, 1))
        self.multi_btn.bind(on_release=lambda *_: self.start_multi())
        row2.add_widget(self.multi_btn)
        self.scan_page.add_widget(row2)
        self.scan_sv, self.scan_box = self._scroll()
        self.scan_page.add_widget(self.scan_sv)

    def _build_my(self):
        from kivy.uix.button import Button
        from kivy.uix.textinput import TextInput
        self.my_page = BoxLayout(orientation="vertical", spacing=dp(6), padding=dp(6))
        row = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(6))
        self.my_in = TextInput(hint_text=fa("نماد، مثلاً فولاد"), multiline=False,
                               font_name="Vazir", halign="right")
        self.my_btn = RButton(text=fa("تحلیل"), font_name="Vazir", size_hint_x=.3,
                             background_normal="", background_color=(.1, .6, .4, 1))
        self.my_btn.bind(on_release=lambda *_: self.start_my())
        self.my_in.bind(on_text_validate=lambda *_: self.start_my())
        row.add_widget(self.my_btn)
        row.add_widget(self.my_in)
        self.my_page.add_widget(row)
        self.my_sv, self.my_box = self._scroll()
        self.my_page.add_widget(self.my_sv)

    def _build_glob(self):
        import globalx
        from kivy.uix.button import Button
        from kivy.uix.textinput import TextInput
        self.glob_page = BoxLayout(orientation="vertical", spacing=dp(6), padding=dp(6))
        row = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(6))
        for sym, name in globalx.GLOBAL:
            b = RButton(text=fa(name), font_name="Vazir", background_normal="",
                       background_color=(.7, .5, .1, 1))
            b.bind(on_release=lambda _b, s=sym, n=name: self.start_glob(s, n))
            row.add_widget(b)
        self.glob_page.add_widget(row)
        row2 = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(6))
        self.glob_in = TextInput(hint_text="Yahoo symbol: e.g. CL=F, AAPL", multiline=False)
        b2 = RButton(text=fa("تحلیل"), font_name="Vazir", size_hint_x=.3, background_normal="",
                    background_color=(.1, .6, .4, 1))
        b2.bind(on_release=lambda *_: self.start_glob(self.glob_in.text.strip(), self.glob_in.text.strip()))
        row2.add_widget(b2)
        row2.add_widget(self.glob_in)
        self.glob_page.add_widget(row2)
        self.glob_sv, self.glob_box = self._scroll()
        self.glob_page.add_widget(self.glob_sv)

    def start_my(self):
        q = self.my_in.text.strip()
        if not q:
            return
        self.set_status("در حال تحلیل...")
        self.my_box.clear_widgets()
        threading.Thread(target=lambda: self._an_job(lambda: core.analyze_tse_symbol(q), self.my_box),
                         daemon=True).start()

    def start_glob(self, sym, name):
        if not sym:
            return
        self.set_status("در حال دریافت داده جهانی...")
        self.glob_box.clear_widgets()
        threading.Thread(target=lambda: self._an_job(lambda: core.analyze_global(sym, name), self.glob_box),
                         daemon=True).start()

    def _an_job(self, fn, box):
        try:
            self.an_done(fn(), "", box)
        except Exception as e:
            self.an_done(None, str(e), box)

    @mainthread
    def an_done(self, rep, err, box):
        box.clear_widgets()
        if err:
            self.set_status("خطا: " + err)
            return
        self.set_status("")
        box.add_widget(FaLabel(raw=rep["name"], font_size="17sp"))
        ch = ChartWidget(size_hint_y=None, height=dp(300))
        ch.set_data(rep["d"], rep["levels"])
        box.add_widget(ch)
        box.add_widget(FaLabel(raw="سبز: حمایت | قرمز: مقاومت | زرد: میانگین ۵۰ روزه", font_size="11sp"))
        for ln in rep["lines"]:
            box.add_widget(FaLabel(raw=ln, font_size="13sp"))
        box.add_widget(FaLabel(
            raw="این تحلیل توضیح وضعیت است، نه توصیه‌ی خرید یا فروش.", font_size="11sp",
            color=(.8, .8, .8, 1)))

    def show(self, name):
        body = self.root_w.ids.body
        body.clear_widgets()
        body.add_widget({"macro": lambda: self.macro_page, "scan": lambda: self.scan_page,
                         "my": lambda: self.my_page, "glob": lambda: self.glob_page}[name]())

    @property
    def macro_page(self):
        if not hasattr(self, "_mp"):
            self._mp = BoxLayout(orientation="vertical")
            self._mp.add_widget(self.macro_btn)
            self._mp.add_widget(self.hist_btn)
            self._mp.add_widget(self.macro_sv)
        return self._mp

    def set_status(self, t):
        self.root_w.ids.status.raw = t

    # ---------- کلان ----------
    def refresh(self):
        self.set_status("در حال دریافت داده‌ها...")
        self.macro_btn.disabled = True
        threading.Thread(target=self._macro_job, daemon=True).start()

    def dl_history(self):
        self.set_status("در حال به‌روزرسانی تاریخچه...")
        self.hist_btn.disabled = True
        def job():
            rep = history.download_all(self.user_data_dir)
            bad = [k for k, v in rep.items() if isinstance(v, str)]
            self.hist_done("تاریخچه به‌روز شد." if not bad else "خطا در: " + "، ".join(bad))
        threading.Thread(target=job, daemon=True).start()

    @mainthread
    def hist_done(self, msg):
        self.hist_btn.disabled = False
        self.set_status(msg)
        if self.data is not None:
            self.macro_done(self.data)

    def _macro_job(self):
        self.ice_in_text = self.ice_in.text.strip()
        try:
            with open(os.path.join(self.user_data_dir, "ice_manual.txt"), "w") as f:
                f.write(self.ice_in_text)
        except Exception:
            pass
        try:
            with open(os.path.join(self.user_data_dir, "liq_manual.txt"), "w") as f:
                f.write(self.liq_in.text.strip())
        except Exception:
            pass
        try:
            d = core.fetch_macro()
            d["usd_base"], d["usd_base_date"] = core.fetch_usd_year_end()
            try:
                d["liq_growth"] = float(self.liq_in.text.strip())
            except Exception:
                d["liq_growth"] = None
            try:
                man = float(self.ice_in_text)
            except Exception:
                man = 0
            if man > 0:
                d["official_fx_toman"] = man
            history.save_snapshot(self.user_data_dir, d)
        except Exception as e:
            d = {"errors": [str(e)]}
        self.macro_done(d)

    @mainthread
    def macro_done(self, d):
        self.macro_btn.disabled = False
        self.data = d
        b = self.macro_box
        b.clear_widgets()
        b.add_widget(FaLabel(raw="نرخ رسمی ICE دستی (تومان) — خالی = خودکار", font_size="12sp"))
        b.add_widget(self.ice_in)
        b.add_widget(FaLabel(raw="رشد نقدینگی نقطه‌به‌نقطه (٪) — دستی", font_size="12sp"))
        b.add_widget(self.liq_in)
        base = d.get("usd_base") or 0
        card_ = lambda t, v: b.add_widget(ValueRow(t, v))
        b.add_widget(FaLabel(raw="— دلار: کف قوی و قیمت تعادلی —", font_size="16sp", color=(.2, .75, .95, 1)))
        if base > 0:
            card_("پایان سال قبل = کف قوی (" + str(d.get("usd_base_date", "")) + ")", f"{base:,.0f}")
            lg = d.get("liq_growth")
            if lg is not None:
                card_("قیمت تعادلی دلار سال بعد", f"{base * (1 + lg / 100):,.0f}")
            else:
                card_("قیمت تعادلی دلار سال بعد", "نامشخص (رشد نقدینگی را وارد کنید)")
        else:
            card_("پایان سال قبل (tgju)", "نامشخص")

        def card(title, val):
            b.add_widget(ValueRow(title, val))

        def num(v, fmt="{:,.0f}", suf=""):
            return (fmt.format(v) + suf) if v and v > 0 else "نامشخص"

        card("تتر (تومان)", num(d.get("usdt_toman")))
        card("دلار رسمی ICE (تومان)", num(d.get("official_fx_toman")))
        card("طلای ۱۸ عیار (tgju، تومان/گرم)", num(d.get("gold18_market_toman")))
        card("سکه امامی (tgju، تومان)", num(d.get("emami_market_toman")))
        card("اونس طلا", num(d.get("gold_ounce"), "${:,.1f}"))
        card("اونس نقره", num(d.get("silver_ounce"), "${:,.2f}"))
        card("نسبت طلا به نقره", num(d.get("gold_ratio"), "{:.1f}"))
        card("دامیننس بیت‌کوین", num(d.get("btc_dominance"), "{:.1f}", "٪"))
        card("ترس و طمع", f"{d.get('fng_val', 0)} {d.get('fng_class', '')}" if d.get("fng_val") else "نامشخص")
        card("شاخص کل", d.get("index_total", "—"))
        card("شاخص هم‌وزن", d.get("index_equal", "—"))
        card("ارزش بورس (همت)", num(d.get("current_hemat")))
        card("ارزش بورس (میلیارد دلار)", num(d.get("market_cap_usd_b"), "{:.1f}"))
        card("P/E بازار", d.get("market_pe", "—"))
        card("سقف دلاری ATH", f"{core.ATH_MARKET_CAP_USD_BILLION:.0f} میلیارد دلار")
        cur = d.get("market_cap_usd_b") or 0
        if cur > 0:
            card("جاماندگی از ATH", f"{max(0, (1 - cur / core.ATH_MARKET_CAP_USD_BILLION) * 100):.1f}٪ | "
                 f"رشد تا ATH {max(0, (core.ATH_MARKET_CAP_USD_BILLION / cur - 1) * 100):.1f}٪")
        lag = core.market_lag(d)
        if lag is not None:
            card("جاماندگی بورس نسبت به دلار", f"{lag:+.1f}٪")

        if d.get("usdt_toman"):
            eq = core.compute_triple_equilibrium(d, dict(d))
            b.add_widget(FaLabel(raw="— تعادل چنددارایی —", font_size="16sp", color=(.2, .75, .95, 1)))
            card("دلار منصفانه", num(eq["usd_fair"]))
            card("شکاف دلار بازار", num(eq["usd_gap"], "{:+.1f}", "٪") if eq["usd_gap"] is not None else "نامشخص")
            card("طلای ۱۸ منصفانه (گرم)", num(eq["gold18_fair"]))
            card("سکه امامی (ارزش ذاتی)", num(eq["emami_fair"]))
            card("وضعیت سکه", eq["emami_state"])
            card("شاخص منصفانه", num(eq["tedpix_fair"]))
            card("شکاف شاخص", f"{eq['tedpix_gap']:+.1f}٪" if eq["tedpix_gap"] is not None else "نامشخص")
            b.add_widget(FaLabel(raw=eq["signal"], font_size="15sp", color=(1, .8, .2, 1)))
        try:
            h = history.analyze(self.user_data_dir)
        except Exception as e:
            h = {"ok": False, "msg": str(e)}
        b.add_widget(FaLabel(raw="— تحلیل بر پایه ۱۰ سال تاریخچه —", font_size="16sp", color=(.2, .75, .95, 1)))
        if not h.get("ok"):
            card("تاریخچه", h.get("msg", "نامشخص"))
        else:
            card("آخرین روز تاریخچه", h["last_day"])
            card("شاخص به دلار (فعلی / میانه ۱۰ ساله)",
                 f"{h['idx_usd_now']:,.0f} / {h['idx_usd_median']:,.0f}")
            card("انحراف از میانه", f"{h['idx_usd_dev']:+.1f}٪")
            card("صدک تاریخی (۰=ارزان ۱۰۰=گران)", f"{h['idx_usd_pct']:.0f}")
            card("شاخص کل منصفانه (میانه تاریخی)", num(h["tse_fair_hist"]))
            card("فاصله از سقف تاریخی شاخص", f"{h['tse_from_peak']:+.1f}٪")
            card("بیشینه افت تاریخی شاخص", f"{h['tse_max_dd']:.1f}٪")
            names = {"usd_toman": "دلار", "gold18_toman": "طلا ۱۸", "sekee_toman": "سکه",
                     "tse_total": "شاخص کل", "tse_equal": "هم‌وزن"}
            for k, n in names.items():
                v = h["cagr"].get(k)
                if v is not None:
                    card(f"رشد سالانه ترکیبی {n}", f"{v:.1f}٪")
            if "gold_premium_now" in h:
                card("حباب طلا (فعلی / میانه)", f"{h['gold_premium_now']:+.1f}٪ / {h['gold_premium_median']:+.1f}٪")
        errs = d.get("errors") or []
        if errs:
            b.add_widget(FaLabel(raw="هشدار: " + " | ".join(errs), font_size="12sp", color=(1, .4, .4, 1)))
        self.set_status("به‌روزرسانی شد.")

    # ---------- اسکنر ----------
    def start_scan(self):
        try:
            mp = float(self.power_in.text)
        except ValueError:
            mp = 1.6
        self.scan_btn.disabled = True
        self.set_status("در حال اسکن...")
        threading.Thread(target=self._scan_job, args=(mp,), daemon=True).start()

    def _scan_job(self, mp):
        try:
            res = core.scan_market(mp, progress=lambda a, t: self.prog(a, t))
            self.scan_done(res, "")
        except Exception as e:
            self.scan_done([], str(e))

    @mainthread
    def prog(self, a, t):
        self.set_status(f"اسکن: {a} از {t}")

    @mainthread
    def scan_done(self, res, err):
        self.scan_btn.disabled = False
        self.results = res
        self.set_status(("خطا: " + err) if err else f"{len(res)} نماد یافت شد.")
        self.render_scan()

    def render_scan(self):
        box = self.scan_box
        box.clear_widgets()
        q = self.filter_in.text.strip().lower()
        for s in self.results:
            if q and q not in s["symbol"].lower() and q not in s["title"].lower():
                continue
            p = s["power"]
            sig = "تجمیع سنگین" if p >= 2.5 else "ورود هوشمند" if p >= 1.8 else "قدرت مطلوب"
            box.add_widget(FaLabel(
                raw=f"{s['symbol']} — {s['title']}\nقیمت {int(s['last_price'] / 10):,} | P/E {s['pe']} | "
                    f"قدرت {p:.2f} | {core.format_hemat(s['net_hemat'])} | {sig}",
                font_size="13sp"))

    def start_multi(self):
        self.multi_btn.disabled = True
        self.set_status("اسکن چندروشی...")
        threading.Thread(target=self._multi_job, daemon=True).start()

    def _multi_job(self):
        try:
            a, b = core.scan_multi(progress=lambda x, t: self.prog(x, t))
            self.multi_done(a, b, "")
        except Exception as e:
            self.multi_done([], [], str(e))

    @mainthread
    def multi_done(self, a, b, err):
        self.multi_btn.disabled = False
        box = self.scan_box
        box.clear_widgets()
        self.results = []
        if err:
            self.set_status("خطا: " + err)
            return
        self.set_status(f"{len(a)} سهم پرایس‌اکشن+توده پول | {len(b)} سهم پرایس‌اکشن+داده‌کاوی")

        def block(title, lst, color):
            box.add_widget(FaLabel(raw=title, font_size="15sp", color=color))
            for s in lst[:50]:
                m = s["methods"]
                lines = [m[k]["text"] for k in ("pa", "money", "mining") if k in m]
                box.add_widget(FaLabel(
                    raw=f"{s['symbol']} — {s['title']}\nقیمت {int(s['last_price'] / 10):,}\n" + "\n".join(lines),
                    font_size="13sp"))
        block("پرایس اکشن + توده پول (بهترین ترکیب بک‌تست)", a, (.3, 1, .5, 1))
        block("پرایس اکشن + داده‌کاوی", b, (1, .8, .3, 1))
        box.add_widget(FaLabel(
            raw="هشدار: برتری این روش‌ها در بک‌تست کوچک بود (حدود ۰٫۷٪ در ۱۰ روز). این فیلتر است، توصیه خرید نیست.",
            font_size="12sp", color=(.8, .8, .8, 1)))

    def start_brk(self):
        self.brk_btn.disabled = True
        self.set_status("اسکن مقاومت...")
        threading.Thread(target=self._brk_job, daemon=True).start()

    def _brk_job(self):
        try:
            b, p = core.scan_breakouts(progress=lambda a, t: self.prog(a, t))
            self.brk_done(b, p, "")
        except Exception as e:
            self.brk_done([], [], str(e))

    @mainthread
    def brk_done(self, b, p, err):
        self.brk_btn.disabled = False
        box = self.scan_box
        box.clear_widgets()
        self.results = []
        if err:
            self.set_status("خطا: " + err)
            return
        self.set_status(f"{len(b)} شکست امروز | {len(p)} پس از شکست")
        box.add_widget(FaLabel(raw="شکست مقاومت ۶۰ روزه با حجم بالا (امروز)", font_size="15sp",
                               color=(.3, 1, .5, 1)))
        for s in b[:60]:
            t = s["today"]
            box.add_widget(FaLabel(
                raw=f"{s['symbol']} — {s['title']}\nقیمت پایانی {int(t['close'] / 10):,} | مقاومت "
                    f"{int(t['resistance'] / 10):,} | {t['over_pct']:+.1f}% بالاتر | حجم {t['vol_ratio']:.1f} برابر میانگین",
                font_size="13sp"))
        box.add_widget(FaLabel(raw="شکست در ۱۵ روز اخیر که قیمت پایانی ۳ روز بعد پایین‌تر آمده", font_size="15sp",
                               color=(1, .6, .3, 1)))
        for s in p[:60]:
            t = s["pull"]
            box.add_widget(FaLabel(
                raw=f"{s['symbol']} — {s['title']}\nروز شکست {t['break_day']} | پایانی شکست "
                    f"{int(t['break_close'] / 10):,} ← ۳ روز بعد {int(t['after_close'] / 10):,} "
                    f"({t['after_pct']:+.1f}%) | الان {t['vs_res_pct']:+.1f}% نسبت به مقاومت",
                font_size="13sp"))

    def export_csv(self):
        if not self.results:
            self.set_status("ابتدا اسکن را انجام دهید.")
            return
        base = self.user_data_dir
        path = os.path.join(base, "tse_hunt.csv")
        if platform == "android":
            try:
                from android.storage import primary_external_storage_path
                base = os.path.join(primary_external_storage_path(), "Download")
                os.makedirs(base, exist_ok=True)
                path = os.path.join(base, "tse_hunt.csv")
            except Exception:
                pass
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(["symbol", "title", "price_toman", "pe", "power", "net_hemat"])
                for s in self.results:
                    w.writerow([s["symbol"], s["title"], int(s["last_price"] / 10),
                                s["pe"], s["power"], s["net_hemat"]])
            self.set_status("ذخیره شد: " + path)
        except Exception as e:
            self.set_status("خطا: " + str(e))


def _crash_screen(msg):
    from kivy.base import runTouchApp
    from kivy.uix.scrollview import ScrollView
    from kivy.uix.textinput import TextInput
    try:
        for d in ("/storage/emulated/0/Download", os.path.expanduser("~")):
            try:
                open(os.path.join(d, "tse_crash.txt"), "w", encoding="utf-8").write(msg)
                break
            except Exception:
                pass
    except Exception:
        pass
    runTouchApp(TextInput(text=msg, readonly=True, font_size="12sp"))


if __name__ == "__main__":
    try:
        TseApp().run()
    except Exception:
        _crash_screen(traceback.format_exc())
