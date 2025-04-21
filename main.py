import time
import hmac
import hashlib
import requests
import pandas as pd

from datetime import datetime

# ========== CONFIGURATION ==========
API_KEY = 'ea2551557fb8c4f4be4b4511b5ff13ddf1ecbb4baf0a13be7c22e8ece8529e4b'
API_SECRET = 'c6d095fe75bf9405ce2c74e54c8402c02e5433dffe4fa5c45a8688284f8647db'
BASE_URL = 'https://testnet.binancefuture.com'
TRADE_SYMBOL = 'BTCUSDT'  # Changed from BTCUSDT to BONKUSDT
INTERVAL = '15m'
TRADE_USD = 1000
LEVERAGE = 10


# ===================================

def get_server_time():
    res = requests.get(BASE_URL + "/fapi/v1/time")
    return res.json()['serverTime']


def send_signed_request(http_method, url_path, payload={}):
    query_string = '&'.join([f"{k}={v}" for k, v in payload.items()])
    timestamp = get_server_time()
    query_string += f"&timestamp={timestamp}"
    signature = hmac.new(API_SECRET.encode(), query_string.encode(), hashlib.sha256).hexdigest()
    url = f"{BASE_URL}{url_path}?{query_string}&signature={signature}"
    headers = {"X-MBX-APIKEY": API_KEY}
    response = requests.request(http_method, url, headers=headers)
    return response.json()


def get_klines(symbol, interval, limit=100):
    url = f"{BASE_URL}/fapi/v1/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    res = requests.get(url, params=params)
    df = pd.DataFrame(res.json(), columns=[
        'timestamp', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'quote_asset_volume', 'num_trades',
        'taker_buy_base_volume', 'taker_buy_quote_volume', 'ignore'
    ])
    df[['open', 'high', 'low', 'close']] = df[['open', 'high', 'low', 'close']].astype(float)
    return df


def compute_heikin_ashi(df):
    ha_df = df.copy()
    ha_df['ha_close'] = (df['open'] + df['high'] + df['low'] + df['close']) / 4
    ha_open = [(df['open'][0] + df['close'][0]) / 2]
    for i in range(1, len(df)):
        ha_open.append((ha_open[i - 1] + ha_df['ha_close'][i - 1]) / 2)
    ha_df['ha_open'] = ha_open
    ha_df['ha_high'] = ha_df[['high', 'ha_open', 'ha_close']].max(axis=1)
    ha_df['ha_low'] = ha_df[['low', 'ha_open', 'ha_close']].min(axis=1)
    return ha_df


def detect_signal(df):
    df['ema21'] = df['close'].ewm(span=21).mean()
    df['ema55'] = df['close'].ewm(span=55).mean()
    ha_curr = df.iloc[-1]
    ha_prev = df.iloc[-2]

    ha_color_change_up = ha_curr['ha_close'] > ha_curr['ha_open'] and ha_prev['ha_close'] < ha_prev['ha_open']
    ha_color_change_down = ha_curr['ha_close'] < ha_curr['ha_open'] and ha_prev['ha_close'] > ha_prev['ha_open']

    buy_condition = ((ha_curr['ema21'] > ha_curr['ema55'] and ha_color_change_up) or
                     (ha_curr['ema21'] < ha_curr['ema55'] and ha_color_change_up))

    sell_condition = ((ha_curr['ema21'] > ha_curr['ema55'] and ha_color_change_down) or
                      (ha_curr['ema21'] < ha_curr['ema55'] and ha_color_change_down))

    print(f"EMA21: {ha_curr['ema21']}, EMA55: {ha_curr['ema55']}")
    print(f"Ha Close: {ha_curr['ha_close']}, Ha Open: {ha_curr['ha_open']}")
    print(f"Previous Ha Close: {ha_prev['ha_close']}, Previous Ha Open: {ha_prev['ha_open']}")
    print(f"Buy Signal: {buy_condition}, Sell Signal: {sell_condition}")

    return buy_condition, sell_condition


def get_price(symbol):
    res = requests.get(f"{BASE_URL}/fapi/v1/ticker/price", params={"symbol": symbol})
    return float(res.json()['price'])


def set_leverage(symbol, leverage):
    payload = {'symbol': symbol, 'leverage': leverage}
    res = send_signed_request("POST", "/fapi/v1/leverage", payload)
    print("Leverage Set:", res)


def get_position():
    res = send_signed_request("GET", "/fapi/v2/positionRisk")
    for pos in res:
        if pos['symbol'] == TRADE_SYMBOL:
            amt = float(pos['positionAmt'])
            return amt
    return 0.0


def close_position(position_amt):
    side = "SELL" if position_amt > 0 else "BUY"
    quantity = abs(position_amt)
    order = place_market_order(side, quantity)
    print(f"✅ Closed position: {side} {quantity}")
    return order


def place_market_order(side, quantity):
    payload = {
        'symbol': TRADE_SYMBOL,
        'side': side,
        'type': 'MARKET',
        'quantity': quantity
    }
    res = send_signed_request("POST", "/fapi/v1/order", payload)
    print(f"Order Placed ({side}):", res)
    return res


def get_quantity_for_usd(symbol, usd_amount):
    price = get_price(symbol)
    qty = (usd_amount * LEVERAGE) / price
    return round(qty, 3)  # 3 decimal places for BTCUSDT



def run_bot():
    print("🤖 Starting Bot with 10x Leverage on Binance Futures Testnet")
    set_leverage(TRADE_SYMBOL, LEVERAGE)

    while True:
        try:
            df = get_klines(TRADE_SYMBOL, INTERVAL)
            ha_df = compute_heikin_ashi(df)
            buy_signal, sell_signal = detect_signal(ha_df)
            position_amt = get_position()

            if buy_signal:
                print(f"{datetime.now()} >> Buy Signal Detected")
                if position_amt < 0:
                    close_position(position_amt)
                if position_amt == 0:
                    qty = get_quantity_for_usd(TRADE_SYMBOL, TRADE_USD)
                    place_market_order("BUY", qty)

            elif sell_signal:
                print(f"{datetime.now()} >> Sell Signal Detected")
                if position_amt > 0:
                    close_position(position_amt)
                if position_amt == 0:
                    qty = get_quantity_for_usd(TRADE_SYMBOL, TRADE_USD)
                    place_market_order("SELL", qty)

            else:
                print(f"{datetime.now()} >> No trade signal.")

        except Exception as e:
            print("❌ Error:", e)

        time.sleep(60 * 15)  # Wait for next 1m candle


if __name__ == "__main__":
    run_bot()
