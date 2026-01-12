import os
import xmlrpc.client
from fastapi import FastAPI, Form
from fastapi.responses import Response
from openai import OpenAI
from dotenv import load_dotenv  # Import this

# Load the secrets from the .env file
load_dotenv()

app = FastAPI()

# CONFIGURATION (SECURE) 
URL = os.getenv("ODOO_URL")
DB = os.getenv("ODOO_DB")
USERNAME = os.getenv("ODOO_USER")
PASSWORD = os.getenv("ODOO_PASS")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

client = OpenAI(api_key=OPENAI_API_KEY)



# ODOO CONNECTION 
def get_odoo_models():
    common = xmlrpc.client.ServerProxy(f'{URL}/xmlrpc/2/common')
    uid = common.authenticate(DB, USERNAME, PASSWORD, {})
    # allow_none=True prevents crashes if Odoo returns nothing
    models = xmlrpc.client.ServerProxy(f'{URL}/xmlrpc/2/object', allow_none=True)
    return uid, models

# AI Translator
def ask_chatgpt_intent(user_text):
    """
    This function sends the Swahili/English text to ChatGPT 
    and asks it to convert it into a simple command like: "SELL|Bread|5"
    """
    system_prompt = """
    You are an inventory assistant for a shop in Kenya. 
    Users will speak in English, Swahili, or Sheng.
    Your job is to classify their intent into one of these strict formats:
    
    1. If they want to SELL something: return "SELL|ItemName|Quantity"
    2. If they want to ADD/RESTOCK:   return "ADD|ItemName|Quantity"
    3. If they want to CHECK stock:   return "CHECK|ItemName"
    
    Rules:
    - Default quantity is 1 if not specified.
    - Extract the Item Name cleanly (e.g., "mkate" -> "Bread").
    - If you don't understand, return "UNKNOWN".
    """

    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text}
            ],
            temperature=0
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"AI Error: {e}")
        return "UNKNOWN"

# System core functions

def find_product_id(models, uid, item_name):
    # Search for product
    product_ids = models.execute_kw(DB, uid, PASSWORD, 'product.product', 'search',
        [[['name', 'ilike', item_name]]])
    return product_ids[0] if product_ids else None

def search_product(item_name):
    try:
        uid, models = get_odoo_models()
        product_id = find_product_id(models, uid, item_name)
        if product_id:
            data = models.execute_kw(DB, uid, PASSWORD, 'product.product', 'read',
                [[product_id]], {'fields': ['name', 'list_price', 'virtual_available']})[0]
            return f"✅ Found: {data['name']}\n💰 Price: {data['list_price']} KES\n📉 Stock: {data['virtual_available']}"
        return f"❌ Item '{item_name}' not found."
    except Exception as e: return str(e)

def make_sale(item_name, quantity):
    try:
        uid, models = get_odoo_models()
        product_id = find_product_id(models, uid, item_name)
        if not product_id: return f"❌ Item '{item_name}' not found."

        partner_ids = models.execute_kw(DB, uid, PASSWORD, 'res.partner', 'search', [[]], {'limit': 1})
        order_id = models.execute_kw(DB, uid, PASSWORD, 'sale.order', 'create', [{'partner_id': partner_ids[0]}])
        models.execute_kw(DB, uid, PASSWORD, 'sale.order.line', 'create', [{
            'order_id': order_id, 'product_id': product_id, 'product_uom_qty': quantity
        }])
        models.execute_kw(DB, uid, PASSWORD, 'sale.order', 'action_confirm', [[order_id]])
        
        # Check new balance
        data = models.execute_kw(DB, uid, PASSWORD, 'product.product', 'read', [[product_id]], {'fields': ['virtual_available']})[0]
        return f"💸 SOLD {quantity} x {item_name}.\n📉 Remaining: {data['virtual_available']}"
    except Exception as e: return f"Sale Error: {e}"

def add_stock(item_name, quantity):
    try:
        uid, models = get_odoo_models()
        product_id = find_product_id(models, uid, item_name)
        if not product_id: return f"❌ Item '{item_name}' not found."

        # Find Stock Location
        location_ids = models.execute_kw(DB, uid, PASSWORD, 'stock.location', 'search', [[['usage', '=', 'internal']]], {'limit': 1})
        quant_ids = models.execute_kw(DB, uid, PASSWORD, 'stock.quant', 'search', [[['product_id', '=', product_id], ['location_id', '=', location_ids[0]]]])

        if quant_ids:
            # Update existing record
            curr = models.execute_kw(DB, uid, PASSWORD, 'stock.quant', 'read', [quant_ids[0]], {'fields': ['quantity']})[0]
            new_qty = (curr.get('quantity') or 0) + quantity
            models.execute_kw(DB, uid, PASSWORD, 'stock.quant', 'write', [[quant_ids[0]], {'inventory_quantity': new_qty}])
           
            
            quant_id = quant_ids[0]
        else:
            # Create new record
            quant_id = models.execute_kw(DB, uid, PASSWORD, 'stock.quant', 'create', [{'product_id': product_id, 'location_id': location_ids[0], 'inventory_quantity': quantity}])

        # Apply Inventory
        try:
            models.execute_kw(DB, uid, PASSWORD, 'stock.quant', 'action_apply_inventory', [[quant_id]])
        except xmlrpc.client.Fault: pass 

        # Get New Balance
        data = models.execute_kw(DB, uid, PASSWORD, 'product.product', 'read', [[product_id]], {'fields': ['virtual_available']})[0]
        return f"🚛 ADDED {quantity} x {item_name}.\n📈 New Stock: {data['virtual_available']}"
    except Exception as e: return f"Restock Error: {e}"

# Whatsapp Router
@app.post("/whatsapp")
async def whatsapp_reply(Body: str = Form(...)):
    print(f"📩 User Said: {Body}")
    
    # Ask ChatGPT what the user wants
    intent_string = ask_chatgpt_intent(Body)
    print(f"🧠 AI Decided: {intent_string}")

    # Split the result "SELL|Bread|5"
    if "|" in intent_string:
        parts = intent_string.split("|")
        action = parts[0]
        item = parts[1]
        
        # If there is a quantity, use it. If not, default to 0 (for check)
        qty = int(parts[2]) if len(parts) > 2 else 0

        if action == "SELL":
            reply_text = make_sale(item, qty)
        elif action == "ADD":
            reply_text = add_stock(item, qty)
        elif action == "CHECK":
            reply_text = search_product(item)
        else:
            reply_text = "⚠️ I understood the item, but not the action."
    else:
        reply_text = "🤖 Sorry, I didn't understand that. Try saying 'Sell 2 Bread' or 'Niuze Mkate'."

    # 3. Reply to WhatsApp
    return Response(content=f"<Response><Message>{reply_text}</Message></Response>", media_type="application/xml")