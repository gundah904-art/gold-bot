import requests
import time
import asyncio
from datetime import datetime, timezone

# ─────────────────────────────────────────
# YOUR CREDENTIALS
# ─────────────────────────────────────────
TELEGRAM_TOKEN = "8772845154:AAEOotdBk-Qm1Vpnn_z-mht-KJxoT2ysDSE"
CHAT_ID        = "8910984306"

METAAPI_TOKEN = "eyJhbGciOiJSUzUxMiIsInR5cCI6IkpXVCJ9.eyJfaWQiOiI3NzdjNzcxOGU5MzgwZjRlZWIxODVlYTc2MTFhM2I1MiIsImFjY2Vzc1J1bGVzIjpbeyJpZCI6InRyYWRpbmctYWNjb3VudC1tYW5hZ2VtZW50LWFwaSIsIm1ldGhvZHMiOlsidHJhZGluZy1hY2NvdW50LW1hbmFnZW1lbnQtYXBpOnJlc3Q6cHVibGljOio6KiJdLCJyb2xlcyI6WyJyZWFkZXIiLCJ3cml0ZXIiXSwicmVzb3VyY2VzIjpbIio6JFVTRVJfSUQkOioiXX0seyJpZCI6Im1ldGFhcGktcmVzdC1hcGkiLCJtZXRob2RzIjpbIm1ldGFhcGktYXBpOnJlc3Q6cHVibGljOio6KiJdLCJyb2xlcyI6WyJyZWFkZXIiLCJ3cml0ZXIiXSwicmVzb3VyY2VzIjpbIio6JFVTRVJfSUQkOioiXX0seyJpZCI6Im1ldGFhcGktcnBjLWFwaSIsIm1ldGhvZHMiOlsibWV0YWFwaS1hcGk6d3M6cHVibGljOio6KiJdLCJyb2xlcyI6WyJyZWFkZXIiLCJ3cml0ZXIiXSwicmVzb3VyY2VzIjpbIio6JFVTRVJfSUQkOioiXX0seyJpZCI6Im1ldGFhcGktcmVhbC10aW1lLXN0cmVhbWluZy1hcGkiLCJtZXRob2RzIjpbIm1ldGFhcGktYXBpOndzOnB1YmxpYzoqOioiXSwicm9sZXMiOlsicmVhZGVyIiwid3JpdGVyIl0sInJlc291cmNlcyI6WyIqOiRVU0VSX0lEJDoqIl19LHsiaWQiOiJtZXRhc3RhdHMtYXBpIiwibWV0aG9kcyI6WyJtZXRhc3RhdHMtYXBpOnJlc3Q6cHVibGljOio6KiJdLCJyb2xlcyI6WyJyZWFkZXIiLCJ3cml0ZXIiXSwicmVzb3VyY2VzIjpbIio6JFVTRVJfSUQkOioiXX0seyJpZCI6InJpc2stbWFuYWdlbWVudC1hcGkiLCJtZXRob2RzIjpbInJpc2stbWFuYWdlbWVudC1hcGk6cmVzdDpwdWJsaWM6KjoqIl0sInJvbGVzIjpbInJlYWRlciIsIndyaXRlciJdLCJyZXNvdXJjZXMiOlsiKjokVVNFUl9JRCQ6KiJdfSx7ImlkIjoiY29weWZhY3RvcnktYXBpIiwibWV0aG9kcyI6WyJjb3B5ZmFjdG9yeS1hcGk6cmVzdDpwdWJsaWM6KjoqIl0sInJvbGVzIjpbInJlYWRlciIsIndyaXRlciJdLCJyZXNvdXJjZXMiOlsiKjokVVNFUl9JRCQ6KiJdfSx7ImlkIjoibXQtbWFuYWdlci1hcGkiLCJtZXRob2RzIjpbIm10LW1hbmFnZXItYXBpOnJlc3Q6ZGVhbGluZzoqOioiLCJtdC1tYW5hZ2VyLWFwaTpyZXN0OnB1YmxpYzoqOioiXSwicm9sZXMiOlsicmVhZGVyIiwid3JpdGVyIl0sInJlc291cmNlcyI6WyIqOiRVU0VSX0lEJDoqIl19LHsiaWQiOiJiaWxsaW5nLWFwaSIsIm1ldGhvZHMiOlsiYmlsbGluZy1hcGk6cmVzdDpwdWJsaWM6KjoqIl0sInJvbGVzIjpbInJlYWRlciJdLCJyZXNvdXJjZXMiOlsiKjokVVNFUl9JRCQ6KiJdfV0sImlnbm9yZVJhdGVMaW1pdHMiOmZhbHNlLCJ0b2tlbklkIjoiMjAyMTAyMTMiLCJpbXBlcnNvbmF0ZWQiOmZhbHNlLCJyZWFsVXNlcklkIjoiNzc3Yzc3MThlOTM4MGY0ZWViMTg1ZWE3NjExYTNiNTIiLCJpYXQiOjE3ODAzMDE5MjB9.cO-_ODe7O7kioipqMx2WmdBZhYHMx4VCKA2D5tKpR8J1TEOUK9Wtik3eNbRbGNdw8BcCpfWdc-GaasKSojb_DgvP2X-Le8DrZXgDzaP2YzAizfswQ2BhF65YZIjaVsXRNn3m1bqb5nZ0_aEjx0NbjTubD2steI2MuMkavZ1OgBUoqqaSBCXwaWuMbfKqtvtv-SIr6vQTb8rxVZDKvFd6YDxFnxALkdYeJxHwSuvaScxusSMk2KnPrlDEf1OomRrBaejYZliM8ej-iH3jYp6RsiZHO3_KOv2F27ObUoSkgoh_xOhTLURc3UqAmdwqt2LeUe5jJrWn_JRgh5JIfWQd6VE-UDBaBGedpiCKFT3d9-Xp8_hbZ16Qdj_gvhMI8dbor9cxn_FAxR7FyjxbNuzAyzNInrjOWPop48R6vpOLWrx_kPmrxqYulS1BUTyu_KoqFj2-Hzi9Sx5T0Qjo2letrWijSXgzE5lBsngcxKDkhnS7q07b2bHldMkIlyfZ7sB_eg4R1cAfHhq8t32noIqAQk44KGuWPLj41Q3b3tRL81C84we4cXDHiBKYQNGXCcczTZYtnmNypv-tg8H5Qtmgdx52ATz8Y7ncLfTF_pk62VAMvnmoQsZQST9rHsAuvxhJFHK04ZtuM0KUJwceYsFGkXwVU-jt170JevuB5h_x9RE"
MT_LOGIN      = "1200111117"
MT_SERVER     = "JustMarkets-Demo3"
MT_PASSWORD   = "Junior_7856"

