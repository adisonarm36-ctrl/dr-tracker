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
    
    # 1. Cache-First Lookup
    cache_key = ticker
    if ticker.endswith(".BK"):
        cache_key = ticker[:-3]
        
    if cache_key in SET_PRICES_CACHE:
        cached = SET_PRICES_CACHE[cache_key]
        if isinstance(cached, dict) and "price" in cached:
            return cached["price"]
        elif isinstance(cached, (int, float)):
            return cached
            
    # On Render, if not in cache, avoid calling Yahoo Finance and return safe fallbacks
    is_render = os.environ.get("RENDER") == "true" or "RENDER_SERVICE_ID" in os.environ
    if is_render:
        fallbacks = {
            "HKDTHB=X": 4.7,
            "USDTHB=X": 36.5,
            "CNYTHB=X": 5.0,
            "SGDTHB=X": 27.0,
            "VNDTHB=X": 0.0014,
            "JPYTHB=X": 0.23,
            "EURTHB=X": 40.0,
            "TWDTHB=X": 1.12,
            "DKKTHB=X": 5.00
        }
        if ticker in fallbacks:
            return fallbacks[ticker]
        print(f"Cache miss for underlying price {ticker} on Render. Returning fallback 0.0")
        return 0.0

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
    
    # 1. Cache-First Lookup
    cache_key = ticker
    if ticker.endswith(".BK"):
        cache_key = ticker[:-3]
        
    if cache_key in SET_PRICES_CACHE:
        cached = SET_PRICES_CACHE[cache_key]
        if isinstance(cached, dict) and "price" in cached and "candles" in cached:
            return {
                "price": cached.get("price", 0.0),
                "prices": cached.get("prices", []),
                "change_pct": cached.get("change_pct", 0.0),
                "delay_msg": cached.get("delay_msg", "Cached"),
                "prev_close": cached.get("prev_close", 0.0),
                "last_trade_time": cached.get("last_trade_time", ""),
                "candles": cached.get("candles", [])
            }
            
    # On Render, if not in cache, avoid calling Yahoo Finance and return dummy data
    is_render = os.environ.get("RENDER") == "true" or "RENDER_SERVICE_ID" in os.environ
    if is_render:
        print(f"Cache miss for rich data {ticker} on Render. Returning fallback safe object.")
        price = get_price_safe(ticker)
        return {"price": price, "prices": [price] if price else [], "change_pct": 0.0, "delay_msg": "Unavailable", "prev_close": 0.0, "last_trade_time": "", "candles": []}

    try:
        t = yf.Ticker(ticker)
        try:
            prev_close = t.fast_info.previous_close
        except:
            prev_close = 0.0

        # Fetch daily history for 45 days (covers approx 30 trading days) for ALL tickers
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
        
        # Keep pricing perfectly real-time by checking fast_info
        try:
            live_price = t.fast_info.last_price
            if live_price and live_price > 0:
                last_price = live_price
                if candles:
                    candles[-1]["close"] = round(float(live_price), 2)
                    if live_price > candles[-1]["high"]:
                        candles[-1]["high"] = round(float(live_price), 2)
                    if live_price < candles[-1]["low"]:
                        candles[-1]["low"] = round(float(live_price), 2)
        except:
            pass

        change_pct = ((last_price - prev_close) / prev_close) * 100 if prev_close and prev_close > 0 else 0.0
        
        # Last trade time
        last_ts = hist.index[-1]
        tz_bangkok = pytz.timezone('Asia/Bangkok')
        if last_ts.tzinfo is not None:
            last_ts_bangkok = last_ts.astimezone(tz_bangkok)
        else:
            last_ts_bangkok = pytz.utc.localize(last_ts).astimezone(tz_bangkok)
        last_trade_time = last_ts_bangkok.strftime('%H:%M (%d/%m)')
        
        # Calculate delay message based on ticker market type
        now_utc = datetime.now(timezone.utc)
        if last_ts.tzinfo is not None:
            last_ts_utc = last_ts.astimezone(timezone.utc)
        else:
            last_ts_utc = last_ts.replace(tzinfo=timezone.utc)
        diff_minutes = int((now_utc - last_ts_utc).total_seconds() / 60)
        
        if ticker.endswith(".BK"):
            delay_msg = "Delayed"
        else:
            # Check for overnight/live
            is_overnight = False
            try:
                tz_th = pytz.timezone('Asia/Bangkok')
                now_th = datetime.now(tz_th)
                time_float = now_th.hour + now_th.minute / 60.0
                if time_float >= 20.5 or time_float <= 3.0:
                    is_overnight = True
            except:
                pass
                
            if is_overnight:
                delay_msg = "Overnight (Live)"
            else:
                if diff_minutes <= 1440:  # within 24 hours
                    delay_msg = "Realtime" if diff_minutes <= 15 else "Delayed"
                else:
                    delay_msg = "Market Closed"
                    
        return {
            "price": round(last_price, 2),
            "prices": prices,
            "change_pct": round(change_pct, 2),
            "delay_msg": delay_msg,
            "prev_close": round(prev_close, 2) if prev_close else 0.0,
            "last_trade_time": last_trade_time,
            "candles": candles
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
            
        # Deduplicate symbols
        symbols = list(dict.fromkeys(symbols))
        
        # 1. Collect all unique underlying tickers from the catalog for recommended DRs
        underlying_tickers = set()
        for sym in symbols:
            cat_item = catalog[sym]
            market = cat_item.get("market", "US")
            
            hk_t = cat_item.get('primary') if market in ['HK', 'CN', 'SG', 'VN', 'JP', 'AS', 'FR', 'IT', 'TW', 'DK', 'DE'] else None
            us_t = cat_item.get('primary') if market == 'US' else cat_item.get('us_adr')
            
            if hk_t: underlying_tickers.add(hk_t)
            if us_t: underlying_tickers.add(us_t)
            
        underlying_tickers = list(underlying_tickers)
        
        # 2. FX rates list
        fx_tickers = ["HKDTHB=X", "USDTHB=X", "CNYTHB=X", "SGDTHB=X", "VNDTHB=X", "JPYTHB=X", "EURTHB=X", "TWDTHB=X", "DKKTHB=X"]
        
        # 3. Combine into a single deduplicated list
        all_tickers = []
        for sym in symbols:
            all_tickers.append(f"{sym}.BK")
        all_tickers.extend(underlying_tickers)
        all_tickers.extend(fx_tickers)
        all_tickers = list(dict.fromkeys(all_tickers))
        
        print(f"Total tickers to fetch in background: {len(all_tickers)} (DRs on SET: {len(symbols)}, Underlyings: {len(underlying_tickers)}, FX: {len(fx_tickers)})")
        
        # Batching configuration: download 30 symbols at a time to keep RAM extremely low!
        BATCH_SIZE = 30
        results = []
        
        for i in range(0, len(all_tickers), BATCH_SIZE):
            batch = all_tickers[i:i+BATCH_SIZE]
            tickers_string = " ".join(batch)
            
            print(f"Downloading batch {i//BATCH_SIZE + 1} ({len(batch)} symbols)...")
            try:
                # Controlled download with 45 days period to get 30 trading days of daily candles!
                data = yf.download(tickers_string, period="45d", group_by='ticker', progress=False)
                
                for ticker_sym in batch:
                    try:
                        if len(batch) == 1:
                            closes = data['Close'].dropna()
                            df = data
                        else:
                            if ticker_sym not in data.columns.levels[0]:
                                continue
                            closes = data[ticker_sym]['Close'].dropna()
                            df = data[ticker_sym]
                            
                        if len(closes) >= 2:
                            last_price = closes.iloc[-1]
                            prev_close = closes.iloc[-2]
                            change = ((last_price - prev_close) / prev_close) * 100
                            
                            # Build daily candles list for the 30-day candlestick chart
                            ticker_df = df.dropna(subset=['Close'])
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
                            
                            parsed_item = {
                                "price": round(float(last_price), 2),
                                "prices": prices_list,
                                "change_pct": round(float(change), 2),
                                "prev_close": round(float(prev_close), 2),
                                "delay_msg": "Delayed",
                                "last_trade_time": last_trade_time,
                                "candles": candles_list
                            }
                            
                            # Cache in SET_PRICES_CACHE
                            if ticker_sym.endswith(".BK"):
                                sym = ticker_sym[:-3]
                                SET_PRICES_CACHE[sym] = parsed_item
                                
                                # Add to results list for movers rankings
                                catalog_item = catalog.get(sym)
                                if catalog_item:
                                    market = catalog_item.get("market", "US")
                                    if market == "US":
                                        market_group = "US"
                                    elif market in ["HK", "CN"]:
                                        market_group = "HK/CN"
                                    elif market == "JP":
                                        market_group = "JP"
                                    else:
                                        market_group = "Others"
                                        
                                    results.append({
                                        "symbol": sym,
                                        "name": catalog_item.get("name", sym),
                                        "price": round(float(last_price), 2),
                                        "change_pct": round(float(change), 2),
                                        "market_group": market_group
                                    })
                            else:
                                SET_PRICES_CACHE[ticker_sym] = parsed_item
                                
                    except Exception as parse_err:
                        print(f"Error parsing ticker {ticker_sym}: {parse_err}")
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
        markets = {"US": [], "HK/CN": [], "JP": [], "Others": []}
        for r in results:
            if r["market_group"] in markets:
                markets[r["market_group"]].append(r)
                
        movers = {}
        for grp, items in markets.items():
            gainers = sorted(items, key=lambda x: x["change_pct"], reverse=True)
            losers = sorted(items, key=lambda x: x["change_pct"])
            
            movers[grp] = {
                "gainers": gainers[:10],
                "losers": losers[:10]
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
            "JP": {"gainers": [], "losers": []},
            "Others": {"gainers": [], "losers": []}
        },
        "is_loading": True
    }

