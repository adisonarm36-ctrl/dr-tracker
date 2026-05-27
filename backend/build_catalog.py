import re
import json
import os

def build():
    raw_path = r"c:\Users\USER\Documents\AI\DR\ผลลัพธ์การค้นหา 378 DR.txt"
    catalog_path = r"c:\Users\USER\Documents\AI\DR\backend\dr_catalog.json"
    
    # Mappings for the 100+ new non-US underlyings to Yahoo Finance primary tickers
    NON_US_MAPPINGS = {
        "ADVANT": "6857.T",
        "AIA": "1299.HK",
        "ANTA": "2020.HK",
        "ASEMI ETF": "3119.HK",
        "ASICS": "7936.T",
        "ASML": "ASML.AS",
        "BABA": "9988.HK",
        "BIDU": "9888.HK",
        "BILIBI": "9626.HK",
        "BIREN": "6082.HK",
        "BONDAS ETF": "N6M.SI",
        "BYD": "1211.HK",
        "BYDCOM": "0285.HK",
        "CAM HSTECH ETF": "3088.HK",
        "CAM CSI300 ETF": "3180.HK",
        "CAM NASDAQ 100 ETF": "3086.HK",
        "CAM JAPAN HDG ETF": "3160.HK",
        "CAM MSCIINDIA ETF": "3074.HK",
        "CAMBRI": "688256.SS",
        "CATL": "300750.SZ",
        "CHHONGQ": "1378.HK",
        "CHMOBILE": "0941.HK",
        "CHMOBILE ETF": "0941.HK",
        "CHNXT50 ETF": "159682.SZ",
        "CMBANK": "3968.HK",
        "CN CSI300 ETF": "510300.SS",
        "CNBIO ETF": "2820.HK",
        "CNEV ETF": "2845.HK",
        "CNRE": "600111.SS",
        "CNROBOAI ETF": "2807.HK",
        "CNSEMI ETF": "3191.HK",
        "CNSTAR50 ETF": "588000.SS",
        "CNTECH": "3088.HK",
        "CYPC": "600900.SS",
        "DBS": "D05.SI",
        "DCVFMVN DIAMOND ETF": "FUEVFVND.HM",
        "DCVFMVN30 ETF": "E1VFVN30.HM",
        "DISCO": "6146.T",
        "E1VFVN30": "E1VFVN30.HM",
        "FANUC": "6954.T",
        "FERRARI": "RACE.MI",
        "FPTVN": "FPT.HM",
        "FUEVFVND": "FUEVFVND.HM",
        "GAC": "2238.HK",
        "GANFENG": "1772.HK",
        "GASVN": "GAS.HM",
        "GDS": "9698.HK",
        "GEELY": "0175.HK",
        "GIGA": "603986.SS",
        "GLOBALX INBLU(HK)ETF": "3110.HK",
        "GLOBALX JAPAN(HK)ETF": "3118.HK",
        "GSEMI ETF": "2644.T",
        "HAIERS": "6690.HK",
        "HANSOH": "3692.HK",
        "HERMES": "RMS.PA",
        "HITACHI": "6501.T",
        "HKEX": "0388.HK",
        "HONDA": "7267.T",
        "HORIZON": "9930.HK",
        "HPG": "HPG.HM",
        "HS JAPAN TPX100 ETF": "3126.HK",
        "HSCEI ETF": "2828.HK",
        "HSHD ETF": "3110.HK",
        "HSTECH ETF": "3032.HK",
        "HUAHONG": "1347.HK",
        "ICBC": "1398.HK",
        "IFLYTEK": "002230.SZ",
        "IS INDIA CLIMATE ETF": "I17.SI",
        "ITOCHU": "8001.T",
        "JD": "9618.HK",
        "JDHEAL": "6618.HK",
        "JLMAG": "6680.HK",
        "JPANIME ETF": "2524.T",
        "JPROBOAI ETF": "2638.T",
        "JPSEMI ETF": "2644.T",
        "KEYENCE": "6861.T",
        "KGI TAIWAN AI 50 ETF": "00915.TW",
        "KGI TAIWAN HD 30 ETF": "00918.TW",
        "KINGSOFT": "3888.HK",
        "KIOXIA": "6600.T",
        "KONAMI": "9766.T",
        "KUAISH": "1024.HK",
        "LAOPU": "6181.HK",
        "LENOVO": "0992.HK",
        "LOREAL": "OR.PA",
        "LVMH": "MC.PA",
        "MAOGEP": "1042.HK",
        "MEITUAN": "3690.HK",
        "MIDEA": "0300.HK",
        "MITSU": "8031.T",
        "MIXUE": "MIXUE",
        "MNSO": "9896.HK",
        "MONTAGE": "688008.SS",
        "MOUTAI": "600519.SS",
        "MSN": "MSN.HM",
        "MUFG": "8306.T",
        "MWG": "MWG.HM",
        "NAURA": "002371.SZ",
        "NIKKEI ETF": "1321.T",
        "NINTENDO": "7974.T",
        "NONGFU": "9633.HK",
        "NOVOB": "NOVO-B.CO",
        "NTES": "9999.HK",
        "PETROCN": "0857.HK",
        "PINGAN": "2318.HK",
        "POPMART": "9992.HK",
        "PREMIA STAR50 ETF": "3151.HK",
        "S&P CRUDE OIL(HK)ETF": "3097.HK",
        "SANOFI": "SAN.PA",
        "SANRIO": "8136.T",
        "SEMB": "U96.SI",
        "SENSE": "0020.HK",
        "SGX": "S68.SI",
        "SIA": "C6L.SI",
        "SINGTEL": "Z74.SI",
        "SINOBIO": "1177.HK",
        "SMFG": "8316.T",
        "SMIC": "0981.HK",
        "SOFTBANK": "9984.T",
        "SONY": "6758.T",
        "SP500HK ETF": "3195.HK",
        "SPDR GOLD (HK) ETF": "2840.HK",
        "SPDR GOLD TRUST(GSD)": "O33.SI",
        "STEG": "S63.SI",
        "SUNNY": "2382.HK",
        "SUSHI": "7550.T",
        "TEL": "8035.T",
        "TENCENT": "0700.HK",
        "THAIBEV": "Y92.SI",
        "TME": "1698.HK",
        "TOYOTA": "7203.T",
        "TRAHK ETF": "2800.HK",
        "TRIPCOM": "9961.HK",
        "UBTECH": "9880.HK",
        "UNIQLO": "9983.T",
        "UOB": "U11.SI",
        "USTR ETF": "3433.HK",
        "VCB": "VCB.HM",
        "VENTURE": "V03.SI",
        "VHM": "VHM.HM",
        "VNFIN LEAD ETF": "FUESSVFL.HM",
        "VNM": "VNM.HM",
        "WORLDA ETF": "EUNL.DE",
        "WUXI": "2269.HK",
        "WUXIAT": "2359.HK",
        "XIAOMI": "1810.HK",
        "XPENG": "9868.HK",
        "YT TAIWAN50 ETF": "0050.TW",
        "ZAI": "9688.HK",
        "ZIJIN": "2899.HK"
    }

    # Load existing catalog to inherit manual/custom mappings
    existing_catalog = {}
    if os.path.exists(catalog_path):
        try:
            with open(catalog_path, "r", encoding="utf-8") as f:
                existing_catalog = json.load(f)
            print(f"Loaded existing catalog of {len(existing_catalog)} entries for inheritance.")
        except Exception as e:
            print(f"Error loading existing catalog: {e}")

    with open(raw_path, "r", encoding="utf-8") as f:
        text = f.read()

    lines = [line.strip() for line in text.split("\n") if line.strip()]

    # Find the header row
    header_idx = -1
    for idx, line in enumerate(lines):
        if "หลักทรัพย์" in line and "Trading Session" in line:
            header_idx = idx
            break

    if header_idx == -1:
        header_idx = 5

    content_lines = lines[header_idx + 1:]

    # Parse entries with a robust look-ahead parser
    blocks = []
    i = 0
    symbol_pattern = re.compile(r"^[A-Z0-9]{3,15}$")

    while i < len(content_lines):
        line = content_lines[i]
        # Check if line looks like a DR Symbol
        if "\t" not in line and symbol_pattern.match(line):
            symbol = line
            data_line = None
            outstanding_line = None
            
            # Find the next line containing tabs (this will be the data row, skipping any XD/XR flags)
            j = i + 1
            while j < len(content_lines):
                next_line = content_lines[j]
                if "\t" in next_line:
                    data_line = next_line
                    # The next non-blank line following data is the outstanding quantities row
                    k = j + 1
                    if k < len(content_lines):
                        outstanding_line = content_lines[k]
                        i = k + 1
                    else:
                        i = j + 1
                    break
                j += 1
                
            if data_line:
                blocks.append({
                    "symbol": symbol,
                    "data": data_line,
                    "outstanding": outstanding_line or ""
                })
        else:
            i += 1

    print(f"Look-ahead scanner parsed {len(blocks)} DR blocks successfully.")

    new_catalog = {}
    for b in blocks:
        symbol = b["symbol"]
        cols = b["data"].split("\t")
        
        # Check if we can inherit if truncated
        inherited = existing_catalog.get(symbol, {})
        
        if len(cols) < 19:
            if inherited:
                new_catalog[symbol] = inherited
                print(f"Truncated symbol {symbol} successfully recovered from existing catalog.")
            continue
            
        issuer = cols[11].strip()
        underlying = cols[13].strip()
        ratio_str = cols[16].strip()
        exchange = cols[18].strip()
        
        # Parse dr_ratio (e.g., "340 : 1" or "1,000 : 1" or "1 : 1")
        try:
            ratio_parts = ratio_str.split(":")
            dr_part = float(ratio_parts[0].replace(",", "").strip())
            dr_ratio = 1.0 / dr_part
        except Exception:
            dr_ratio = 0.001
            
        # 1. Check existing catalog for overlay fields
        inherited = existing_catalog.get(symbol, {})
        us_adr = inherited.get("us_adr")
        adr_ratio = inherited.get("adr_ratio")
        
        primary_ticker = None
        market = None
        
        # 2. Auto-resolve using our comprehensive mappings & rules
        if True:
            if "Copenhagen" in exchange:
                market = "DK"
                primary_ticker = NON_US_MAPPINGS.get(underlying, f"{underlying}.CO")
            elif "Nasdaq" in exchange or "New York Stock Exchange" in exchange or "NYSE" in exchange or "Archipelago" in exchange:
                market = "US"
                # Strip " ETF" suffix if present in underlying asset name
                primary_ticker = underlying.replace(" ETF", "")
                # Custom ETF mapper for popular indexes
                if primary_ticker == "SP500US": primary_ticker = "SPY"
                elif primary_ticker == "SPDR GOLD (US)": primary_ticker = "GLD"
                elif primary_ticker == "SPBOND": primary_ticker = "BND"
                elif primary_ticker == "SPENGY": primary_ticker = "XLE"
                elif primary_ticker == "SPFIN": primary_ticker = "XLF"
                elif primary_ticker == "SPHLTH": primary_ticker = "XLV"
                elif primary_ticker == "SPTECH": primary_ticker = "XLK"
            elif "Hong Kong" in exchange:
                market = "HK"
                if underlying in NON_US_MAPPINGS:
                    primary_ticker = NON_US_MAPPINGS[underlying]
                elif underlying.isdigit():
                    primary_ticker = f"{underlying.zfill(4)}.HK"
                else:
                    primary_ticker = f"{underlying}.HK"
            elif "Tokyo Stock Exchange" in exchange or "Japan" in exchange:
                market = "JP"
                primary_ticker = NON_US_MAPPINGS.get(underlying, f"{underlying}.T")
            elif "Singapore Exchange" in exchange:
                market = "SG"
                primary_ticker = NON_US_MAPPINGS.get(underlying, f"{underlying}.SI")
            elif "Hochiminh Stock Exchange" in exchange or "Vietnam" in exchange:
                market = "VN"
                primary_ticker = NON_US_MAPPINGS.get(underlying, f"{underlying}.HM")
                if "DIAMOND" in underlying: primary_ticker = "FUEVFVND.HM"
                elif "VN30" in underlying or "E1VFVN30" in underlying: primary_ticker = "E1VFVN30.HM"
                elif "VNFIN" in underlying: primary_ticker = "FUESSVFL.HM"
            elif "Paris" in exchange:
                market = "FR"
                primary_ticker = NON_US_MAPPINGS.get(underlying, f"{underlying}.PA")
            elif "Amsterdam" in exchange:
                market = "AS"
                primary_ticker = NON_US_MAPPINGS.get(underlying, f"{underlying}.AS")
            elif "Milan" in exchange:
                market = "IT"
                primary_ticker = NON_US_MAPPINGS.get(underlying, f"{underlying}.MI")
            elif "Taiwan" in exchange:
                market = "TW"
                primary_ticker = NON_US_MAPPINGS.get(underlying, f"{underlying}.TW")
            elif "Shanghai" in exchange:
                market = "HK"
                primary_ticker = NON_US_MAPPINGS.get(underlying, f"{underlying}.SS")
            elif "Shenzhen" in exchange:
                market = "HK"
                primary_ticker = NON_US_MAPPINGS.get(underlying, f"{underlying}.SZ")
            elif "Deutsche" in exchange:
                market = "DE"
                primary_ticker = NON_US_MAPPINGS.get(underlying, f"{underlying}.DE")
            else:
                # Default fallback
                market = "US"
                primary_ticker = underlying
                
        # Make a friendly display name
        name = f"{underlying} DR ({issuer})"
        
        # Build catalog item
        item = {
            "primary": primary_ticker,
            "market": market,
            "dr_ratio": dr_ratio,
            "name": name,
            "issuer": issuer,
            "underlying": underlying
        }
        if us_adr: item["us_adr"] = us_adr
        if adr_ratio: item["adr_ratio"] = adr_ratio
        
        new_catalog[symbol] = item

    # Hardcoded recovery for truncated/known cut-off entries at the end of the file
    if "ZJINNO80" not in new_catalog:
        new_catalog["ZJINNO80"] = {
            "primary": "300308.SZ",
            "market": "HK",
            "dr_ratio": 0.001,
            "name": "ZJINNO DR (KTB)",
            "issuer": "KTB",
            "underlying": "ZJINNO"
        }
        print("Truncated symbol ZJINNO80 successfully recovered using hardcoded fallback.")

    # Group by underlying asset to recommend the single best broker
    by_underlying = {}
    for sym, config in new_catalog.items():
        und = config["underlying"]
        if und not in by_underlying:
            by_underlying[und] = []
        by_underlying[und].append(sym)

    # Broker prioritisation rank
    issuer_rank = {
        "KTB": 1,
        "BLS": 2,
        "INVX": 3,
        "KKPS": 4,
        "YUANTA": 5,
        "FSS": 6,
        "PI": 7,
        "KGI": 8,
        "KS": 9
    }

    recommended_count = 0
    for und, syms in by_underlying.items():
        # Sort based on ranking
        sorted_syms = sorted(syms, key=lambda s: issuer_rank.get(new_catalog[s]["issuer"], 99))
        best_sym = sorted_syms[0]
        
        for s in syms:
            new_catalog[s]["recommend"] = (s == best_sym)
            if s == best_sym:
                recommended_count += 1

    # Save to file
    with open(catalog_path, "w", encoding="utf-8") as f:
        json.dump(new_catalog, f, indent=2, ensure_ascii=False)

    print(f"Successfully generated new catalog with {len(new_catalog)} DR configurations!")
    print(f"Recommended primes: {recommended_count}, Alternatives: {len(new_catalog) - recommended_count}")

if __name__ == "__main__":
    build()
