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
from concurrent.futures import ThreadPoolExecutor

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
    "last_fetched": 0,
    "is_updating": False
}
cache_lock = threading.Lock()
MOVERS_CACHE_FILE = os.path.join(os.path.dirname(__file__), "top_movers_cache.json")
SET_PRICES_CACHE = {}
SET_PRICES_FILE = os.path.join(os.path.dirname(__file__), "set_prices_cache.json")

def load_movers_cache_from_file():
    global top_movers_cache, SET_PRICES_CACHE
    if os.path.exists(MOVERS_CACHE_FILE):
        try:
            with open(MOVERS_CACHE_FILE, "r", encoding="utf-8") as f:
                cached = json.load(f)
                top_movers_cache["data"] = cached.get("data")
                top_movers_cache["last_fetched"] = cached.get("last_fetched", 0)
                print("Loaded top movers cache from file successfully.")
        except Exception as e:
            print("Failed to load top movers cache file:", e)
            
    if os.path.exists(SET_PRICES_FILE):
        try:
            with open(SET_PRICES_FILE, "r", encoding="utf-8") as f:
                SET_PRICES_CACHE = json.load(f)
                print("Loaded SET prices cache from file successfully.")
        except Exception as e:
            print("Failed to load SET prices cache file:", e)

# Load cache immediately on server startup
load_movers_cache_from_file()

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

        if ticker.endswith(".BK"):
            # Fetch daily candles for the last 45 days (approx 30 trading days)
            hist = t.history(period="45d")
            if hist.empty:
                raise ValueError("No daily history found")
            
            candles = []
            prices = []
            for idx, row in hist.iterrows():
                candles.append({
                    "date": idx.strftime('%Y-%m-%d'),
                    "open": round(float(row['Open']), 2),
                    "high": round(float(row['High']), 2),
                    "low": round(float(row['Low']), 2),
                    "close": round(float(row['Close']), 2)
                })
                prices.append(round(float(row['Close']), 2))
                
            candles = candles[-30:]
            prices = prices[-30:]
            last_price = prices[-1] if prices else 0.0
            change_pct = ((last_price - prev_close) / prev_close) * 100 if prev_close and prev_close > 0 else 0.0
            
            last_ts = hist.index[-1]
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
                "delay_msg": "Delayed",
                "prev_close": round(prev_close, 2) if prev_close else 0.0,
                "last_trade_time": last_trade_time,
                "candles": candles
            }

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

def fetch_all_parallel(tickers):
    if not tickers:
        return {}
    with ThreadPoolExecutor(max_workers=min(len(tickers), 16)) as executor:
        results = list(executor.map(get_rich_market_data, tickers))
    return dict(zip(tickers, results))

def fetch_fx_parallel(fx_tickers):
    if not fx_tickers:
        return {}
    with ThreadPoolExecutor(max_workers=min(len(fx_tickers), 10)) as executor:
        results = list(executor.map(get_price_safe, fx_tickers))
    return dict(zip(fx_tickers, results))