NARRATIVE_MAPPING = {
    "NVDA": {
        "name": "NVIDIA",
        "sector": "Semiconductors",
        "themes": ["AI", "Data Center", "Semiconductor", "Compute"],
        "granular_group": "AI Processing Chips",
        "description": "ผู้นำชิปประมวลผล GPU สำหรับปัญญาประดิษฐ์และโครงสร้างพื้นฐาน Data Center"
    },
    "AAPL": {
        "name": "Apple",
        "sector": "Technology",
        "themes": ["AI", "Compute"],
        "granular_group": "Consumer Electronics & Edge AI",
        "description": "ยักษ์ใหญ่เทคโนโลยีผู้พัฒนา Apple Intelligence และชิประดับสูง Apple Silicon"
    },
    "MSFT": {
        "name": "Microsoft",
        "sector": "Software",
        "themes": ["AI", "Compute"],
        "granular_group": "Hyperscale Cloud & Enterprise Software",
        "description": "ผู้นำซอฟต์แวร์ระดับโลก คลาวด์ Azure AI และความร่วมมือแนบแน่นกับ OpenAI"
    },
    "TSLA": {
        "name": "Tesla",
        "sector": "Electronic Technology",
        "themes": ["AI", "Compute"],
        "granular_group": "Autonomous Systems & EV Robotics",
        "description": "ผู้ผลิตยานยนต์ไฟฟ้าอัจฉริยะ นำเทคโนโลยี AI มาใช้ในการขับเคลื่อนอัตโนมัติและหุ่นยนต์"
    },
    "AVGO": {
        "name": "Broadcom",
        "sector": "Semiconductors",
        "themes": ["Semiconductor", "Data Center", "Optical"],
        "granular_group": "AI Processing Chips",
        "description": "ชิปการเชื่อมต่อระบบเครือข่ายความเร็วสูง และโมดูลส่งสัญญาณแสงสำหรับโครงข่ายข้อมูล"
    },
    "AMD": {
        "name": "AMD",
        "sector": "Semiconductors",
        "themes": ["AI", "Compute", "Semiconductor", "Data Center"],
        "granular_group": "AI Processing Chips",
        "description": "ผู้ท้าชิงหลักชิป AI GPU (Instinct) และซีพียูสำหรับเซิร์ฟเวอร์ EPYC"
    },
    "SMCI": {
        "name": "Super Micro",
        "sector": "Technology",
        "themes": ["Compute", "Data Center"],
        "granular_group": "AI Servers & Liquid Cooling",
        "description": "ผู้ผลิตเซิร์ฟเวอร์ประมวลผล AI สมรรถนะสูงพร้อมโซลูชันระบบระบายความร้อนด้วยของเหลว"
    },
    "MU": {
        "name": "Micron",
        "sector": "Semiconductors",
        "themes": ["Semiconductor", "Compute", "Data Center"],
        "granular_group": "High-Performance Memory",
        "description": "ผู้ผลิตหน่วยความจำแบนด์วิดท์สูง (HBM3E) สำคัญสำหรับการประมวลผลจีพียู AI"
    },
    "ASML": {
        "name": "ASML",
        "sector": "Semiconductors",
        "themes": ["Semiconductor"],
        "granular_group": "Semiconductor Equipment & Fab Supply",
        "description": "ผู้ผลิตเครื่องจักรฉายรังสีออปติคอล EUV ชิ้นสำคัญในการพิมพ์ลายวงจรชิปขั้นสูงที่สุดในโลก"
    },
    "LRCX": {
        "name": "Lam Research",
        "sector": "Semiconductors",
        "themes": ["Semiconductor"],
        "granular_group": "Semiconductor Equipment & Fab Supply",
        "description": "ผู้ผลิตอุปกรณ์สลักแผ่นเวเฟอร์ซิลิคอนระดับนาโนสำหรับโรงงานผลิตชิป"
    },
    "AMAT": {
        "name": "Applied Materials",
        "sector": "Semiconductors",
        "themes": ["Semiconductor"],
        "granular_group": "Semiconductor Equipment & Fab Supply",
        "description": "ผู้ผลิตเครื่องจักรเคลือบสารตัวนำผิวเวเฟอร์ในอุตสาหกรรมชิป"
    },
    "VST": {
        "name": "Vistra",
        "sector": "Electronic Technology",
        "themes": ["Power Infra", "Data Center"],
        "granular_group": "Clean Energy & Power Infrastructure",
        "description": "ผู้ผลิตพลังงานไฟฟ้าสะอาดที่ใหญ่ที่สุดรายหนึ่งในสหรัฐฯ ซัพพลายระบบ Data Center"
    },
    "CEG": {
        "name": "Constellation",
        "sector": "Electronic Technology",
        "themes": ["Power Infra", "Data Center"],
        "granular_group": "Clean Energy & Power Infrastructure",
        "description": "ผู้ผลิตพลังงานนิวเคลียร์สะอาดอันดับหนึ่งของสหรัฐฯ เซ็นสัญญาจ่ายไฟแก่ไมโครซอฟท์"
    },
    "GEV": {
        "name": "GE Vernova",
        "sector": "Electronic Technology",
        "themes": ["Power Infra"],
        "granular_group": "Clean Energy & Power Infrastructure",
        "description": "ผู้นำอุปกรณ์ระบบกริดสายส่งไฟฟ้า กังหันลม และเครื่องปั่นไฟฟ้าขนาดใหญ่ทั่วโลก"
    },
    "DELL": {
        "name": "Dell",
        "sector": "Technology",
        "themes": ["Compute", "Data Center"],
        "granular_group": "AI Servers & Liquid Cooling",
        "description": "ผู้จำหน่ายเซิร์ฟเวอร์ AI และโครงสร้างพื้นฐานการจัดการข้อมูลสำหรับองค์กร"
    },
    "ANET": {
        "name": "Arista Networks",
        "sector": "Technology",
        "themes": ["Data Center", "Optical"],
        "granular_group": "High-Speed Cloud Networking",
        "description": "ผู้นำสวิตช์สายส่งโครงข่ายความเร็วสูงระดับ Ultra-low Latency ในระดับ Data Center ขนาดใหญ่"
    },
    "COHR": {
        "name": "Coherent",
        "sector": "Technology",
        "themes": ["Optical", "Photonics"],
        "granular_group": "Optical Signal Communications",
        "description": "ผู้นำเทคโนโลยีชิ้นส่วนเลเซอร์และชิปสื่อสารส่งข้อมูลด้วยแสง 800G/1.6T"
    },
    "LITE": {
        "name": "Lumentum",
        "sector": "Technology",
        "themes": ["Optical", "Photonics"],
        "granular_group": "Optical Signal Communications",
        "description": "ผู้นำตัวรับส่งสัญญาณแสงพลังสูง เลเซอร์ไดโอดความแม่นยำสูงในระบบโครงข่ายสัญญาณ"
    },
    "QCOM": {
        "name": "Qualcomm",
        "sector": "Semiconductors",
        "themes": ["Semiconductor", "AI", "Compute"],
        "granular_group": "Consumer Electronics & Edge AI",
        "description": "ผู้นำชิปประมวลผลสื่อสารเคลื่อนที่ Snapdragon และสถาปัตยกรรม On-Device AI"
    },
    "META": {
        "name": "Meta",
        "sector": "Software",
        "themes": ["AI"],
        "granular_group": "Social Media & AI Ecosystems",
        "description": "ผู้พัฒนาโมเดล Llama AI และโซเชียลมีเดียชั้นนำระดับโลก"
    },
    "GOOG": {
        "name": "Alphabet",
        "sector": "Software",
        "themes": ["AI", "Compute", "Data Center"],
        "granular_group": "Hyperscale Cloud & Enterprise Software",
        "description": "ผู้พัฒนา Gemini AI บริการค้นหา คลาวด์ และตัวเร่งประมวลผล Tensor Processing Unit"
    },
    "AMZN": {
        "name": "Amazon",
        "sector": "Software",
        "themes": ["AI", "Data Center", "Compute"],
        "granular_group": "Hyperscale Cloud & Enterprise Software",
        "description": "ผู้นำบริการคลาวด์ยักษ์ใหญ่ AWS และผู้พัฒนาชิปเซ็ตประมวลผลและฝึกหัด AI"
    },
    "ADVANT": {
        "name": "Advantest",
        "sector": "Electronic Technology",
        "themes": ["Semiconductor", "Compute"],
        "granular_group": "Semiconductor Equipment & Fab Supply",
        "description": "ผู้ผลิตและออกแบบระบบทดสอบความถูกต้องของชิปเซ็ตและแผงวงจรความเร็วสูงของญี่ปุ่น"
    },
    "JPSEMI": {
        "name": "JPSEMI ETF",
        "sector": "Semiconductors",
        "themes": ["Semiconductor"],
        "granular_group": "Semiconductor Equipment & Fab Supply",
        "description": "กองทุนรวม ETF รวบรวมยักษ์ใหญ่ผู้ผลิตเครื่องจักรและชิปเซมิคอนดักเตอร์ของญี่ปุ่น"
    },
    "ASEMI": {
        "name": "ASEMI ETF",
        "sector": "Semiconductors",
        "themes": ["Semiconductor"],
        "granular_group": "Semiconductor Equipment & Fab Supply",
        "description": "กองทุนรวม ETF หุ้นเซมิคอนดักเตอร์ของเอเชียและฮ่องกง"
    },
    "CNSEMI": {
        "name": "CNSEMI ETF",
        "sector": "Semiconductors",
        "themes": ["Semiconductor"],
        "granular_group": "Semiconductor Equipment & Fab Supply",
        "description": "กองทุนรวม ETF หุ้นผู้พัฒนาเทคโนโลยีชิปพึ่งพาตนเองชั้นนำของจีน"
    }
}

