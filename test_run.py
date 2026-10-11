from market_data import get_live_crypto_price, get_live_stock_price

print("Fetching live market prices...")

btc = get_live_crypto_price("BTC")
eth = get_live_crypto_price("ETH")
aapl = get_live_stock_price("AAPL")

print("-" * 35)
print(f"Bitcoin (BTC):  ${btc:,.2f}" if btc else "BTC fetch failed")
print(f"Ethereum (ETH): ${eth:,.2f}" if eth else "ETH fetch failed")
print(f"Apple (AAPL):   ${aapl:,.2f}" if aapl else "AAPL fetch failed")
print("-" * 35)