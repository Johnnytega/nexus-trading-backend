import psycopg2

# Paste your copied Neon connection string between the quotes below:
DB_URL = "postgresql://neondb_owner:npg_Ywlj9VSzU2bW@ep-restless-sky-b48aax8g-pooler.c-6.us-east-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require"

def init_database():
    print("Connecting to Neon PostgreSQL...")
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    print("Creating tables...")
    # 1. Users Table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id VARCHAR(50) PRIMARY KEY,
            email VARCHAR(255) UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # 2. Wallets Table (with check constraint to block overdrafts)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS wallets (
            wallet_id SERIAL PRIMARY KEY,
            user_id VARCHAR(50) REFERENCES users(user_id) ON DELETE CASCADE,
            fiat_balance DECIMAL(15, 2) DEFAULT 0.00,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT check_positive_balance CHECK (fiat_balance >= 0)
        );
    """)

    # 3. Portfolios Table (tracks current holdings)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS portfolios (
            portfolio_id SERIAL PRIMARY KEY,
            user_id VARCHAR(50) REFERENCES users(user_id) ON DELETE CASCADE,
            asset_symbol VARCHAR(10) NOT NULL,
            quantity DECIMAL(18, 8) DEFAULT 0.00000000,
            average_buy_price DECIMAL(15, 2) NOT NULL,
            UNIQUE(user_id, asset_symbol),
            CONSTRAINT check_positive_quantity CHECK (quantity >= 0)
        );
    """)

    # 4. Trades Table (transaction log)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            trade_id SERIAL PRIMARY KEY,
            user_id VARCHAR(50) REFERENCES users(user_id),
            asset_symbol VARCHAR(10) NOT NULL,
            trade_type VARCHAR(4) NOT NULL,
            quantity DECIMAL(18, 8) NOT NULL,
            execution_price DECIMAL(15, 2) NOT NULL,
            total_value DECIMAL(15, 2) NOT NULL,
            executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    print("Seeding test user 'demo_user' with $10,000.00...")
    # Insert a sample user and seed their wallet with $10,000 for testing
    cur.execute("""
        INSERT INTO users (user_id, email)
        VALUES ('user_001', 'trader@demo.com')
        ON CONFLICT (user_id) DO NOTHING;
    """)

    cur.execute("""
        INSERT INTO wallets (user_id, fiat_balance)
        SELECT 'user_001', 10000.00
        WHERE NOT EXISTS (SELECT 1 FROM wallets WHERE user_id = 'user_001');
    """)

    conn.commit()
    cur.close()
    conn.close()
    print("Database initialized successfully!")

if __name__ == "__main__":
    init_database()