SECTOR_NARRATIVES = {
    "Technology": "กลุ่มสินค้าและบริการเทคโนโลยีเป็นกลไกขับเคลื่อนการทำ Digital Transformation ทั่วโลก โดยปัจจุบันมีแรงหนุนหลักจากการปรับสถาปัตยกรรมคลาวด์เพื่อรับมือการคำนวณและบริหารจัดการ AI ในระดับองค์กรขนาดใหญ่",
    "Semiconductors": "เซมิคอนดักเตอร์คือ 'น้ำมันยุคใหม่' ชิปประมวลผล (GPU) และชิปหน่วยความจำแบนด์วิดท์สูง (HBM) เป็นทรัพยากรคอขวดที่ทุกค่ายยักษ์ใหญ่กำลังแย่งชิงกัน",
    "Software": "กลุ่มผู้พัฒนาซอฟต์แวร์และแอปพลิเคชันคลาวด์กำลังได้รับประโยชน์จากการรวมปัญญาประดิษฐ์ (AI Copilot) เข้ากับบริการเดิมเพื่อเรียกเก็บค่าบริการเพิ่มขึ้นแบบก้าวกระโดด",
    "Electronic Technology": "กลุ่มอิเล็กทรอนิกส์และผู้ให้บริการพลังงาน ได้รับประโยชน์อย่างมหาศาลจากการเร่งสร้างสายส่งไฟฟ้าและระบบโครงข่ายไฟฟ้ารองรับ Data Center และชิป AI ยุคใหม่"
}

