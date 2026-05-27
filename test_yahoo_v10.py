import requests
import json
url = "https://query2.finance.yahoo.com/v10/finance/quoteSummary/SIL?modules=price"
headers = {'User-Agent': 'Mozilla/5.0'}
r = requests.get(url, headers=headers)
with open('test_yahoo_v10.json', 'w', encoding='utf-8') as f:
    json.dump(r.json(), f, indent=2)