def compute_tracker_data(dr_config):
    current_market, status = get_market_info()
    
    # Parallel fetch of FX rates
    fx_list = ["HKDTHB=X", "USDTHB=X", "CNYTHB=X", "SGDTHB=X", "VNDTHB=X", "JPYTHB=X", "EURTHB=X", "TWDTHB=X", "DKKTHB=X"]
    fx_map = fetch_fx_parallel(fx_list)
    
    fx_hkd = fx_map.get("HKDTHB=X") or 4.7
    fx_usd = fx_map.get("USDTHB=X") or 36.5
    fx_cny = fx_map.get("CNYTHB=X") or 5.0
    fx_sgd = fx_map.get("SGDTHB=X") or 27.0
    fx_vnd = fx_map.get("VNDTHB=X") or 0.0014
    fx_jpy = fx_map.get("JPYTHB=X") or 0.23
    fx_eur = fx_map.get("EURTHB=X") or 40.0
    fx_twd = fx_map.get("TWDTHB=X") or 1.12
    fx_dkk = fx_map.get("DKKTHB=X") or 5.00
    
    # Pre-collect all unique stock tickers to fetch in parallel
    stock_tickers = set()
    for symbol, cfg in dr_config.items():
        market = cfg.get('market', 'US')
        hk_t = cfg.get('primary') if market in ['HK', 'CN', 'SG', 'VN', 'JP', 'AS', 'FR', 'IT', 'TW', 'DK', 'DE'] else None
        us_t = cfg.get('primary') if market == 'US' else cfg.get('us_adr')
        if hk_t: stock_tickers.add(hk_t)
        if us_t: stock_tickers.add(us_t)
        
        # Add local Thai DR ticker (traded on SET) to fetch only if NOT in cache
        if symbol not in SET_PRICES_CACHE:
            stock_tickers.add(f"{symbol}.BK")
        
    # Parallel fetch stock rich data
    stock_data_map = fetch_all_parallel(list(stock_tickers))
    
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
            hk_rich = stock_data_map.get(item["hk_ticker"])
            if hk_rich and hk_rich.get("price"):
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
            us_rich = stock_data_map.get(item["us_ticker"])
            if us_rich and us_rich.get("price"):
                item["us_price"] = round(us_rich["price"], 2)
                item["us_rich"] = us_rich
                item["us_multiplier"] = (1 / us_ratio) * fx_usd * dr_ratio

        # ---------------- คำนวณราคา DR (THB) ----------------
        item["dr_thb"] = "0.00"
        if active == "US" and item["us_price"]:
            item["dr_thb"] = round(item["us_price"] * item["us_multiplier"], 2)
        elif active == "HK" and item["hk_price"]:
            item["dr_thb"] = round(item["hk_price"] * item["hk_multiplier"], 2)
            
        # ---------------- ดึงราคาซื้อขายจริงบน SET 🇹🇭 ----------------
        set_ticker = f"{symbol}.BK"
        set_rich = None
        
        if symbol in SET_PRICES_CACHE:
            set_rich = SET_PRICES_CACHE[symbol]
        else:
            set_rich = stock_data_map.get(set_ticker)
            
        item["set_price"] = ""
        item["premium_pct"] = ""
        item["set_rich"] = None
        
        if set_rich and set_rich.get("price"):
            item["set_price"] = round(set_rich["price"], 2)
            item["set_rich"] = set_rich
            
            # คำนวณส่วนต่าง Premium / Discount
            if item["dr_thb"] and item["dr_thb"] != "0.00":
                try:
                    dr_thb_val = float(item["dr_thb"])
                    if dr_thb_val > 0:
                        diff = ((item["set_price"] - dr_thb_val) / dr_thb_val) * 100
                        item["premium_pct"] = round(diff, 2)
                except:
                    pass
            
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
def get_tracker(symbols: str = None):
    if symbols:
        sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
        catalog = load_dr_catalog()
        dr_config = {}
        for sym in sym_list:
            if sym in catalog:
                dr_config[sym] = catalog[sym]
            else:
                market = "US" if sym.endswith("80") or sym.endswith("01") else "HK"
                primary = sym + ".BK"
                dr_config[sym] = {
                    "primary": primary,
                    "market": market,
                    "dr_ratio": 0.001,
                    "name": f"Custom {sym}"
                }
    else:
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