THEME_NARRATIVES = {
    "AI": "ปัญญาประดิษฐ์ Generative AI คือ narrative การปฏิวัติทางวิทยาการที่ใหญ่ที่สุดในทศวรรษนี้ โดยบริษัทขนาดใหญ่แข่งขันพัฒนาโมเดลภาษาและการใช้งาน AI เชิงธุรกิจอย่างกว้างขวาง",
    "Data Center": "ศูนย์ข้อมูล Hyperscale Data Center โดดเด่นอย่างมากจากความจำเป็นในการปรับระบบระบายความร้อนด้วยของเหลว (Liquid Cooling) และเซิร์ฟเวอร์ประกอบเฉพาะทางสำหรับ AI",
    "Optical": "ระบบส่งสัญญาณเครือข่ายความเร็วสูงด้วยเส้นใยแก้วออปติกส์ระดับ 800G เป็นจุดสำคัญที่หลีกเลี่ยงไม่ได้ในการเชื่อมต่อกลุ่มจีพียูจำนวนมหาศาลเข้าด้วยกันใน Data Center",
    "Photonics": "เทคโนโลยีโฟโตนิกส์ (Photonics) นำพาการปฏิวัติการนำแสงเลเซอร์ส่งข้อมูลแทนสายไฟเพื่อทลายข้อจำกัดด้านพลังงานความร้อนและความเร็วยุคถัดไป",
    "Semiconductor": "อุตสาหกรรมชิปเซมิคอนดักเตอร์ต้นน้ำ โดดเด่นจากการลงทุนระดับชาติและการสร้างความมั่นคงด้านวิทยาการชิปเพื่อพึ่งพาตนเอง ทั้งในสหรัฐฯ ฮ่องกง และญี่ปุ่น",
    "Compute": "ความต้องการขีดความสามารถการประมวลผลสมรรถนะสูงเป็นตัวขับเคลื่อนหลัก นำมาซึ่งความต้องการชิป GPU ตัวท็อป และชิปประมวลผลคลาวด์ที่ออกแบบขึ้นเป็นการเฉพาะ",
    "Power Infra": "โครงสร้างพื้นฐานพลังงานไฟฟ้าและนิวเคลียร์คือกลุ่มเหมืองทองคำใหม่ในการป้อนกระแสไฟฟ้าอันมหาศาลแก่ Data Center ทั่วสหรัฐฯ สัญญาส่งจ่ายไฟฟ้าสะอาดระยะยาวได้รับแรงหนุนสุดร้อนแรง"
}

