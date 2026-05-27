import requests
import json
import re

headers = {'User-Agent': 'Mozilla/5.0'}
r = requests.get("https://finance.yahoo.com/quote/SIL/", headers=headers)
html = r.text

# Try to find JSON blobs
matches = re.findall(r'<script type="application/json" data-sveltekit-fetched(.*?)>(.*?)</script>', html)
for i, match in enumerate(matches):
    try:
        data = json.loads(match[1])
        if str(95) in match[1] or "regularMarketPrice" in match[1]:
            with open(f'test_html_json_{i}.json', 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
    except:
        pass
        
# also look for raw JSON string in script tags
with open('test_html_raw.txt', 'w', encoding='utf-8') as f:
    f.write(html)
