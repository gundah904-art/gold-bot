import os
import csv
import requests
import time
import asyncio
from datetime import datetime, timezone, timedelta

# ─────────────────────────────────────────
# CREDENTIALS — loaded from Railway environment variables
# ─────────────────────────────────────────
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID        = os.environ.get("CHAT_ID")
METAAPI_TOKEN  = os.environ.get("METAAPI_TOKEN")
MT_LOGIN       = os.environ.get("MT_LOGIN")
MT_SERVER      = os.environ.get("MT_SERVER")
MT_PASSWORD    = os.environ.get("MT_PASSWORD")

_required = {
    "TELEGRAM_TOKEN": TELEGRAM_TOKEN,
    "CHAT_ID": CHAT_ID,
    "METAAPI_TOKEN": METAAPI_TOKEN,
    "MT_LOGIN": MT_LOGIN,
    "MT_SERVER": MT_SERVER,
    "MT_PASSWORD": MT_PASSWORD,
}
_missing = [k for k, v in _required.items() if not v]
if _missing:
    raise RuntimeError(
        f"Missing required environment variables: {', '.join(_missing)}. "
        f"Set them in Railway's Variables tab before deploying."
    )

# ─────────────────────────────────────────
# SETTINGS
# ─────────────────────────────────────────
CHECK_EVERY      = 900   # 15 minutes
GAP_THRESHOLD    = 2.0
SWING_LOOKBACK    = 3
ZONE_LOOKBACK     = 30     # candles to scan for support/resistance zones
ZONE_TOLERANCE    = 3.0    # $ distance from a zone that counts as a "touch"
AUTO_TRADE        = True   # set False to only receive signals, no auto trading
ORDERS_PER_SIGNAL = 5      # number of orders fired per signal
TRADE_LOG_FILE    = "trade_log.csv"
WEEKLY_SUMMARY_WEEKDAY = 6  # 0=Mon ... 6=Sunday
WEEKLY_SUMMARY_HOUR    = 20  # UTC hour to send the weekly recap

SESSIONS = [
    {"name": "Tokyo",    "start": 0,  "end": 9},
    {"name": "London",   "start": 7,  "end": 16},
    {"name": "New York", "start": 12, "end": 21},
]

TRADE_SETTINGS = {
    "SCALP": {"tp": 5,  "sl": 3,  "lot": 0.01, "label": "Scalp (15min)"},
    "DAY":   {"tp": 15, "sl": 7,  "lot": 0.02, "label": "Day Trade (1hr)"},
    "SWING": {"tp": 30, "sl": 10, "lot": 0.03, "label": "Swing (4hr+)"},
    "GAP":   {"tp": 0,  "sl": 5,  "lot": 0.05, "label": "Monday Gap"},
    "ZONE":  {"tp": 10, "sl": 5,  "lot": 0.02, "label": "Zone Reaction"},
}

# ─────────────────────────────────────────
# TELEGRAM
# ─────────────────────────────────────────
def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": CHAT_ID, "text": message})
        print("Telegram sent!")
    except Exception as e:
        print(f"Telegram error: {e}")

# ─────────────────────────────────────────
# SESSION
# ─────────────────────────────────────────
def is_trading_session():
    utc_hour = datetime.now(timezone.utc).hour
    for session in SESSIONS:
        if session["start"] <= utc_hour < session["end"]:
            return True, session["name"]
    return False, None

def is_monday(): return datetime.now(timezone.utc).weekday() == 0
def is_friday(): return datetime.now(timezone.utc).weekday() == 4

# ─────────────────────────────────────────
# GOLD PRICE
# ─────────────────────────────────────────
def get_gold_price():
    try:
        url = "https://api.coinbase.com/v2/prices/XAU-USD/spot"
        response = requests.get(url, timeout=10)
        return float(response.json()["data"]["amount"])
    except Exception as e:
        print(f"Gold price error: {e}")
        return None

# ─────────────────────────────────────────
# CANDLE BUILDER — multi timeframe
# ─────────────────────────────────────────
candles_15m, candles_1h, candles_4h = [], [], []
last_15m_time = last_1h_time = last_4h_time = None

