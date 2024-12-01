import config
import logging
import math
import asyncio
import traceback
from telethon import TelegramClient, events
from pybit.unified_trading import HTTP

# Logging configuration
logging.basicConfig(
    filename='pybit_telegram.log',
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)s %(message)s'
)

# Bybit API credentials
api_key=config.api_key
api_secret=config.api_secret

# Telegram API credentials
api_id=config.api_id
api_hash=config.api_hash
bot_username=config.bot_username

# Initialize the Telegram client
client = TelegramClient('my_session', api_id, api_hash)

# Initialize Bybit session
session = HTTP(api_key=api_key, api_secret=api_secret, testnet=False, demo=True)


def get_step_size(symbol):
    """Fetch the step size for the given symbol."""
    try:
        instruments = session.get_instruments_info(category="linear")
        linear_list = instruments["result"]["list"]
        symbol_info = next((x for x in linear_list if x["symbol"] == symbol), None)

        if symbol_info:
            return float(symbol_info["lotSizeFilter"]["qtyStep"])
        else:
            raise ValueError(f"Symbol {symbol} not found in instruments")
    except Exception:
        logging.error("Error fetching step size: %s", traceback.format_exc())
        raise


async def handle_bot_response(event):
    """Handles bot response to extract trading parameters and place an order."""
    bot_message = event.raw_text.strip('"').strip()

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

        logging.info(f"Extracted values - Symbol: {symbol}, Price: {price}, Stop Loss: {stop_loss_price}, Take Profit: {take_profit_price}")
        print(f"Extracted values - Symbol: {symbol}, Price: {price}, Stop Loss: {stop_loss_price}, Take Profit: {take_profit_price}")

        step_size = get_step_size(symbol)

        # Fetch account balance
        account_balance = session.get_wallet_balance(accountType="UNIFIED")
        logging.debug("Full account balance response: %s", account_balance)
        print("Account Balance Response:", account_balance)

        # Parse USDT balance
        try:
            wallet_list = account_balance["result"]["list"]
            if not wallet_list or not isinstance(wallet_list, list):
                raise ValueError("Wallet list is empty or not a valid list")

            usdt_data = next(
                (coin for account in wallet_list for coin in account.get("coin", []) if coin.get("coin") == "USDT"),
                None
            )
            
            if not usdt_data:
                raise ValueError("USDT balance not found in the response")
            
            equity = float(usdt_data.get("equity", 0))
            wallet_balance = float(usdt_data.get("walletBalance", 0))
            usd_value = float(usdt_data.get("usdValue", 0))

            logging.info(f"USDT Equity: {equity}, Wallet Balance: {wallet_balance}, USD Value: {usd_value}")
            print(f"USDT Equity: {equity}, Wallet Balance: {wallet_balance}, USD Value: {usd_value}")
        except Exception as e:
            logging.error("Error processing wallet balance: %s", traceback.format_exc())
            raise ValueError("Failed to parse wallet balance") from e

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

            logging.info(f"Placing order with parameters: {order_params}")
            print(f"Placing order with parameters: {order_params}")

            order = session.place_order(**order_params)

            if order["retCode"] == 0:
                logging.info(f"Limit order placed successfully with SL/TP: {order}")
                print(f"Limit order placed successfully with SL/TP: {order}")
            else:
                logging.error(f"Error placing order: {order['retMsg']}")
                print(f"Error placing order: {order['retMsg']}")
        else:
            logging.error("Insufficient balance to place even a minimum quantity order")
            print("Insufficient balance to place even a minimum quantity order")
    except Exception as e:
        logging.error("Error handling bot response: %s", traceback.format_exc())
        print(f"Error handling bot response: {traceback.format_exc()}")


@client.on(events.NewMessage(from_users=bot_username))
async def bot_message_handler(event):
    print(f"Bot response received: {event.raw_text}")
    await handle_bot_response(event)


async def main():
    print("Starting Telegram client...")
    await client.start()
    print("Telegram client started. Listening for bot messages...")
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
