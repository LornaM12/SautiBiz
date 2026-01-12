import xmlrpc.client

# 1. Configuration (These match what you just set up!)
url = "http://localhost:8069"
db = "sautibiz_db"
username = "admin"
password = "admin"

# 2. Connect to the Server
print("Connecting to Odoo...")
common = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/common')

# 3. Login
try:
    uid = common.authenticate(db, username, password, {})
    
    if uid:
        print(f"✅ SUCCESS! Logged in with User ID: {uid}")
        
        # 4. Let's ask Odoo for its version to double-check
        version = common.version()
        print(f"Server Version: {version['server_version']}")
    else:
        print("❌ Login Failed. Check your username/password.")

except ConnectionRefusedError:
    print("❌ Connection Failed. Is Docker running?")
except Exception as e:
    print(f"❌ Error: {e}")