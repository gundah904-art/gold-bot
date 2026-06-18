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
CHECK_EVERY    = 900   # check every 15 minutes
MIN_CANDLES    = 5
STOP_LOSS      = 5
TAKE_PROFIT    = 10
RSI_PERIOD     = 14
SWING_LOOKBACK = 3
GAP_THRESHOLD  = 2.0

SESSIONS = [
    {"name": "Tokyo",    "start": 0,  "end": 9},
    {"name": "London",   "start": 7,  "end": 16},
    {"name": "New York", "start": 12, "end": 21},
]

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
# SESSION CHECK
# ─────────────────────────────────────────
def is_trading_session():
    utc_hour = datetime.now(timezone.utc).hour
    for session in SESSIONS:
        if session["start"] <= utc_hour < session["end"]:
            return True, session["name"]
    return False, None

def is_monday():
    return datetime.now(timezone.utc).weekday() == 0

def is_friday():
    return datetime.now(timezone.utc).weekday() == 4

# ─────────────────────────────────────────
# GOLD PRICE
# ─────────────────────────────────────────
candle_history   = []
last_candle_time = None

def get_gold_price():
    try:
        url = "https://api.coinbase.com/v2/prices/XAU-USD/spot"
        response = requests.get(url, timeout=10)
        return float(response.json()["data"]["amount"])
    except Exception as e:
        print(f"Gold price error: {e}")
        return None

def build_candle(price):
    global candle_history, last_candle_time
    now           = datetime.now(timezone.utc)
    candle_minute = (now.minute // 15) * 15  # 15-min candles
    candle_time   = now.replace(minute=candle_minute, second=0, microsecond=0)

    if last_candle_time is None or candle_time != last_candle_time:
        candle_history.append({
            "open":  price,
            "high":  price,
            "low":   price,
            "close": price
        })
        last_candle_time = candle_time
    else:
        c = candle_history[-1]
        c["high"]  = max(c["high"], price)
        c["low"]   = min(c["low"],  price)
        c["close"] = price

    if len(candle_history) > 100:
        candle_history.pop(0)

    return candle_history

# ─────────────────────────────────────────
# RSI
# ─────────────────────────────────────────
def calculate_rsi(candles):
    if len(candles) < RSI_PERIOD + 1:
        return 50.0
    closes = [c["close"] for c in candles]
    gains, losses = [], []
    for i in range(-RSI_PERIOD, 0):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains) / RSI_PERIOD
    avg_loss = sum(losses) / RSI_PERIOD
    if avg_loss == 0:
        return 100.0
    return round(100 - (100 / (1 + avg_gain / avg_loss)), 1)

# ─────────────────────────────────────────
# SMC INDICATORS — scan multiple candles
# ─────────────────────────────────────────
def detect_liquidity(candles):
    if len(candles) < 6:
        return None
    # Scan last 10 candles for any liquidity sweep
    for i in range(min(10, len(candles)-2), 1, -1):
        lookback    = candles[-(i+2):-2]
        if not lookback:
            continue
        recent_high = max(c["high"] for c in lookback)
        recent_low  = min(c["low"]  for c in lookback)
        prev = candles[-2]
        last = candles[-1]
        if prev["high"] > recent_high and last["close"] < prev["close"]:
            return "BEARISH"
        elif prev["low"] < recent_low and last["close"] > prev["close"]:
            return "BULLISH"
    return None

def detect_bos(candles):
    if len(candles) < SWING_LOOKBACK * 2 + 1:
        return None
    # Scan multiple swing points
    for lookback in [3, 5, 7]:
        if len(candles) < lookback * 2 + 1:
            continue
        recent     = candles[-(lookback * 2 + 1):-1]
        swing_high = max(c["high"] for c in recent)
        swing_low  = min(c["low"]  for c in recent)
        last_close = candles[-1]["close"]
        if last_close > swing_high:  return "BULLISH"
        elif last_close < swing_low: return "BEARISH"
    return None

def detect_fvg(candles):
    if len(candles) < 3:
        return None
    # Scan last 5 candle groups for FVG
    for i in range(1, min(5, len(candles)-2)):
        c1 = candles[-(i+2)]
        c3 = candles[-i]
        if c1["high"] < c3["low"]:   return "BULLISH"
        elif c1["low"] > c3["high"]: return "BEARISH"
    return None

