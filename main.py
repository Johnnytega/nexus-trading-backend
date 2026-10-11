import os
import bcrypt
import jwt
import psycopg2
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from trading_engine import execute_buy_order, execute_sell_order
from market_data import get_live_stock_price, get_live_crypto_price

# Load environment variables from the hidden .env file
load_dotenv()

app = FastAPI(title="Trading Broker API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Fetch secrets dynamically (these will crash if your .env file is missing or named incorrectly)
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
    cur.execute("ALTER TABLE users DROP COLUMN IF EXISTS email;")
    conn.commit()
    cur.close()
    conn.close()

init_db()

class TradeRequest(BaseModel):
    user_id: str
    asset_symbol: str
    quantity: float
    is_crypto: bool = False

class UserAuth(BaseModel):
    user_id: str
    password: str

# --- SECURITY DEPENDENCY ---
def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Intercepts the request, decodes the JWT, and extracts the authenticated user."""
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("sub")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session expired. Please log in again.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid authentication token.")

# ----------------- AUTHENTICATION ENDPOINTS -----------------

@app.post("/api/auth/register")
def register_user(user: UserAuth):
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    
    cur.execute("SELECT user_id FROM users WHERE user_id = %s;", (user.user_id,))
    if cur.fetchone():
        cur.close()
        conn.close()
        raise HTTPException(status_code=400, detail="User already exists")
    
    password_bytes = user.password.encode('utf-8')
    hashed_password = bcrypt.hashpw(password_bytes, bcrypt.gensalt()).decode('utf-8')
    
    cur.execute("INSERT INTO users (user_id, password_hash) VALUES (%s, %s);", (user.user_id, hashed_password))
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
    
    if not result:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    
    stored_hash = result[0].encode('utf-8')
    password_bytes = user.password.encode('utf-8')
    
    if not bcrypt.checkpw(password_bytes, stored_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")
        
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode = {"sub": user.user_id, "exp": expire}
    token = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    
    return {"access_token": token, "token_type": "bearer"}

# ----------------- PROTECTED TRADING & DATA ENDPOINTS -----------------

@app.get("/api/wallet/{user_id}")
def get_wallet_balance(user_id: str, token_user: str = Depends(verify_token)):
    if token_user != user_id:
        raise HTTPException(status_code=403, detail="IDOR attempt blocked: Token does not match requested wallet.")
        
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute("SELECT fiat_balance FROM wallets WHERE user_id = %s;", (user_id,))
    result = cur.fetchone()
    cur.close()
    conn.close()
    
    if not result:
        raise HTTPException(status_code=404, detail="Wallet not found")
    return {"user_id": user_id, "balance": float(result[0])}

@app.get("/api/price/{symbol}")
def get_price(symbol: str, is_crypto: bool = False):
    """Public endpoint - market data doesn't require authentication."""
    price = get_live_crypto_price(symbol) if is_crypto else get_live_stock_price(symbol)
    if not price:
        raise HTTPException(status_code=404, detail="Asset price not found")
    return {"symbol": symbol.upper(), "price": price}

@app.get("/api/portfolio/{user_id}")
def get_portfolio(user_id: str, token_user: str = Depends(verify_token)):
    if token_user != user_id:
        raise HTTPException(status_code=403, detail="IDOR attempt blocked: Token does not match requested portfolio.")
        
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute("SELECT asset_symbol, quantity, average_buy_price FROM portfolios WHERE user_id = %s;", (user_id,))
    holdings = [{"symbol": row[0], "quantity": float(row[1]), "avg_price": float(row[2])} for row in cur.fetchall()]
    cur.close()
    conn.close()
    return {"user_id": user_id, "holdings": holdings}

@app.post("/api/trade/buy")
def buy_asset(trade: TradeRequest, token_user: str = Depends(verify_token)):
    if token_user != trade.user_id:
        raise HTTPException(status_code=403, detail="IDOR attempt blocked: Cannot execute trade for another user.")
        
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
        raise HTTPException(status_code=403, detail="IDOR attempt blocked: Cannot execute trade for another user.")
        
    live_price = get_live_crypto_price(trade.asset_symbol) if trade.is_crypto else get_live_stock_price(trade.asset_symbol)
    if not live_price:
        raise HTTPException(status_code=400, detail="Could not fetch live price")
        
    result = execute_sell_order(DB_URL, trade.user_id, trade.asset_symbol, trade.quantity, live_price)
    
    if result["status"] == "error":
        raise HTTPException(status_code=400, detail=result["message"])
    return result