def update_movers_background():
    global top_movers_cache, SET_PRICES_CACHE
    try:
        import time as pytime
        print("Starting batch background update of top movers...")
        
        is_render = os.environ.get("RENDER") == "true" or "RENDER_SERVICE_ID" in os.environ
        if is_render:
            try:
                import urllib.request
                
                # Fetch SET prices cache from GitHub Raw first to keep them completely synchronized!
                try:
                    github_set_url = "https://raw.githubusercontent.com/adisonarm36-ctrl/dr-tracker/main/backend/set_prices_cache.json"
                    print(f"Attempting to fetch pre-compiled SET prices cache from GitHub Raw: {github_set_url}")
                    req_set = urllib.request.Request(github_set_url, headers={'User-Agent': 'Mozilla/5.0'})
                    with urllib.request.urlopen(req_set, timeout=5) as response_set:
                        if response_set.status == 200:
                            cached_set_data = json.loads(response_set.read().decode('utf-8'))
                            if cached_set_data:
                                SET_PRICES_CACHE = cached_set_data
                                try:
                                    with open(SET_PRICES_FILE, "w", encoding="utf-8") as f:
                                        json.dump(cached_set_data, f, indent=2, ensure_ascii=False)
                                    print("Successfully updated and saved SET prices cache from GitHub.")
                                except Exception as file_err:
                                    print("Failed to write SET prices cache to local disk:", file_err)
                except Exception as set_err:
                    print("Failed to fetch SET prices cache from GitHub:", set_err)

                github_url = "https://raw.githubusercontent.com/adisonarm36-ctrl/dr-tracker/main/backend/top_movers_cache.json"
                print(f"Attempting to fetch pre-compiled cache from GitHub Raw: {github_url}")
                req = urllib.request.Request(github_url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=5) as response:
                    if response.status == 200:
                        cached_file_data = json.loads(response.read().decode('utf-8'))
                        if cached_file_data and "data" in cached_file_data and "movers" in cached_file_data["data"]:
                            response_data = cached_file_data["data"]
                            
                            with cache_lock:
                                top_movers_cache["data"] = response_data
                                top_movers_cache["last_fetched"] = pytime.time()
                                top_movers_cache["is_updating"] = False
                                
                            try:
                                with open(MOVERS_CACHE_FILE, "w", encoding="utf-8") as f:
                                    json.dump(cached_file_data, f, indent=2, ensure_ascii=False)
                                print("Successfully updated and saved local cache from GitHub pre-compiled file.")
                            except Exception as file_err:
                                print("Failed to write loaded GitHub cache to local disk:", file_err)
                            return
            except Exception as github_err:
                print("Failed to pull pre-compiled cache from GitHub raw, falling back to Yahoo Finance:", github_err)

        catalog = load_dr_catalog()
        # Query ALL recommended DRs (approx 262) as requested by user to get the complete market picture!
        symbols = [sym for sym, cat in catalog.items() if cat.get("recommend", False)]
        if not symbols:
            symbols = list(catalog.keys())
            
        # Deduplicate
        symbols = list(dict.fromkeys(symbols))
        
        # Batching configuration: download 20 symbols at a time to keep RAM extremely low!
        BATCH_SIZE = 20
        results = []
        
        for i in range(0, len(symbols), BATCH_SIZE):
            batch = symbols[i:i+BATCH_SIZE]
            tickers_string = " ".join([f"{sym}.BK" for sym in batch])
            
            print(f"Downloading batch {i//BATCH_SIZE + 1} ({len(batch)} symbols)...")
            try:
                # Controlled small download with 45 days period to get 30 trading days of daily candles!
                data = yf.download(tickers_string, period="45d", group_by='ticker', progress=False)
                
                for sym in batch:
                    ticker_sym = f"{sym}.BK"
                    try:
                        if ticker_sym in data.columns.levels[0]:
                            closes = data[ticker_sym]['Close'].dropna()
                            if len(closes) >= 2:
                                last_price = closes.iloc[-1]
                                prev_close = closes.iloc[-2]
                                change = ((last_price - prev_close) / prev_close) * 100
                                
                                catalog_item = catalog[sym]
                                
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
                                
                                # Build daily candles list for the 30-day candlestick chart
                                ticker_df = data[ticker_sym].dropna(subset=['Close'])
                                candles_list = []
                                for idx, row in ticker_df.iterrows():
                                    try:
                                        candles_list.append({
                                            "date": idx.strftime('%Y-%m-%d'),
                                            "open": round(float(row['Open']), 2),
                                            "high": round(float(row['High']), 2),
                                            "low": round(float(row['Low']), 2),
                                            "close": round(float(row['Close']), 2)
                                        })
                                    except Exception:
                                        pass
                                
                                candles_list = candles_list[-30:]
                                prices_list = [c["close"] for c in candles_list]
                                
                                tz_bangkok = pytz.timezone('Asia/Bangkok')
                                last_trade_time = datetime.now(tz_bangkok).strftime('%H:%M (%d/%m)')
                                SET_PRICES_CACHE[sym] = {
                                    "price": round(float(last_price), 2),
                                    "prices": prices_list,
                                    "change_pct": round(float(change), 2),
                                    "prev_close": round(float(prev_close), 2),
                                    "delay_msg": "Delayed",
                                    "last_trade_time": last_trade_time,
                                    "candles": candles_list
                                }
                    except Exception:
                        pass
            except Exception as e:
                print(f"Error in batch {i//BATCH_SIZE + 1}:", e)
                
            # Controlled delay between batches to be extremely gentle on memory/CPU
            pytime.sleep(0.5)
            
        if not results:
            print("No movers results parsed from batch download.")
            with cache_lock:
                top_movers_cache["is_updating"] = False
            return
            
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
        
        # Update cache in memory and write to disk
        with cache_lock:
            top_movers_cache["data"] = response_data
            top_movers_cache["last_fetched"] = pytime.time()
            top_movers_cache["is_updating"] = False
            
        try:
            with open(MOVERS_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "data": response_data,
                    "last_fetched": top_movers_cache["last_fetched"]
                }, f, indent=2, ensure_ascii=False)
            print("Saved top movers batch cache to file successfully.")
        except Exception as e:
            print("Failed to save top movers batch cache file:", e)
            
        try:
            with open(SET_PRICES_FILE, "w", encoding="utf-8") as f:
                json.dump(SET_PRICES_CACHE, f, indent=2, ensure_ascii=False)
            print("Saved SET prices cache to file successfully.")
        except Exception as e:
            print("Failed to save SET prices cache file:", e)
            
    except Exception as e:
        print("Error updating top movers in background:", e)
        with cache_lock:
            top_movers_cache["is_updating"] = False

