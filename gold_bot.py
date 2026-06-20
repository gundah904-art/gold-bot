import os
import requests
import time
import asyncio
from datetime import datetime, timezone

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
CHECK_EVERY    = 900   # 15 minutes
GAP_THRESHOLD  = 2.0
SWING_LOOKBACK = 3
ZONE_LOOKBACK  = 30     # candles to scan for support/resistance zones
AUTO_TRADE     = True   # set False to only receive signals, no auto trading

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

    # Resistance = strongest cluster of recent highs (top 20%)
    sorted_highs = sorted(highs, reverse=True)
    resistance = round(sum(sorted_highs[:max(2, len(sorted_highs)//5)]) / max(2, len(sorted_highs)//5), 2)

    # Support = strongest cluster of recent lows (bottom 20%)
    sorted_lows = sorted(lows)
    support = round(sum(sorted_lows[:max(2, len(sorted_lows)//5)]) / max(2, len(sorted_lows)//5), 2)

    # Demand zone: lowest 3-candle consolidation before an upward push
    demand_zone = None
    for i in range(len(recent) - 4, 2, -1):
        block = recent[i-3:i]
        push  = recent[i]
        block_range = max(c["high"] for c in block) - min(c["low"] for c in block)
        avg_range   = sum(c["high"] - c["low"] for c in recent) / len(recent)
        if block_range < avg_range * 0.8 and push["close"] > max(c["high"] for c in block):
            demand_zone = round(min(c["low"] for c in block), 2)
            break

    # Supply zone: lowest 3-candle consolidation before a downward push
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
# MULTI-TIMEFRAME ANALYSIS
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
    if total_buy < 3 and total_sell < 3:
        return "HOLD", None, None, trend_15m, trend_1h, trend_4h

    direction = "BUY" if total_buy > total_sell else "SELL"
    if direction == "BUY":
        tf_count = sum([buy_15m>=2, buy_1h>=2, buy_4h>=2])
    else:
        tf_count = sum([sell_15m>=2, sell_1h>=2, sell_4h>=2])

    trade_type = "SWING" if tf_count==3 else ("DAY" if tf_count==2 else "SCALP")
    return direction, trade_type, tf_count, trend_15m, trend_1h, trend_4h

# ─────────────────────────────────────────
# METAAPI — PLACE TRADE
# ─────────────────────────────────────────
async def _place_trade_async(signal, lot, tp, sl):
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

        if signal == "BUY":
            await connection.create_market_buy_order("XAUUSD", lot, stop_loss=sl, take_profit=tp)
        else:
            await connection.create_market_sell_order("XAUUSD", lot, stop_loss=sl, take_profit=tp)

        await api.close()
        return True
    except Exception as e:
        print(f"MetaAPI trade error: {e}")
        return False

def place_trade(signal, lot, tp, sl):
    if not AUTO_TRADE:
        return False
    try:
        return asyncio.run(_place_trade_async(signal, lot, tp, sl))
    except Exception as e:
        print(f"Trade wrapper error: {e}")
        return False

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
# MAIN LOOP
# ─────────────────────────────────────────
def main():
    print("Edgar's Auto-Trading Multi-Timeframe Gold Bot Started!")
    send_telegram(
        "Hello Edgar!\n"
        "Auto-Trading Gold Bot is LIVE!\n"
        "Strategy: SMC - Liquidity + BOS + FVG\n"
        "Timeframes: 15min + 1hr + 4hr\n"
        "Now marking Support/Resistance + Supply/Demand zones!\n"
        "Trades placed AUTOMATICALLY on Just Markets!\n"
        f"Account: {MT_LOGIN} ({MT_SERVER})\n"
        "Sessions: Tokyo + London + New York"
    )

    in_trade = False
    trade_type = None
    entry_price = tp_price = sl_price = None
    last_signal = None
    last_session_notified = None
    friday_close = None
    gap_traded_today = False

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

        if is_monday() and not gap_traded_today and friday_close and price:
            gap = price - friday_close
            gap_size = abs(gap)
            if gap_size >= GAP_THRESHOLD and not in_trade:
                gap_signal = "SELL" if gap > 0 else "BUY"
                entry_price = price
                tp_price = round(friday_close, 2)
                sl_price = round(price-5,2) if gap_signal=="BUY" else round(price+5,2)
                trade_type = "GAP"
                in_trade = True
                gap_traded_today = True
                lot = TRADE_SETTINGS["GAP"]["lot"]
                send_telegram(
                    f"MONDAY GAP - {gap_signal}\nGap: ${gap_size:,.2f}\nEntry: ${entry_price:,.2f}\n"
                    f"TP: ${tp_price:,.2f}\nSL: ${sl_price:,.2f}\nLot: {lot}\nPlacing trade automatically..."
                )
                success = place_trade(gap_signal, lot, tp_price, sl_price)
                send_telegram(f"TRADE PLACED! {gap_signal} XAUUSD" if success else "Auto-trade failed - place manually!")

        if datetime.now(timezone.utc).weekday() == 1:
            gap_traded_today = False

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

        if in_trade:
            print(f"In {trade_type} | TP:{tp_price} SL:{sl_price}")
            if trade_type in ["BUY","GAP"]:
                if last_high >= tp_price:
                    send_telegram(f"TAKE PROFIT HIT!\nEntry: ${entry_price:,.2f}\nExit: ${tp_price:,.2f}\nTime: {now}")
                    in_trade = False
                elif last_low <= sl_price:
                    send_telegram(f"STOP LOSS HIT!\nEntry: ${entry_price:,.2f}\nExit: ${sl_price:,.2f}\nTime: {now}")
                    in_trade = False
            elif trade_type == "SELL":
                if last_low <= tp_price:
                    send_telegram(f"TAKE PROFIT HIT!\nEntry: ${entry_price:,.2f}\nExit: ${tp_price:,.2f}\nTime: {now}")
                    in_trade = False
                elif last_high >= sl_price:
                    send_telegram(f"STOP LOSS HIT!\nEntry: ${entry_price:,.2f}\nExit: ${sl_price:,.2f}\nTime: {now}")
                    in_trade = False

        if not in_trade:
            direction, t_type, tf_count, t15, t1h, t4h = analyze_all_timeframes(price)
            print(f"Direction: {direction} | Type: {t_type} | TF: {tf_count}")

            if direction in ["BUY","SELL"] and direction != last_signal:
                settings = TRADE_SETTINGS[t_type]
                entry_price = price
                if direction == "BUY":
                    tp_price = round(price + settings["tp"], 2)
                    sl_price = round(price - settings["sl"], 2)
                else:
                    tp_price = round(price - settings["tp"], 2)
                    sl_price = round(price + settings["sl"], 2)
                trade_type = direction
                in_trade = True
                last_signal = direction

                # Find key zones on the 1h candles for context
                support, resistance, demand, supply = find_zones(candles_1h)
                zones_text = ""
                if support:    zones_text += f"Support:    ${support:,.2f}\n"
                if resistance: zones_text += f"Resistance: ${resistance:,.2f}\n"
                if demand:     zones_text += f"Demand Zone: ${demand:,.2f}\n"
                if supply:     zones_text += f"Supply Zone: ${supply:,.2f}\n"
                if not zones_text:
                    zones_text = "Not enough data yet\n"

                send_telegram(
                    f"NEW SIGNAL - {direction} ({settings['label']})\n"
                    f"Entry: ${entry_price:,.2f}\n"
                    f"TP: ${tp_price:,.2f}\n"
                    f"SL: ${sl_price:,.2f}\n"
                    f"Lot: {settings['lot']}\n"
                    f"Timeframes aligned: {tf_count}/3\n"
                    f"-------------------\n"
                    f"{zones_text}"
                    f"-------------------\n"
                    f"Placing trade automatically...\n"
                    f"Time: {now}"
                )
                success = place_trade(direction, settings["lot"], tp_price, sl_price)
                send_telegram(f"TRADE PLACED! {direction} XAUUSD" if success else "Auto-trade failed - place manually!")

        time.sleep(CHECK_EVERY)

if __name__ == "__main__":
    main()