UPCOMING_EVENTS = [
    {
        "symbol": "AAPL",
        "underlying": "Apple",
        "event_name": "Apple WWDC 2026 Developer Conference",
        "date": "มิถุนายน 2026",
        "impact": "High",
        "description": "การเปิดตัว iOS 20 พร้อมฟีเจอร์ AI 'Apple Intelligence 2.0' ที่ประมวลผลบนชิป Apple Silicon รุ่นใหม่ คาดกระตุ้นยอดขายอัปเกรด iPhone ยุคใหม่"
    },
    {
        "symbol": "NVDA",
        "underlying": "NVIDIA",
        "event_name": "Computex Taipei 2026 & Keynote",
        "date": "ต้นมิถุนายน 2026",
        "impact": "Critical",
        "description": "CEO Jensen Huang เตรียมขึ้นแถลงเปิดตัวสถาปัตยกรรมชิป AI รุ่นถัดไป (คาดเป็นรหัส Rubin หรือสถาปัตยกรรม Blackwell Ultra) คาดกระตุ้นความต้องการสั่งซื้อ GPU ทั่วโลก"
    },
    {
        "symbol": "TSLA",
        "underlying": "Tesla",
        "event_name": "Tesla RoboTaxi FSD V13 Launch",
        "date": "กลางปี 2026",
        "impact": "High",
        "description": "งานเปิดตัวทดลองใช้บริการ RoboTaxi บนเครือข่าย FSD เต็มระบบเชิงพาณิชย์ในสหรัฐฯ เป็นจุดเปลี่ยนสำคัญด้าน AI ในยานยนต์ไร้คนขับ"
    },
    {
        "symbol": "MSFT",
        "underlying": "Microsoft",
        "event_name": "Azure AI Partner Summit 2026",
        "date": "กรกฎาคม 2026",
        "impact": "Medium",
        "description": "การประกาศแผนการรวมโมเดล GPT-5 (หรือโมเดล AI รุ่นถัดไปจาก OpenAI) เข้าสู่ระบบปฏิบัติการ Windows และคลาวด์ Azure ในเชิงพาณิชย์"
    },
    {
        "symbol": "ASML",
        "underlying": "ASML",
        "event_name": "High-NA EUV Machine Shipments Update",
        "date": "ไตรมาส 3 2026",
        "impact": "High",
        "description": "รายงานความคืบหน้าการส่งมอบเครื่องพิมพ์ลายวงจรชิปขนาดจิ๋วรุ่นประหยัดพลังงานตัวท็อปราคา 350 ล้านดอลลาร์ ให้แก่ Intel, TSMC, และ Samsung"
    }
]

