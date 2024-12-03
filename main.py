import config
import logging
import math
import asyncio
import traceback
import os
from telethon import TelegramClient, events
from pybit.unified_trading import HTTP
from flask import Flask, request, jsonify
from threading import Thread

# Logging configuration
logging.basicConfig(
    filename='pybit_telegram.log',
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)s %(message)s'
)

# Bybit API credentials
api_key = config.api_key
api_secret = config.api_secret

# Telegram API credentials
api_id = config.api_id
api_hash = config.api_hash
bot_username = config.bot_username  # Keep the bot username for listening to bot messages
phone_number = config.phone_number  # Using a single phone number for account
session_file = 'my_session.session'  # Session file name

# Initialize Bybit session
print("Initializing Bybit session...")
session = HTTP(api_key=api_key, api_secret=api_secret, testnet=False, demo=True)
print("Bybit session initialized.")

# OTP storage
otp_data = None  # Single OTP data for login

# Flask application for receiving OTP via POST request
app = Flask(__name__)

@app.route('/receive_otp', methods=['POST'])
def receive_otp():
    global otp_data
    data = request.json
    otp = data.get('otp')
    
    print(f"OTP received: {otp}")
    # Store the OTP data for login
    otp_data = otp
    return jsonify({"status": "OTP received"}), 200

def get_step_size(symbol):
    """Fetch the step size for the given symbol."""
    try:
        print(f"Fetching step size for symbol: {symbol}")
        instruments = session.get_instruments_info(category="linear")
        linear_list = instruments["result"]["list"]
        symbol_info = next((x for x in linear_list if x["symbol"] == symbol), None)

        if symbol_info:
            step_size = float(symbol_info["lotSizeFilter"]["qtyStep"])
            print(f"Step size for {symbol}: {step_size}")
            return step_size
        else:
            raise ValueError(f"Symbol {symbol} not found in instruments")
    except Exception:
        logging.error("Error fetching step size: %s", traceback.format_exc())
        raise

async def handle_bot_response(event):
    """Handles bot response to extract trading parameters and place an order."""
    bot_message = event.raw_text.strip('"').strip()
    print(f"Bot response received: {bot_message}")

    try:
        # Parse bot message
        message_parts = bot_message.split("\n")
        symbol, price, stop_loss_price, take_profit_price = None, None, None, None

        for part in message_parts:
            if part.startswith("Symbol:"):
                symbol = part.replace("Symbol:", "").strip()
            elif part.startswith("Price:"):
                price = float(part.replace("Price:", "").strip())
            elif part.startswith("Stop Loss:"):
                stop_loss_price = float(part.replace("Stop Loss:", "").strip())
            elif part.startswith("Take Profit:"):
                take_profit_price = float(part.replace("Take Profit:", "").strip())

        if not all([symbol, price, stop_loss_price, take_profit_price]):
            raise ValueError("Invalid message format received from the bot")

        print(f"Extracted values - Symbol: {symbol}, Price: {price}, Stop Loss: {stop_loss_price}, Take Profit: {take_profit_price}")

        step_size = get_step_size(symbol)

        # Fetch account balance
        print("Fetching account balance...")
        account_balance = session.get_wallet_balance(accountType="UNIFIED")
        logging.debug("Full account balance response: %s", account_balance)
        print("Account Balance Response:", account_balance)

        # Parse USDT balance
        wallet_list = account_balance["result"]["list"]
        usdt_data = next(
            (coin for account in wallet_list for coin in account.get("coin", []) if coin.get("coin") == "USDT"),
            None
        )
        equity = float(usdt_data.get("equity", 0))
        wallet_balance = float(usdt_data.get("walletBalance", 0))
        usd_value = float(usdt_data.get("usdValue", 0))

        print(f"USDT Equity: {equity}, Wallet Balance: {wallet_balance}, USD Value: {usd_value}")

        # Calculate maximum quantity
        max_qty = wallet_balance / price
        max_qty = math.floor(max_qty / step_size) * step_size

        if max_qty > 0:
            order_params = {
                "category": "linear",
                "symbol": symbol,
                "side": "Buy",
                "order_type": "Limit",
                "qty": max_qty,
                "price": price,
                "time_in_force": "GTC",
                "stopLoss": stop_loss_price,
                "takeProfit": take_profit_price
            }

            print(f"Placing order with parameters: {order_params}")
            order = session.place_order(**order_params)

            if order["retCode"] == 0:
                print(f"Limit order placed successfully with SL/TP: {order}")
            else:
                print(f"Error placing order: {order['retMsg']}")
        else:
            print("Insufficient balance to place even a minimum quantity order")
    except Exception as e:
        logging.error("Error handling bot response: %s", traceback.format_exc())
        print(f"Error handling bot response: {traceback.format_exc()}")

# Initialize the Telegram client
print("Initializing Telegram client...")
client = TelegramClient(session_file, api_id, api_hash)
print("Telegram client initialized.")

@client.on(events.NewMessage(from_users=bot_username))
async def bot_message_handler(event):
    print(f"New message from bot: {event.raw_text}")
    await handle_bot_response(event)

async def login_with_phone(client, phone_number):
    if not os.path.exists(session_file):
        print("Session file not found. Creating a new session...")
        await client.start(phone_number)
    else:
        await client.connect()
        if not await client.is_user_authorized():
            print(f"Logging in with phone number: {phone_number}")
            await client.send_code_request(phone_number)

            print("Waiting for OTP...")
            while otp_data is None:
                await asyncio.sleep(1)

            otp = otp_data
            if otp:
                await client.sign_in(phone_number, otp)
                print("Logged in successfully!")
            else:
                print("Failed to receive OTP.")
                raise Exception("OTP not received")

async def main():
    print("Starting Telegram client...")
    await login_with_phone(client, phone_number)
    await client.start()
    print("Telegram client started. Listening for bot messages...")
    await client.run_until_disconnected()

def run_flask():
    print("Starting Flask server...")
    app.run(host="0.0.0.0", port=5000)

flask_thread = Thread(target=run_flask)
flask_thread.start()

async def run():
    while True:
        try:
            await main()
        except Exception as e:
            print(f"Error occurred: {e}. Restarting the bot...")
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(run())
