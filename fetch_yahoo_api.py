import requests
import json
url = "https://query1.finance.yahoo.com/v8/finance/chart/SIL?region=US&lang=en-US&includePrePost=true&interval=2m&useYfid=true&range=1d"
headers = {'User-Agent': 'Mozilla/5.0'}
r = requests.get(url, headers=headers)
try:
    data = r.json()
    meta = data['chart']['result'][0]['meta']
    res = {
        'regularMarketPrice': meta.get('regularMarketPrice'),
        'postMarketPrice': meta.get('postMarketPrice'),
        'extendedMarketPrice': meta.get('extendedMarketPrice'),
        'hasPrePostMarketData': meta.get('hasPrePostMarketData')
    }
except Exception as e:
    res = {"error": str(e), "text": r.text[:200]}

with open('test_api.json', 'w', encoding='utf-8') as f:
    json.dump(res, f, indent=2)
