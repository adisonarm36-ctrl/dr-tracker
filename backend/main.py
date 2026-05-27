import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, Any
import yfinance as yf
import json
from datetime import datetime, timezone
import pytz
import os
import math
import threading

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_no_cache_headers(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

def load_dr_catalog():
    file_path = os.path.join(os.path.dirname(__file__), "dr_catalog.json")
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print("Error loading dr_catalog.json, using empty catalog:", e)
        return {}

# Load catalog on startup
DR_CATALOG = load_dr_catalog()

# Caching for top movers endpoint to ensure rapid delivery without hitting Yahoo limits
top_movers_cache = {
    "data": None,
    "last_fetched": 0
}
cache_lock = threading.Lock()

class ConfigSaveRequest(BaseModel):
    config: Dict[str, Any]

def load_dr_config():
    file_path = os.path.join(os.path.dirname(__file__), "dr_config.json")
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)

def get_market_info():
    tz_th = pytz.timezone('Asia/Bangkok')
    now = datetime.now(tz_th)
    time_float = now.hour + now.minute / 60.0
    
    if 8.5 <= time_float <= 15.2: return "HK", "LIVE"
    if time_float >= 20.5 or time_float <= 3.0: return "US", "LIVE"
    return "CLOSED", "CLOSED (Last Close)"

def get_price_safe(ticker):
    if not ticker: return None
    try:
        price = yf.Ticker(ticker).fast_info.last_price
        if price is None or price == 0:
             raise ValueError("Price not found")
        return price
    except Exception:
        try:
            return yf.Ticker(ticker).history(period="1d")['Close'].iloc[-1]
        except Exception:
            return 0.0

def get_rich_market_data(ticker):
    if not ticker: return None
    try:
        t = yf.Ticker(ticker)
        try:
            prev_close = t.fast_info.previous_close
        except:
            prev_close = 0.0

        hist = t.history(period="1d", interval="15m", prepost=True)
        if hist.empty:
            price = get_price_safe(ticker)
            last_ts = None
            try:
                hist_daily = t.history(period="1d")
                if not hist_daily.empty:
                    last_ts = hist_daily.index[-1]
            except:
                pass
            last_trade_time = ""
            if last_ts is not None:
                tz_bangkok = pytz.timezone('Asia/Bangkok')
                if last_ts.tzinfo is not None:
                    last_ts_bangkok = last_ts.astimezone(tz_bangkok)
                else:
                    last_ts_bangkok = pytz.utc.localize(last_ts).astimezone(tz_bangkok)
                last_trade_time = last_ts_bangkok.strftime('%H:%M (%d/%m)')
            return {"price": price, "prices": [price] if price else [], "change_pct": 0.0, "delay_msg": "Closed", "prev_close": prev_close, "last_trade_time": last_trade_time}
            
        prices = [round(p, 2) for p in hist['Close'].tolist() if not math.isnan(p)]
        if not prices:
             price = get_price_safe(ticker)
             last_ts = None
             try:
                 hist_daily = t.history(period="1d")
                 if not hist_daily.empty:
                     last_ts = hist_daily.index[-1]
             except:
                 pass
             last_trade_time = ""
             if last_ts is not None:
                 tz_bangkok = pytz.timezone('Asia/Bangkok')
                 if last_ts.tzinfo is not None:
                     last_ts_bangkok = last_ts.astimezone(tz_bangkok)
                 else:
                     last_ts_bangkok = pytz.utc.localize(last_ts).astimezone(tz_bangkok)
                 last_trade_time = last_ts_bangkok.strftime('%H:%M (%d/%m)')
             return {"price": price, "prices": [price] if price else [], "change_pct": 0.0, "delay_msg": "Closed", "prev_close": prev_close, "last_trade_time": last_trade_time}
             
        last_price = prices[-1]
        
        change_pct = ((last_price - prev_close) / prev_close) * 100 if prev_close and prev_close > 0 else 0.0
        
        last_ts = hist.index[-1]
        now_utc = datetime.now(timezone.utc)
        if last_ts.tzinfo is not None:
            last_ts_utc = last_ts.astimezone(timezone.utc)
        else:
            last_ts_utc = last_ts.replace(tzinfo=timezone.utc)
            
        diff_minutes = int((now_utc - last_ts_utc).total_seconds() / 60)
        
        is_overnight = False
        if hasattr(last_ts, 'hour'):
            time_float = last_ts.hour + last_ts.minute / 60.0
            if time_float >= 16.0 or time_float < 9.5:
                is_overnight = True
                
        if is_overnight:
             if diff_minutes <= 15:
                 delay_msg = "Overnight (Live)"
             else:
                 delay_msg = "Overnight (Close)"
        else:
            if diff_minutes <= 10:
                delay_msg = "Realtime"
            elif diff_minutes > 120:
                 delay_msg = "Market Closed"
            else:
                 delay_msg = f"Delayed {diff_minutes}m"
             
        tz_bangkok = pytz.timezone('Asia/Bangkok')
        if last_ts.tzinfo is not None:
            last_ts_bangkok = last_ts.astimezone(tz_bangkok)
        else:
            last_ts_bangkok = pytz.utc.localize(last_ts).astimezone(tz_bangkok)
        last_trade_time = last_ts_bangkok.strftime('%H:%M (%d/%m)')
        
        return {
            "price": last_price,
            "prices": prices,
            "change_pct": round(change_pct, 2),
            "delay_msg": delay_msg,
            "prev_close": round(prev_close, 2) if prev_close else 0.0,
            "last_trade_time": last_trade_time
        }
    except Exception as e:
        print(f"Error fetching {ticker}: {e}")
        price = get_price_safe(ticker)
        return {"price": price, "prices": [price] if price else [], "change_pct": 0.0, "delay_msg": "Error", "prev_close": 0.0, "last_trade_time": ""}