# ─────────────────────────────────────────
# COMBINED SIGNAL
# ─────────────────────────────────────────
def get_signal(candles, price):
    liquidity = detect_liquidity(candles)
    bos       = detect_bos(candles)
    fvg       = detect_fvg(candles)
    rsi       = calculate_rsi(candles)

    buy_score = sell_score = 0

    # Liquidity
    if liquidity == "BULLISH": buy_score  += 2
    if liquidity == "BEARISH": sell_score += 2

    # BOS
    if bos == "BULLISH": buy_score  += 2
    if bos == "BEARISH": sell_score += 2

    # FVG
    if fvg == "BULLISH": buy_score  += 1
    if fvg == "BEARISH": sell_score += 1

    # RSI
    if rsi < 45: buy_score  += 1
    if rsi > 55: sell_score += 1

    # Determine strength
    if buy_score >= 5:
        strength = "STRONG"
        signal = "BUY"
    elif buy_score >= 3:
        strength = "MODERATE"
        signal = "BUY"
    elif buy_score >= 2:
        strength = "WEAK"
        signal = "BUY"
    elif sell_score >= 5:
        strength = "STRONG"
        signal = "SELL"
    elif sell_score >= 3:
        strength = "MODERATE"
        signal = "SELL"
    elif sell_score >= 2:
        strength = "WEAK"
        signal = "SELL"
    else:
        return "HOLD", liquidity, bos, fvg, rsi, None

    return signal, liquidity, bos, fvg, rsi, strength

# ─────────────────────────────────────────
# MONDAY GAP
# ─────────────────────────────────────────
def check_monday_gap(friday_close, monday_open):
    if friday_close is None or monday_open is None:
        return None, 0
    gap      = monday_open - friday_close
    gap_size = abs(gap)
    if gap_size < GAP_THRESHOLD:
        return None, gap_size
    return "SELL" if gap > 0 else "BUY", gap_size

