import requests
from bs4 import BeautifulSoup
import json

headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

# Let's try to get the raw quote page from Yahoo Finance
url = "https://finance.yahoo.com/quote/SIL/"
r = requests.get(url, headers=headers)
soup = BeautifulSoup(r.text, 'html.parser')

# Find fin-streamer tags which Yahoo uses for live prices
streamers = soup.find_all('fin-streamer')
for s in streamers:
    field = s.get('data-field')
    value = s.get('data-value')
    if field in ['postMarketPrice', 'preMarketPrice', 'regularMarketPrice', 'extendedMarketPrice']:
        print(f"Yahoo streamer {field}: {value}")

# Let's also check investing.com structure briefly
inv_url = "https://www.investing.com/etfs/global-x-silver-miners"
r2 = requests.get(inv_url, headers=headers)
if r2.status_code == 200:
    print("Investing.com loaded successfully without Cloudflare block.")
    soup2 = BeautifulSoup(r2.text, 'html.parser')
    # Try to find after hours price
    # It might be in a span with data-test="instrument-price-last" or similar
else:
    print(f"Investing.com blocked: {r2.status_code}")

