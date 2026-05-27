import requests
import json

url = "https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol?symbols=SIL&requestMethod=itv&noform=1&fund=1&exthrs=1&output=json"
r = requests.get(url)
with open('test_cnbc.json', 'w', encoding='utf-8') as f:
    json.dump(r.json(), f, indent=2)