def build_candles(price):
    global candles_15m, candles_1h, candles_4h
    global last_15m_time, last_1h_time, last_4h_time
    now = datetime.now(timezone.utc)

    t15 = now.replace(minute=(now.minute // 15) * 15, second=0, microsecond=0)
    if last_15m_time is None or t15 != last_15m_time:
        candles_15m.append({"open": price, "high": price, "low": price, "close": price})
        last_15m_time = t15
    else:
        c = candles_15m[-1]
        c["high"] = max(c["high"], price); c["low"] = min(c["low"], price); c["close"] = price
    if len(candles_15m) > 100: candles_15m.pop(0)

    t1h = now.replace(minute=0, second=0, microsecond=0)
    if last_1h_time is None or t1h != last_1h_time:
        candles_1h.append({"open": price, "high": price, "low": price, "close": price})
        last_1h_time = t1h
    else:
        c = candles_1h[-1]
        c["high"] = max(c["high"], price); c["low"] = min(c["low"], price); c["close"] = price
    if len(candles_1h) > 100: candles_1h.pop(0)

    t4h = now.replace(hour=(now.hour // 4) * 4, minute=0, second=0, microsecond=0)
    if last_4h_time is None or t4h != last_4h_time:
        candles_4h.append({"open": price, "high": price, "low": price, "close": price})
        last_4h_time = t4h
    else:
        c = candles_4h[-1]
        c["high"] = max(c["high"], price); c["low"] = min(c["low"], price); c["close"] = price
    if len(candles_4h) > 100: candles_4h.pop(0)

# ─────────────────────────────────────────
# SMC INDICATORS
# ─────────────────────────────────────────
def detect_liquidity(candles):
    if len(candles) < 6: return None
    lookback = candles[-6:-1]
    recent_high = max(c["high"] for c in lookback)
    recent_low  = min(c["low"]  for c in lookback)
    prev, last = candles[-2], candles[-1]
    if prev["high"] > recent_high and last["close"] < prev["close"]: return "BEARISH"
    elif prev["low"] < recent_low and last["close"] > prev["close"]: return "BULLISH"
    return None

def detect_bos(candles):
    if len(candles) < SWING_LOOKBACK * 2 + 1: return None
    recent = candles[-(SWING_LOOKBACK * 2 + 1):-1]
    swing_high = max(c["high"] for c in recent)
    swing_low  = min(c["low"]  for c in recent)
    last_close = candles[-1]["close"]
    if last_close > swing_high:  return "BULLISH"
    elif last_close < swing_low: return "BEARISH"
    return None

def detect_fvg(candles):
    if len(candles) < 3: return None
    c1, c3 = candles[-3], candles[-1]
    if c1["high"] < c3["low"]:   return "BULLISH"
    elif c1["low"] > c3["high"]: return "BEARISH"
    return None

def get_trend(candles):
    if len(candles) < 5: return None
    closes = [c["close"] for c in candles[-5:]]
    if closes[-1] > closes[0]: return "BULLISH"
    elif closes[-1] < closes[0]: return "BEARISH"
    return "NEUTRAL"

# ─────────────────────────────────────────
# SUPPORT / RESISTANCE + SUPPLY/DEMAND ZONES
# ─────────────────────────────────────────
def find_zones(candles, lookback=ZONE_LOOKBACK):
    """
    Finds key support/resistance levels by detecting swing highs and lows
    that were touched multiple times (clusters = strong zones).
    Also flags supply zones (drop after consolidation) and demand zones
    (rally after consolidation).
    """
    if len(candles) < 10:
        return None, None, None, None

    recent = candles[-lookback:] if len(candles) >= lookback else candles

    highs = [c["high"] for c in recent]
    lows  = [c["low"]  for c in recent]

    sorted_highs = sorted(highs, reverse=True)
    resistance = round(sum(sorted_highs[:max(2, len(sorted_highs)//5)]) / max(2, len(sorted_highs)//5), 2)

    sorted_lows = sorted(lows)
    support = round(sum(sorted_lows[:max(2, len(sorted_lows)//5)]) / max(2, len(sorted_lows)//5), 2)

    demand_zone = None
    for i in range(len(recent) - 4, 2, -1):
        block = recent[i-3:i]
        push  = recent[i]
        block_range = max(c["high"] for c in block) - min(c["low"] for c in block)
        avg_range   = sum(c["high"] - c["low"] for c in recent) / len(recent)
        if block_range < avg_range * 0.8 and push["close"] > max(c["high"] for c in block):
            demand_zone = round(min(c["low"] for c in block), 2)
            break

    supply_zone = None
    for i in range(len(recent) - 4, 2, -1):
        block = recent[i-3:i]
        push  = recent[i]
        block_range = max(c["high"] for c in block) - min(c["low"] for c in block)
        avg_range   = sum(c["high"] - c["low"] for c in recent) / len(recent)
        if block_range < avg_range * 0.8 and push["close"] < min(c["low"] for c in block):
            supply_zone = round(max(c["high"] for c in block), 2)
            break

    return support, resistance, demand_zone, supply_zone

# ─────────────────────────────────────────
# MULTI-TIMEFRAME SMC ANALYSIS
# ─────────────────────────────────────────
def analyze_all_timeframes(price):
    liq_15m, bos_15m, fvg_15m = detect_liquidity(candles_15m), detect_bos(candles_15m), detect_fvg(candles_15m)
    liq_1h,  bos_1h,  fvg_1h  = detect_liquidity(candles_1h),  detect_bos(candles_1h),  detect_fvg(candles_1h)
    liq_4h,  bos_4h,  fvg_4h  = detect_liquidity(candles_4h),  detect_bos(candles_4h),  detect_fvg(candles_4h)
    trend_15m, trend_1h, trend_4h = get_trend(candles_15m), get_trend(candles_1h), get_trend(candles_4h)

    buy_15m  = sum([liq_15m=="BULLISH", bos_15m=="BULLISH", fvg_15m=="BULLISH"])
    sell_15m = sum([liq_15m=="BEARISH", bos_15m=="BEARISH", fvg_15m=="BEARISH"])
    buy_1h   = sum([liq_1h=="BULLISH", bos_1h=="BULLISH", fvg_1h=="BULLISH"])
    sell_1h  = sum([liq_1h=="BEARISH", bos_1h=="BEARISH", fvg_1h=="BEARISH"])
    buy_4h   = sum([liq_4h=="BULLISH", bos_4h=="BULLISH", fvg_4h=="BULLISH"])
    sell_4h  = sum([liq_4h=="BEARISH", bos_4h=="BEARISH", fvg_4h=="BEARISH"])

    total_buy, total_sell = buy_15m+buy_1h+buy_4h, sell_15m+sell_1h+sell_4h
    if total_buy < 1 and total_sell < 1:
        return "HOLD", None, None, trend_15m, trend_1h, trend_4h

    direction = "BUY" if total_buy > total_sell else "SELL"
    if direction == "BUY":
        tf_count = sum([buy_15m>=2, buy_1h>=2, buy_4h>=2])
    else:
        tf_count = sum([sell_15m>=2, sell_1h>=2, sell_4h>=2])

    trade_type = "SWING" if tf_count==3 else ("DAY" if tf_count==2 else "SCALP")
    return direction, trade_type, tf_count, trend_15m, trend_1h, trend_4h

# ─────────────────────────────────────────
# ZONE SIGNAL ANALYSIS — reacts to demand/supply zones
# ─────────────────────────────────────────
def analyze_zone_signal(price):
    support, resistance, demand, supply = find_zones(candles_1h)
    if demand is not None and abs(price - demand) <= ZONE_TOLERANCE:
        return "BUY", demand, support, resistance, demand, supply
    if supply is not None and abs(price - supply) <= ZONE_TOLERANCE:
        return "SELL", supply, support, resistance, demand, supply
    return None, None, support, resistance, demand, supply

# ─────────────────────────────────────────
# METAAPI — PLACE TRADE (fires ORDERS_PER_SIGNAL orders)
# ─────────────────────────────────────────
async def _place_trade_async(signal, lot, tp, sl, orders=ORDERS_PER_SIGNAL):
    placed = 0
    try:
        from metaapi_cloud_sdk import MetaApi
        api = MetaApi(METAAPI_TOKEN)
        accounts = await api.metatrader_account_api.get_accounts_with_infinite_scroll_pagination()
        account = None
        for acc in accounts:
            if str(acc.login) == str(MT_LOGIN):
                account = acc
                break
        if account is None:
            account = await api.metatrader_account_api.create_account({
                'name': 'Edgar Gold Bot',
                'type': 'cloud',
                'login': MT_LOGIN,
                'password': MT_PASSWORD,
                'server': MT_SERVER,
                'platform': 'mt5',
                'magic': 123456
            })
        await account.deploy()
        await account.wait_deployed()
        connection = account.get_rpc_connection()
        await connection.connect()
        await connection.wait_synchronized()

        for _ in range(orders):
            try:
                if signal == "BUY":
                    await connection.create_market_buy_order("XAUUSD", lot, stop_loss=sl, take_profit=tp)
                else:
                    await connection.create_market_sell_order("XAUUSD", lot, stop_loss=sl, take_profit=tp)
                placed += 1
            except Exception as order_err:
                print(f"Order {placed+1}/{orders} failed: {order_err}")

        await api.close()
        return placed
    except Exception as e:
        print(f"MetaAPI trade error: {e}")
        return placed

def place_trade(signal, lot, tp, sl, orders=ORDERS_PER_SIGNAL):
    if not AUTO_TRADE:
        return 0
    try:
        return asyncio.run(_place_trade_async(signal, lot, tp, sl, orders))
    except Exception as e:
        print(f"Trade wrapper error: {e}")
        return 0

# ─────────────────────────────────────────
# FRIDAY ALERT
# ─────────────────────────────────────────
def friday_close_alert(price):
    utc_hour = datetime.now(timezone.utc).hour
    utc_min  = datetime.now(timezone.utc).minute
    now      = datetime.now().strftime("%H:%M:%S")
    if utc_hour == 21 and utc_min >= 59:
        if len(candles_15m) >= 5:
            ranges = [c["high"]-c["low"] for c in candles_15m[-5:]]
            avg_range = sum(ranges)/len(ranges)
            if avg_range > 15:
                send_telegram(f"FRIDAY WARNING!\nToo volatile - SKIP weekend!\nRange: ${avg_range:,.2f}\nTime: {now}")
            else:
                buy_sl, sell_sl = round(price-5,2), round(price+5,2)
                send_telegram(
                    f"ENTER NOW - 1 MIN TO CLOSE!\nGold: ${price:,.2f}\nVolatility: LOW SAFE!\nLot: 0.05\n"
                    f"-------------------\nACCOUNT 1 BUY @ ${price:,.2f}\nSL: ${buy_sl:,.2f}\n\n"
                    f"ACCOUNT 2 SELL @ ${price:,.2f}\nSL: ${sell_sl:,.2f}\n-------------------\n"
                    f"Check Monday 1AM Nairobi!\nTime: {now}"
                )

# ─────────────────────────────────────────
# TRADE LOG — records every closed trade for performance tracking
# ─────────────────────────────────────────
trade_log = []  # in-memory record for this run (persists until container restarts)

def log_trade(strategy, direction, entry, exit_price, result):
    pnl = round(exit_price - entry, 2) if direction == "BUY" else round(entry - exit_price, 2)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "strategy": strategy,
        "direction": direction,
        "entry": entry,
        "exit": exit_price,
        "result": result,
        "pnl": pnl,
    }
    trade_log.append(record)
    try:
        write_header = not os.path.exists(TRADE_LOG_FILE)
        with open(TRADE_LOG_FILE, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=record.keys())
            if write_header:
                writer.writeheader()
            writer.writerow(record)
    except Exception as e:
        print(f"Trade log write error: {e}")

def send_weekly_summary():
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    week_trades = [t for t in trade_log if datetime.fromisoformat(t["timestamp"]) >= cutoff]

    if not week_trades:
        send_telegram("WEEKLY SUMMARY\nNo trades closed in the last 7 days.")
        return

    total = len(week_trades)
    wins = sum(1 for t in week_trades if t["result"] == "WIN")
    losses = total - wins
    win_rate = round(wins / total * 100, 1)
    total_pnl = round(sum(t["pnl"] for t in week_trades), 2)

    by_strategy = {}
    for t in week_trades:
        s = t["strategy"]
        by_strategy.setdefault(s, {"total": 0, "wins": 0, "pnl": 0.0})
        by_strategy[s]["total"] += 1
        by_strategy[s]["pnl"] += t["pnl"]
        if t["result"] == "WIN":
            by_strategy[s]["wins"] += 1

    strategy_text = ""
    for s, d in by_strategy.items():
        rate = round(d["wins"] / d["total"] * 100, 1)
        strategy_text += f"{s}: {d['wins']}/{d['total']} wins ({rate}%) | ${d['pnl']:,.2f}\n"

    send_telegram(
        f"WEEKLY SUMMARY (last 7 days)\n"
        f"-------------------\n"
        f"Total Trades: {total}\n"
        f"Wins: {wins} | Losses: {losses}\n"
        f"Win Rate: {win_rate}%\n"
        f"Net Result: ${total_pnl:,.2f}\n"
        f"-------------------\n"
        f"{strategy_text}"
        f"-------------------\n"
        f"Note: stats reset if the bot restarts/redeploys."
    )

# ─────────────────────────────────────────
# TRADE STATE HELPERS — independent per strategy
# ─────────────────────────────────────────
def new_trade_state():
    return {
        "in_trade": False,
        "trade_type": None,   # BUY / SELL
        "entry": None,
        "tp": None,
        "sl": None,
        "last_signal": None,
    }

def check_tp_sl(name, state, last_high, last_low, now):
    if not state["in_trade"]:
        return
    if state["trade_type"] == "BUY":
        if last_high >= state["tp"]:
            send_telegram(f"[{name}] TAKE PROFIT HIT!\nEntry: ${state['entry']:,.2f}\nExit: ${state['tp']:,.2f}\nTime: {now}")
            log_trade(name, "BUY", state["entry"], state["tp"], "WIN")
            state["in_trade"] = False
        elif last_low <= state["sl"]:
            send_telegram(f"[{name}] STOP LOSS HIT!\nEntry: ${state['entry']:,.2f}\nExit: ${state['sl']:,.2f}\nTime: {now}")
            log_trade(name, "BUY", state["entry"], state["sl"], "LOSS")
            state["in_trade"] = False
    elif state["trade_type"] == "SELL":
        if last_low <= state["tp"]:
            send_telegram(f"[{name}] TAKE PROFIT HIT!\nEntry: ${state['entry']:,.2f}\nExit: ${state['tp']:,.2f}\nTime: {now}")
            log_trade(name, "SELL", state["entry"], state["tp"], "WIN")
            state["in_trade"] = False
        elif last_high >= state["sl"]:
            send_telegram(f"[{name}] STOP LOSS HIT!\nEntry: ${state['entry']:,.2f}\nExit: ${state['sl']:,.2f}\nTime: {now}")
            log_trade(name, "SELL", state["entry"], state["sl"], "LOSS")
            state["in_trade"] = False

# ─────────────────────────────────────────
# MAIN LOOP
# ─────────────────────────────────────────
def main():
    print("Edgar's Multi-Position Auto-Trading Gold Bot Started!")
    send_telegram(
        "Hello Edgar!\n"
        "Multi-Position Auto-Trading Bot is LIVE!\n"
        "Running 3 INDEPENDENT strategies - each can hold\n"
        "its own open position at the same time:\n"
        "1. SMC Signal - Liquidity + BOS + FVG (15m/1h/4h)\n"
        "2. Zone Signal - Demand/Supply zone reaction\n"
        "3. Monday Gap Strategy\n"
        f"Trades placed AUTOMATICALLY on Just Markets! ({ORDERS_PER_SIGNAL} orders/signal)\n"
        f"Account: {MT_LOGIN} ({MT_SERVER})\n"
        "Sessions: Tokyo + London + New York"
    )

    smc_state  = new_trade_state()
    zone_state = new_trade_state()
    gap_state  = new_trade_state()
    gap_state["traded_today"] = False

    last_session_notified = None
    friday_close = None
    last_weekly_summary = None

    while True:
        now = datetime.now().strftime("%H:%M:%S")
        trading, session_name = is_trading_session()

        price = get_gold_price()
        if price:
            build_candles(price)
            print(f"[{now}] Gold: ${price:,.2f} | 15m:{len(candles_15m)} 1h:{len(candles_1h)} 4h:{len(candles_4h)}")

        if is_friday() and price:
            friday_close = price
            friday_close_alert(price)

        # ── WEEKLY SUMMARY ──
        utc_now = datetime.now(timezone.utc)
        if utc_now.weekday() == WEEKLY_SUMMARY_WEEKDAY and utc_now.hour >= WEEKLY_SUMMARY_HOUR:
            week_key = utc_now.isocalendar()[:2]  # (iso_year, iso_week)
            if last_weekly_summary != week_key:
                send_weekly_summary()
                last_weekly_summary = week_key

        # ── MONDAY GAP STRATEGY ──
        if is_monday() and not gap_state["traded_today"] and friday_close and price:
            gap = price - friday_close
            gap_size = abs(gap)
            if gap_size >= GAP_THRESHOLD and not gap_state["in_trade"]:
                gap_signal = "SELL" if gap > 0 else "BUY"
                gap_state["entry"] = price
                gap_state["tp"] = round(friday_close, 2)
                gap_state["sl"] = round(price-5,2) if gap_signal=="BUY" else round(price+5,2)
                gap_state["trade_type"] = gap_signal
                gap_state["in_trade"] = True
                gap_state["traded_today"] = True
                lot = TRADE_SETTINGS["GAP"]["lot"]
                send_telegram(
                    f"[GAP] MONDAY GAP - {gap_signal}\nGap: ${gap_size:,.2f}\nEntry: ${gap_state['entry']:,.2f}\n"
                    f"TP: ${gap_state['tp']:,.2f}\nSL: ${gap_state['sl']:,.2f}\nLot: {lot}\nPlacing {ORDERS_PER_SIGNAL} orders automatically..."
                )
                placed = place_trade(gap_signal, lot, gap_state["tp"], gap_state["sl"])
                send_telegram(f"[GAP] {placed}/{ORDERS_PER_SIGNAL} ORDERS PLACED! {gap_signal} XAUUSD" if placed else "[GAP] Auto-trade failed - place manually!")

        if datetime.now(timezone.utc).weekday() == 1:
            gap_state["traded_today"] = False

        # ── SESSION NOTIFICATIONS ──
        if trading and session_name != last_session_notified:
            send_telegram(f"Session Open! {session_name} active\nScanning 15min+1hr+4hr...")
            last_session_notified = session_name
        if not trading and last_session_notified is not None:
            send_telegram("Sessions Closed! Bot resumes next session.")
            last_session_notified = None

        if not trading or not price or len(candles_15m) < 5:
            time.sleep(CHECK_EVERY)
            continue

        last_high, last_low = candles_15m[-1]["high"], candles_15m[-1]["low"]

        # ── CHECK TP/SL FOR ALL OPEN STRATEGIES ──
        check_tp_sl("SMC", smc_state, last_high, last_low, now)
        check_tp_sl("ZONE", zone_state, last_high, last_low, now)
        check_tp_sl("GAP", gap_state, last_high, last_low, now)

        # ── SMC SIGNAL ──
        if not smc_state["in_trade"]:
            direction, t_type, tf_count, t15, t1h, t4h = analyze_all_timeframes(price)
            print(f"[SMC] Direction: {direction} | Type: {t_type} | TF: {tf_count}")

            if direction in ["BUY","SELL"] and direction != smc_state["last_signal"]:
                settings = TRADE_SETTINGS[t_type]
                smc_state["entry"] = price
                if direction == "BUY":
                    smc_state["tp"] = round(price + settings["tp"], 2)
                    smc_state["sl"] = round(price - settings["sl"], 2)
                else:
                    smc_state["tp"] = round(price - settings["tp"], 2)
                    smc_state["sl"] = round(price + settings["sl"], 2)
                smc_state["trade_type"] = direction
                smc_state["in_trade"] = True
                smc_state["last_signal"] = direction

                support, resistance, demand, supply = find_zones(candles_1h)
                zones_text = ""
                if support:    zones_text += f"Support:    ${support:,.2f}\n"
                if resistance: zones_text += f"Resistance: ${resistance:,.2f}\n"
                if demand:     zones_text += f"Demand Zone: ${demand:,.2f}\n"
                if supply:     zones_text += f"Supply Zone: ${supply:,.2f}\n"
                if not zones_text:
                    zones_text = "Not enough data yet\n"

                send_telegram(
                    f"[SMC] NEW SIGNAL - {direction} ({settings['label']})\n"
                    f"Entry: ${smc_state['entry']:,.2f}\n"
                    f"TP: ${smc_state['tp']:,.2f}\n"
                    f"SL: ${smc_state['sl']:,.2f}\n"
                    f"Lot: {settings['lot']}\n"
                    f"Timeframes aligned: {tf_count}/3\n"
                    f"-------------------\n"
                    f"{zones_text}"
                    f"-------------------\n"
                    f"Placing {ORDERS_PER_SIGNAL} orders automatically...\n"
                    f"Time: {now}"
                )
                placed = place_trade(direction, settings["lot"], smc_state["tp"], smc_state["sl"])
                send_telegram(f"[SMC] {placed}/{ORDERS_PER_SIGNAL} ORDERS PLACED! {direction} XAUUSD" if placed else "[SMC] Auto-trade failed - place manually!")

        # ── ZONE SIGNAL ──
        if not zone_state["in_trade"]:
            z_direction, z_level, support, resistance, demand, supply = analyze_zone_signal(price)
            print(f"[ZONE] Direction: {z_direction} | Level: {z_level}")

            if z_direction in ["BUY","SELL"] and z_direction != zone_state["last_signal"]:
                settings = TRADE_SETTINGS["ZONE"]
                zone_state["entry"] = price
                if z_direction == "BUY":
                    zone_state["tp"] = round(price + settings["tp"], 2)
                    zone_state["sl"] = round(price - settings["sl"], 2)
                else:
                    zone_state["tp"] = round(price - settings["tp"], 2)
                    zone_state["sl"] = round(price + settings["sl"], 2)
                zone_state["trade_type"] = z_direction
                zone_state["in_trade"] = True
                zone_state["last_signal"] = z_direction

                send_telegram(
                    f"[ZONE] NEW SIGNAL - {z_direction} (Reacted off ${z_level:,.2f})\n"
                    f"Entry: ${zone_state['entry']:,.2f}\n"
                    f"TP: ${zone_state['tp']:,.2f}\n"
                    f"SL: ${zone_state['sl']:,.2f}\n"
                    f"Lot: {settings['lot']}\n"
                    f"Placing {ORDERS_PER_SIGNAL} orders automatically...\n"
                    f"Time: {now}"
                )
                placed = place_trade(z_direction, settings["lot"], zone_state["tp"], zone_state["sl"])
                send_telegram(f"[ZONE] {placed}/{ORDERS_PER_SIGNAL} ORDERS PLACED! {z_direction} XAUUSD" if placed else "[ZONE] Auto-trade failed - place manually!")

        time.sleep(CHECK_EVERY)

if __name__ == "__main__":
    main()