# ─────────────────────────────────────────
# SETTINGS
# ─────────────────────────────────────────
CHECK_EVERY    = 900   # 15 minutes
GAP_THRESHOLD  = 2.0
SWING_LOOKBACK = 3
ZONE_LOOKBACK  = 30     # candles to scan for support/resistance zones
AUTO_TRADE     = True   # set False to only receive signals, no auto trading
POSITIONS_PER_SIGNAL = 5  # how many identical orders to fire per signal

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
    "ZONE":  {"tp": 15, "sl": 6,  "lot": 0.02, "label": "Demand/Supply Zone"},
}

ZONE_TOUCH_DISTANCE = 3.0   # price must be within $3 of a zone to trigger

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
# ZONE TRADING SIGNAL (separate from SMC)
# Trades ONLY based on price reacting at a
# demand zone (BUY) or supply zone (SELL).
# Independent of Liquidity/BOS/FVG signal.
# ─────────────────────────────────────────
def get_zone_signal(price):
    support, resistance, demand, supply = find_zones(candles_1h)

    # Prefer demand/supply zones over plain support/resistance
    buy_level  = demand  if demand  else support
    sell_level = supply  if supply  else resistance

    if buy_level and abs(price - buy_level) <= ZONE_TOUCH_DISTANCE:
        return "BUY", buy_level, support, resistance, demand, supply
    if sell_level and abs(price - sell_level) <= ZONE_TOUCH_DISTANCE:
        return "SELL", sell_level, support, resistance, demand, supply

    return None, None, support, resistance, demand, supply


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
    if total_buy < 2 and total_sell < 2:
        return "HOLD", None, None, trend_15m, trend_1h, trend_4h

    direction = "BUY" if total_buy > total_sell else "SELL"
    if direction == "BUY":
        tf_count = sum([buy_15m>=1, buy_1h>=1, buy_4h>=1])
    else:
        tf_count = sum([sell_15m>=1, sell_1h>=1, sell_4h>=1])

    trade_type = "SWING" if tf_count==3 else ("DAY" if tf_count==2 else "SCALP")
    return direction, trade_type, tf_count, trend_15m, trend_1h, trend_4h