def compute_tracker_data(dr_config):
    current_market, status = get_market_info()
    
    fx_hkd = get_price_safe("HKDTHB=X") or 4.7
    fx_usd = get_price_safe("USDTHB=X") or 36.5
    fx_cny = get_price_safe("CNYTHB=X") or 5.0
    fx_sgd = get_price_safe("SGDTHB=X") or 27.0
    fx_vnd = get_price_safe("VNDTHB=X") or 0.0014
    fx_jpy = get_price_safe("JPYTHB=X") or 0.23
    fx_eur = get_price_safe("EURTHB=X") or 40.0
    fx_twd = get_price_safe("TWDTHB=X") or 1.12
    fx_dkk = get_price_safe("DKKTHB=X") or 5.00
    
    data = []
    for symbol, cfg in dr_config.items():
        item = {"symbol": symbol}
        active = "HK"
        
        market = cfg.get('market', 'US')
        dr_ratio = cfg.get('dr_ratio', 0.001)
        
        if market == "US" or (current_market == "US" and "us_adr" in cfg):
            active = "US"
        item["active_market"] = active
        
        # ---------------- ตลาดฝั่งเอเชีย / ยุโรป (Asiatic/European) ----------------
        item["hk_ticker"] = cfg.get('primary') if market in ['HK', 'CN', 'SG', 'VN', 'JP', 'AS', 'FR', 'IT', 'TW', 'DK', 'DE'] else None
        item["hk_price"] = ""
        item["hk_multiplier"] = ""
        item["hk_rich"] = None
        
        if item["hk_ticker"]:
            hk_rich = get_rich_market_data(item["hk_ticker"])
            if hk_rich and hk_rich["price"]:
                item["hk_price"] = round(hk_rich["price"], 2)
                item["hk_rich"] = hk_rich
                
                if market == 'HK':
                    if item["hk_ticker"].endswith(".SS") or item["hk_ticker"].endswith(".SZ"):
                        item["hk_multiplier"] = fx_cny * dr_ratio
                    else:
                        item["hk_multiplier"] = fx_hkd * dr_ratio
                elif market == 'JP':
                    item["hk_multiplier"] = fx_jpy * dr_ratio
                elif market == 'SG':
                    item["hk_multiplier"] = fx_sgd * dr_ratio
                elif market == 'VN':
                    item["hk_multiplier"] = fx_vnd * dr_ratio
                elif market == 'TW':
                    item["hk_multiplier"] = fx_twd * dr_ratio
                elif market == 'DK':
                    item["hk_multiplier"] = fx_dkk * dr_ratio
                elif market in ['AS', 'FR', 'IT', 'DE']:
                    item["hk_multiplier"] = fx_eur * dr_ratio
                else:
                    item["hk_multiplier"] = fx_hkd * dr_ratio

        # ---------------- ตลาดฝั่งอเมริกา (US) ----------------
        if market == 'US':
            item["us_ticker"] = cfg.get('primary')
            us_ratio = 1
        elif "us_adr" in cfg:
            item["us_ticker"] = cfg.get('us_adr')
            us_ratio = cfg.get('adr_ratio', 1)
        else:
            item["us_ticker"] = None
            us_ratio = 1
            
        item["us_price"] = ""
        item["us_multiplier"] = ""
        item["us_rich"] = None
        
        if item["us_ticker"]:
            us_rich = get_rich_market_data(item["us_ticker"])
            if us_rich and us_rich["price"]:
                item["us_price"] = round(us_rich["price"], 2)
                item["us_rich"] = us_rich
                item["us_multiplier"] = (1 / us_ratio) * fx_usd * dr_ratio

        # ---------------- คำนวณราคา DR (THB) ----------------
        item["dr_thb"] = "0.00"
        if active == "US" and item["us_price"]:
            item["dr_thb"] = round(item["us_price"] * item["us_multiplier"], 2)
        elif active == "HK" and item["hk_price"]:
            item["dr_thb"] = round(item["hk_price"] * item["hk_multiplier"], 2)
            
        data.append(item)
        
    return {
        "status": status, 
        "fx_hkd": round(fx_hkd, 4), 
        "fx_usd": round(fx_usd, 4), 
        "fx_cny": round(fx_cny, 4),
        "fx_sgd": round(fx_sgd, 4),
        "fx_vnd": round(fx_vnd, 4),
        "fx_jpy": round(fx_jpy, 4),
        "fx_eur": round(fx_eur, 4),
        "fx_twd": round(fx_twd, 4),
        "fx_dkk": round(fx_dkk, 4),
        "data": data
    }

