import os
import csv
import json
import asyncio
import requests
import time
from datetime import datetime, timezone, timedelta

# ─────────────────────────────────────────
# CREDENTIALS
# ─────────────────────────────────────────
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID        = os.environ.get("CHAT_ID")
METAAPI_TOKEN  = os.environ.get("METAAPI_TOKEN")
MT_LOGIN       = os.environ.get("MT_LOGIN")
MT_SERVER      = os.environ.get("MT_SERVER")
MT_PASSWORD    = os.environ.get("MT_PASSWORD")
MT_LOGIN2      = os.environ.get("MT_LOGIN2")
MT_PASSWORD2   = os.environ.get("MT_PASSWORD2")

_missing = [k for k,v in {
    "TELEGRAM_TOKEN": TELEGRAM_TOKEN,
    "CHAT_ID": CHAT_ID,
    "METAAPI_TOKEN": METAAPI_TOKEN,
    "MT_LOGIN": MT_LOGIN,
    "MT_SERVER": MT_SERVER,
    "MT_PASSWORD": MT_PASSWORD
}.items() if not v]
if _missing:
    raise RuntimeError(f"Missing env vars: {', '.join(_missing)}")

# ─────────────────────────────────────────
# SETTINGS
# ─────────────────────────────────────────
CHECK_EVERY       = 900   # 15 minutes
SWING_LOOKBACK    = 3
ZONE_LOOKBACK     = 30
ZONE_TOLERANCE    = 3.0
AUTO_TRADE        = True
ORDERS_PER_SIGNAL = 20
TRADE_LOG_FILE    = "trade_log.csv"
WEEKLY_DAY        = 6    # Sunday
WEEKLY_HOUR       = 20   # 20:00 UTC

SESSIONS = [
    {"name": "Tokyo",    "start": 0,  "end": 9},
    {"name": "London",   "start": 7,  "end": 16},
    {"name": "New York", "start": 12, "end": 21},
]

TRADE_SETTINGS = {
    "SCALP": {"tp": 5, "sl": 5,  "lot": 0.01, "label": "Scalp (15min)"},
    "DAY":   {"tp": 5, "sl": 5,  "lot": 0.02, "label": "Day Trade (1hr)"},
    "SWING": {"tp": 5, "sl": 5,  "lot": 0.03, "label": "Swing (4hr+)"},
}

# ─────────────────────────────────────────
# TELEGRAM
# ─────────────────────────────────────────
def send_telegram(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": msg},
            timeout=10
        )
        print("Telegram sent!")
    except Exception as e:
        print(f"Telegram error: {e}")

# ─────────────────────────────────────────
# SESSION
# ─────────────────────────────────────────
def is_trading_session():
    h = datetime.now(timezone.utc).hour
    for s in SESSIONS:
        if s["start"] <= h < s["end"]:
            return True, s["name"]
    return False, None

def is_friday():
    return datetime.now(timezone.utc).weekday() == 4

# ─────────────────────────────────────────
# GOLD PRICE
# ─────────────────────────────────────────
def get_gold_price():
    try:
        r = requests.get("https://api.coinbase.com/v2/prices/XAU-USD/spot", timeout=10)
        return float(r.json()["data"]["amount"])
    except Exception as e:
        print(f"Price error: {e}")
        return None

# ─────────────────────────────────────────
# CANDLES
# ─────────────────────────────────────────
candles_15m, candles_1h, candles_4h = [], [], []
last_15m_time = last_1h_time = last_4h_time = None

