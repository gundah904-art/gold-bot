import os
import csv
import asyncio
import requests
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

_missing = [k for k,v in {"TELEGRAM_TOKEN":TELEGRAM_TOKEN,"CHAT_ID":CHAT_ID,"METAAPI_TOKEN":METAAPI_TOKEN,"MT_LOGIN":MT_LOGIN,"MT_SERVER":MT_SERVER,"MT_PASSWORD":MT_PASSWORD}.items() if not v]
if _missing:
    raise RuntimeError(f"Missing env vars: {', '.join(_missing)}")

# ─────────────────────────────────────────
# SETTINGS
# ─────────────────────────────────────────
CHECK_EVERY        = 900
SWING_LOOKBACK     = 3
ZONE_LOOKBACK      = 30
ZONE_TOLERANCE     = 3.0
AUTO_TRADE         = True
ORDERS_PER_SIGNAL  = 5
TRADE_LOG_FILE     = "trade_log.csv"
WEEKLY_DAY         = 6
WEEKLY_HOUR        = 20

SESSIONS = [
    {"name": "Tokyo",    "start": 0,  "end": 9},
    {"name": "London",   "start": 7,  "end": 16},
    {"name": "New York", "start": 12, "end": 21},
]

TRADE_SETTINGS = {
    "SCALP": {"tp": 5,  "sl": 3,  "lot": 0.01, "label": "Scalp (15min)"},
    "DAY":   {"tp": 15, "sl": 7,  "lot": 0.02, "label": "Day Trade (1hr)"},
    "SWING": {"tp": 30, "sl": 10, "lot": 0.03, "label": "Swing (4hr+)"},
    "ZONE":  {"tp": 10, "sl": 5,  "lot": 0.02, "label": "Zone Reaction"},
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

def is_friday(): return datetime.now(timezone.utc).weekday() == 4

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
    global candles_15m, candles_1h, candles_4h, last_15m_time, last_1h_time, last_4h_time
    now = datetime.now(timezone.utc)
    t15 = now.replace(minute=(now.minute//15)*15, second=0, microsecond=0)
    if last_15m_time is None or t15 != last_15m_time:
        candles_15m.append({"open":price,"high":price,"low":price,"close":price}); last_15m_time = t15
    else:
        c=candles_15m[-1]; c["high"]=max(c["high"],price); c["low"]=min(c["low"],price); c["close"]=price
    if len(candles_15m)>100: candles_15m.pop(0)
    t1h = now.replace(minute=0, second=0, microsecond=0)
    if last_1h_time is None or t1h != last_1h_time:
        candles_1h.append({"open":price,"high":price,"low":price,"close":price}); last_1h_time = t1h
    else:
        c=candles_1h[-1]; c["high"]=max(c["high"],price); c["low"]=min(c["low"],price); c["close"]=price
    if len(candles_1h)>100: candles_1h.pop(0)
    t4h = now.replace(hour=(now.hour//4)*4, minute=0, second=0, microsecond=0)
    if last_4h_time is None or t4h != last_4h_time:
        candles_4h.append({"open":price,"high":price,"low":price,"close":price}); last_4h_time = t4h
    else:
        c=candles_4h[-1]; c["high"]=max(c["high"],price); c["low"]=min(c["low"],price); c["close"]=price
    if len(candles_4h)>100: candles_4h.pop(0)

# ─────────────────────────────────────────
# SMC INDICATORS
# ─────────────────────────────────────────
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

def analyze_all_timeframes(price):
    l15=detect_liquidity(candles_15m); b15=detect_bos(candles_15m); f15=detect_fvg(candles_15m)
    l1=detect_liquidity(candles_1h);   b1=detect_bos(candles_1h);   f1=detect_fvg(candles_1h)
    l4=detect_liquidity(candles_4h);   b4=detect_bos(candles_4h);   f4=detect_fvg(candles_4h)
    t15=get_trend(candles_15m); t1=get_trend(candles_1h); t4=get_trend(candles_4h)
    buy15=sum([l15=="BULLISH",b15=="BULLISH",f15=="BULLISH"]); sell15=sum([l15=="BEARISH",b15=="BEARISH",f15=="BEARISH"])
    buy1=sum([l1=="BULLISH",b1=="BULLISH",f1=="BULLISH"]);     sell1=sum([l1=="BEARISH",b1=="BEARISH",f1=="BEARISH"])
    buy4=sum([l4=="BULLISH",b4=="BULLISH",f4=="BULLISH"]);     sell4=sum([l4=="BEARISH",b4=="BEARISH",f4=="BEARISH"])
    tb=buy15+buy1+buy4; ts=sell15+sell1+sell4
    if tb<3 and ts<3: return "HOLD",None,None,t15,t1,t4
    d="BUY" if tb>ts else "SELL"
    tfc=sum([buy15>=2,buy1>=2,buy4>=2]) if d=="BUY" else sum([sell15>=2,sell1>=2,sell4>=2])
    tt="SWING" if tfc==3 else ("DAY" if tfc==2 else "SCALP")
    return d,tt,tfc,t15,t1,t4

def analyze_all_timeframes_track(price):
    """Same as analyze_all_timeframes but threshold=1 for observation only."""
    l15=detect_liquidity(candles_15m); b15=detect_bos(candles_15m); f15=detect_fvg(candles_15m)
    l1=detect_liquidity(candles_1h);   b1=detect_bos(candles_1h);   f1=detect_fvg(candles_1h)
    l4=detect_liquidity(candles_4h);   b4=detect_bos(candles_4h);   f4=detect_fvg(candles_4h)
    t15=get_trend(candles_15m); t1=get_trend(candles_1h); t4=get_trend(candles_4h)
    buy15=sum([l15=="BULLISH",b15=="BULLISH",f15=="BULLISH"]); sell15=sum([l15=="BEARISH",b15=="BEARISH",f15=="BEARISH"])
    buy1=sum([l1=="BULLISH",b1=="BULLISH",f1=="BULLISH"]);     sell1=sum([l1=="BEARISH",b1=="BEARISH",f1=="BEARISH"])
    buy4=sum([l4=="BULLISH",b4=="BULLISH",f4=="BULLISH"]);     sell4=sum([l4=="BEARISH",b4=="BEARISH",f4=="BEARISH"])
    tb=buy15+buy1+buy4; ts=sell15+sell1+sell4
    if tb<1 and ts<1: return "HOLD",None,None,t15,t1,t4
    d="BUY" if tb>ts else "SELL"
    tfc=sum([buy15>=2,buy1>=2,buy4>=2]) if d=="BUY" else sum([sell15>=2,sell1>=2,sell4>=2])
    tt="SWING" if tfc==3 else ("DAY" if tfc==2 else "SCALP")
    return d,tt,tfc,t15,t1,t4

def analyze_zone_signal(price):
    support,resistance,demand,supply=find_zones(candles_1h)
    if demand is not None and abs(price-demand)<=ZONE_TOLERANCE: return "BUY",demand,support,resistance,demand,supply
    if supply is not None and abs(price-supply)<=ZONE_TOLERANCE: return "SELL",supply,support,resistance,demand,supply
    return None,None,support,resistance,demand,supply

# ─────────────────────────────────────────
# TRADE LOG
# ─────────────────────────────────────────
trade_log = []

def log_trade(strategy, direction, entry, exit_price, result):
    pnl = round(exit_price-entry,2) if direction=="BUY" else round(entry-exit_price,2)
    record = {"timestamp":datetime.now(timezone.utc).isoformat(),"strategy":strategy,
              "direction":direction,"entry":entry,"exit":exit_price,"result":result,"pnl":pnl}
    trade_log.append(record)
    try:
        wh = not os.path.exists(TRADE_LOG_FILE)
        with open(TRADE_LOG_FILE,"a",newline="") as f:
            w=csv.DictWriter(f,fieldnames=record.keys())
            if wh: w.writeheader()
            w.writerow(record)
    except Exception as e:
        print(f"Log error: {e}")

def send_weekly_summary():
    cutoff=datetime.now(timezone.utc)-timedelta(days=7)
    wt=[t for t in trade_log if datetime.fromisoformat(t["timestamp"])>=cutoff]
    if not wt: send_telegram("WEEKLY SUMMARY\nNo trades closed in the last 7 days."); return
    total=len(wt); wins=sum(1 for t in wt if t["result"]=="WIN")
    wr=round(wins/total*100,1); pnl=round(sum(t["pnl"] for t in wt),2)
    bs={}
    for t in wt:
        s=t["strategy"]; bs.setdefault(s,{"total":0,"wins":0,"pnl":0.0})
        bs[s]["total"]+=1; bs[s]["pnl"]+=t["pnl"]
        if t["result"]=="WIN": bs[s]["wins"]+=1
    st=""
    for s,d in bs.items():
        r=round(d["wins"]/d["total"]*100,1)
        st+=f"{s}: {d['wins']}/{d['total']} wins ({r}%) | ${d['pnl']:,.2f}\n"
    send_telegram(f"WEEKLY SUMMARY (last 7 days)\n-------------------\nTotal: {total}\nWins: {wins} | Losses: {total-wins}\nWin Rate: {wr}%\nNet: ${pnl:,.2f}\n-------------------\n{st}")

# ─────────────────────────────────────────
# TRADE STATE
# ─────────────────────────────────────────
def new_trade_state():
    return {"in_trade":False,"trade_type":None,"entry":None,"tp":None,"sl":None,"last_signal":None}

def check_tp_sl(name, state, last_high, last_low, now):
    if not state["in_trade"]: return
    if state["trade_type"]=="BUY":
        tp_hit=last_high>=state["tp"]; sl_hit=last_low<=state["sl"]
        if tp_hit and sl_hit:
            if last_high-state["entry"]>=state["entry"]-last_low:
                send_telegram(f"[{name}] TAKE PROFIT HIT!\nEntry: ${state['entry']:,.2f}\nExit: ${state['tp']:,.2f}\nTime: {now}")
                log_trade(name,"BUY",state["entry"],state["tp"],"WIN")
            else:
                send_telegram(f"[{name}] STOP LOSS HIT!\nEntry: ${state['entry']:,.2f}\nExit: ${state['sl']:,.2f}\nTime: {now}")
                log_trade(name,"BUY",state["entry"],state["sl"],"LOSS")
            state["in_trade"]=False
        elif tp_hit:
            send_telegram(f"[{name}] TAKE PROFIT HIT!\nEntry: ${state['entry']:,.2f}\nExit: ${state['tp']:,.2f}\nTime: {now}")
            log_trade(name,"BUY",state["entry"],state["tp"],"WIN"); state["in_trade"]=False
        elif sl_hit:
            send_telegram(f"[{name}] STOP LOSS HIT!\nEntry: ${state['entry']:,.2f}\nExit: ${state['sl']:,.2f}\nTime: {now}")
            log_trade(name,"BUY",state["entry"],state["sl"],"LOSS"); state["in_trade"]=False
    elif state["trade_type"]=="SELL":
        tp_hit=last_low<=state["tp"]; sl_hit=last_high>=state["sl"]
        if tp_hit and sl_hit:
            if state["entry"]-last_low>=last_high-state["entry"]:
                send_telegram(f"[{name}] TAKE PROFIT HIT!\nEntry: ${state['entry']:,.2f}\nExit: ${state['tp']:,.2f}\nTime: {now}")
                log_trade(name,"SELL",state["entry"],state["tp"],"WIN")
            else:
                send_telegram(f"[{name}] STOP LOSS HIT!\nEntry: ${state['entry']:,.2f}\nExit: ${state['sl']:,.2f}\nTime: {now}")
                log_trade(name,"SELL",state["entry"],state["sl"],"LOSS")
            state["in_trade"]=False
        elif tp_hit:
            send_telegram(f"[{name}] TAKE PROFIT HIT!\nEntry: ${state['entry']:,.2f}\nExit: ${state['tp']:,.2f}\nTime: {now}")
            log_trade(name,"SELL",state["entry"],state["tp"],"WIN"); state["in_trade"]=False
        elif sl_hit:
            send_telegram(f"[{name}] STOP LOSS HIT!\nEntry: ${state['entry']:,.2f}\nExit: ${state['sl']:,.2f}\nTime: {now}")
            log_trade(name,"SELL",state["entry"],state["sl"],"LOSS"); state["in_trade"]=False

# ─────────────────────────────────────────
# METAAPI — FAST RPC (skips deploy, short timeout)
# ─────────────────────────────────────────
async def _place(login, password, signal, lot, tp, sl, orders):
    placed = 0
    api = None
    try:
        from metaapi_cloud_sdk import MetaApi
        api = MetaApi(METAAPI_TOKEN, {'region': 'london'})
        accounts = await api.metatrader_account_api.get_accounts_with_infinite_scroll_pagination()
        account = next((a for a in accounts if str(a.login)==str(login)), None)
        if account is None:
            account = await api.metatrader_account_api.create_account({
                'name': f'Gold Bot {login}', 'type': 'cloud',
                'login': login, 'password': password,
                'server': MT_SERVER, 'platform': 'mt5', 'magic': 123456
            })
        if account.state not in ['DEPLOYED','DEPLOYING']:
            await account.deploy()
            await account.wait_deployed()
        conn = account.get_rpc_connection()
        await conn.connect()
        await conn.wait_synchronized(timeout_in_seconds=30)
        # Auto-detect correct symbol name
        symbol = "XAUUSD"
        try:
            symbols = await conn.get_symbols()
            for s in symbols:
                if 'XAU' in s and 'USD' in s:
                    symbol = s
                    break
        except:
            pass
        print(f"Using symbol: {symbol}")
        for _ in range(orders):
            try:
                if signal=="BUY":
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
    login = login or MT_LOGIN
    password = password or MT_PASSWORD
    try:
        return asyncio.run(_place(login, password, signal, lot, tp, sl, orders))
    except Exception as e:
        print(f"Trade error: {e}")
        return 0

# ─────────────────────────────────────────
# FRIDAY HEDGE
# ─────────────────────────────────────────
def friday_hedge(price):
    now = datetime.now().strftime("%H:%M:%S")
    if len(candles_15m)>=5:
        ranges=[c["high"]-c["low"] for c in candles_15m[-5:]]
        if sum(ranges)/len(ranges)>15:
            send_telegram(f"FRIDAY WARNING! Too volatile - SKIP!\nTime: {now}"); return
    buy_sl=round(price-5,2); sell_sl=round(price+5,2)
    buy_placed=place_trade("BUY",0.05,0,buy_sl,1)
    sell_placed=place_trade("SELL",0.05,0,sell_sl,1,MT_LOGIN2,MT_PASSWORD2)
    send_telegram(
        f"FRIDAY HEDGE!\nGold: ${price:,.2f}\n"
        f"ACC1 BUY SL:${buy_sl} — {'✅' if buy_placed else '❌'}\n"
        f"ACC2 SELL SL:${sell_sl} — {'✅' if sell_placed else '❌'}\n"
        f"Check Monday 1AM Nairobi!\nTime: {now}"
    )

# ─────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────
def main():
    print("Gold Bot Started!")
    send_telegram(
        "Hello Edgar!\nMulti-Position Auto-Trading Bot is LIVE!\n"
        "1. SMC Signal - Liquidity + BOS + FVG (15m/1h/4h)\n"
        "2. Zone Signal - Demand/Supply zone reaction\n"
        "3. Friday Hedge - Auto BUY+SELL at 23:56:55 UTC (02:56:55 EAT)\n"
        f"({ORDERS_PER_SIGNAL} orders/signal)\nAccount: {MT_LOGIN} ({MT_SERVER})\n"
        "Sessions: Tokyo + London + New York"
    )

    smc_state  = new_trade_state()
    zone_state = new_trade_state()
    last_session = None
    last_weekly  = None
    hedge_fired  = False
    track_last_signal = [None]  # mutable container for tracking mode

    import time
    while True:
        now = datetime.now().strftime("%H:%M:%S")
        utc = datetime.now(timezone.utc)
        trading, session_name = is_trading_session()

        # ── FRIDAY TIGHT LOOP ──
        if is_friday() and utc.hour==23 and utc.minute>=52:
            hedge_fired=False
            while True:
                utc=datetime.now(timezone.utc)
                if utc.weekday()==5: break
                if not hedge_fired and utc.hour==23 and utc.minute==56 and utc.second>=55:
                    p=get_gold_price()
                    if p: friday_hedge(p)
                    hedge_fired=True
                time.sleep(1)

        # ── WEEKLY SUMMARY ──
        if utc.weekday()==WEEKLY_DAY and utc.hour>=WEEKLY_HOUR:
            wk=utc.isocalendar()[:2]
            if last_weekly!=wk: send_weekly_summary(); last_weekly=wk

        # ── PRICE ──
        price=get_gold_price()
        if price:
            build_candles(price)
            print(f"[{now}] Gold: ${price:,.2f} | 15m:{len(candles_15m)} 1h:{len(candles_1h)} 4h:{len(candles_4h)}")

        # ── SESSION ──
        if trading and session_name!=last_session:
            send_telegram(f"Session Open! {session_name} active\nScanning..."); last_session=session_name
        if not trading and last_session is not None:
            send_telegram("Sessions Closed! Bot resumes next session."); last_session=None

        if not trading or not price or len(candles_15m)<5:
            time.sleep(CHECK_EVERY); continue

        lh=candles_15m[-1]["high"]; ll=candles_15m[-1]["low"]
        check_tp_sl("SMC",smc_state,lh,ll,now)
        check_tp_sl("ZONE",zone_state,lh,ll,now)

        # ── SMC SIGNAL (threshold 3 — live trading) ──
        if not smc_state["in_trade"]:
            d,tt,tfc,t15,t1,t4=analyze_all_timeframes(price)
            print(f"[SMC] {d} | {tt} | TF:{tfc}")
            if d in ["BUY","SELL"] and d!=smc_state["last_signal"]:
                s=TRADE_SETTINGS[tt]
                smc_state["entry"]=price
                smc_state["tp"]=round(price+s["tp"],2) if d=="BUY" else round(price-s["tp"],2)
                smc_state["sl"]=round(price-s["sl"],2) if d=="BUY" else round(price+s["sl"],2)
                smc_state["trade_type"]=d; smc_state["in_trade"]=True; smc_state["last_signal"]=d
                sup,res,dem,sup2=find_zones(candles_1h)
                zt=""
                if sup: zt+=f"Support: ${sup:,.2f}\n"
                if res: zt+=f"Resistance: ${res:,.2f}\n"
                if dem: zt+=f"Demand: ${dem:,.2f}\n"
                if sup2: zt+=f"Supply: ${sup2:,.2f}\n"
                placed=place_trade(d,s["lot"],smc_state["tp"],smc_state["sl"])
                send_telegram(
                    f"[SMC] {d} ({s['label']})\nEntry: ${price:,.2f}\n"
                    f"TP: ${smc_state['tp']:,.2f} | SL: ${smc_state['sl']:,.2f}\n"
                    f"Lot: {s['lot']} | TF: {tfc}/3\n{zt}"
                    f"{'✅ '+str(placed)+'/'+str(ORDERS_PER_SIGNAL)+' PLACED!' if placed else '❌ Failed - place manually!'}\nTime: {now}"
                )

        # ── TRACK SIGNAL (threshold 1 — no trades, observation only) ──
        track_d,track_tt,track_tfc,_,_,_=analyze_all_timeframes_track(price)
        if track_d in ["BUY","SELL"] and track_d!=track_last_signal[0]:
            track_s=TRADE_SETTINGS[track_tt]
            track_tp=round(price+track_s["tp"],2) if track_d=="BUY" else round(price-track_s["tp"],2)
            track_sl=round(price-track_s["sl"],2) if track_d=="BUY" else round(price+track_s["sl"],2)
            track_last_signal[0]=track_d
            send_telegram(
                f"[TRACK] {track_d} ({track_s['label']}) — observation only, no trade\n"
                f"Entry: ${price:,.2f}\n"
                f"TP: ${track_tp:,.2f} | SL: ${track_sl:,.2f}\n"
                f"TF: {track_tfc}/3 | Time: {now}\n"
                f"Watch if price hits TP or SL to build data."
            )

        # ── ZONE SIGNAL ──
        if not zone_state["in_trade"]:
            zd,zl,sup,res,dem,sup2=analyze_zone_signal(price)
            print(f"[ZONE] {zd} | {zl}")
            if zd in ["BUY","SELL"] and zd!=zone_state["last_signal"]:
                s=TRADE_SETTINGS["ZONE"]
                zone_state["entry"]=price
                zone_state["tp"]=round(price+s["tp"],2) if zd=="BUY" else round(price-s["tp"],2)
                zone_state["sl"]=round(price-s["sl"],2) if zd=="BUY" else round(price+s["sl"],2)
                zone_state["trade_type"]=zd; zone_state["in_trade"]=True; zone_state["last_signal"]=zd
                placed=place_trade(zd,s["lot"],zone_state["tp"],zone_state["sl"])
                send_telegram(
                    f"[ZONE] {zd} (off ${zl:,.2f})\nEntry: ${price:,.2f}\n"
                    f"TP: ${zone_state['tp']:,.2f} | SL: ${zone_state['sl']:,.2f}\n"
                    f"{'✅ '+str(placed)+'/'+str(ORDERS_PER_SIGNAL)+' PLACED!' if placed else '❌ Failed - place manually!'}\nTime: {now}"
                )

        time.sleep(CHECK_EVERY)

if __name__=="__main__":
    main()
