import requests
import json
url = "https://quoteapi.webullfintech.com/api/quote/tickerRealTime?tickerId=913247615"
r = requests.get(url)
with open('test_wb_price.json', 'w', encoding='utf-8') as f:
    json.dump(r.json(), f, indent=2)
