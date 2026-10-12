import os
import asyncio
import bcrypt
import jwt
import psycopg2
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from trading_engine import (
    execute_buy_order, 
    execute_sell_order, 
    place_limit_order, 
    cancel_limit_order, 
    match_and_fill_orders
)
from market_data import get_live_stock_price, get_live_crypto_price, get_historical_data

load_dotenv()

DB_URL = os.getenv("DB_URL")
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

security = HTTPBearer()

def init_db():
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id VARCHAR(50) PRIMARY KEY
        );
    """)
    cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash VARCHAR(255);")
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS wallets (
            user_id VARCHAR(50) PRIMARY KEY,
            fiat_balance NUMERIC DEFAULT 0
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS portfolios (
            user_id VARCHAR(50),
            asset_symbol VARCHAR(10),
            quantity NUMERIC,
            average_buy_price NUMERIC,
            PRIMARY KEY (user_id, asset_symbol)
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id SERIAL PRIMARY KEY,
            user_id VARCHAR(50),
            asset_symbol VARCHAR(10),
            side VARCHAR(4),
            quantity NUMERIC,
            price NUMERIC,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id SERIAL PRIMARY KEY,
            user_id VARCHAR(50),
            asset_symbol VARCHAR(10),
            side VARCHAR(4),
            quantity NUMERIC,
            target_price NUMERIC,
            status VARCHAR(20) DEFAULT 'PENDING',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # NEW: Master Equity Tracking Table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS equity_history (
            id SERIAL PRIMARY KEY,
            user_id VARCHAR(50),
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            equity NUMERIC
        );
    """)
    conn.commit()
    cur.close()
    conn.close()

init_db()

async def order_book_matching_worker():
    symbols = ['AAPL', 'TSLA', 'NVDA', 'BTC', 'ETH', 'SOL']
    while True:
        try:
            live_prices = {}
            for sym in symbols:
                price = get_live_crypto_price(sym) if sym in ['BTC', 'ETH', 'SOL'] else get_live_stock_price(sym)
                if price:
                    live_prices[sym] = price
            
            match_and_fill_orders(DB_URL, live_prices)
        except Exception as e:
            print(f"Matcher error: {e}")
        await asyncio.sleep(5)

@asynccontextmanager
async def lifespan(app: FastAPI):
    worker_task = asyncio.create_task(order_book_matching_worker())
    yield
    worker_task.cancel()

