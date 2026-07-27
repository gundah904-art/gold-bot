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
    "TELEGRAM_TOKEN": TELEGRAM_TOKEN, "CHAT_ID": CHAT_ID,
    "METAAPI_TOKEN": METAAPI_TOKEN, "MT_LOGIN": MT_LOGIN,
    "MT_SERVER": MT_SERVER, "MT_PASSWORD": MT_PASSWORD
}.items() if not v]
if _missing:
    raise RuntimeError(f"Missing env vars: {', '.join(_missing)}")

# ─────────────────────────────────────────
# SETTINGS
# ─────────────────────────────────────────
CHECK_EVERY       = 900
SWING_LOOKBACK    = 3
ZONE_LOOKBACK     = 30
ZONE_TOLERANCE    = 3.0
AUTO_TRADE        = True
ORDERS_PER_SIGNAL = 20
TRADE_LOG_FILE    = "trade_log.csv"
WEEKLY_DAY        = 6
WEEKLY_HOUR       = 20

SESSIONS = [
    {"name": "Tokyo",    "start": 0,  "end": 9},
    {"name": "London",   "start": 7,  "end": 16},
    {"name": "New York", "start": 12, "end": 21},
]

TRADE_SETTINGS = {
    "SCALP": {"tp": 10, "sl": 5, "lot": 0.01, "label": "Scalp (15min)"},
    "DAY":   {"tp": 10, "sl": 5, "lot": 0.02, "label": "Day Trade (1hr)"},
    "SWING": {"tp": 10, "sl": 5, "lot": 0.03, "label": "Swing (4hr+)"},
}

# ─────────────────────────────────────────
# TELEGRAM
# ─────────────────────────────────────────
def send_telegram(msg):
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                      data={"chat_id": CHAT_ID, "text": msg}, timeout=10)
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
candles_5m, candles_15m, candles_1h, candles_4h = [], [], [], []
last_5m_time = last_15m_time = last_1h_time = last_4h_time = None