GRANULAR_GROUPS_METADATA = {
    "Hyperscale Cloud & Enterprise Software": {
        "name_th": "คลาวด์ยักษ์ใหญ่ & ซอฟต์แวร์องค์กร",
        "icon": "☁️",
        "description": "ผู้ให้บริการโครงสร้างพื้นฐานคลาวด์ (IaaS) และผู้พัฒนาซอฟต์แวร์ระบบคลาวด์สำหรับธุรกิจและ AI ในระดับองค์กรยักษ์ใหญ่"
    },
    "Social Media & AI Ecosystems": {
        "name_th": "โซเชียลมีเดีย & ระบบโมเดล AI เปิด",
        "icon": "💬",
        "description": "ผู้นำแพลตฟอร์มโซเชียลมีเดียระดับพันล้านผู้ใช้งาน และผู้พัฒนาโครงข่ายโมเดลเปิดภาษาขนาดใหญ่ (Open-source AI Llama)"
    },
    "Consumer Electronics & Edge AI": {
        "name_th": "อุปกรณ์ไอที & ปัญญาประดิษฐ์บนอุปกรณ์พกพา",
        "icon": "📱",
        "description": "ผู้พัฒนาอุปกรณ์อิเล็กทรอนิกส์พรีเมียมส่วนบุคคล ชิปประมวลผลขนาดจิ๋ว และสถาปัตยกรรม Edge AI บนสมาร์ตโฟนและแล็ปท็อป"
    },
    "AI Processing Chips": {
        "name_th": "ผู้ออกแบบชิปประมวลผล AI & GPU",
        "icon": "👾",
        "description": "บริษัทผู้คิดค้นและออกแบบการ์ดประมวลผลหลัก (GPU) และชิปเฉพาะทางสำหรับการเรียนรู้และประมวลผลเชิงลึกของปัญญาประดิษฐ์"
    },
    "High-Performance Memory": {
        "name_th": "หน่วยความจำสมรรถนะสูง & HBM",
        "icon": "💾",
        "description": "ผู้ผลิตและพัฒนาชิปหน่วยความจำแบนด์วิดท์สูงพิเศษ (HBM) ซึ่งเป็นทรัพยากรหลักที่ขาดไม่ได้ในการส่งข้อมูลให้ GPU ประมวลผล"
    },
    "AI Servers & Liquid Cooling": {
        "name_th": "เซิร์ฟเวอร์ AI & ระบบระบายความร้อน",
        "icon": "🖥️",
        "description": "ผู้ประกอบระบบตู้เซิร์ฟเวอร์ประกอบเฉพาะทางสำหรับ AI, โซลูชันการจัดการความร้อน และการระบายความร้อนด้วยของเหลวในดาต้าเซ็นเตอร์"
    },
    "High-Speed Cloud Networking": {
        "name_th": "ระบบเครือข่ายความเร็วสูง & สวิตช์เชื่อมต่อ",
        "icon": "🔌",
        "description": "ผู้จัดหาระบบสวิตช์เราเตอร์และอุปกรณ์เชื่อมต่อสายส่งเครือข่ายความเร็วสูงเป็นพิเศษในการผูกกลุ่มคลัสเตอร์ GPU ขนาดใหญ่เข้าด้วยกัน"
    },
    "Optical Signal Communications": {
        "name_th": "เลเซอร์ & การสื่อสารสัญญาณแสง",
        "icon": "⚡",
        "description": "ผู้พัฒนาชิ้นส่วนเลเซอร์ออปติคอลโมดูล และตัวรับส่งสัญญาณส่งถ่ายข้อมูลความเร็วสูง 800G/1.6T เพื่อประหยัดพลังงานความร้อน"
    },
    "Semiconductor Equipment & Fab Supply": {
        "name_th": "เครื่องจักรผลิตชิป & เทคโนโลยีการพิมพ์วงจร",
        "icon": "⚙️",
        "description": "บริษัทเครื่องจักรอุตสาหกรรมต้นน้ำระดับโลก ทั้งด้านการพิมพ์ลายวงจรด้วยรังสี (EUV), การเคลือบผิวเวเฟอร์ และระบบการตรวจสอบชิป"
    },
    "Autonomous Systems & EV Robotics": {
        "name_th": "ระบบยานยนต์อัตโนมัติ & หุ่นยนต์อัจฉริยะ",
        "icon": "🚗",
        "description": "ผู้พัฒนาโครงข่ายชิปประมวลผลการขับเคลื่อนอัตโนมัติเต็มระบบ (FSD), บริการแท็กซี่ไร้คนขับ และหุ่นยนต์ฮิวแมนนอยด์อัจฉริยะ"
    },
    "Clean Energy & Power Infrastructure": {
        "name_th": "พลังงานสะอาด & โครงสร้างพื้นฐานไฟฟ้า",
        "icon": "🔋",
        "description": "ผู้ให้บริการพลังงานไฟฟ้านิวเคลียร์ สายส่งส่งจ่ายพลังงานสะอาด และโรงผลิตพลังงานไฟฟ้าสำหรับป้อนแก่ Hyperscale Data Center"
    },
    "Financial Services": {
        "name_th": "ธุรกิจการเงิน & การธนาคาร",
        "icon": "🏦",
        "description": "กลุ่มธุรกิจธนาคาร ประกันภัย กองทุน และบริการการชำระเงินในระดับโลก"
    },
    "Healthcare": {
        "name_th": "สุขภาพ & การแพทย์ชีวภาพ",
        "icon": "🏥",
        "description": "ผู้พัฒนาเภสัชภัณฑ์ชีวภาพ อุปกรณ์ทางการแพทย์ และบริการดูแลสุขภาพชั้นนำ"
    },
    "Consumer Cyclical": {
        "name_th": "สินค้าฟุ่มเฟือย & ยานยนต์ระดับโลก",
        "icon": "🛍️",
        "description": "แบรนด์แฟชั่นหรูระดับโลก บริการการท่องเที่ยว ร้านอาหาร และผู้ผลิตยานยนต์ชั้นนำ"
    },
    "Consumer Defensive": {
        "name_th": "สินค้าอุปโภคบริโภคจำเป็น",
        "icon": "🛒",
        "description": "ผู้ผลิตและค้าปลีกอาหาร เครื่องดื่ม และสินค้าอุปโภคจำเป็นพื้นฐานในชีวิตประจำวัน"
    },
    "Industrials": {
        "name_th": "อุตสาหกรรมหนัก & วิศวรรณระบบ",
        "icon": "🏗️",
        "description": "กลุ่มเทคโนโลยีอุตสาหกรรม เครื่องจักร สายพานสายส่ง และระบบขับเคลื่อนไฟฟ้าขนาดใหญ่"
    },
    "Basic Materials": {
        "name_th": "วัสดุพื้นฐาน & พลังงานสะอาดต้นน้ำ",
        "icon": "💎",
        "description": "ผู้ผลิตทรัพยากรต้นน้ำ โลหะ เหมืองแร่ ลิเทียม และสารตัวนำป้อนอุตสาหกรรมสีเขียว"
    },
    "Communication Services": {
        "name_th": "สื่อสาร & บันเทิงแพลตฟอร์ม",
        "icon": "📡",
        "description": "ผู้นำบริการสื่อสารเคลื่อนที่ แพลตฟอร์มสตรีมมิ่ง โซเชียลเน็ตเวิร์ก และเกมออนไลน์"
    },
    "Utilities": {
        "name_th": "สาธารณูปโภค & พลังงานทดแทน",
        "icon": "🚰",
        "description": "ผู้ส่งจ่ายกระแสไฟฟ้า น้ำประปา และระบบพลังงานทดแทนพื้นฐานของประเทศ"
    },
    "Energy": {
        "name_th": "พลังงานดั้งเดิม & น้ำมันปิโตรเลียม",
        "icon": "🛢️",
        "description": "ผู้สำรวจ ผลิต และกลั่นน้ำมันดิบ ก๊าซธรรมชาติป้อนอุตสาหกรรมหลักทั่วโลก"
    },
    "ETFs & Indices": {
        "name_th": "กองทุนดัชนี & ETFs รวมตลาด",
        "icon": "📈",
        "description": "กองทุนดัชนี ETFs รวมตลาดหุ้นต่างประเทศ ดัชนีหลัก และพันธบัตรรัฐบาลเพื่อการกระจายความเสี่ยง"
    },
    "Other / Diverse": {
        "name_th": "ธุรกิจหลากหลาย & กองทุนรวมเฉพาะกลุ่ม",
        "icon": "💼",
        "description": "สินทรัพย์ทางเลือกอื่น ๆ กองทุนรวมเฉพาะกลุ่ม หรือหุ้นที่มีความหลากหลายทางธุรกิจสูง"
    }
}

