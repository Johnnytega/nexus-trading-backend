import yfinance as yf

def get_live_stock_price(symbol: str):
    """Fetches live stock prices using Yahoo Finance."""
    try:
        ticker = yf.Ticker(symbol)
        data = ticker.history(period="1d")
        if not data.empty:
            return float(data['Close'].iloc[-1])
        return None
    except Exception as e:
        print(f"Stock Fetch Error for {symbol}: {e}")
        return None

def get_live_crypto_price(symbol: str):
    """Fetches live crypto prices using Yahoo Finance to bypass ISP blocks."""
    try:
        # Yahoo Finance expects crypto symbols in the format 'BTC-USD'
        ticker = yf.Ticker(f"{symbol.upper()}-USD")
        data = ticker.history(period="1d")
        if not data.empty:
            return float(data['Close'].iloc[-1])
        return None
    except Exception as e:
        print(f"Crypto Fetch Error for {symbol}: {e}")
        return None