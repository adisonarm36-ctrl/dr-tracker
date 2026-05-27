import requests
import json

url = "https://api.robinhood.com/quotes/SIL/"
headers = {
    'Accept': '*/*',
    'Accept-Encoding': 'gzip, deflate',
    'Connection': 'keep-alive',
}
r = requests.get(url, headers=headers)
try:
    with open('test_rh.json', 'w', encoding='utf-8') as f:
        json.dump(r.json(), f, indent=2)
except Exception as e:
    with open('test_rh.json', 'w', encoding='utf-8') as f:
        f.write(str(e) + "\n" + r.text)
