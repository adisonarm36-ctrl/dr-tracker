import yfinance as yf
t = yf.Ticker('SIL')
hist = t.history(period='5d', interval='15m', prepost=True)
print('Fast_info last_price:', t.fast_info.last_price)
print('Fast_info prev_close:', t.fast_info.previous_close)
print('Info currentPrice:', t.info.get('currentPrice'))
print('Info regularMarketPrice:', t.info.get('regularMarketPrice'))
print('Info postMarketPrice:', t.info.get('postMarketPrice'))
print('Hist tail:\n', hist['Close'].tail(10))