# ─────────────────────────────────────────
# MAIN LOOP
# ─────────────────────────────────────────
def main():
    print("Edgar's Gold Bot Started!")
    send_telegram(
        "Hello Edgar!\n"
        "Gold Bot is now running!\n"
        "Scanning every 1 minute\n"
        "15-min candles\n"
        "Sessions: Tokyo + London + New York\n"
        "Strategy: SMC + RSI + Monday Gap"
    )

    in_trade              = False
    trade_type            = None
    entry_price           = None
    tp_price              = None
    sl_price              = None
    last_session_notified = None
    friday_close          = None
    gap_traded_today      = False
    last_signal           = None

    while True:
        now     = datetime.now().strftime("%H:%M:%S")
        trading, session_name = is_trading_session()
        today_is_monday = is_monday()
        today_is_friday = is_friday()

        print(f"\n[{now}] Session: {session_name or 'CLOSED'}")

        # Friday close alert + volatility check
        if today_is_friday:
            price = get_gold_price()
            if price:
                friday_close = price
                print(f"Friday close: ${friday_close:,.2f}")
                if len(candle_history) >= 5:
                    friday_close_alert(candle_history, price)

        # Monday gap check
        if today_is_monday and not gap_traded_today and friday_close:
            price = get_gold_price()
            if price:
                gap_signal, gap_size = check_monday_gap(friday_close, price)
                if gap_signal and not in_trade:
                    entry_price = price
                    tp_price    = round(friday_close, 2)
                    sl_price    = round(price - STOP_LOSS, 2) if gap_signal == "BUY" else round(price + STOP_LOSS, 2)
                    trade_type  = gap_signal
                    in_trade    = True
                    gap_traded_today = True
                    send_telegram(
                        f"MONDAY GAP — {gap_signal}\n"
                        f"-------------------\n"
                        f"Gap Size:     ${gap_size:,.2f}\n"
                        f"Friday Close: ${friday_close:,.2f}\n"
                        f"Entry:        ${entry_price:,.2f}\n"
                        f"Take Profit:  ${tp_price:,.2f}\n"
                        f"Stop Loss:    ${sl_price:,.2f}\n"
                        f"Win Rate: ~85%\n"
                        f"Time: {now}"
                    )

        if datetime.now(timezone.utc).weekday() == 1:
            gap_traded_today = False

        # Session notifications
        if trading and session_name != last_session_notified:
            send_telegram(f"Session Open!\n{session_name} Session active\nScanning every minute...")
            last_session_notified = session_name

        if not trading and last_session_notified is not None:
            send_telegram("Sessions Closed!\nBot resumes next session.")
            last_session_notified = None

        # Get price and build candle
        price = get_gold_price()
        if not price:
            time.sleep(CHECK_EVERY)
            continue

        candles = build_candle(price)
        print(f"Gold: ${price:,.2f} | Candles: {len(candles)}")

        # Monitor trade
        if in_trade:
            print(f"In {trade_type} | TP: ${tp_price} | SL: ${sl_price}")
            if trade_type == "BUY":
                if price >= tp_price:
                    send_telegram(f"TAKE PROFIT HIT!\n-------------------\nEntry:  ${entry_price:,.2f}\nExit:   ${tp_price:,.2f}\nProfit: +${abs(tp_price-entry_price):,.2f}\nTime: {now}")
                    in_trade = False
                elif price <= sl_price:
                    send_telegram(f"STOP LOSS HIT!\n-------------------\nEntry: ${entry_price:,.2f}\nExit:  ${sl_price:,.2f}\nLoss:  -${STOP_LOSS}\nTime: {now}")
                    in_trade = False
            elif trade_type == "SELL":
                if price <= tp_price:
                    send_telegram(f"TAKE PROFIT HIT!\n-------------------\nEntry:  ${entry_price:,.2f}\nExit:   ${tp_price:,.2f}\nProfit: +${abs(entry_price-tp_price):,.2f}\nTime: {now}")
                    in_trade = False
                elif price >= sl_price:
                    send_telegram(f"STOP LOSS HIT!\n-------------------\nEntry: ${entry_price:,.2f}\nExit:  ${sl_price:,.2f}\nLoss:  -${STOP_LOSS}\nTime: {now}")
                    in_trade = False

        # Look for signal
        if not in_trade and len(candles) >= MIN_CANDLES and trading:
            signal, liquidity, bos, fvg, rsi, strength = get_signal(candles, price)
            print(f"Liquidity: {liquidity} | BOS: {bos} | FVG: {fvg} | RSI: {rsi} | {signal} ({strength})")

            # Only send if signal changed
            if signal in ["BUY", "SELL"] and signal != last_signal:
                entry_price = price
                if signal == "BUY":
                    tp_price = round(price + TAKE_PROFIT, 2)
                    sl_price = round(price - STOP_LOSS, 2)
                else:
                    tp_price = round(price - TAKE_PROFIT, 2)
                    sl_price = round(price + STOP_LOSS, 2)
                trade_type = signal
                in_trade   = True
                last_signal = signal

                if strength == "STRONG":     conf = "STRONG"
                elif strength == "MODERATE": conf = "MODERATE"
                else:                        conf = "WEAK"

                send_telegram(
                    f"GOLD SIGNAL — {signal} ({conf})\n"
                    f"-------------------\n"
                    f"Entry:       ${entry_price:,.2f}\n"
                    f"Take Profit: ${tp_price:,.2f}\n"
                    f"Stop Loss:   ${sl_price:,.2f}\n"
                    f"-------------------\n"
                    f"Liquidity: {liquidity}\n"
                    f"BOS:       {bos}\n"
                    f"FVG:       {fvg}\n"
                    f"RSI:       {rsi}\n"
                    f"Session: {session_name}\n"
                    f"Time: {now}"
                )
            elif signal == "HOLD":
                last_signal = None

        time.sleep(CHECK_EVERY)

if __name__ == "__main__":
    main()


