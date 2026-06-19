import requests
import time
from datetime import datetime, timezone

# ─────────────────────────────────────────
# YOUR CREDENTIALS
# ─────────────────────────────────────────
TELEGRAM_TOKEN = "8772845154:AAEOotdBk-Qm1Vpnn_z-mht-KJxoT2ysDSE"
CHAT_ID        = "8910984306"

# ─────────────────────────────────────────
# SETTINGS
# ─────────────────────────────────────────
CHECK_EVERY    = 900   # 15 minutes
GAP_THRESHOLD  = 2.0
SWING_LOOKBACK = 3

SESSIONS = [
    {"name": "Tokyo",    "start": 0,  "end": 9},
    {"name": "London",   "start": 7,  "end": 16},
    {"name": "New York", "start": 12, "end": 21},
]

# Trade type settings
TRADE_SETTINGS = {
    "SCALP":     {"tp": 5,  "sl": 3,  "label": "Scalp  (15min)"},
    "DAY":       {"tp": 15, "sl": 7,  "label": "Day Trade (1hr)"},
    "SWING":     {"tp": 30, "sl": 10, "label": "Swing (4hr+)"},
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
# GET GOLD PRICE
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
# CANDLE BUILDER — multiple timeframes
# ─────────────────────────────────────────
candles_15m = []
candles_1h  = []
candles_4h  = []
last_15m_time = last_1h_time = last_4h_time = None

def build_candles(price):
    global candles_15m, candles_1h, candles_4h
    global last_15m_time, last_1h_time, last_4h_time
    now = datetime.now(timezone.utc)

    # 15-minute candles
    t15 = now.replace(minute=(now.minute // 15) * 15, second=0, microsecond=0)
    if last_15m_time is None or t15 != last_15m_time:
        candles_15m.append({"open": price, "high": price, "low": price, "close": price})
        last_15m_time = t15
    else:
        c = candles_15m[-1]
        c["high"] = max(c["high"], price)
        c["low"]  = min(c["low"],  price)
        c["close"] = price
    if len(candles_15m) > 100: candles_15m.pop(0)

    # 1-hour candles
    t1h = now.replace(minute=0, second=0, microsecond=0)
    if last_1h_time is None or t1h != last_1h_time:
        candles_1h.append({"open": price, "high": price, "low": price, "close": price})
        last_1h_time = t1h
    else:
        c = candles_1h[-1]
        c["high"] = max(c["high"], price)
        c["low"]  = min(c["low"],  price)
        c["close"] = price
    if len(candles_1h) > 100: candles_1h.pop(0)

    # 4-hour candles
    t4h = now.replace(hour=(now.hour // 4) * 4, minute=0, second=0, microsecond=0)
    if last_4h_time is None or t4h != last_4h_time:
        candles_4h.append({"open": price, "high": price, "low": price, "close": price})
        last_4h_time = t4h
    else:
        c = candles_4h[-1]
        c["high"] = max(c["high"], price)
        c["low"]  = min(c["low"],  price)
        c["close"] = price
    if len(candles_4h) > 100: candles_4h.pop(0)

# ─────────────────────────────────────────
# SMC INDICATORS
# ─────────────────────────────────────────
def detect_liquidity(candles):
    if len(candles) < 6: return None
    lookback    = candles[-6:-1]
    recent_high = max(c["high"] for c in lookback)
    recent_low  = min(c["low"]  for c in lookback)
    prev = candles[-2]
    last = candles[-1]
    if prev["high"] > recent_high and last["close"] < prev["close"]: return "BEARISH"
    elif prev["low"] < recent_low and last["close"] > prev["close"]: return "BULLISH"
    return None

def detect_bos(candles):
    if len(candles) < SWING_LOOKBACK * 2 + 1: return None
    recent     = candles[-(SWING_LOOKBACK * 2 + 1):-1]
    swing_high = max(c["high"] for c in recent)
    swing_low  = min(c["low"]  for c in recent)
    last_close = candles[-1]["close"]
    if last_close > swing_high:  return "BULLISH"
    elif last_close < swing_low: return "BEARISH"
    return None

def detect_fvg(candles):
    if len(candles) < 3: return None
    c1 = candles[-3]
    c3 = candles[-1]
    if c1["high"] < c3["low"]:   return "BULLISH"
    elif c1["low"] > c3["high"]: return "BEARISH"
    return None

def get_trend(candles):
    """Get overall trend from candles"""
    if len(candles) < 5: return None
    closes = [c["close"] for c in candles[-5:]]
    if closes[-1] > closes[0]: return "BULLISH"
    elif closes[-1] < closes[0]: return "BEARISH"
    return "NEUTRAL"

# ─────────────────────────────────────────
# MULTI-TIMEFRAME ANALYSIS + TRADE TYPE
# ─────────────────────────────────────────
def analyze_all_timeframes(price):
    # Get signals from each timeframe
    liq_15m = detect_liquidity(candles_15m)
    bos_15m = detect_bos(candles_15m)
    fvg_15m = detect_fvg(candles_15m)
    trend_15m = get_trend(candles_15m)

    liq_1h  = detect_liquidity(candles_1h)
    bos_1h  = detect_bos(candles_1h)
    fvg_1h  = detect_fvg(candles_1h)
    trend_1h = get_trend(candles_1h)

    liq_4h  = detect_liquidity(candles_4h)
    bos_4h  = detect_bos(candles_4h)
    fvg_4h  = detect_fvg(candles_4h)
    trend_4h = get_trend(candles_4h)

    # Score each direction per timeframe
    buy_15m = sell_15m = buy_1h = sell_1h = buy_4h = sell_4h = 0

    if liq_15m == "BULLISH": buy_15m  += 1
    if liq_15m == "BEARISH": sell_15m += 1
    if bos_15m == "BULLISH": buy_15m  += 1
    if bos_15m == "BEARISH": sell_15m += 1
    if fvg_15m == "BULLISH": buy_15m  += 1
    if fvg_15m == "BEARISH": sell_15m += 1

    if liq_1h == "BULLISH": buy_1h  += 1
    if liq_1h == "BEARISH": sell_1h += 1
    if bos_1h == "BULLISH": buy_1h  += 1
    if bos_1h == "BEARISH": sell_1h += 1
    if fvg_1h == "BULLISH": buy_1h  += 1
    if fvg_1h == "BEARISH": sell_1h += 1

    if liq_4h == "BULLISH": buy_4h  += 1
    if liq_4h == "BEARISH": sell_4h += 1
    if bos_4h == "BULLISH": buy_4h  += 1
    if bos_4h == "BEARISH": sell_4h += 1
    if fvg_4h == "BULLISH": buy_4h  += 1
    if fvg_4h == "BEARISH": sell_4h += 1

    # Determine direction
    total_buy  = buy_15m + buy_1h + buy_4h
    total_sell = sell_15m + sell_1h + sell_4h

    if total_buy < 3 and total_sell < 3:
        return "HOLD", None, None, trend_15m, trend_1h, trend_4h

    direction = "BUY" if total_buy > total_sell else "SELL"

    # Determine trade type based on timeframe alignment
    # All 3 timeframes agree = SWING
    # 2 timeframes agree = DAY TRADE
    # Only 15min = SCALP

    if direction == "BUY":
        tf_count = sum([
            1 if buy_15m >= 2 else 0,
            1 if buy_1h  >= 2 else 0,
            1 if buy_4h  >= 2 else 0
        ])
    else:
        tf_count = sum([
            1 if sell_15m >= 2 else 0,
            1 if sell_1h  >= 2 else 0,
            1 if sell_4h  >= 2 else 0
        ])

    if tf_count == 3:
        trade_type = "SWING"
    elif tf_count == 2:
        trade_type = "DAY"
    else:
        trade_type = "SCALP"

    return direction, trade_type, tf_count, trend_15m, trend_1h, trend_4h

# ─────────────────────────────────────────
# FRIDAY CLOSE ALERT
# ─────────────────────────────────────────
def friday_close_alert(price):
    utc_hour = datetime.now(timezone.utc).hour
    utc_min  = datetime.now(timezone.utc).minute
    now      = datetime.now().strftime("%H:%M:%S")

    if utc_hour == 21 and utc_min >= 59:
        if len(candles_15m) >= 5:
            ranges    = [c["high"] - c["low"] for c in candles_15m[-5:]]
            avg_range = sum(ranges) / len(ranges)
            if avg_range > 15:
                send_telegram(
                    f"FRIDAY WARNING!\n"
                    f"Too volatile — SKIP weekend!\n"
                    f"Range: ${avg_range:,.2f}\n"
                    f"Time: {now}"
                )
            else:
                buy_sl  = round(price - 5, 2)
                sell_sl = round(price + 5, 2)
                send_telegram(
                    f"ENTER NOW — 1 MIN TO CLOSE!\n"
                    f"Gold: ${price:,.2f}\n"
                    f"Volatility: LOW SAFE!\n"
                    f"Lot: 0.05\n"
                    f"-------------------\n"
                    f"ACCOUNT 1 BUY @ ${price:,.2f}\n"
                    f"SL: ${buy_sl:,.2f}\n\n"
                    f"ACCOUNT 2 SELL @ ${price:,.2f}\n"
                    f"SL: ${sell_sl:,.2f}\n"
                    f"-------------------\n"
                    f"Check Monday 1AM Nairobi!\n"
                    f"Time: {now}"
                )

# ─────────────────────────────────────────
# MAIN LOOP
# ─────────────────────────────────────────
def main():
    print("Edgar's Multi-Timeframe Gold Bot Started!")
    send_telegram(
        "Hello Edgar!\n"
        "Multi-Timeframe Gold Bot is LIVE!\n"
        "Strategy: SMC — Liquidity + BOS + FVG\n"
        "Timeframes: 15min + 1hr + 4hr\n"
        "Auto detects: Scalp / Day / Swing\n"
        "Sessions: Tokyo + London + New York"
    )

    in_trade              = False
    trade_type            = None
    entry_price           = None
    tp_price              = None
    sl_price              = None
    last_signal           = None
    last_session_notified = None
    friday_close          = None
    gap_traded_today      = False

    while True:
        now     = datetime.now().strftime("%H:%M:%S")
        trading, session_name = is_trading_session()

        price = get_gold_price()
        if price:
            build_candles(price)
            print(f"[{now}] Gold: ${price:,.2f} | 15m:{len(candles_15m)} 1h:{len(candles_1h)} 4h:{len(candles_4h)}")

        # Friday alert
        if is_friday() and price:
            friday_close = price
            friday_close_alert(price)

        # Monday gap
        if is_monday() and not gap_traded_today and friday_close and price:
            gap      = price - friday_close
            gap_size = abs(gap)
            if gap_size >= GAP_THRESHOLD and not in_trade:
                gap_signal  = "SELL" if gap > 0 else "BUY"
                entry_price = price
                tp_price    = round(friday_close, 2)
                sl_price    = round(price - 5, 2) if gap_signal == "BUY" else round(price + 5, 2)
                trade_type  = "GAP"
                in_trade    = True
                gap_traded_today = True
                send_telegram(
                    f"MONDAY GAP — {gap_signal}\n"
                    f"Gap Size: ${gap_size:,.2f}\n"
                    f"Friday Close: ${friday_close:,.2f}\n"
                    f"Entry: ${entry_price:,.2f}\n"
                    f"TP: ${tp_price:,.2f}\n"
                    f"SL: ${sl_price:,.2f}\n"
                    f"Win Rate: ~85%\n"
                    f"Time: {now}"
                )

        if datetime.now(timezone.utc).weekday() == 1:
            gap_traded_today = False

        # Session notifications
        if trading and session_name != last_session_notified:
            send_telegram(f"Session Open!\n{session_name} active\nScanning 15min + 1hr + 4hr...")
            last_session_notified = session_name
        if not trading and last_session_notified is not None:
            send_telegram("Sessions Closed!\nBot resumes next session.")
            last_session_notified = None

        if not trading:
            time.sleep(CHECK_EVERY)
            continue

        if not price or len(candles_15m) < 5:
            time.sleep(CHECK_EVERY)
            continue

        last_high = candles_15m[-1]["high"]
        last_low  = candles_15m[-1]["low"]

        # Monitor trade
        if in_trade:
            print(f"In {trade_type} {trade_type} | TP: ${tp_price} | SL: ${sl_price}")
            if trade_type in ["BUY", "GAP"]:
                if last_high >= tp_price:
                    send_telegram(f"TAKE PROFIT HIT!\nEntry: ${entry_price:,.2f}\nExit: ${tp_price:,.2f}\nProfit: +${abs(tp_price-entry_price):,.2f}\nTime: {now}")
                    in_trade = False
                elif last_low <= sl_price:
                    send_telegram(f"STOP LOSS HIT!\nEntry: ${entry_price:,.2f}\nExit: ${sl_price:,.2f}\nTime: {now}")
                    in_trade = False
            elif trade_type == "SELL":
                if last_low <= tp_price:
                    send_telegram(f"TAKE PROFIT HIT!\nEntry: ${entry_price:,.2f}\nExit: ${tp_price:,.2f}\nProfit: +${abs(entry_price-tp_price):,.2f}\nTime: {now}")
                    in_trade = False
                elif last_high >= sl_price:
                    send_telegram(f"STOP LOSS HIT!\nEntry: ${entry_price:,.2f}\nExit: ${sl_price:,.2f}\nTime: {now}")
                    in_trade = False

        # Look for signal
        if not in_trade:
            direction, t_type, tf_count, t15, t1h, t4h = analyze_all_timeframes(price)
            print(f"Direction: {direction} | Type: {t_type} | TF count: {tf_count}")
            print(f"Trends — 15m: {t15} | 1h: {t1h} | 4h: {t4h}")

            if direction in ["BUY", "SELL"] and direction != last_signal:
                settings    = TRADE_SETTINGS[t_type]
                entry_price = price
                if direction == "BUY":
                    tp_price = round(price + settings["tp"], 2)
                    sl_price = round(price - settings["sl"], 2)
                else:
                    tp_price = round(price - settings["tp"], 2)
                    sl_price = round(price + settings["sl"], 2)

                trade_type  = direction
                in_trade    = True
                last_signal = direction

                send_telegram(
                    f"GOLD SIGNAL — {direction}\n"
                    f"Trade Type: {settings['label']}\n"
                    f"Timeframes: {tf_count}/3 aligned\n"
                    f"-------------------\n"
                    f"Entry: ${entry_price:,.2f}\n"
                    f"TP:    ${tp_price:,.2f} (+${settings['tp']})\n"
                    f"SL:    ${sl_price:,.2f} (-${settings['sl']})\n"
                    f"-------------------\n"
                    f"15min trend: {t15}\n"
                    f"1hr trend:   {t1h}\n"
                    f"4hr trend:   {t4h}\n"
                    f"Session: {session_name}\n"
                    f"Time: {now}"
                )
            elif direction == "HOLD":
                last_signal = None

        time.sleep(CHECK_EVERY)

if __name__ == "__main__":
    main()
    
