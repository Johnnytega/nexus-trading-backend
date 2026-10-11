import psycopg2
from market_data import get_live_stock_price
from trading_engine import execute_buy_order, execute_sell_order

# Paste the exact same Neon connection string you used in setup_db.py:
DB_URL = "postgresql://neondb_owner:npg_Ywlj9VSzU2bW@ep-restless-sky-b48aax8g-pooler.c-6.us-east-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require"

USER_ID = "user_001"
SYMBOL = "AAPL"

def run_trade_test():
    # 1. Check starting wallet balance
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute("SELECT fiat_balance FROM wallets WHERE user_id = %s;", (USER_ID,))
    starting_balance = cur.fetchone()[0]
    print(f"Starting Wallet Balance: ${starting_balance:,.2f}")

    # 2. Fetch the live market price
    print(f"\nFetching live market price for {SYMBOL}...")
    live_price = get_live_stock_price(SYMBOL)
    if not live_price:
        print("Failed to fetch live price. Aborting.")
        cur.close()
        conn.close()
        return

    print(f"Current Price of {SYMBOL}: ${live_price:,.2f}")

    # 3. Test Buy Order (Buy 2 shares)
    print("\n--- EXECUTING BUY ORDER ---")
    shares_to_buy = 2
    print(f"Total Buy Cost for {shares_to_buy} shares: ${live_price * shares_to_buy:,.2f}")
    
    buy_result = execute_buy_order(
        db_connection_string=DB_URL,
        user_id=USER_ID,
        asset_symbol=SYMBOL,
        quantity=shares_to_buy,
        current_market_price=live_price
    )
    print(f"Buy Result: {buy_result}")

    # 4. Test Sell Order (Sell 1 share)
    print("\n--- EXECUTING SELL ORDER ---")
    shares_to_sell = 1
    print(f"Total Sell Value for {shares_to_sell} shares: ${live_price * shares_to_sell:,.2f}")
    
    sell_result = execute_sell_order(
        db_connection_string=DB_URL,
        user_id=USER_ID,
        asset_symbol=SYMBOL,
        quantity=shares_to_sell,
        current_market_price=live_price
    )
    print(f"Sell Result: {sell_result}")

    # 5. Verify updated balance, portfolio, and trade logs
    cur.execute("SELECT fiat_balance FROM wallets WHERE user_id = %s;", (USER_ID,))
    new_balance = cur.fetchone()[0]

    cur.execute("SELECT asset_symbol, quantity, average_buy_price FROM portfolios WHERE user_id = %s AND asset_symbol = %s;", (USER_ID, SYMBOL))
    portfolio = cur.fetchone()
    
    # Get the last two trades to show both the buy and the sell logs
    cur.execute("""
        SELECT trade_id, trade_type, quantity, total_value 
        FROM trades 
        WHERE user_id = %s AND asset_symbol = %s 
        ORDER BY executed_at DESC LIMIT 2;
    """, (USER_ID, SYMBOL))
    recent_trades = cur.fetchall()

    print("\n" + "=" * 50)
    print("DATABASE AUDIT VERIFICATION")
    print("=" * 50)
    print(f"Final Wallet Balance: ${new_balance:,.2f}")
    
    if portfolio:
        print(f"Current Holdings:     {portfolio[1]:.2f} shares of {portfolio[0]}")
    else:
        print("Current Holdings:     None")
        
    print("\nRecent Transaction Logs:")
    for t in recent_trades:
        print(f" - ID #{t[0]} | {t[1]} {t[2]:.2f} {SYMBOL} | Total: ${t[3]:,.2f}")
    print("=" * 50)

    cur.close()
    conn.close()

if __name__ == "__main__":
    run_trade_test()