# ─────────────────────────────────────────
# METAAPI — PLACE TRADE
# ─────────────────────────────────────────
async def _get_connection():
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
    return api, connection

async def _place_trade_async(signal, lot, tp, sl, count=1):
    try:
        api, connection = await _get_connection()
        placed = 0
        for _ in range(count):
            try:
                if signal == "BUY":
                    await connection.create_market_buy_order("XAUUSD", lot, stop_loss=sl, take_profit=tp)
                else:
                    await connection.create_market_sell_order("XAUUSD", lot, stop_loss=sl, take_profit=tp)
                placed += 1
            except Exception as order_err:
                print(f"Order {placed+1}/{count} failed: {order_err}")
        await api.close()
        return placed
    except Exception as e:
        print(f"MetaAPI trade error: {e}")
        return 0

def place_trade(signal, lot, tp, sl, count=1):
    if not AUTO_TRADE:
        return 0
    try:
        return asyncio.run(_place_trade_async(signal, lot, tp, sl, count))
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
        "Trades placed AUTOMATICALLY on Just Markets!\n"
        f"Account: {MT_LOGIN} ({MT_SERVER})\n"
        "Sessions: Tokyo + London + New York"
    )

    # Independent trade state per strategy
    gap_in_trade = zone_in_trade = smc_in_trade = False
    gap_type = zone_type = smc_type = None
    gap_entry = gap_tp = gap_sl = None
    zone_entry = zone_tp = zone_sl = None
    smc_entry = smc_tp = smc_sl = None

    last_smc_signal = None
    last_zone_signal = None
    last_session_notified = None
    friday_close = None
    gap_traded_today = False

    while True:
        now = datetime.now().strftime("%H:%M:%S")
        trading, session_name = is_trading_session()

        price = get_gold_price()
        if price:
            build_candles(price)
            print(f"[{now}] Gold: ${price:,.2f} | 15m:{len(candles_15m)} 1h:{len(candles_1h)} 4h:{len(candles_4h)} "
                  f"| GAP:{gap_in_trade} ZONE:{zone_in_trade} SMC:{smc_in_trade}")

        # ── FRIDAY ALERT ──
        if is_friday() and price:
            friday_close = price
            friday_close_alert(price)

        # ── MONDAY GAP STRATEGY (own position slot) ──
        if is_monday() and not gap_traded_today and friday_close and price and not gap_in_trade:
            gap = price - friday_close
            gap_size = abs(gap)
            if gap_size >= GAP_THRESHOLD:
                gap_signal = "SELL" if gap > 0 else "BUY"
                gap_entry = price
                gap_tp = round(friday_close, 2)
                gap_sl = round(price-5,2) if gap_signal=="BUY" else round(price+5,2)
                gap_type = gap_signal
                gap_in_trade = True
                gap_traded_today = True
                lot = TRADE_SETTINGS["GAP"]["lot"]
                send_telegram(
                    f"MONDAY GAP - {gap_signal}\nGap: ${gap_size:,.2f}\nEntry: ${gap_entry:,.2f}\n"
                    f"TP: ${gap_tp:,.2f}\nSL: ${gap_sl:,.2f}\nLot: {lot}\nPlacing trade automatically..."
                )
                success = place_trade(gap_signal, lot, gap_tp, gap_sl, POSITIONS_PER_SIGNAL)
                send_telegram(f"TRADE PLACED! {success}/{POSITIONS_PER_SIGNAL} orders filled - {gap_signal} XAUUSD (GAP)" if success else "Auto-trade failed - place manually!")

        if datetime.now(timezone.utc).weekday() == 1:
            gap_traded_today = False

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

        # ── MONITOR GAP TRADE ──
        if gap_in_trade:
            print(f"GAP trade | {gap_type} | TP:{gap_tp} SL:{gap_sl}")
            hit_tp = last_high >= gap_tp if gap_type == "BUY" else last_low <= gap_tp
            hit_sl = last_low <= gap_sl if gap_type == "BUY" else last_high >= gap_sl
            if hit_tp:
                send_telegram(f"TAKE PROFIT HIT! (GAP)\nEntry: ${gap_entry:,.2f}\nExit: ${gap_tp:,.2f}\nTime: {now}")
                gap_in_trade = False
            elif hit_sl:
                send_telegram(f"STOP LOSS HIT! (GAP)\nEntry: ${gap_entry:,.2f}\nExit: ${gap_sl:,.2f}\nTime: {now}")
                gap_in_trade = False

        # ── MONITOR ZONE TRADE ──
        if zone_in_trade:
            print(f"ZONE trade | {zone_type} | TP:{zone_tp} SL:{zone_sl}")
            hit_tp = last_high >= zone_tp if zone_type == "BUY" else last_low <= zone_tp
            hit_sl = last_low <= zone_sl if zone_type == "BUY" else last_high >= zone_sl
            if hit_tp:
                send_telegram(f"TAKE PROFIT HIT! (ZONE)\nEntry: ${zone_entry:,.2f}\nExit: ${zone_tp:,.2f}\nTime: {now}")
                zone_in_trade = False
            elif hit_sl:
                send_telegram(f"STOP LOSS HIT! (ZONE)\nEntry: ${zone_entry:,.2f}\nExit: ${zone_sl:,.2f}\nTime: {now}")
                zone_in_trade = False

        # ── MONITOR SMC TRADE ──
        if smc_in_trade:
            print(f"SMC trade | {smc_type} | TP:{smc_tp} SL:{smc_sl}")
            hit_tp = last_high >= smc_tp if smc_type == "BUY" else last_low <= smc_tp
            hit_sl = last_low <= smc_sl if smc_type == "BUY" else last_high >= smc_sl
            if hit_tp:
                send_telegram(f"TAKE PROFIT HIT! (SMC)\nEntry: ${smc_entry:,.2f}\nExit: ${smc_tp:,.2f}\nTime: {now}")
                smc_in_trade = False
            elif hit_sl:
                send_telegram(f"STOP LOSS HIT! (SMC)\nEntry: ${smc_entry:,.2f}\nExit: ${smc_sl:,.2f}\nTime: {now}")
                smc_in_trade = False

        # ── STRATEGY 1: ZONE SIGNAL (only if zone slot free) ──
        zone_dir, zone_level, support, resistance, demand, supply = get_zone_signal(price)
        print(f"Zone check -> {zone_dir} at {zone_level} | Support:{support} Resistance:{resistance} Demand:{demand} Supply:{supply}")

        if not zone_in_trade and zone_dir in ["BUY", "SELL"] and zone_dir != last_zone_signal:
            settings = TRADE_SETTINGS["ZONE"]
            zone_entry = price
            if zone_dir == "BUY":
                zone_tp = round(price + settings["tp"], 2)
                zone_sl = round(price - settings["sl"], 2)
            else:
                zone_tp = round(price - settings["tp"], 2)
                zone_sl = round(price + settings["sl"], 2)
            zone_type = zone_dir
            zone_in_trade = True
            last_zone_signal = zone_dir

            zones_text = ""
            if support:    zones_text += f"Support:    ${support:,.2f}\n"
            if resistance: zones_text += f"Resistance: ${resistance:,.2f}\n"
            if demand:     zones_text += f"Demand Zone: ${demand:,.2f}\n"
            if supply:     zones_text += f"Supply Zone: ${supply:,.2f}\n"

            send_telegram(
                f"ZONE SIGNAL - {zone_dir}\n"
                f"Reacted at: ${zone_level:,.2f}\n"
                f"-------------------\nEntry: ${zone_entry:,.2f}\nTP: ${zone_tp:,.2f}\nSL: ${zone_sl:,.2f}\n"
                f"Lot: {settings['lot']}\n-------------------\n"
                f"KEY ZONES:\n{zones_text}"
                f"-------------------\nSession: {session_name}\nPlacing trade automatically...\nTime: {now}"
            )
            success = place_trade(zone_dir, settings["lot"], zone_tp, zone_sl, POSITIONS_PER_SIGNAL)
            send_telegram(f"TRADE PLACED!\n{success}/{POSITIONS_PER_SIGNAL} orders filled\n{zone_dir} XAUUSD @ ${price:,.2f} (Zone trade)" if success else "Auto-trade failed - place manually on Just Markets!")
        elif zone_dir is None:
            last_zone_signal = None

        # ── STRATEGY 2: SMC SIGNAL (only if SMC slot free) ──
        direction, t_type, tf_count, t15, t1h, t4h = analyze_all_timeframes(price)
        print(f"SMC Direction: {direction} | Type: {t_type} | TF: {tf_count}")

        if not smc_in_trade and direction in ["BUY","SELL"] and direction != last_smc_signal:
            settings = TRADE_SETTINGS[t_type]
            smc_entry = price
            if direction == "BUY":
                smc_tp = round(price + settings["tp"], 2)
                smc_sl = round(price - settings["sl"], 2)
            else:
                smc_tp = round(price - settings["tp"], 2)
                smc_sl = round(price + settings["sl"], 2)
            smc_type = direction
            smc_in_trade = True
            last_smc_signal = direction

            zones_text = ""
            if support:    zones_text += f"Support:    ${support:,.2f}\n"
            if resistance: zones_text += f"Resistance: ${resistance:,.2f}\n"
            if demand:     zones_text += f"Demand Zone: ${demand:,.2f}\n"
            if supply:     zones_text += f"Supply Zone: ${supply:,.2f}\n"
            if not zones_text:
                zones_text = "Not enough data yet\n"

            send_telegram(
                f"SMC SIGNAL - {direction}\nTrade Type: {settings['label']}\nTF aligned: {tf_count}/3\n"
                f"-------------------\nEntry: ${smc_entry:,.2f}\nTP: ${smc_tp:,.2f}\nSL: ${smc_sl:,.2f}\n"
                f"Lot: {settings['lot']}\n-------------------\n"
                f"KEY ZONES:\n{zones_text}"
                f"-------------------\n15m:{t15} 1h:{t1h} 4h:{t4h}\n"
                f"Session: {session_name}\nPlacing trade automatically...\nTime: {now}"
            )
            success = place_trade(direction, settings["lot"], smc_tp, smc_sl, POSITIONS_PER_SIGNAL)
            send_telegram(f"TRADE PLACED!\n{success}/{POSITIONS_PER_SIGNAL} orders filled\n{direction} XAUUSD @ ${price:,.2f} (SMC trade)" if success else "Auto-trade failed - place manually on Just Markets!")
        elif direction == "HOLD":
            last_smc_signal = None

        time.sleep(CHECK_EVERY)

if __name__ == "__main__":
    main()