@app.get("/api/tracker")
def get_tracker():
    dr_config = load_dr_config() 
    return compute_tracker_data(dr_config)

class TrackerQueryRequest(BaseModel):
    config: Dict[str, Any]

@app.post("/api/tracker")
def post_tracker(req: TrackerQueryRequest):
    return compute_tracker_data(req.config)

@app.get("/api/catalog")
def get_catalog():
    return load_dr_catalog()

@app.post("/api/config/save")
def save_config(req: ConfigSaveRequest):
    try:
        file_path = os.path.join(os.path.dirname(__file__), "dr_config.json")
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(req.config, f, indent=2, ensure_ascii=False)
        # Dynamic reload of global catalog
        global DR_CATALOG
        DR_CATALOG = load_dr_catalog()
        return {"status": "success", "message": "Configuration saved successfully."}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/top_movers")
def get_top_movers():
    import time
    now = time.time()
    
    with cache_lock:
        if top_movers_cache["data"] and (now - top_movers_cache["last_fetched"] < 120):
            return top_movers_cache["data"]
            
    try:
        catalog = load_dr_catalog()
        symbols = list(catalog.keys())
        tickers_string = " ".join([f"{sym}.BK" for sym in symbols])
        
        # Parallel fetch from yfinance using yf.download (takes ~6.5s)
        data = yf.download(tickers_string, period="5d", group_by='ticker', progress=False)
        
        results = []
        for sym in symbols:
            ticker_sym = f"{sym}.BK"
            try:
                if ticker_sym in data.columns.levels[0]:
                    closes = data[ticker_sym]['Close'].dropna()
                    if len(closes) >= 2:
                        last_price = closes.iloc[-1]
                        prev_close = closes.iloc[-2]
                        change = ((last_price - prev_close) / prev_close) * 100
                        
                        catalog_item = catalog[sym]
                        
                        # Only include recommended items to avoid duplicate underlying assets (e.g. multiple brokers for the same asset)
                        if not catalog_item.get("recommend", False):
                            continue
                            
                        market_group = "US" if catalog_item["market"] == "US" else (
                            "HK/CN" if catalog_item["market"] in ["HK", "CN"] else "Others"
                        )
                        
                        if catalog_item["market"] in ["SG", "VN", "JP", "AS", "FR", "IT", "TW", "DK", "DE"]:
                            market_group = "Others"
                            
                        results.append({
                            "symbol": sym,
                            "name": catalog_item.get("name", sym),
                            "price": round(float(last_price), 2),
                            "change_pct": round(float(change), 2),
                            "market_group": market_group
                        })
            except Exception as ex:
                pass
                
        # Group and rank results
        markets = {"US": [], "HK/CN": [], "Others": []}
        for r in results:
            if r["market_group"] in markets:
                markets[r["market_group"]].append(r)
                
        movers = {}
        for grp, items in markets.items():
            gainers = sorted(items, key=lambda x: x["change_pct"], reverse=True)
            losers = sorted(items, key=lambda x: x["change_pct"])
            
            movers[grp] = {
                "gainers": gainers[:5],
                "losers": losers[:5]
            }
            
        response_data = {
            "status": "success",
            "timestamp": datetime.now().isoformat(),
            "movers": movers
        }
        
        with cache_lock:
            top_movers_cache["data"] = response_data
            top_movers_cache["last_fetched"] = now
            
        return response_data
    except Exception as e:
        print("Error getting top movers:", e)
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
