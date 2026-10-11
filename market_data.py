import yfinance as yf
import pandas as pd

def get_live_stock_price(symbol):
    try:
        ticker = yf.Ticker(symbol)
        return float(ticker.history(period="1d")["Close"].iloc[-1])
    except Exception:
        return None

def get_live_crypto_price(symbol):
    try:
        ticker = yf.Ticker(f"{symbol}-USD")
        return float(ticker.history(period="1d")["Close"].iloc[-1])
    except Exception:
        return None

def get_historical_data(symbol, is_crypto=False):
    try:
        target_symbol = f"{symbol}-USD" if is_crypto else symbol
        ticker = yf.Ticker(target_symbol)
        
        hist = ticker.history(period="5d", interval="15m")
        if hist.empty:
            return []
            
        chart_data = []
        for index, row in hist.iterrows():
            chart_data.append({
                "time": int(index.timestamp()), 
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": float(row["Volume"]) # NEW: Capturing trade volume
            })
        return chart_data
    except Exception as e:
        print(f"Error fetching historical data: {e}")
        return []