import requests
import hmac
import hashlib
import base64
import time
import logging
import json
import re
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.types import Message
from aiogram import Router
from dotenv import load_dotenv
import os
from datetime import datetime 

# ASCII Art
ascii_art = """
  ____ _____ _______ _____ ______ _______    _____        __  __ __ 
 |  _ \_   _|__   __/ ____|  ____|__   __|  / ____|      /_ |/_ /_ |
 | |_) || |    | | | |  __| |__     | |    | (___   __   _| | | || |
 |  _ < | |    | | | | |_ |  __|    | |     \___ \  \ \ / / | | || |
 | |_) || |_   | | | |__| | |____   | |     ____) |  \ V /| |_| || |
 |____/_____|  |_|  \_____|______|  |_|    |_____/    \_/ |_(_)_||_|
                                                                                                                                                                              
"""

print(ascii_art)

# Load API keys from short.env file
load_dotenv('short.env')

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
API_KEY = os.getenv("BITGET_API_KEY")
SECRET_KEY = os.getenv("BITGET_API_SECRET").encode('utf-8')
PASSPHRASE = os.getenv("BITGET_API_PASSPHRASE")

BASE_URL = "https://api.bitget.com"

# Initialize bot and dispatcher
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()
router = Router()

# Configure logging
logging.basicConfig(level=logging.INFO)

# Regular expressions for recognizing tickers
PATTERNS = [
    r"\((.*?)\)",  # (BTC)
    r"([A-Za-z]+USDT)",  # COOKIEUSDT
    r"Binance Will Delist\s+([A-Za-z,\s]+)\s+on"  # New pattern for detecting delisted tokens
]

# Function to sign requests
def sign_request(timestamp, method, endpoint, secret_key, body=""):
    prepared_str = f"{timestamp}{method.upper()}{endpoint}{body}"
    logging.info(f"String to sign: {prepared_str}")
    hmac_signature = hmac.new(secret_key, prepared_str.encode('utf-8'), hashlib.sha256).digest()
    signature = base64.b64encode(hmac_signature).decode('utf-8')
    logging.info(f"Signature: {signature}")
    return signature

# Get server time
def get_server_time():
    endpoint = "/api/spot/v1/public/time"
    url = f"{BASE_URL}{endpoint}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        logging.info(f"Server response: {response.text}")
        json_response = response.json()
        server_time = json_response.get("data")
        if server_time is None:
            raise ValueError("No 'data' field in response")
        logging.info(f"Server time: {server_time}")
        return int(server_time)
    except Exception as e:
        logging.error(f"Error fetching server time: {e}")
        return None

# Function to get contract configuration
def get_contract_config(symbol):
    endpoint = "/api/v2/mix/market/contracts"
    url = f"{BASE_URL}{endpoint}"
    timestamp = str(int(time.time() * 1000))

    params = {
        "symbol": f"{symbol}USDT",
        "productType": "USDT-FUTURES"
    }

    query_string = "&".join(f"{key}={value}" for key, value in params.items())
    signature = sign_request(timestamp, "GET", f"{endpoint}?{query_string}", SECRET_KEY)

    headers = {
        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": signature,
        "ACCESS-PASSPHRASE": PASSPHRASE,
        "ACCESS-TIMESTAMP": timestamp,
        "locale": "en-US",
        "Content-Type": "application/json",
    }

    try:
        response = requests.get(f"{url}?{query_string}", headers=headers)
        response.raise_for_status()
        return response.json()['data'][0]
    except Exception as e:
        logging.error(f"Error fetching contract config for {symbol}: {e}")
        return None

# Function to get current token price
def get_current_price(symbol):
    endpoint = "/api/v2/mix/market/ticker"
    url = f"{BASE_URL}{endpoint}"
    timestamp = str(int(time.time() * 1000))

    params = {
        "symbol": f"{symbol}USDT",
        "productType": "USDT-FUTURES"
    }

    query_string = "&".join(f"{key}={value}" for key, value in params.items())
    signature = sign_request(timestamp, "GET", f"{endpoint}?{query_string}", SECRET_KEY)

    headers = {
        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": signature,
        "ACCESS-PASSPHRASE": PASSPHRASE,
        "ACCESS-TIMESTAMP": timestamp,
        "locale": "en-US",
        "Content-Type": "application/json",
    }

    try:
        response = requests.get(f"{url}?{query_string}", headers=headers)
        logging.info(f"API response for price of {symbol}: {response.text}")
        response.raise_for_status()
        data = response.json()['data'][0]
        return float(data['lastPr'])
    except Exception as e:
        logging.error(f"Error fetching price for {symbol}: {e}")
        return None