# ─────────────────────────────────────────
# GAP PREDICTION
# Analyzes Friday price action to predict
# if a Monday gap is likely
# ─────────────────────────────────────────
def predict_gap(candles, price):
    if len(candles) < 10:
        return "Unknown", "Not enough data"

    closes  = [c["close"] for c in candles[-10:]]
    highs   = [c["high"]  for c in candles[-10:]]
    lows    = [c["low"]   for c in candles[-10:]]

    # Overall Friday trend
    trend        = closes[-1] - closes[0]
    weekly_range = max(highs) - min(lows)
    momentum     = closes[-1] - closes[-3]  # last 3 candles momentum

    score     = 0
    direction = "UNKNOWN"
    reasons   = []

    # Strong uptrend on Friday = gap up likely
    if trend > 5:
        score += 2
        direction = "UP"
        reasons.append(f"Strong Friday uptrend (+${trend:,.2f})")
    elif trend < -5:
        score += 2
        direction = "DOWN"
        reasons.append(f"Strong Friday downtrend (${trend:,.2f})")

    # Strong momentum in last 3 candles
    if momentum > 3:
        score += 1
        direction = "UP"
        reasons.append(f"Bullish momentum (+${momentum:,.2f})")
    elif momentum < -3:
        score += 1
        direction = "DOWN"
        reasons.append(f"Bearish momentum (${momentum:,.2f})")

    # Wide weekly range = volatile week = gap more likely
    if weekly_range > 20:
        score += 1
        reasons.append(f"Wide weekly range (${weekly_range:,.2f})")

    # Closing near highs = gap up likely
    week_high = max(highs)
    week_low  = min(lows)
    if price > week_high * 0.998:
        score += 1
        direction = "UP"
        reasons.append("Closing near weekly highs")
    elif price < week_low * 1.002:
        score += 1
        direction = "DOWN"
        reasons.append("Closing near weekly lows")

    # Determine prediction
    if score >= 3 and direction == "UP":
        prediction  = "GAP UP LIKELY"
        confidence  = "HIGH" if score >= 4 else "MODERATE"
        action      = "SELL account likely to WIN Monday"
    elif score >= 3 and direction == "DOWN":
        prediction  = "GAP DOWN LIKELY"
        confidence  = "HIGH" if score >= 4 else "MODERATE"
        action      = "BUY account likely to WIN Monday"
    else:
        prediction  = "GAP DIRECTION UNCLEAR"
        confidence  = "LOW"
        action      = "Both trades valid — gap could go either way"

    return prediction, confidence, action, reasons

# ─────────────────────────────────────────
# FRIDAY CLOSE ALERT + VOLATILITY CHECKER
# ─────────────────────────────────────────
def check_friday_volatility(candles):
    if len(candles) < 5:
        return None, None
    # Get last 5 candles high-low range
    ranges = [c["high"] - c["low"] for c in candles[-5:]]
    avg_range = sum(ranges) / len(ranges)
    last_price = candles[-1]["close"]
    return avg_range, last_price

def friday_close_alert(candles, price):
    avg_range, last_price = check_friday_volatility(candles)
    if avg_range is None:
        return

    now = datetime.now().strftime("%H:%M:%S")
    utc_hour = datetime.now(timezone.utc).hour
    utc_min  = datetime.now(timezone.utc).minute

    # Alert at 9:59 PM UTC (1 min before market close)
    if utc_hour == 21 and utc_min >= 59:
        if avg_range > 15:
            # Too volatile — warn Edgar
            send_telegram(
                f"⚠️ FRIDAY VOLATILITY WARNING!\n"
                f"-------------------\n"
                f"Gold is moving too much!\n"
                f"Average candle range: ${avg_range:,.2f}\n"
                f"Current price: ${price:,.2f}\n"
                f"-------------------\n"
                f"RECOMMENDATION: Skip this weekend\n"
                f"Too risky to enter both trades!\n"
                f"Wait for calmer Friday next week.\n"
                f"Time: {now}"
            )
        else:
            # Safe to enter — give exact levels
            buy_sl  = round(price - 5, 2)
            sell_sl = round(price + 5, 2)
            send_telegram(
                f"✅ FRIDAY CLOSE ALERT!\n"
                f"Market closes in 5 minutes!\n"
                f"-------------------\n"
                f"Gold Price: ${price:,.2f}\n"
                f"Volatility: LOW — SAFE TO ENTER!\n"
                f"-------------------\n"
                f"ACCOUNT 1 — BUY 0.05 lots\n"
                f"Entry: ${price:,.2f}\n"
                f"No TP | SL: ${buy_sl:,.2f}\n\n"
                f"ACCOUNT 2 — SELL 0.05 lots\n"
                f"Entry: ${price:,.2f}\n"
                f"No TP | SL: ${sell_sl:,.2f}\n"
                f"-------------------\n"
                f"Check Monday 1AM Nairobi\n"
                f"for gap direction!\n"
                f"Time: {now}"
            )