def build_candles(price):
    global candles_5m, candles_15m, candles_1h, candles_4h
    global last_5m_time, last_15m_time, last_1h_time, last_4h_time
    now = datetime.now(timezone.utc)
    t5 = now.replace(minute=(now.minute//5)*5, second=0, microsecond=0)
    if last_5m_time is None or t5 != last_5m_time:
        candles_5m.append({"open":price,"high":price,"low":price,"close":price}); last_5m_time=t5
    else:
        c=candles_5m[-1]; c["high"]=max(c["high"],price); c["low"]=min(c["low"],price); c["close"]=price
    if len(candles_5m)>200: candles_5m.pop(0)
    t15 = now.replace(minute=(now.minute//15)*15, second=0, microsecond=0)
    if last_15m_time is None or t15 != last_15m_time:
        candles_15m.append({"open":price,"high":price,"low":price,"close":price,"ticks":1}); last_15m_time=t15
    else:
        c=candles_15m[-1]; c["high"]=max(c["high"],price); c["low"]=min(c["low"],price); c["close"]=price
        c["ticks"]=c.get("ticks",0)+1
    if len(candles_15m)>100: candles_15m.pop(0)
    t1h = now.replace(minute=0, second=0, microsecond=0)
    if last_1h_time is None or t1h != last_1h_time:
        candles_1h.append({"open":price,"high":price,"low":price,"close":price}); last_1h_time=t1h
    else:
        c=candles_1h[-1]; c["high"]=max(c["high"],price); c["low"]=min(c["low"],price); c["close"]=price
    if len(candles_1h)>100: candles_1h.pop(0)
    t4h = now.replace(hour=(now.hour//4)*4, minute=0, second=0, microsecond=0)
    if last_4h_time is None or t4h != last_4h_time:
        candles_4h.append({"open":price,"high":price,"low":price,"close":price}); last_4h_time=t4h
    else:
        c=candles_4h[-1]; c["high"]=max(c["high"],price); c["low"]=min(c["low"],price); c["close"]=price
    if len(candles_4h)>100: candles_4h.pop(0)

# ─────────────────────────────────────────
# ORDER FLOW INDICATOR — imbalance + volume spike (validated on real GC data)
# ─────────────────────────────────────────
OF_IMBALANCE_THRESHOLD = 0.8   # how close to the bar's extreme the close must be
OF_INTENSITY_THRESHOLD = 1.5   # volume vs rolling baseline, in multiples

def order_flow_imbalance(bar):
    """Where close sits within the bar's range. +1 = closed at high (buy pressure),
    -1 = closed at low (sell pressure). Used as a FADE signal — extremes tend to snap back."""
    rng = bar["high"] - bar["low"]
    if rng <= 0: return 0.0
    close_pos = (bar["close"] - bar["low"]) / rng
    return (close_pos - 0.5) * 2

def trade_intensity(candles, window=20):
    """Current bar's tick volume vs. rolling baseline. >1.5 = unusually active bar."""
    if len(candles) < window + 1: return None
    baseline = sum(c.get("ticks", 1) for c in candles[-window-1:-1]) / window
    if baseline <= 0: return None
    return candles[-1].get("ticks", 1) / baseline

def order_flow_signal(candles):
    """
    Returns 'BULLISH', 'BEARISH', or None.
    Fires only when a strong imbalance bar (near its high/low) coincides with
    a volume spike — the one combination that showed a real (if thin) edge
    on real COMEX 1-minute data. This is a FADE signal: closed near high on
    heavy volume -> expect reversal down, and vice versa.
    """
    if len(candles) < 21: return None
    imb = order_flow_imbalance(candles[-1])
    intensity = trade_intensity(candles)
    if intensity is None or intensity < OF_INTENSITY_THRESHOLD:
        return None
    if imb > OF_IMBALANCE_THRESHOLD: return "BEARISH"
    if imb < -OF_IMBALANCE_THRESHOLD: return "BULLISH"
    return None

def detect_liquidity(c):
    if len(c)<6: return None
    lb=c[-6:-1]; rh=max(x["high"] for x in lb); rl=min(x["low"] for x in lb)
    p,l=c[-2],c[-1]
    if p["high"]>rh and l["close"]<p["close"]: return "BEARISH"
    if p["low"]<rl and l["close"]>p["close"]: return "BULLISH"
    return None

def detect_bos(c):
    if len(c)<SWING_LOOKBACK*2+1: return None
    r=c[-(SWING_LOOKBACK*2+1):-1]
    sh=max(x["high"] for x in r); sl=min(x["low"] for x in r); lc=c[-1]["close"]
    if lc>sh: return "BULLISH"
    if lc<sl: return "BEARISH"
    return None

def detect_fvg(c):
    if len(c)<3: return None
    c1,c3=c[-3],c[-1]
    if c1["high"]<c3["low"]: return "BULLISH"
    if c1["low"]>c3["high"]: return "BEARISH"
    return None

def get_trend(c):
    if len(c)<5: return None
    cl=[x["close"] for x in c[-5:]]
    if cl[-1]>cl[0]: return "BULLISH"
    if cl[-1]<cl[0]: return "BEARISH"
    return "NEUTRAL"



# ─────────────────────────────────────────
# ICT INDICATORS
# ─────────────────────────────────────────
def detect_market_structure(c):
    """ICT: Higher Highs + Higher Lows = BULLISH, Lower Highs + Lower Lows = BEARISH."""
    if len(c)<6: return None
    highs=[x["high"] for x in c[-6:]]; lows=[x["low"] for x in c[-6:]]
    if highs[-1]>highs[-3] and lows[-1]>lows[-3]: return "BULLISH"
    if highs[-1]<highs[-3] and lows[-1]<lows[-3]: return "BEARISH"
    return None

def detect_order_block(c):
    """ICT: Last opposing candle before a strong push."""
    if len(c)<3: return None
    c1,c2=c[-3],c[-2]
    if c1["close"]<c1["open"] and c2["close"]>c2["open"] and c2["close"]>c1["high"]: return "BULLISH"
    if c1["close"]>c1["open"] and c2["close"]<c2["open"] and c2["close"]<c1["low"]: return "BEARISH"
    return None

def detect_displacement(c):
    """ICT: Strong impulsive move at least 3x average candle size."""
    if len(c)<5: return None
    avg=sum(x["high"]-x["low"] for x in c[-5:-1])/4
    last=c[-1]
    if last["high"]-last["low"]>=avg*3:
        return "BULLISH" if last["close"]>last["open"] else "BEARISH"
    return None

# ─────────────────────────────────────────
# ZONES
# ─────────────────────────────────────────
def find_zones(candles, lookback=ZONE_LOOKBACK):
    if len(candles)<10: return None,None,None,None
    recent=candles[-lookback:] if len(candles)>=lookback else candles
    highs=[c["high"] for c in recent]; lows=[c["low"] for c in recent]
    sh=sorted(highs,reverse=True); resistance=round(sum(sh[:max(2,len(sh)//5)])/max(2,len(sh)//5),2)
    sl=sorted(lows); support=round(sum(sl[:max(2,len(sl)//5)])/max(2,len(sl)//5),2)
    demand_zone=None
    for i in range(len(recent)-4,2,-1):
        block=recent[i-3:i]; push=recent[i]
        br=max(c["high"] for c in block)-min(c["low"] for c in block)
        ar=sum(c["high"]-c["low"] for c in recent)/len(recent)
        if br<ar*0.8 and push["close"]>max(c["high"] for c in block):
            demand_zone=round(min(c["low"] for c in block),2); break
    supply_zone=None
    for i in range(len(recent)-4,2,-1):
        block=recent[i-3:i]; push=recent[i]
        br=max(c["high"] for c in block)-min(c["low"] for c in block)
        ar=sum(c["high"]-c["low"] for c in recent)/len(recent)
        if br<ar*0.8 and push["close"]<min(c["low"] for c in block):
            supply_zone=round(max(c["high"] for c in block),2); break
    return support,resistance,demand_zone,supply_zone

# ─────────────────────────────────────────
# PULLBACK + SWEEP + FVG STRATEGY (validated: 60% win rate, 105 trades / 1 month on real GC data)
# ─────────────────────────────────────────
def find_fvg_live(candles_ltf, since_index, direction):
    """Look for a Fair Value Gap in `direction` among candles from since_index onward."""
    for i in range(max(2, since_index), len(candles_ltf)):
        a, c = candles_ltf[i-2], candles_ltf[i]
        if direction == "BULLISH" and a["high"] < c["low"]:
            return c
        if direction == "BEARISH" and a["low"] > c["high"]:
            return c
    return None

# ─────────────────────────────────────────
# REVERSAL STRATEGY (validated: 78.4% win rate, 227 trades / 1 month on real GC data)
# Two-stage 50% retracement rejection -> trade the reversal, not the continuation.
# ─────────────────────────────────────────
def find_last_swing_move(candles, window=5):
    """Find the most recent completed swing-high-to-swing-low (or low-to-high) move.
    Returns (direction, start_price, end_price) where direction is the ORIGINAL move's
    direction ('BEARISH' = high->low, 'BULLISH' = low->high), or None if not enough data."""
    if len(candles) < window * 2 + 2:
        return None
    swings = []
    for i in range(window, len(candles) - window):
        seg = candles[i - window:i + window + 1]
        if candles[i]["high"] == max(c["high"] for c in seg):
            swings.append((i, "high", candles[i]["high"]))
        if candles[i]["low"] == min(c["low"] for c in seg):
            swings.append((i, "low", candles[i]["low"]))
    if len(swings) < 2:
        return None
    idx1, typ1, price1 = swings[-2]
    idx2, typ2, price2 = swings[-1]
    if typ1 == "high" and typ2 == "low" and price2 < price1:
        return "BEARISH", price1, price2, idx2
    if typ1 == "low" and typ2 == "high" and price2 > price1:
        return "BULLISH", price1, price2, idx2
    return None

def analyze_reversal_signal(state):
    """
    Stateful, two-stage reversal detector on candles_5m:
    1. Find the last swing move (e.g. a bearish high->low).
    2. Wait for price to retrace to 50% of that move and CLOSE back past it
       (confirmation the first rejection held).
    3. Mark the new, smaller range (retrace high -> original low), compute ITS 50%.
    4. Wait for price to return to that new 50% -> enter trading the REVERSAL
       (i.e. buy after a bearish move, sell after a bullish move) — two rejections
       in a row is exhaustion, not continuation.
    Returns (direction, entry, target, stop) or (None, None, None, None).
    """
    c = candles_5m
    if len(c) < 15:
        return None, None, None, None, None

    if state["phase"] == "idle":
        move = find_last_swing_move(c)
        if not move:
            return None, None, None, None, None
        direction, start_price, end_price, end_idx = move
        if state.get("last_move_idx") == end_idx:
            return None, None, None, None, None  # already processed this exact move
        state["move_dir"] = direction
        state["move_start"] = start_price
        state["move_end"] = end_price
        state["last_move_idx"] = end_idx
        state["fib50"] = start_price - (start_price - end_price) * 0.5 if direction == "BEARISH" \
                          else start_price + (end_price - start_price) * 0.5
        state["retrace_extreme"] = end_price
        state["phase"] = "waiting_first_confirm"
        return None, None, None, None, None

    last = c[-1]

    if state["phase"] == "waiting_first_confirm":
        if state["move_dir"] == "BEARISH":
            state["retrace_extreme"] = max(state["retrace_extreme"], last["high"])
            if last["close"] > state["move_start"]:  # invalidated - broke past original high
                state["phase"] = "idle"; return None, None, None, None, None
            if last["high"] >= state["fib50"] and last["close"] < state["fib50"]:
                new_high = state["retrace_extreme"]
                state["new_fib"] = new_high - (new_high - state["move_end"]) * 0.5
                state["phase"] = "waiting_entry"
        else:
            state["retrace_extreme"] = min(state["retrace_extreme"], last["low"])
            if last["close"] < state["move_start"]:
                state["phase"] = "idle"; return None, None, None, None, None
            if last["low"] <= state["fib50"] and last["close"] > state["fib50"]:
                new_low = state["retrace_extreme"]
                state["new_fib"] = new_low + (state["move_end"] - new_low) * 0.5
                state["phase"] = "waiting_entry"
        return None, None, None, None, None

    if state["phase"] == "waiting_entry":
        if state["move_dir"] == "BEARISH":
            if last["close"] > state["move_start"]:
                state["phase"] = "idle"; return None, None, None, None, None
            if last["high"] >= state["new_fib"]:
                entry = state["new_fib"]
                stop = state["move_end"]
                state["phase"] = "idle"
                risk = entry - stop
                if risk > 0:
                    target1, target2 = entry + risk, entry + risk * 2  # 1:1 and 2:1
                    return "BUY", entry, target1, target2, stop
        else:
            if last["close"] < state["move_start"]:
                state["phase"] = "idle"; return None, None, None, None, None
            if last["low"] <= state["new_fib"]:
                entry = state["new_fib"]
                stop = state["move_end"]
                state["phase"] = "idle"
                risk = stop - entry
                if risk > 0:
                    target1, target2 = entry - risk, entry - risk * 2  # 1:1 and 2:1
                    return "SELL", entry, target1, target2, stop
        return None, None, None, None, None

    return None, None, None, None, None

def analyze_pullback_signal():
    """
    1H trend -> find the pullback candle (against trend) -> mark its high/low
    -> wait for a sweep of that range -> drop to 5m for an FVG in the trend
    direction -> entry there, target = opposite side of the marked range.
    Returns (direction, entry, target, stop) or (None, None, None, None).
    """
    if len(candles_1h) < 8 or len(candles_5m) < 10:
        return None, None, None, None

    trend = get_trend(candles_1h)
    if trend not in ["BULLISH", "BEARISH"]:
        return None, None, None, None

    # Find the most recent pullback candle among the last few 1H candles
    pullback_idx = None
    for i in range(len(candles_1h) - 2, max(len(candles_1h) - 8, 0), -1):
        candle = candles_1h[i]
        is_pullback = (
            (trend == "BULLISH" and candle["close"] < candle["open"]) or
            (trend == "BEARISH" and candle["close"] > candle["open"])
        )
        if is_pullback:
            pullback_idx = i
            break
    if pullback_idx is None:
        return None, None, None, None

    crt_high = candles_1h[pullback_idx]["high"]
    crt_low  = candles_1h[pullback_idx]["low"]

    # Check for the sweep in candles after the pullback candle
    swept = False
    for j in range(pullback_idx + 1, len(candles_1h)):
        if trend == "BULLISH" and candles_1h[j]["low"] < crt_low:
            swept = True; break
        if trend == "BEARISH" and candles_1h[j]["high"] > crt_high:
            swept = True; break
    if not swept:
        return None, None, None, None

    # Drop to 5m for the FVG entry
    fvg_candle = find_fvg_live(candles_5m, 0, trend)
    if not fvg_candle:
        return None, None, None, None

    entry = fvg_candle["close"]
    if trend == "BULLISH":
        target, stop = crt_high, crt_low
        if target <= entry: return None, None, None, None
        return "BUY", entry, target, stop
    else:
        target, stop = crt_low, crt_high
        if target >= entry: return None, None, None, None
        return "SELL", entry, target, stop

# ─────────────────────────────────────────
# TRADE LOG
# ─────────────────────────────────────────
trade_log=[]

def log_trade(strategy,direction,entry,exit_price,result):
    pnl=round(exit_price-entry,2) if direction=="BUY" else round(entry-exit_price,2)
    record={"timestamp":datetime.now(timezone.utc).isoformat(),"strategy":strategy,
            "direction":direction,"entry":entry,"exit":exit_price,"result":result,"pnl":pnl}
    trade_log.append(record)
    try:
        wh=not os.path.exists(TRADE_LOG_FILE)
        with open(TRADE_LOG_FILE,"a",newline="") as f:
            w=csv.DictWriter(f,fieldnames=record.keys())
            if wh: w.writeheader()
            w.writerow(record)
    except Exception as e:
        print(f"Log error: {e}")

REVERSAL_LOG_FILE = "reversal_log.jsonl"
STATE_FILE = "bot_state.json"

def save_state(smc_state, reversal_state):
    """Persist in-trade state so a restart doesn't forget an open batch of orders."""
    try:
        with open(STATE_FILE, "w") as f:
            json.dump({"smc_state": smc_state, "reversal_state": reversal_state}, f)
    except Exception as e:
        print(f"State save error: {e}")

def load_state():
    """Load persisted in-trade state on startup, if it exists."""
    if not os.path.exists(STATE_FILE):
        return None, None
    try:
        with open(STATE_FILE, "r") as f:
            data = json.load(f)
        return data.get("smc_state"), data.get("reversal_state")
    except Exception as e:
        print(f"State load error: {e}")
        return None, None

def log_reversal_result(direction, result):
    """Persist REVERSAL closes to disk so they survive bot restarts."""
    record = {"timestamp": datetime.now(timezone.utc).isoformat(), "direction": direction, "result": result}
    try:
        with open(REVERSAL_LOG_FILE, "a") as f:
            f.write(json.dumps(record) + "\n")
    except Exception as e:
        print(f"Reversal log error: {e}")

def load_reversal_results(days=7):
    """Read REVERSAL closes from disk, filtered to the last N days."""
    if not os.path.exists(REVERSAL_LOG_FILE):
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    results = []
    try:
        with open(REVERSAL_LOG_FILE, "r") as f:
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
        print(f"Reversal log read error: {e}")
    return results

def send_weekly_summary(reversal_results=[]):
    cutoff=datetime.now(timezone.utc)-timedelta(days=7)
    wt=[t for t in trade_log if datetime.fromisoformat(t["timestamp"])>=cutoff]
    # Always load REVERSAL's persisted results — don't let an empty PULLBACK log
    # short-circuit before REVERSAL is ever checked, and don't lose history on restart.
    reversal_results = load_reversal_results(days=7) or reversal_results
    if not wt and not reversal_results:
        send_telegram("WEEKLY SUMMARY\nNo trades closed in the last 7 days.")
        return
    total=len(wt); wins=sum(1 for t in wt if t["result"]=="WIN")
    wr=round(wins/total*100,1) if total else 0
    pnl=round(sum(t["pnl"] for t in wt),2)
    bs={}
    for t in wt:
        s=t["strategy"]; bs.setdefault(s,{"total":0,"wins":0,"pnl":0.0})
        bs[s]["total"]+=1; bs[s]["pnl"]+=t["pnl"]
        if t["result"]=="WIN": bs[s]["wins"]+=1
    st=""
    for s,d in bs.items():
        r=round(d["wins"]/d["total"]*100,1)
        st+=f"{s}: {d['wins']}/{d['total']} wins ({r}%) | ${d['pnl']:,.2f}\n"
    reversal_text=""
    if reversal_results:
        tt=len(reversal_results); tp=sum(1 for t in reversal_results if t["result"]=="TP")
        twr=round(tp/tt*100,1)
        verdict="⚠️ Weak — reconsider" if twr<40 else "✅ Signals valid" if twr>60 else "⚖️ Mixed"
        reversal_text=f"\n-------------------\n[REVERSAL] Win Rate: {twr}% ({tp}/{tt})\n{verdict}"
    send_telegram(f"WEEKLY SUMMARY\n-------------------\nTotal: {total} | Wins: {wins} | Losses: {total-wins}\nWin Rate: {wr}%\nNet: ${pnl:,.2f}\n-------------------\n{st}{reversal_text}")

# ─────────────────────────────────────────
# TRADE STATE
# ─────────────────────────────────────────
def new_trade_state():
    return {"in_trade":False,"trade_type":None,"entry":None,"tp":None,"sl":None,"last_signal":None}

def check_tp_sl(name,state,lh,ll,now):
    if not state["in_trade"]: return
    if state["trade_type"]=="BUY":
        tp_hit=lh>=state["tp"]; sl_hit=ll<=state["sl"]
        if tp_hit and sl_hit:
            won=lh-state["entry"]>=state["entry"]-ll
            result="WIN" if won else "LOSS"
            exit_p=state["tp"] if won else state["sl"]
            send_telegram(f"[{name}] {'TAKE PROFIT' if won else 'STOP LOSS'} HIT!\nEntry: ${state['entry']:,.2f}\nExit: ${exit_p:,.2f}\nTime: {now}")
            log_trade(name,"BUY",state["entry"],exit_p,result); state["in_trade"]=False
        elif tp_hit:
            send_telegram(f"[{name}] TAKE PROFIT HIT!\nEntry: ${state['entry']:,.2f}\nExit: ${state['tp']:,.2f}\nTime: {now}")
            log_trade(name,"BUY",state["entry"],state["tp"],"WIN"); state["in_trade"]=False
        elif sl_hit:
            send_telegram(f"[{name}] STOP LOSS HIT!\nEntry: ${state['entry']:,.2f}\nExit: ${state['sl']:,.2f}\nTime: {now}")
            log_trade(name,"BUY",state["entry"],state["sl"],"LOSS"); state["in_trade"]=False
    elif state["trade_type"]=="SELL":
        tp_hit=ll<=state["tp"]; sl_hit=lh>=state["sl"]
        if tp_hit and sl_hit:
            won=state["entry"]-ll>=lh-state["entry"]
            result="WIN" if won else "LOSS"
            exit_p=state["tp"] if won else state["sl"]
            send_telegram(f"[{name}] {'TAKE PROFIT' if won else 'STOP LOSS'} HIT!\nEntry: ${state['entry']:,.2f}\nExit: ${exit_p:,.2f}\nTime: {now}")
            log_trade(name,"SELL",state["entry"],exit_p,result); state["in_trade"]=False
        elif tp_hit:
            send_telegram(f"[{name}] TAKE PROFIT HIT!\nEntry: ${state['entry']:,.2f}\nExit: ${state['tp']:,.2f}\nTime: {now}")
            log_trade(name,"SELL",state["entry"],state["tp"],"WIN"); state["in_trade"]=False
        elif sl_hit:
            send_telegram(f"[{name}] STOP LOSS HIT!\nEntry: ${state['entry']:,.2f}\nExit: ${state['sl']:,.2f}\nTime: {now}")
            log_trade(name,"SELL",state["entry"],state["sl"],"LOSS"); state["in_trade"]=False

def check_reversal_legs(state, lh, ll, now):
    """
    REVERSAL runs two legs from the same entry/stop — 1:1 target and 2:1 target.
    Each leg closes independently (hits its own TP, or the shared SL). Only once
    BOTH legs have closed does the trade fully clear and the bot look for a new signal.
    """
    if not state["in_trade"]:
        return
    d = state["direction"]
    entry, sl = state["entry"], state["sl"]

    def leg_outcome(tp):
        if d == "BUY":
            tp_hit, sl_hit = lh >= tp, ll <= sl
        else:
            tp_hit, sl_hit = ll <= tp, lh >= sl
        if tp_hit and sl_hit:
            # both touched same bar — assume worse case (SL) since we can't know order within the bar
            return "SL", sl
        if tp_hit:
            return "TP", tp
        if sl_hit:
            return "SL", sl
        return None, None

    if not state["leg1_closed"]:
        result, exit_p = leg_outcome(state["tp1"])
        if result:
            pnl = round((exit_p-entry) if d=="BUY" else (entry-exit_p), 2)
            send_telegram(f"[REVERSAL] Leg1 (1:1) {'TAKE PROFIT' if result=='TP' else 'STOP LOSS'} HIT!\nEntry: ${entry:,.2f}\nExit: ${exit_p:,.2f}\nP&L: ${pnl:+.2f}\nTime: {now}")
            log_trade("REVERSAL-1:1", d, entry, exit_p, "WIN" if result=="TP" else "LOSS")
            state["leg1_closed"] = True

    if not state["leg2_closed"]:
        result, exit_p = leg_outcome(state["tp2"])
        if result:
            pnl = round((exit_p-entry) if d=="BUY" else (entry-exit_p), 2)
            send_telegram(f"[REVERSAL] Leg2 (2:1) {'TAKE PROFIT' if result=='TP' else 'STOP LOSS'} HIT!\nEntry: ${entry:,.2f}\nExit: ${exit_p:,.2f}\nP&L: ${pnl:+.2f}\nTime: {now}")
            log_trade("REVERSAL-2:1", d, entry, exit_p, "WIN" if result=="TP" else "LOSS")
            log_reversal_result(d, "TP" if result=="TP" else "SL")
            state["leg2_closed"] = True

    if state["leg1_closed"] and state["leg2_closed"]:
        state["in_trade"] = False

# ─────────────────────────────────────────
# METAAPI — TRADE PLACEMENT
# ─────────────────────────────────────────
async def _place(login,password,signal,lot,tp,sl,orders):
    placed=0; api=None
    try:
        from metaapi_cloud_sdk import MetaApi
        api=MetaApi(METAAPI_TOKEN,{"region":"london"})
        accounts=await api.metatrader_account_api.get_accounts_with_infinite_scroll_pagination()
        account=next((a for a in accounts if str(a.login)==str(login)),None)
        if account is None:
            account=await api.metatrader_account_api.create_account({
                "name":f"Gold Bot {login}","type":"cloud","login":login,"password":password,
                "server":MT_SERVER,"platform":"mt5","magic":123456})
        if account.state not in ["DEPLOYED","DEPLOYING"]:
            await account.deploy(); await account.wait_deployed()
        conn=account.get_rpc_connection()
        await conn.connect()
        await conn.wait_synchronized(timeout_in_seconds=30)
        symbol="XAUUSD.m"
        try:
            symbols=await conn.get_symbols()
            for s in symbols:
                if "XAU" in s and "USD" in s: symbol=s; break
        except: pass
        print(f"Symbol: {symbol}")
        for _ in range(orders):
            try:
                if signal=="BUY": await conn.create_market_buy_order(symbol,lot,stop_loss=sl,take_profit=tp)
                else: await conn.create_market_sell_order(symbol,lot,stop_loss=sl,take_profit=tp)
                placed+=1
            except Exception as e: print(f"Order failed: {e}")
        try: await conn.close()
        except: pass
    except Exception as e: print(f"MetaAPI error: {e}")
    finally:
        if api:
            try: await api.close()
            except: pass
    return placed

TRAIL_DISTANCE = 3   # $ — how far behind current price the trailing stop sits

async def _trail(login,password,trail_distance):
    api=None
    try:
        from metaapi_cloud_sdk import MetaApi
        api=MetaApi(METAAPI_TOKEN,{"region":"london"})
        accounts=await api.metatrader_account_api.get_accounts_with_infinite_scroll_pagination()
        account=next((a for a in accounts if str(a.login)==str(login)),None)
        if account is None: return
        if account.state not in ["DEPLOYED","DEPLOYING"]:
            await account.deploy(); await account.wait_deployed()
        conn=account.get_rpc_connection()
        await conn.connect()
        await conn.wait_synchronized(timeout_in_seconds=30)
        positions=await conn.get_positions()
        for p in positions:
            if "XAU" not in p.get("symbol",""): continue
            price=p.get("currentPrice")
            if price is None: continue
            cur_sl=p.get("stopLoss")
            if p.get("type")=="POSITION_TYPE_BUY":
                new_sl=round(price-trail_distance,2)
                if cur_sl is None or new_sl>cur_sl:
                    try:
                        await conn.modify_position(p["id"],stop_loss=new_sl,take_profit=p.get("takeProfit"))
                        print(f"Trailed BUY {p['id']} SL -> {new_sl}")
                    except Exception as e: print(f"Trail modify failed: {e}")
            else:
                new_sl=round(price+trail_distance,2)
                if cur_sl is None or new_sl<cur_sl:
                    try:
                        await conn.modify_position(p["id"],stop_loss=new_sl,take_profit=p.get("takeProfit"))
                        print(f"Trailed SELL {p['id']} SL -> {new_sl}")
                    except Exception as e: print(f"Trail modify failed: {e}")
        try: await conn.close()
        except: pass
    except Exception as e: print(f"Trail error: {e}")
    finally:
        if api:
            try: await api.close()
            except: pass

def trail_stop(login,password,trail_distance=TRAIL_DISTANCE):
    try: asyncio.run(_trail(login,password,trail_distance))
    except Exception as e: print(f"Trail sync error: {e}")

def place_trade(signal,lot,tp,sl,orders=ORDERS_PER_SIGNAL,login=None,password=None):
    if not AUTO_TRADE: return 0
    login=login or MT_LOGIN; password=password or MT_PASSWORD
    try: return asyncio.run(_place(login,password,signal,lot,tp,sl,orders))
    except Exception as e: print(f"Trade error: {e}"); return 0

# ─────────────────────────────────────────
# METAAPI — CHECK REAL CLOSED DEALS
# ─────────────────────────────────────────
async def _get_deals(login,password):
    api=None
    try:
        from metaapi_cloud_sdk import MetaApi
        api=MetaApi(METAAPI_TOKEN,{"region":"london"})
        accounts=await api.metatrader_account_api.get_accounts_with_infinite_scroll_pagination()
        account=next((a for a in accounts if str(a.login)==str(login)),None)
        if account is None: return []
        if account.state not in ["DEPLOYED","DEPLOYING"]:
            await account.deploy(); await account.wait_deployed()
        conn=account.get_rpc_connection()
        await conn.connect()
        await conn.wait_synchronized(timeout_in_seconds=30)
        history=await conn.get_deals_by_time_range(
            datetime.now(timezone.utc)-timedelta(hours=1),datetime.now(timezone.utc))
        try: await conn.close()
        except: pass
        return history.get("deals",[])
    except Exception as e: print(f"Deal fetch error: {e}"); return []
    finally:
        if api:
            try: await api.close()
            except: pass

def check_real_positions(smc_state,now):
    """Only PULLBACK uses real-broker confirmation. REVERSAL runs two simultaneous
    legs from one entry, which makes matching individual real broker deals to a
    specific leg ambiguous — it relies on check_reversal_legs (price-based) instead."""
    try:
        deals=asyncio.run(_get_deals(MT_LOGIN,MT_PASSWORD))
        for deal in deals:
            if deal.get("entryType")!="DEAL_ENTRY_OUT": continue
            profit=deal.get("profit",0); close_px=deal.get("price",0)
            result="WIN" if profit>0 else "LOSS"
            if smc_state["in_trade"] and smc_state["entry"]:
                send_telegram(f"[PULLBACK] ✅ Real close from JustMarkets!\nEntry: ${smc_state['entry']:,.2f} → ${close_px:,.2f}\nProfit: ${profit:,.2f} — {result}\nTime: {now}")
                log_trade("PULLBACK",smc_state["trade_type"],smc_state["entry"],close_px,result)
                smc_state["in_trade"]=False; break
    except Exception as e: print(f"Acc1 check error: {e}")

# ─────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────
def main():
    print("Gold Bot Started!")
    send_telegram(
        "Hello Edgar!\nMulti-Position Auto-Trading Bot is LIVE!\n"
        "1. Pullback Signal — 1H pullback range + 5m FVG entry\n"
        "2. Reversal Signal — 2-stage 50% retrace rejection, dual leg (1:1 + 2:1 RR)\n"

        f"({ORDERS_PER_SIGNAL} orders/signal) | Account: {MT_LOGIN} ({MT_SERVER})\n"
        "Sessions: Tokyo + London + New York"
    )

    saved_smc, saved_reversal = load_state()
    smc_state    = saved_smc if saved_smc else new_trade_state()
    last_session = None
    last_weekly  = None
    reversal_state    = saved_reversal if saved_reversal else {
        "in_trade":False,"direction":None,"entry":None,"sl":None,
        "tp1":None,"tp2":None,"leg1_closed":False,"leg2_closed":False
    }
    reversal_phase_state = {"phase":"idle"}  # tracks the 2-stage 50%-retrace detection
    reversal_results  = []

    while True:
        now=datetime.now().strftime("%H:%M:%S")
        utc=datetime.now(timezone.utc)
        trading,session_name=is_trading_session()

        # ── WEEKLY SUMMARY ──
        if utc.weekday()==WEEKLY_DAY and utc.hour>=WEEKLY_HOUR:
            wk=utc.isocalendar()[:2]
            if last_weekly!=wk: send_weekly_summary(reversal_results); last_weekly=wk

        # ── PRICE + CANDLES ──
        price=get_gold_price()
        if price:
            build_candles(price)
            print(f"[{now}] Gold: ${price:,.2f} | 5m:{len(candles_5m)} 15m:{len(candles_15m)} 1h:{len(candles_1h)} 4h:{len(candles_4h)}")

        # ── SESSION ──
        if trading and session_name!=last_session:
            send_telegram(f"Session Open! {session_name} active\nScanning..."); last_session=session_name
        if not trading and last_session is not None:
            send_telegram("Sessions Closed! Bot resumes next session."); last_session=None

        if not trading or not price or len(candles_15m)<5:
            time.sleep(CHECK_EVERY); continue

        lh=candles_15m[-1]["high"]; ll=candles_15m[-1]["low"]

        # ── CHECK REAL BROKER POSITIONS ──
        if smc_state["in_trade"]:
            check_real_positions(smc_state,now)

        # ── TRAIL STOP-LOSS on open positions (PULLBACK only — testing showed
        # trailing hurts REVERSAL's dual hard-target structure, so it's skipped there) ──
        if smc_state["in_trade"]:
            trail_stop(MT_LOGIN, MT_PASSWORD)

        # ── CHECK TP/SL (fallback) ──
        check_tp_sl("PULLBACK",smc_state,lh,ll,now)
        check_reversal_legs(reversal_state,lh,ll,now)

        # ── PULLBACK+SWEEP+FVG SIGNAL (1H trend, pullback range, 5m FVG entry) ──
        if not smc_state["in_trade"]:
            d, entry_price, target, stop = analyze_pullback_signal()
            print(f"[PULLBACK] {d} | entry:{entry_price} target:{target} stop:{stop}")
            if d in ["BUY","SELL"] and d!=smc_state["last_signal"]:
                lot = 0.02
                tp, sl = round(target,2), round(stop,2)
                placed=place_trade(d,lot,tp,sl)
                if placed:
                    # Only track as an open trade if placement actually succeeded —
                    # otherwise this becomes a phantom trade that logs a fake result later.
                    smc_state["entry"]=entry_price; smc_state["tp"]=tp; smc_state["sl"]=sl
                    smc_state["trade_type"]=d; smc_state["in_trade"]=True; smc_state["last_signal"]=d
                send_telegram(
                    f"[PULLBACK] {d} (1H pullback + 5m FVG)\nEntry: ${entry_price:,.2f}\n"
                    f"TP: ${tp:,.2f} | SL: ${sl:,.2f}\nLot: {lot}\n"
                    f"{'✅ '+str(placed)+'/'+str(ORDERS_PER_SIGNAL)+' PLACED!' if placed else '❌ Failed - place manually! (not tracked as open trade)'}\nTime: {now}"
                )

        # ── REVERSAL SIGNAL (dual-leg: 1:1 + 2:1 RR, same entry/stop — best-tested combo) ──
        if not reversal_state["in_trade"]:
            d, entry_price, target1, target2, stop = analyze_reversal_signal(reversal_phase_state)
            if d in ["BUY","SELL"]:
                print(f"[REVERSAL] {d} | entry:{entry_price:.2f} tp1:{target1:.2f} tp2:{target2:.2f} stop:{stop:.2f}")
                tp1, tp2, sl = round(target1,2), round(target2,2), round(stop,2)
                # Both legs on Account 2 — half-size lot each, same entry/stop, different targets.
                placed_leg1=place_trade(d,0.01,tp1,sl,ORDERS_PER_SIGNAL,MT_LOGIN2,MT_PASSWORD2)
                placed_leg2=place_trade(d,0.01,tp2,sl,ORDERS_PER_SIGNAL,MT_LOGIN2,MT_PASSWORD2)
                if placed_leg1 or placed_leg2:
                    # Only track as an open trade if at least one leg actually placed —
                    # otherwise this becomes a phantom trade that logs a fake result later.
                    reversal_state["in_trade"]=True; reversal_state["direction"]=d
                    reversal_state["entry"]=entry_price; reversal_state["sl"]=sl
                    reversal_state["tp1"]=tp1; reversal_state["tp2"]=tp2
                    reversal_state["leg1_closed"]=not placed_leg1  # if it never placed, treat as already "closed" (nothing to track)
                    reversal_state["leg2_closed"]=not placed_leg2
                send_telegram(
                    f"[REVERSAL] {d} — dual leg (1:1 + 2:1 RR)\n"
                    f"Entry: ${entry_price:,.2f}\nSL: ${sl:,.2f}\n"
                    f"Leg1 TP (1:1): ${tp1:,.2f} — {'✅ PLACED' if placed_leg1 else '❌ Failed'}\n"
                    f"Leg2 TP (2:1): ${tp2:,.2f} — {'✅ PLACED' if placed_leg2 else '❌ Failed'}\n"
                    f"{'⚠️ Neither leg placed — not tracking this as a trade.' if not (placed_leg1 or placed_leg2) else ''}\n"
                    f"Time: {now}"
                )

        save_state(smc_state, reversal_state)
        time.sleep(CHECK_EVERY)

if __name__=="__main__":
    main()