# Function to check position
async def check_position(symbol):
    endpoint = "/api/v2/mix/position/single-position"
    url = f"{BASE_URL}{endpoint}"
    timestamp = str(int(time.time() * 1000))

    params = {
        "productType": "USDT-FUTURES",
        "symbol": f"{symbol}USDT",
        "marginCoin": "USDT"
    }

    query_string = "&".join(f"{key}={value}" for key, value in params.items())
    signature = sign_request(timestamp, "GET", f"{endpoint}?{query_string}", SECRET_KEY)

    headers = {
        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": signature,
        "ACCESS-PASSPHRASE": PASSPHRASE,
        "ACCESS-TIMESTAMP": timestamp,
        "locale": "en-US",
        "Content-Type": "application/json",
    }

    try:
        response = requests.get(f"{url}?{query_string}", headers=headers)
        logging.info(f"HTTP status: {response.status_code}, Response: {response.text}")
        response.raise_for_status()
        position_data = response.json()
        if position_data['data']:
            return position_data['data'][0]
        return None
    except Exception as e:
        logging.error(f"Error checking position: {e}")
        return None

# Function to open a short position on Bitget
async def place_short_position_async(ticker, investment_usd=1, leverage=40):
    contract_config = get_contract_config(ticker)
    if not contract_config:
        return {"error": f"Failed to get contract config for {ticker}"}

    # Check max leverage from contract config
    max_leverage = int(contract_config.get('maxLever', 40))
    if leverage > max_leverage:
        logging.info(f"Leverage {leverage} exceeds max leverage {max_leverage}. Adjusting to max leverage.")
        leverage = max_leverage

    price = get_current_price(ticker)
    if price is None:
        return {"error": f"Failed to get price for {ticker}"}

    size = (investment_usd * leverage) / (price * 1)
    print(f"investment_usd: {investment_usd}")
    print(f"leverage: {leverage}")
    print(f"price: {price}")
    print(f"size: {size}")

    # Ensure size complies with minTradeNum
    min_trade_num = float(contract_config['minTradeNum'])
    size = max(min_trade_num, round(size, int(contract_config['volumePlace'])))

    endpoint = "/api/v2/mix/order/place-order"
    url = f"{BASE_URL}{endpoint}"
    timestamp = str(int(time.time() * 1000))

    # Calculate SL price at -50%, adjusted for leverage
    loss_percent = -0.5  # -50%
    sl_price = price * (1 - (loss_percent / leverage))

    # Get price precision from contract config
    price_precision = int(contract_config.get('pricePlace', 4))  # Default to 4 if not found
    
    # Round to the correct precision
    sl_price = round(sl_price, price_precision)

    body = {
        "symbol": f"{ticker.upper()}USDT",
        "productType": "USDT-FUTURES",
        "marginMode": "isolated",
        "marginCoin": "USDT",
        "size": str(size),
        "side": "sell",
        "tradeSide": "open",
        "orderType": "market",
        "force": "ioc",
        "clientOid": str(int(time.time() * 1000)),
        "presetStopLossPrice": str(sl_price),
    }

    body_string = json.dumps(body, separators=(',', ':'))
    signature = sign_request(timestamp, "POST", endpoint, SECRET_KEY, body=body_string)

    headers = {
        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": signature,
        "ACCESS-PASSPHRASE": PASSPHRASE,
        "ACCESS-TIMESTAMP": timestamp,
        "Content-Type": "application/json",
        "locale": "en-US",
    }

    try:
        logging.info(f"Headers sent to API: {headers}")
        logging.info(f"Body sent to API: {body_string}")
        response = requests.post(url, headers=headers, data=body_string)
        logging.info(f"HTTP status: {response.status_code}, Response: {response.text}")
        response.raise_for_status()
        open_result = response.json()

        await asyncio.sleep(1)  # Wait for 1 second before placing the close order

        close_result = await close_short_position_with_limit(ticker, leverage)
        if "error" in close_result:
            return {"error": f"Position opened, but closing order failed: {close_result['error']}", "open_order": open_result}
        else:
            return {"open_order": open_result, "close_order": close_result}
    except Exception as e:
        logging.error(f"Error opening position: {e}")
        return {"error": str(e)}

async def close_short_position_with_limit(symbol, leverage):
    position = await check_position(symbol)
    if position is None:
        return {"error": f"No position found for {symbol}"}

    open_price = float(position.get("openPriceAvg", 0))
    size = position.get("total", 0)

    profit_percent = 1.0  # 100% profit
    target_price = open_price * (1 - (profit_percent / leverage))

    contract_config = get_contract_config(symbol)
    if not contract_config:
        return {"error": f"Failed to get contract config for {symbol}"}

    min_trade_num = float(contract_config['minTradeNum'])
    volume_place = int(contract_config['volumePlace'])
    size = max(min_trade_num, round(float(size), volume_place))

    current_price = get_current_price(symbol)
    if current_price is None:
        return {"error": f"Failed to get current price for {symbol}"}

    price_precision = int(contract_config.get('pricePlace', 5))
    adjusted_price = min(target_price, current_price * 1.05)
    adjusted_price = round(adjusted_price, price_precision)

    endpoint = "/api/v2/mix/order/place-order"
    url = f"{BASE_URL}{endpoint}"
    timestamp = str(int(time.time() * 1000))

    body = {
        "symbol": f"{symbol}USDT",
        "productType": "USDT-FUTURES",
        "marginMode": "isolated",
        "marginCoin": "USDT",
        "size": str(size),
        "price": str(adjusted_price),
        "side": "sell",
        "tradeSide": "close",
        "orderType": "limit",
        "force": "gtc",
        "clientOid": str(int(time.time() * 1000)),
    }

    body_string = json.dumps(body, separators=(',', ':'))
    signature = sign_request(timestamp, "POST", endpoint, SECRET_KEY, body=body_string)

    headers = {
        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": signature,
        "ACCESS-PASSPHRASE": PASSPHRASE,
        "ACCESS-TIMESTAMP": timestamp,
        "Content-Type": "application/json",
        "locale": "en-US",
    }

    try:
        logging.info(f"Headers for close order: {headers}")
        logging.info(f"Body for close order: {body_string}")
        response = requests.post(url, headers=headers, data=body_string)
        logging.info(f"HTTP status for close order: {response.status_code}, Response: {response.text}")
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logging.error(f"Error closing position: {e}")
        return {"error": str(e)}