@app.get("/api/top_movers")
def get_top_movers(force: bool = False):
    import time
    now = time.time()
    
    with cache_lock:
        cached_data = top_movers_cache["data"]
        last_fetched = top_movers_cache["last_fetched"]
        is_updating = top_movers_cache["is_updating"]
        
    # Dynamic cache timing: 15 minutes (900s) on Render to save RAM/CPU, 3 minutes (180s) locally for fast updates!
    is_render = os.environ.get("RENDER") == "true" or "RENDER_SERVICE_ID" in os.environ
    cache_timeout = 900 if is_render else 180
    
    is_stale = (now - last_fetched > cache_timeout) or (cached_data is None) or force
    
    if force:
        print("Force refresh requested for top movers. Bypassing cache!")
        if not is_updating:
            with cache_lock:
                top_movers_cache["data"] = None
                cached_data = None
    
    if is_stale and not is_updating:
        with cache_lock:
            top_movers_cache["is_updating"] = True
        t = threading.Thread(target=update_movers_background)
        t.daemon = True
        t.start()
        
    if cached_data:
        return cached_data
        
    # Brief active wait (up to 2 seconds) for first-load case to see if background thread finishes quickly
    import time as pytime
    for _ in range(20):
        pytime.sleep(0.1)
        with cache_lock:
            if top_movers_cache["data"]:
                return top_movers_cache["data"]
                
    return {
        "status": "success",
        "timestamp": datetime.now().isoformat(),
        "movers": {
            "US": {"gainers": [], "losers": []},
            "HK/CN": {"gainers": [], "losers": []},
            "Others": {"gainers": [], "losers": []}
        },
        "is_loading": True
    }

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