app = FastAPI(title="Trading Broker API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class TradeRequest(BaseModel):
    user_id: str
    asset_symbol: str
    quantity: float
    is_crypto: bool = False

class LimitOrderRequest(BaseModel):
    user_id: str
    asset_symbol: str
    side: str
    quantity: float
    target_price: float

class UserAuth(BaseModel):
    user_id: str
    password: str

# NEW: Data model for frontend equity snapshots
class EquitySnapshot(BaseModel):
    user_id: str
    equity: float

def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("sub")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session expired.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token.")

@app.post("/api/auth/register")
def register_user(user: UserAuth):
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users WHERE user_id = %s;", (user.user_id,))
    if cur.fetchone():
        cur.close()
        conn.close()
        raise HTTPException(status_code=400, detail="User already exists")
    
    hashed = bcrypt.hashpw(user.password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    cur.execute("INSERT INTO users (user_id, password_hash) VALUES (%s, %s);", (user.user_id, hashed))
    cur.execute("INSERT INTO wallets (user_id, fiat_balance) VALUES (%s, %s) ON CONFLICT DO NOTHING;", (user.user_id, 10000.00))
    conn.commit()
    cur.close()
    conn.close()
    return {"message": "User registered successfully"}

@app.post("/api/auth/login")
def login_user(user: UserAuth):
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute("SELECT password_hash FROM users WHERE user_id = %s;", (user.user_id,))
    result = cur.fetchone()
    cur.close()
    conn.close()
    
    if not result or not bcrypt.checkpw(user.password.encode('utf-8'), result[0].encode('utf-8')):
        raise HTTPException(status_code=401, detail="Invalid username or password")
        
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    token = jwt.encode({"sub": user.user_id, "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)
    return {"access_token": token, "token_type": "bearer"}

@app.get("/api/wallet/{user_id}")
def get_wallet_balance(user_id: str, token_user: str = Depends(verify_token)):
    if token_user != user_id:
        raise HTTPException(status_code=403, detail="IDOR attempt blocked.")
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute("SELECT fiat_balance FROM wallets WHERE user_id = %s;", (user_id,))
    result = cur.fetchone()
    cur.close()
    conn.close()
    if not result:
        raise HTTPException(status_code=404, detail="Wallet not found")
    return {"user_id": user_id, "balance": float(result[0])}

@app.get("/api/portfolio/{user_id}")
def get_portfolio(user_id: str, token_user: str = Depends(verify_token)):
    if token_user != user_id:
        raise HTTPException(status_code=403, detail="IDOR attempt blocked.")
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute("SELECT asset_symbol, quantity, average_buy_price FROM portfolios WHERE user_id = %s;", (user_id,))
    holdings = [{"symbol": row[0], "quantity": float(row[1]), "avg_price": float(row[2])} for row in cur.fetchall()]
    cur.close()
    conn.close()
    return {"user_id": user_id, "holdings": holdings}

@app.get("/api/price/{symbol}")
def get_price(symbol: str, is_crypto: bool = False):
    price = get_live_crypto_price(symbol) if is_crypto else get_live_stock_price(symbol)
    if not price:
        raise HTTPException(status_code=404, detail="Asset price not found")
    return {"symbol": symbol.upper(), "price": price}

@app.get("/api/chart/{symbol}")
def get_chart_data(symbol: str, is_crypto: bool = False):
    data = get_historical_data(symbol, is_crypto)
    if not data:
        raise HTTPException(status_code=404, detail="Historical data not found")
    return {"symbol": symbol.upper(), "data": data}

@app.get("/api/transactions/{user_id}")
def get_transactions(user_id: str, token_user: str = Depends(verify_token)):
    if token_user != user_id:
        raise HTTPException(status_code=403, detail="IDOR attempt blocked.")
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute("SELECT asset_symbol, side, quantity, price, timestamp FROM transactions WHERE user_id = %s ORDER BY timestamp DESC LIMIT 50;", (user_id,))
    txs = [{"symbol": r[0], "side": r[1], "quantity": float(r[2]), "price": float(r[3]), "time": r[4]} for r in cur.fetchall()]
    cur.close()
    conn.close()
    return {"user_id": user_id, "transactions": txs}

# NEW: Master Equity Snapshot Engine
@app.post("/api/equity/record")
def record_equity(snapshot: EquitySnapshot, token_user: str = Depends(verify_token)):
    if token_user != snapshot.user_id:
        raise HTTPException(status_code=403, detail="IDOR attempt blocked.")
    
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    
    # Throttle: Only insert a new snapshot if the last one was over 5 minutes ago to avoid spamming the DB
    cur.execute("SELECT id FROM equity_history WHERE user_id = %s AND timestamp > NOW() - INTERVAL '5 minutes';", (snapshot.user_id,))
    if not cur.fetchone():
        cur.execute("INSERT INTO equity_history (user_id, equity) VALUES (%s, %s);", (snapshot.user_id, snapshot.equity))
        conn.commit()
        
    cur.execute("SELECT EXTRACT(EPOCH FROM timestamp), equity FROM equity_history WHERE user_id = %s ORDER BY timestamp ASC;", (snapshot.user_id,))
    rows = cur.fetchall()
    
    # Seed Data: If this is a new account, inject a flat line of $10,000 for the last 7 days so the chart renders nicely
    if len(rows) < 2:
        base_time = datetime.now() - timedelta(days=7)
        cur.execute("INSERT INTO equity_history (user_id, timestamp, equity) VALUES (%s, %s, %s);", (snapshot.user_id, base_time, 10000.00))
        cur.execute("INSERT INTO equity_history (user_id, timestamp, equity) VALUES (%s, %s, %s);", (snapshot.user_id, datetime.now(), snapshot.equity))
        conn.commit()
        cur.execute("SELECT EXTRACT(EPOCH FROM timestamp), equity FROM equity_history WHERE user_id = %s ORDER BY timestamp ASC;", (snapshot.user_id,))
        rows = cur.fetchall()

    # Format perfectly for Lightweight Charts AreaSeries
    history = [{"time": int(r[0]), "value": float(r[1])} for r in rows]
    
    cur.close()
    conn.close()
    return {"history": history}

@app.post("/api/trade/buy")
def buy_asset(trade: TradeRequest, token_user: str = Depends(verify_token)):
    if token_user != trade.user_id:
        raise HTTPException(status_code=403, detail="IDOR attempt blocked.")
    live_price = get_live_crypto_price(trade.asset_symbol) if trade.is_crypto else get_live_stock_price(trade.asset_symbol)
    if not live_price:
        raise HTTPException(status_code=400, detail="Could not fetch live price")
    result = execute_buy_order(DB_URL, trade.user_id, trade.asset_symbol, trade.quantity, live_price)
    if result["status"] == "error":
        raise HTTPException(status_code=400, detail=result["message"])
    return result

@app.post("/api/trade/sell")
def sell_asset(trade: TradeRequest, token_user: str = Depends(verify_token)):
    if token_user != trade.user_id:
        raise HTTPException(status_code=403, detail="IDOR attempt blocked.")
    live_price = get_live_crypto_price(trade.asset_symbol) if trade.is_crypto else get_live_stock_price(trade.asset_symbol)
    if not live_price:
        raise HTTPException(status_code=400, detail="Could not fetch live price")
    result = execute_sell_order(DB_URL, trade.user_id, trade.asset_symbol, trade.quantity, live_price)
    if result["status"] == "error":
        raise HTTPException(status_code=400, detail=result["message"])
    return result

@app.post("/api/trade/limit")
def create_limit_order(order: LimitOrderRequest, token_user: str = Depends(verify_token)):
    if token_user != order.user_id:
        raise HTTPException(status_code=403, detail="IDOR attempt blocked.")
    result = place_limit_order(DB_URL, order.user_id, order.asset_symbol, order.side, order.quantity, order.target_price)
    if result["status"] == "error":
        raise HTTPException(status_code=400, detail=result["message"])
    return result

@app.get("/api/orders/{user_id}")
def get_active_orders(user_id: str, token_user: str = Depends(verify_token)):
    if token_user != user_id:
        raise HTTPException(status_code=403, detail="IDOR attempt blocked.")
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, asset_symbol, side, quantity, target_price, created_at 
        FROM orders 
        WHERE user_id = %s AND status = 'PENDING' 
        ORDER BY created_at DESC;
    """, (user_id,))
    active_orders = [{"id": r[0], "symbol": r[1], "side": r[2], "quantity": float(r[3]), "target_price": float(r[4]), "created_at": r[5]} for r in cur.fetchall()]
    cur.close()
    conn.close()
    return {"user_id": user_id, "orders": active_orders}

@app.post("/api/orders/cancel/{order_id}")
def cancel_order(order_id: int, token_user: str = Depends(verify_token)):
    result = cancel_limit_order(DB_URL, token_user, order_id)
    if result["status"] == "error":
        raise HTTPException(status_code=400, detail=result["message"])
    return result