# Function to handle messages from channel - modified to open positions concurrently
@router.message()
async def handle_message(message: Message):
    logging.info(f"Received message: {message.text}")
    found_tickers = []
    for pattern in PATTERNS:
        matches = re.findall(pattern, message.text)
        if pattern == r"Binance Will Delist\s+([A-Za-z,\s]+)\s+on":
            # Split the matched string into individual tickers and append USDT
            for ticker in matches[0].split(','):
                found_tickers.append(f"{ticker.strip()}USDT")
        else:
            found_tickers.extend(matches)

    # Remove duplicates, if any
    found_tickers = list(set(found_tickers))
    
    if found_tickers:
        tasks = []
        for ticker in found_tickers:
            # Remove 'USDT' if it was already in the string or add it if it's not there
            symbol = ticker.upper() if ticker.upper().endswith('USDT') else f"{ticker.upper()}USDT"
            logging.info(f"Processing ticker: {symbol}")
            await message.answer(f"Bitget Recognized ticker: {symbol}. Setting short position with SL and setting close order...")
            task = asyncio.create_task(place_short_position_async(symbol.replace('USDT', '')))
            tasks.append(task)

        # Wait for all positions to be opened
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for ticker, result in zip(found_tickers, results):
            symbol = ticker.replace('USDT', '')  # Use the base symbol for messaging
            if isinstance(result, Exception):
                logging.error(f"Error opening position for {symbol}: {str(result)}")
                await message.answer(f"Failed to set position for {symbol}. Error: {str(result)}")
            else:
                logging.info(f"Result from Bitget API for {symbol}: {result}")
                if 'error' in result:
                    await message.answer(f"Bitget Failed to open position for {symbol}: {result['error']}")
                else:
                    await message.answer(f"Bitget Position for {symbol} opened successfully with SL set and close order placed.")

             # Check and send unrealized P&L
                    position = await check_position(symbol)
                    if position:
                        unrealized_pl = position.get('unrealizedPL', '0')
                        await message.answer(f"[{datetime.now().strftime('%d.%m.%Y %H:%M')}]\nBitget Current unrealized P&L for {symbol}: {unrealized_pl}")
                    else:
                        await message.answer(f"[{datetime.now().strftime('%d.%m.%Y %H:%M')}]\nBitget Could not fetch position data for {symbol} to get unrealized P&L.")

        # Start the continuous update of unrealized P&L
        asyncio.create_task(send_unrealized_pl(message.chat.id))

# update unrealized pl periodically
async def send_unrealized_pl(chat_id):
    while True:
        try:
            endpoint = "/api/v2/mix/position/all-position"
            url = f"{BASE_URL}{endpoint}"
            timestamp = str(int(time.time() * 1000))

            params = {
                "productType": "USDT-FUTURES",
            }

            query_string = "&".join(f"{key}={value}" for key, value in params.items())
            signature = sign_request(timestamp, "GET", f"{endpoint}?{query_string}", SECRET_KEY)

            headers = {
                "ACCESS-KEY": API_KEY,
                "ACCESS-SIGN": signature,
                "ACCESS-PASSPHRASE": PASSPHRASE,
                "ACCESS-TIMESTAMP": timestamp,
                "locale": "en-US",
                "Content-Type": "application/json",
            }

            response = requests.get(f"{url}?{query_string}", headers=headers)
            logging.info(f"HTTP status for all positions: {response.status_code}, Response: {response.text}")
            response.raise_for_status()
            positions_data = response.json()

            if positions_data['data']:
                for position in positions_data['data']:
                    symbol = position.get("symbol", "Unknown").replace('USDT', '')
                    unrealized_pl = position.get("unrealizedPL", "0")
                    await bot.send_message(chat_id=chat_id, text=f"[{datetime.now().strftime('%d.%m.%Y %H:%M')}]\nBitget Current unrealized P&L for {symbol}: {unrealized_pl}")
            # If there are no open positions, no message is sent
        except Exception as e:
            logging.error(f"Bitget Error fetching or sending unrealized P/L: {e}")
        
        # Wait for 2 seconds before checking again
        await asyncio.sleep(2)



# Main bot function
async def main():
    logging.info("Bot is running and polling...")
    dp.include_router(router)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())