def compute_narratives_data():
    import re
    # Load catalog to make sure we map accurately
    catalog = load_dr_catalog()
    
    # Group DRs by underlying prefix first to prevent duplicate assets (ตัวไม่ซ้ำกัน)
    # For each prefix, we keep the one with the highest absolute performance change percentage.
    best_drs_by_prefix = {}
    for sym, cached in SET_PRICES_CACHE.items():
        # Only process recommended DRs listed in the catalog
        if sym not in catalog or not catalog[sym].get("recommend", False):
            continue
            
        change_pct = cached.get("change_pct", 0.0)
        price = cached.get("price", 0.0)
        
        # Match symbol prefix (strip trailing digits e.g., ASML01 -> ASML)
        match = re.match(r"^([A-Z]+)", sym)
        matched_prefix = match.group(1) if match else sym
        
        mapping_item = NARRATIVE_MAPPING.get(matched_prefix)
        if mapping_item:
            group_key = mapping_item["granular_group"]
            name = mapping_item["name"]
            description = mapping_item["description"]
        else:
            # Fallback to catalog-enriched sector
            group_key = catalog[sym].get("sector", "Other / Diverse")
            if not group_key or group_key == "N/A" or group_key == "None":
                group_key = "Other / Diverse"
            name = catalog[sym].get("name", sym)
            if " DR" in name:
                name = name.split(" DR")[0]
            market_label = catalog[sym].get("market", "US")
            description = f"หุ้นเด่นในกลุ่ม {group_key} (ตลาด {market_label})"
            
        # Get active price from parent ticker if available for display
        primary_sym = catalog[sym].get("primary")
        parent_price = price
        if primary_sym and primary_sym in SET_PRICES_CACHE:
            parent_price = SET_PRICES_CACHE[primary_sym].get("price", parent_price)
            
        # Select best representative for this underlying prefix based on absolute return of the DR
        if matched_prefix not in best_drs_by_prefix or abs(change_pct) > abs(best_drs_by_prefix[matched_prefix]["change_pct"]):
            best_drs_by_prefix[matched_prefix] = {
                "symbol": sym, # Keep actual Thai DR symbol e.g., ASML01, LRCX23
                "name": name,
                "price": price, # Actual Thai DR stock price on SET in Baht
                "parent_price": parent_price, # Global parent stock price
                "change_pct": change_pct, # Actual Thai DR daily change percent (e.g. 37.14% for DELL19)
                "description": description,
                "granular_group": group_key
            }
            
    # Establish dynamic groups
    groups_data = {}
    for group_key in GRANULAR_GROUPS_METADATA.keys():
        groups_data[group_key] = []
        
    # Classify unique DRs into their groups
    for prefix, dr_item in best_drs_by_prefix.items():
        grp = dr_item["granular_group"]
        if grp not in groups_data:
            grp = "Other / Diverse"
        groups_data[grp].append(dr_item)
        
    # Compute statistics for each group
    groups_results = []
    for grp_key, items in groups_data.items():
        if not items:
            continue
            
        avg_change = sum(x["change_pct"] for x in items) / len(items)
        leader = sorted(items, key=lambda x: x["change_pct"], reverse=True)[0]
        meta = GRANULAR_GROUPS_METADATA.get(grp_key, {"name_th": grp_key, "icon": "📁", "description": ""})
        
        # Sort items inside the group from highest change (+) to lowest change (-)
        sorted_items = sorted(items, key=lambda x: x["change_pct"], reverse=True)
        
        groups_results.append({
            "group_key": grp_key,
            "name_th": meta["name_th"],
            "icon": meta["icon"],
            "description": meta["description"],
            "avg_change": round(avg_change, 2),
            "dr_count": len(items),
            "leader_symbol": leader["symbol"],
            "leader_name": leader["name"],
            "leader_change": leader["change_pct"],
            "items": sorted_items
        })
        
    # Sort groups by avg_change descending (Hottest groups first)
    groups_results = sorted(groups_results, key=lambda x: x["avg_change"], reverse=True)
    
    return {
        "status": "success",
        "timestamp": datetime.now().isoformat(),
        "groups": groups_results,
        "events": UPCOMING_EVENTS
    }

@app.get("/api/narratives")
def get_narratives():
    return compute_narratives_data()

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)

