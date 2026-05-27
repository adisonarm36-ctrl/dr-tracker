import requests
from bs4 import BeautifulSoup

headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
url = "https://finance.yahoo.com/quote/SIL/"
try:
    r = requests.get(url, headers=headers)
    soup = BeautifulSoup(r.text, 'html.parser')

    streamers = soup.find_all('fin-streamer')
    res = []
    for s in streamers:
        field = s.get('data-field')
        value = s.get('data-value')
        if field in ['postMarketPrice', 'preMarketPrice', 'regularMarketPrice', 'extendedMarketPrice', 'regularMarketTime', 'postMarketTime']:
            res.append(f"{field}: {value}")
    
    with open('inv_out2.txt', 'w', encoding='utf-8') as f:
        f.write("\n".join(res))
except Exception as e:
    with open('inv_out2.txt', 'w', encoding='utf-8') as f:
        f.write(str(e))
