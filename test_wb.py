import requests
import json

url = "https://quotes-gw.webullfintech.com/api/search/pc/tickers?keyword=SIL&regionId=6&pageIndex=1&pageSize=10"
r = requests.get(url)
try:
    with open('test_wb.json', 'w', encoding='utf-8') as f:
        json.dump(r.json(), f, indent=2)
except:
    pass