def build_candles(price):
    global candles_15m, candles_1h, candles_4h
    global last_15m_time, last_1h_time, last_4h_time

    now = datetime.now(timezone.utc)

    t15 = now.replace(minute=(now.minute // 15) * 15, second=0, microsecond=0)
    if last_15m_time is None or t15 != last_15m_time:
        candles_15m.append({"open": price, "high": price, "low": price, "close": price, "ticks": 1})
        last_15m_time = t15
    else:
        c = candles_15m[-1]
        c["high"] = max(c["high"], price)
        c["low"]  = min(c["low"],  price)
        c["close"] = price
        c["ticks"] = c.get("ticks", 0) + 1
    if len(candles_15m) > 100: candles_15m.pop(0)

    t1h = now.replace(minute=0, second=0, microsecond=0)
    if last_1h_time is None or t1h != last_1h_time:
        candles_1h.append({"open": price, "high": price, "low": price, "close": price, "ticks": 1})
        last_1h_time = t1h
    else:
        c = candles_1h[-1]
        c["high"] = max(c["high"], price)
        c["low"]  = min(c["low"],  price)
        c["close"] = price
        c["ticks"] = c.get("ticks", 0) + 1
    if len(candles_1h) > 100: candles_1h.pop(0)

    t4h = now.replace(hour=(now.hour // 4) * 4, minute=0, second=0, microsecond=0)
    if last_4h_time is None or t4h != last_4h_time:
        candles_4h.append({"open": price, "high": price, "low": price, "close": price, "ticks": 1})
        last_4h_time = t4h
    else:
        c = candles_4h[-1]
        c["high"] = max(c["high"], price)
        c["low"]  = min(c["low"],  price)
        c["close"] = price
        c["ticks"] = c.get("ticks", 0) + 1
    if len(candles_4h) > 100: candles_4h.pop(0)

# ─────────────────────────────────────────
# SMC INDICATORS
# ─────────────────────────────────────────
def detect_liquidity(c):
    if len(c) < 6: return None
    lb = c[-6:-1]
    rh = max(x["high"] for x in lb)
    rl = min(x["low"]  for x in lb)
    p, l = c[-2], c[-1]
    if p["high"] > rh and l["close"] < p["close"]: return "BEARISH"
    if p["low"]  < rl and l["close"] > p["close"]: return "BULLISH"
    return None

def detect_bos(c):
    if len(c) < SWING_LOOKBACK * 2 + 1: return None
    r  = c[-(SWING_LOOKBACK * 2 + 1):-1]
    sh = max(x["high"] for x in r)
    sl = min(x["low"]  for x in r)
    lc = c[-1]["close"]
    if lc > sh: return "BULLISH"
    if lc < sl: return "BEARISH"
    return None

def detect_fvg(c):
    if len(c) < 3: return None
    c1, c3 = c[-3], c[-1]
    # Calculate average candle range for size filter
    avg_range = sum(x["high"] - x["low"] for x in c[-10:]) / min(10, len(c))
    bullish_gap = c3["low"] - c1["high"]
    bearish_gap = c1["low"] - c3["high"]
    # Only flag FVG if gap is at least 1.5x the average candle range (high value)
    if bullish_gap > 0 and bullish_gap >= avg_range * 1.5: return "BULLISH"
    if bearish_gap > 0 and bearish_gap >= avg_range * 1.5: return "BEARISH"
    return None

def get_trend(c):
    if len(c) < 5: return None
    cl = [x["close"] for x in c[-5:]]
    if cl[-1] > cl[0]: return "BULLISH"
    if cl[-1] < cl[0]: return "BEARISH"
    return "NEUTRAL"

def get_bigger_trend(c, lookback=20):
    """Longer-window trend read — used to tell a real reversal apart from a pullback."""
    if len(c) < lookback: return None
    cl = [x["close"] for x in c[-lookback:]]
    if cl[-1] > cl[0]: return "BULLISH"
    if cl[-1] < cl[0]: return "BEARISH"
    return "NEUTRAL"



def detect_order_block(c):
    """Last opposite-colored candle before a strong impulsive move that breaks its range."""
    if len(c) < 2: return None
    prev, last = c[-2], c[-1]
    prev_range = prev["high"] - prev["low"]
    prev_bearish = prev["close"] < prev["open"]
    last_bullish = last["close"] > last["open"]
    if prev_bearish and last_bullish and last["close"] > prev["high"] and (last["close"] - last["open"]) > prev_range:
        return "BULLISH"
    prev_bullish = prev["close"] > prev["open"]
    last_bearish = last["close"] < last["open"]
    if prev_bullish and last_bearish and last["close"] < prev["low"] and (last["open"] - last["close"]) > prev_range:
        return "BEARISH"
    return None

def detect_equal_highs_lows(c):
    """Equal highs/lows swept then rejected — a liquidity-grab reversal signal."""
    if len(c) < 6: return None
    recent = c[-6:-1]
    last = c[-1]
    highs = [x["high"] for x in recent]
    lows  = [x["low"]  for x in recent]
    max_high, min_low = max(highs), min(lows)
    eq_highs = sum(1 for h in highs if abs(h - max_high) <= 1.0) >= 2
    eq_lows  = sum(1 for l in lows  if abs(l - min_low)  <= 1.0) >= 2
    if eq_highs and last["high"] > max_high and last["close"] < max_high:
        return "BEARISH"
    if eq_lows and last["low"] < min_low and last["close"] > min_low:
        return "BULLISH"
    return None

# ─────────────────────────────────────────
# 15M ENTRY — 5 ICT concepts, 15m-only, fires on ANY match with trend
# ─────────────────────────────────────────
TRACK_MIN_CONFIRM = 1   # 1 of 5 signals agreeing is enough — fires often by design

def find_15m_entry(trend_4h):
    """Pure 15m entry check. Only uses candles_15m — no 1h/4h confluence required."""
    if trend_4h not in ["BULLISH", "BEARISH"]:
        return None, 0
    signals = [
        detect_liquidity(candles_15m),
        detect_bos(candles_15m),
        detect_fvg(candles_15m),
        detect_order_block(candles_15m),
        detect_equal_highs_lows(candles_15m),
    ]
    score = sum(1 for s in signals if s == trend_4h)
    if score >= TRACK_MIN_CONFIRM:
        direction = "BUY" if trend_4h == "BULLISH" else "SELL"
        return direction, score
    return None, score

# ─────────────────────────────────────────
# VOLUME PROFILE (tick-volume proxy — MT5 CFDs have no real traded volume)
# ─────────────────────────────────────────
VP_BIN_SIZE = 1.0   # $ per price bucket

def build_volume_profile(candles, bin_size=VP_BIN_SIZE):
    """Bucket price by tick count. Returns (poc_price, high_volume_zones list, bins dict)."""
    if len(candles) < 10:
        return None, [], {}
    bins = {}
    for c in candles:
        mid = (c["high"] + c["low"]) / 2
        b = round(mid / bin_size) * bin_size
        bins[b] = bins.get(b, 0) + c.get("ticks", 1)
    if not bins:
        return None, [], {}
    sorted_bins = sorted(bins.items(), key=lambda x: -x[1])
    poc_price = sorted_bins[0][0]                      # Point of Control (highest tick volume)
    top_n = max(3, len(sorted_bins) // 5)               # top ~20% of bins = high-volume zones
    hv_zones = [p for p, _ in sorted_bins[:top_n]]
    return poc_price, hv_zones, bins

def is_near_high_volume_zone(price, hv_zones, tolerance=2.0):
    """True if price is within `tolerance` $ of any high-volume node."""
    return any(abs(price - z) <= tolerance for z in hv_zones)

# ─────────────────────────────────────────
# ZONES
# ─────────────────────────────────────────
def find_zones(candles, lookback=ZONE_LOOKBACK):
    if len(candles) < 10: return None, None, None, None
    recent = candles[-lookback:] if len(candles) >= lookback else candles
    highs = [c["high"] for c in recent]
    lows  = [c["low"]  for c in recent]
    sh = sorted(highs, reverse=True)
    resistance = round(sum(sh[:max(2, len(sh)//5)]) / max(2, len(sh)//5), 2)
    sl = sorted(lows)
    support = round(sum(sl[:max(2, len(sl)//5)]) / max(2, len(sl)//5), 2)
    demand_zone = None
    for i in range(len(recent) - 4, 2, -1):
        block = recent[i-3:i]; push = recent[i]
        br = max(c["high"] for c in block) - min(c["low"] for c in block)
        ar = sum(c["high"] - c["low"] for c in recent) / len(recent)
        if br < ar * 0.8 and push["close"] > max(c["high"] for c in block):
            demand_zone = round(min(c["low"] for c in block), 2); break
    supply_zone = None
    for i in range(len(recent) - 4, 2, -1):
        block = recent[i-3:i]; push = recent[i]
        br = max(c["high"] for c in block) - min(c["low"] for c in block)
        ar = sum(c["high"] - c["low"] for c in recent) / len(recent)
        if br < ar * 0.8 and push["close"] < min(c["low"] for c in block):
            supply_zone = round(max(c["high"] for c in block), 2); break
    return support, resistance, demand_zone, supply_zone

# ─────────────────────────────────────────
# MULTI-TIMEFRAME ANALYSIS (threshold 3 — live trading)
# ─────────────────────────────────────────
def analyze_all_timeframes(price):
    l15 = detect_liquidity(candles_15m); b15 = detect_bos(candles_15m); f15 = detect_fvg(candles_15m)
    l1  = detect_liquidity(candles_1h);  b1  = detect_bos(candles_1h);  f1  = detect_fvg(candles_1h)
    l4  = detect_liquidity(candles_4h);  b4  = detect_bos(candles_4h);  f4  = detect_fvg(candles_4h)
    t15 = get_trend(candles_15m); t1 = get_trend(candles_1h); t4 = get_trend(candles_4h)
    buy15  = sum([l15=="BULLISH", b15=="BULLISH", f15=="BULLISH"])
    sell15 = sum([l15=="BEARISH", b15=="BEARISH", f15=="BEARISH"])
    buy1   = sum([l1=="BULLISH",  b1=="BULLISH",  f1=="BULLISH"])
    sell1  = sum([l1=="BEARISH",  b1=="BEARISH",  f1=="BEARISH"])
    buy4   = sum([l4=="BULLISH",  b4=="BULLISH",  f4=="BULLISH"])
    sell4  = sum([l4=="BEARISH",  b4=="BEARISH",  f4=="BEARISH"])
    tb = buy15 + buy1 + buy4
    ts = sell15 + sell1 + sell4
    if tb < 3 and ts < 3: return "HOLD", None, None, t15, t1, t4
    d = "BUY" if tb > ts else "SELL"
    tfc = sum([buy15>=2, buy1>=2, buy4>=2]) if d == "BUY" else sum([sell15>=2, sell1>=2, sell4>=2])
    tt  = "SWING" if tfc == 3 else ("DAY" if tfc == 2 else "SCALP")
    return d, tt, tfc, t15, t1, t4

# ─────────────────────────────────────────
# MULTI-TIMEFRAME ANALYSIS (threshold 1 — tracking only)
# ─────────────────────────────────────────
def analyze_all_timeframes_track(price):
    l15 = detect_liquidity(candles_15m); b15 = detect_bos(candles_15m); f15 = detect_fvg(candles_15m)
    l1  = detect_liquidity(candles_1h);  b1  = detect_bos(candles_1h);  f1  = detect_fvg(candles_1h)
    l4  = detect_liquidity(candles_4h);  b4  = detect_bos(candles_4h);  f4  = detect_fvg(candles_4h)
    t15 = get_trend(candles_15m); t1 = get_trend(candles_1h); t4 = get_trend(candles_4h)
    buy15  = sum([l15=="BULLISH", b15=="BULLISH", f15=="BULLISH"])
    sell15 = sum([l15=="BEARISH", b15=="BEARISH", f15=="BEARISH"])
    buy1   = sum([l1=="BULLISH",  b1=="BULLISH",  f1=="BULLISH"])
    sell1  = sum([l1=="BEARISH",  b1=="BEARISH",  f1=="BEARISH"])
    buy4   = sum([l4=="BULLISH",  b4=="BULLISH",  f4=="BULLISH"])
    sell4  = sum([l4=="BEARISH",  b4=="BEARISH",  f4=="BEARISH"])
    tb = buy15 + buy1 + buy4
    ts = sell15 + sell1 + sell4
    if tb < 1 and ts < 1: return "HOLD", None, None, t15, t1, t4
    d = "BUY" if tb > ts else "SELL"
    tfc = sum([buy15>=2, buy1>=2, buy4>=2]) if d == "BUY" else sum([sell15>=2, sell1>=2, sell4>=2])
    tt  = "SWING" if tfc == 3 else ("DAY" if tfc == 2 else "SCALP")
    return d, tt, tfc, t15, t1, t4

# ─────────────────────────────────────────
# TRADE LOG
# ─────────────────────────────────────────
trade_log = []

def log_trade(strategy, direction, entry, exit_price, result):
    pnl = round(exit_price - entry, 2) if direction == "BUY" else round(entry - exit_price, 2)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "strategy":  strategy,
        "direction": direction,
        "entry":     entry,
        "exit":      exit_price,
        "result":    result,
        "pnl":       pnl,
    }
    trade_log.append(record)
    try:
        wh = not os.path.exists(TRADE_LOG_FILE)
        with open(TRADE_LOG_FILE, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=record.keys())
            if wh: w.writeheader()
            w.writerow(record)
    except Exception as e:
        print(f"Log error: {e}")

TRACK_LOG_FILE = "track_log.jsonl"

def log_track_result(direction, result):
    """Persist TRACK closes to disk so they survive bot restarts."""
    record = {"timestamp": datetime.now(timezone.utc).isoformat(), "direction": direction, "result": result}
    try:
        with open(TRACK_LOG_FILE, "a") as f:
            f.write(json.dumps(record) + "\n")
    except Exception as e:
        print(f"Track log error: {e}")

def load_track_results(days=7):
    """Read TRACK closes from disk, filtered to the last N days."""
    if not os.path.exists(TRACK_LOG_FILE):
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    results = []
    try:
        with open(TRACK_LOG_FILE, "r") as f:
            for line in f:
                line = line.strip()
                if not line: continue
                try:
                    rec = json.loads(line)
                    if datetime.fromisoformat(rec["timestamp"]) >= cutoff:
                        results.append(rec)
                except Exception:
                    continue
    except Exception as e:
        print(f"Track log read error: {e}")
    return results

def send_weekly_summary(track_results=[]):
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    wt = [t for t in trade_log if datetime.fromisoformat(t["timestamp"]) >= cutoff]
    # Always load TRACK's persisted results too — don't rely only on in-memory state,
    # and don't let an empty SMC log short-circuit TRACK reporting.
    track_results = load_track_results(days=7) or track_results
    if not wt and not track_results:
        send_telegram("WEEKLY SUMMARY\nNo trades closed in the last 7 days.")
        return
    total = len(wt)
    wins  = sum(1 for t in wt if t["result"] == "WIN")
    wr    = round(wins / total * 100, 1) if total else 0
    pnl   = round(sum(t["pnl"] for t in wt), 2)
    bs = {}
    for t in wt:
        s = t["strategy"]
        bs.setdefault(s, {"total": 0, "wins": 0, "pnl": 0.0})
        bs[s]["total"] += 1
        bs[s]["pnl"]   += t["pnl"]
        if t["result"] == "WIN": bs[s]["wins"] += 1
    st = ""
    for s, d in bs.items():
        r = round(d["wins"] / d["total"] * 100, 1)
        st += f"{s}: {d['wins']}/{d['total']} wins ({r}%) | ${d['pnl']:,.2f}\n"

    # Track results
    track_text = ""
    if track_results:
        t_total = len(track_results)
        t_tp    = sum(1 for t in track_results if t["result"] == "TP")
        t_wr    = round(t_tp / t_total * 100, 1)
        by_dir  = {}
        for t in track_results:
            by_dir.setdefault(t["direction"], {"tp": 0, "sl": 0})
            if t["result"] == "TP": by_dir[t["direction"]]["tp"] += 1
            else:                   by_dir[t["direction"]]["sl"] += 1
        dir_text = ""
        for d, v in by_dir.items():
            dir_text += f"  {d}: {v['tp']} TP / {v['sl']} SL\n"
        verdict = (
            "⚠️ Weak edge — reconsider entry filter" if t_wr < 40
            else "✅ Trend-aligned entries look valid" if t_wr > 60
            else "⚖️ Mixed — need more data"
        )
        track_text = (
            f"\n-------------------\n"
            f"[TRACK] Trend-Aligned Observation:\n"
            f"Total: {t_total} | TP: {t_tp} | SL: {t_total - t_tp}\n"
            f"Win Rate: {t_wr}%\n{dir_text}{verdict}"
        )

    send_telegram(
        f"WEEKLY SUMMARY (last 7 days)\n"
        f"-------------------\n"
        f"Total Trades: {total}\n"
        f"Wins: {wins} | Losses: {total - wins}\n"
        f"Win Rate: {wr}%\n"
        f"Net: ${pnl:,.2f}\n"
        f"-------------------\n"
        f"{st}{track_text}"
    )

# ─────────────────────────────────────────
# TRADE STATE
# ─────────────────────────────────────────
def new_trade_state():
    return {"in_trade": False, "trade_type": None, "entry": None,
            "tp": None, "sl": None, "last_signal": None}

def check_tp_sl(name, state, last_high, last_low, now):
    if not state["in_trade"]: return
    if state["trade_type"] == "BUY":
        tp_hit = last_high >= state["tp"]
        sl_hit = last_low  <= state["sl"]
        if tp_hit and sl_hit:
            won = last_high - state["entry"] >= state["entry"] - last_low
            if won:
                send_telegram(f"[{name}] TAKE PROFIT HIT!\nEntry: ${state['entry']:,.2f}\nExit: ${state['tp']:,.2f}\nTime: {now}")
                log_trade(name, "BUY", state["entry"], state["tp"], "WIN")
            else:
                send_telegram(f"[{name}] STOP LOSS HIT!\nEntry: ${state['entry']:,.2f}\nExit: ${state['sl']:,.2f}\nTime: {now}")
                log_trade(name, "BUY", state["entry"], state["sl"], "LOSS")
            state["in_trade"] = False
        elif tp_hit:
            send_telegram(f"[{name}] TAKE PROFIT HIT!\nEntry: ${state['entry']:,.2f}\nExit: ${state['tp']:,.2f}\nTime: {now}")
            log_trade(name, "BUY", state["entry"], state["tp"], "WIN")
            state["in_trade"] = False
        elif sl_hit:
            send_telegram(f"[{name}] STOP LOSS HIT!\nEntry: ${state['entry']:,.2f}\nExit: ${state['sl']:,.2f}\nTime: {now}")
            log_trade(name, "BUY", state["entry"], state["sl"], "LOSS")
            state["in_trade"] = False
    elif state["trade_type"] == "SELL":
        tp_hit = last_low  <= state["tp"]
        sl_hit = last_high >= state["sl"]
        if tp_hit and sl_hit:
            won = state["entry"] - last_low >= last_high - state["entry"]
            if won:
                send_telegram(f"[{name}] TAKE PROFIT HIT!\nEntry: ${state['entry']:,.2f}\nExit: ${state['tp']:,.2f}\nTime: {now}")
                log_trade(name, "SELL", state["entry"], state["tp"], "WIN")
            else:
                send_telegram(f"[{name}] STOP LOSS HIT!\nEntry: ${state['entry']:,.2f}\nExit: ${state['sl']:,.2f}\nTime: {now}")
                log_trade(name, "SELL", state["entry"], state["sl"], "LOSS")
            state["in_trade"] = False
        elif tp_hit:
            send_telegram(f"[{name}] TAKE PROFIT HIT!\nEntry: ${state['entry']:,.2f}\nExit: ${state['tp']:,.2f}\nTime: {now}")
            log_trade(name, "SELL", state["entry"], state["tp"], "WIN")
            state["in_trade"] = False
        elif sl_hit:
            send_telegram(f"[{name}] STOP LOSS HIT!\nEntry: ${state['entry']:,.2f}\nExit: ${state['sl']:,.2f}\nTime: {now}")
            log_trade(name, "SELL", state["entry"], state["sl"], "LOSS")
            state["in_trade"] = False

# ─────────────────────────────────────────
# METAAPI — FAST PER-TRADE CONNECTION
# ─────────────────────────────────────────
async def _place(login, password, signal, lot, tp, sl, orders):
    placed = 0
    api = None
    try:
        from metaapi_cloud_sdk import MetaApi
        api = MetaApi(METAAPI_TOKEN, {"region": "london"})
        accounts = await api.metatrader_account_api.get_accounts_with_infinite_scroll_pagination()
        account = next((a for a in accounts if str(a.login) == str(login)), None)
        if account is None:
            account = await api.metatrader_account_api.create_account({
                "name": f"Gold Bot {login}", "type": "cloud",
                "login": login, "password": password,
                "server": MT_SERVER, "platform": "mt5", "magic": 123456
            })
        if account.state not in ["DEPLOYED", "DEPLOYING"]:
            await account.deploy()
            await account.wait_deployed()
        conn = account.get_rpc_connection()
        await conn.connect()
        await conn.wait_synchronized(timeout_in_seconds=30)
        # Auto-detect correct symbol name
        symbol = "XAUUSD.m"
        try:
            symbols = await conn.get_symbols()
            for s in symbols:
                if "XAU" in s and "USD" in s:
                    symbol = s; break
        except:
            pass
        print(f"Using symbol: {symbol}")
        for _ in range(orders):
            try:
                if signal == "BUY":
                    await conn.create_market_buy_order(symbol, lot, stop_loss=sl, take_profit=tp)
                else:
                    await conn.create_market_sell_order(symbol, lot, stop_loss=sl, take_profit=tp)
                placed += 1
            except Exception as e:
                print(f"Order failed: {e}")
        try: await conn.close()
        except: pass
    except Exception as e:
        print(f"MetaAPI error: {e}")
    finally:
        if api:
            try: await api.close()
            except: pass
    return placed

def place_trade(signal, lot, tp, sl, orders=ORDERS_PER_SIGNAL, login=None, password=None):
    if not AUTO_TRADE: return 0
    login    = login    or MT_LOGIN
    password = password or MT_PASSWORD
    try:
        return asyncio.run(_place(login, password, signal, lot, tp, sl, orders))
    except Exception as e:
        print(f"Trade error: {e}")
        return 0

# ─────────────────────────────────────────
# FRIDAY HEDGE — fires at 20:56:55 UTC (23:56:55 EAT)
# ─────────────────────────────────────────
def friday_hedge(price):
    now = datetime.now().strftime("%H:%M:%S")
    if len(candles_15m) >= 5:
        ranges = [c["high"] - c["low"] for c in candles_15m[-5:]]
        if sum(ranges) / len(ranges) > 15:
            send_telegram(f"FRIDAY WARNING! Too volatile - SKIP!\nTime: {now}")
            return
    buy_placed  = place_trade("BUY",  0.05, None, None, 1)
    sell_placed = place_trade("SELL", 0.05, None, None, 1, MT_LOGIN2, MT_PASSWORD2)
    send_telegram(
        f"FRIDAY HEDGE PLACED!\n"
        f"Gold: ${price:,.2f}\n"
        f"ACC1 BUY  (no TP/SL) — {'✅' if buy_placed  else '❌'}\n"
        f"ACC2 SELL (no TP/SL) — {'✅' if sell_placed else '❌'}\n"
        f"Check Monday 1AM Nairobi!\nTime: {now}"
    )

# ─────────────────────────────────────────
# METAAPI — CHECK REAL CLOSED POSITIONS
# ─────────────────────────────────────────
# ─────────────────────────────────────────
# METAAPI — GET REAL CLOSED DEALS FROM JUSTMARKETS
# ─────────────────────────────────────────
async def _get_deals(login, password):
    api = None
    try:
        from metaapi_cloud_sdk import MetaApi
        api = MetaApi(METAAPI_TOKEN, {"region": "london"})
        accounts = await api.metatrader_account_api.get_accounts_with_infinite_scroll_pagination()
        account = next((a for a in accounts if str(a.login) == str(login)), None)
        if account is None: return []
        if account.state not in ["DEPLOYED", "DEPLOYING"]:
            await account.deploy()
            await account.wait_deployed()
        conn = account.get_rpc_connection()
        await conn.connect()
        await conn.wait_synchronized(timeout_in_seconds=30)
        start_time = datetime.now(timezone.utc) - timedelta(hours=1)
        end_time   = datetime.now(timezone.utc)
        history = await conn.get_deals_by_time_range(start_time, end_time)
        try: await conn.close()
        except: pass
        return history.get("deals", [])
    except Exception as e:
        print(f"Deal fetch error: {e}")
        return []
    finally:
        if api:
            try: await api.close()
            except: pass

def check_real_positions(smc_state, track_state, track_results, now):
    """Query actual closed positions from JustMarkets and update trade states."""
    # Check Account 1 (SMC + Zone)
    try:
        deals = asyncio.run(_get_deals(MT_LOGIN, MT_PASSWORD))
        for deal in deals:
            if deal.get("entryType") != "DEAL_ENTRY_OUT": continue
            profit   = deal.get("profit", 0)
            close_px = deal.get("price", 0)
            result   = "WIN" if profit > 0 else "LOSS"
            # Match to SMC
            if smc_state["in_trade"] and smc_state["entry"]:
                send_telegram(
                    f"[SMC] ✅ Real close from JustMarkets!\n"
                    f"Entry: ${smc_state['entry']:,.2f} → Exit: ${close_px:,.2f}\n"
                    f"Profit: ${profit:,.2f} — {'WIN' if result=='WIN' else 'LOSS'}\nTime: {now}"
                )
                log_trade("SMC", smc_state["trade_type"], smc_state["entry"], close_px, result)
                smc_state["in_trade"] = False
                break
    except Exception as e:
        print(f"Account 1 position check error: {e}")

    # Check Account 2 (Track)
    if track_state["in_trade"] and MT_LOGIN2:
        try:
            deals2 = asyncio.run(_get_deals(MT_LOGIN2, MT_PASSWORD2))
            for deal in deals2:
                if deal.get("entryType") != "DEAL_ENTRY_OUT": continue
                profit   = deal.get("profit", 0)
                close_px = deal.get("price", 0)
                result   = "WIN" if profit > 0 else "LOSS"
                send_telegram(
                    f"[TRACK] ✅ Real close from JustMarkets!\n"
                    f"Entry: ${track_state['entry']:,.2f} → Exit: ${close_px:,.2f}\n"
                    f"Profit: ${profit:,.2f} — {'WIN' if result=='WIN' else 'LOSS'}\n"
                    f"{'(Reversed = opposite would have ' + ('LOST ❌' if result=='WIN' else 'WON ✅') + ')'}\nTime: {now}"
                )
                result_tag = "TP" if result == "WIN" else "SL"
                track_results.append({"direction": track_state["direction"], "result": result_tag})
                log_track_result(track_state["direction"], result_tag)
                track_state["in_trade"] = False
                break
        except Exception as e:
            print(f"Account 2 position check error: {e}")

# ─────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────
def main():
    print("Gold Bot Started!")
    send_telegram(
        "Hello Edgar!\n"
        "Multi-Position Auto-Trading Bot is LIVE!\n"
        "Strategies:\n"
        "1. SMC Signal - Liquidity + BOS + FVG (15m/1h/4h) | Threshold: 3\n"
        "2. Friday Hedge - Auto BUY+SELL at 20:56:55 UTC (23:56:55 EAT)\n"
        "3. [TRACK] mode - 4h trend + 15m ICT entry (live, Account 2)\n"
        f"({ORDERS_PER_SIGNAL} orders/signal) | Account: {MT_LOGIN} ({MT_SERVER})\n"
        "Sessions: Tokyo + London + New York"
    )

    smc_state    = new_trade_state()
    last_session = None
    last_weekly  = None
    hedge_fired  = False

    # Track mode state
    track_state       = {"in_trade": False, "direction": None, "entry": None, "tp": None, "sl": None}
    track_last_signal = [None]
    track_results     = []

    while True:
        now = datetime.now().strftime("%H:%M:%S")
        utc = datetime.now(timezone.utc)
        trading, session_name = is_trading_session()

        # ── FRIDAY TIGHT LOOP (20:52–21:00 UTC) ──
        if is_friday() and utc.hour == 20 and utc.minute >= 52:
            hedge_fired = False
            while True:
                utc = datetime.now(timezone.utc)
                if utc.hour == 21: break
                if not hedge_fired and utc.hour == 20 and utc.minute == 56 and utc.second >= 55:
                    p = get_gold_price()
                    if p: friday_hedge(p)
                    hedge_fired = True
                time.sleep(1)

        # ── WEEKLY SUMMARY (Sunday 20:00 UTC) ──
        if utc.weekday() == WEEKLY_DAY and utc.hour >= WEEKLY_HOUR:
            wk = utc.isocalendar()[:2]
            if last_weekly != wk:
                send_weekly_summary(track_results)
                last_weekly = wk

        # ── PRICE + CANDLES ──
        price = get_gold_price()
        if price:
            build_candles(price)
            print(f"[{now}] Gold: ${price:,.2f} | 15m:{len(candles_15m)} 1h:{len(candles_1h)} 4h:{len(candles_4h)}")

        # ── SESSION NOTIFICATIONS ──
        if trading and session_name != last_session:
            send_telegram(f"Session Open! {session_name} active\nScanning...")
            last_session = session_name
        if not trading and last_session is not None:
            send_telegram("Sessions Closed! Bot resumes next session.")
            last_session = None

        if not trading or not price or len(candles_15m) < 5:
            time.sleep(CHECK_EVERY)
            continue

        lh = candles_15m[-1]["high"]
        ll = candles_15m[-1]["low"]

        # ── CHECK REAL POSITIONS FROM METAAPI ──
        # (verifies actual broker TP/SL hits instead of guessing from price)
        # Runs passively — only updates if a real closed position is found

        # ── CHECK TP/SL (price-based fallback) ──
        check_tp_sl("SMC", smc_state, lh, ll, now)

        # ── CHECK REAL BROKER POSITIONS ──
        if smc_state["in_trade"] or track_state["in_trade"]:
            check_real_positions(smc_state, track_state, track_results, now)

        # ── SMC SIGNAL (threshold 3 — live trading) ──
        if not smc_state["in_trade"]:
            # Minimum candle size filter — skip if market is consolidating
            recent_ranges = [c["high"] - c["low"] for c in candles_15m[-5:]]
            avg_range = sum(recent_ranges) / len(recent_ranges) if recent_ranges else 0
            market_active = avg_range >= 2.0  # minimum $2 average range per candle

            d, tt, tfc, t15, t1, t4 = analyze_all_timeframes(price)

            # Volume profile confirmation (tick-volume proxy) — only take trades near a
            # high-activity zone, since that's where real reactions are more likely.
            poc, hv_zones, _ = build_volume_profile(candles_1h)
            vp_confirmed = is_near_high_volume_zone(price, hv_zones, tolerance=3.0) if hv_zones else True
            vp_tag = f"POC:${poc:,.2f}" if poc else "VP:n/a"

            print(f"[SMC] {d} | {tt} | TF:{tfc} | AvgRange:${avg_range:.2f} | {vp_tag} | VPconfirm:{vp_confirmed}")
            if d in ["BUY", "SELL"] and d != smc_state["last_signal"] and market_active and vp_confirmed:
                s = TRADE_SETTINGS[tt]
                smc_state["entry"]       = price
                smc_state["tp"]          = round(price + s["tp"], 2) if d == "BUY" else round(price - s["tp"], 2)
                smc_state["sl"]          = round(price - s["sl"], 2) if d == "BUY" else round(price + s["sl"], 2)
                smc_state["trade_type"]  = d
                smc_state["in_trade"]    = True
                smc_state["last_signal"] = d
                sup, res, dem, sup2 = find_zones(candles_1h)
                zt = ""
                if sup:  zt += f"Support:    ${sup:,.2f}\n"
                if res:  zt += f"Resistance: ${res:,.2f}\n"
                if dem:  zt += f"Demand:     ${dem:,.2f}\n"
                if sup2: zt += f"Supply:     ${sup2:,.2f}\n"
                placed = place_trade(d, s["lot"], smc_state["tp"], smc_state["sl"])
                send_telegram(
                    f"[SMC] {d} ({s['label']})\n"
                    f"Entry: ${price:,.2f}\n"
                    f"TP: ${smc_state['tp']:,.2f} | SL: ${smc_state['sl']:,.2f}\n"
                    f"Lot: {s['lot']} | TF: {tfc}/3\n"
                    f"{zt}"
                    f"{'✅ ' + str(placed) + '/' + str(ORDERS_PER_SIGNAL) + ' PLACED!' if placed else '❌ Failed - place manually!'}\n"
                    f"Time: {now}"
                )

        # ── TRACK MODE — trend-aligned: 4h bias + 15m ICT entry timing ──
        # Logic: check 4h trend, then drop to 15m for liquidity/BOS/FVG confirmation
        # before entering WITH the trend (this replaces the old counter-trend fade).
        if track_state["in_trade"]:
            td = track_state["direction"]
            if td == "BUY":
                if lh >= track_state["tp"]:
                    send_telegram(f"[TRACK] BUY hit TP ✅\nEntry: ${track_state['entry']:,.2f} → ${track_state['tp']:,.2f}")
                    track_results.append({"direction": "BUY", "result": "TP"})
                    log_track_result("BUY", "TP")
                    track_state["in_trade"] = False
                elif ll <= track_state["sl"]:
                    send_telegram(f"[TRACK] BUY hit SL ❌\nEntry: ${track_state['entry']:,.2f} → ${track_state['sl']:,.2f}")
                    track_results.append({"direction": "BUY", "result": "SL"})
                    log_track_result("BUY", "SL")
                    track_state["in_trade"] = False
            elif td == "SELL":
                if ll <= track_state["tp"]:
                    send_telegram(f"[TRACK] SELL hit TP ✅\nEntry: ${track_state['entry']:,.2f} → ${track_state['tp']:,.2f}")
                    track_results.append({"direction": "SELL", "result": "TP"})
                    log_track_result("SELL", "TP")
                    track_state["in_trade"] = False
                elif lh >= track_state["sl"]:
                    send_telegram(f"[TRACK] SELL hit SL ❌\nEntry: ${track_state['entry']:,.2f} → ${track_state['sl']:,.2f}")
                    track_results.append({"direction": "SELL", "result": "SL"})
                    log_track_result("SELL", "SL")
                    track_state["in_trade"] = False

        if not track_state["in_trade"]:
            bigger_trend = get_bigger_trend(candles_4h, lookback=20)
            short_trend  = get_trend(candles_4h)
            divergence   = (bigger_trend in ["BULLISH", "BEARISH"] and short_trend in ["BULLISH", "BEARISH"]
                            and bigger_trend != short_trend and len(candles_4h) >= 20)

            # 4h shows a divergence -> treat it as a reversal in the short_trend direction.
            # Entry timing comes from 15m ICT confirmation (any 1 of 5), not the 4h flip itself.
            trend_4h = short_trend if divergence else bigger_trend

            if trend_4h in ["BULLISH", "BEARISH"] and len(candles_4h) >= 5:
                td2, score = find_15m_entry(trend_4h)
                tag = "reversal (4h divergence)" if divergence else "trend-aligned"
                print(f"[TRACK] 4h:{trend_4h} ({tag}) | 15m confirm score:{score}/5 | entry:{td2}")

                if td2 and td2 != track_last_signal[0]:
                    ts2 = TRADE_SETTINGS["SCALP"]
                    t_tp = round(price + ts2["tp"], 2) if td2 == "BUY" else round(price - ts2["tp"], 2)
                    t_sl = round(price - ts2["sl"], 2) if td2 == "BUY" else round(price + ts2["sl"], 2)
                    track_last_signal[0]     = td2
                    track_state["in_trade"]  = True
                    track_state["direction"] = td2
                    track_state["entry"]     = price
                    track_state["tp"]        = t_tp
                    track_state["sl"]        = t_sl
                    placed = place_trade(td2, ts2["lot"], t_tp, t_sl, ORDERS_PER_SIGNAL, MT_LOGIN2, MT_PASSWORD2)
                    send_telegram(
                        f"[TRACK] {td2} — {tag}, 4h {trend_4h}, 15m confirm {score}/5\n"
                        f"Entry: ${price:,.2f}\n"
                        f"TP: ${t_tp:,.2f} | SL: ${t_sl:,.2f}\n"
                        f"Account 2 | {'✅ ' + str(placed) + '/' + str(ORDERS_PER_SIGNAL) + ' PLACED!' if placed else '❌ Failed - place manually!'}\n"
                        f"Time: {now}"
                    )

        time.sleep(CHECK_EVERY)

if __name__ == "__main__":
    main()
