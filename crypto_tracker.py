import requests
import math
import os
import time
import yfinance as yf
import streamlit as st

# --- Constants ---
# Using a static list of S&P 500 tickers is more reliable than scraping
SP500_TICKERS = [
    'AAPL', 'MSFT', 'GOOGL', 'GOOG', 'AMZN', 'NVDA', 'TSLA', 'META', 'BRK-B', 'UNH', 
    'JNJ', 'XOM', 'JPM', 'V', 'LLY', 'PG', 'AVGO', 'HD', 'CVX', 'MA', 'MRK', 'ABBV', 
    'PEP', 'KO', 'COST', 'WMT', 'BAC', 'PFE', 'MCD', 'CSCO', 'TMO', 'ACN', 'CRM', 
    'ABT', 'LIN', 'DHR', 'NFLX', 'WFC', 'DIS', 'ADBE', 'NEE', 'TXN', 'PM', 'AMD', 'HON',
    'UNP', 'ORCL', 'NKE', 'UPS', 'BMY', 'RTX', 'LOW', 'MDT', 'SPGI', 'INTC', 'GS', 'AMGN',
    'CAT', 'SBUX', 'ISRG', 'PLD', 'DE', 'BLK', 'BA', 'GE', 'EL', 'GILD', 'C', 'MS', 'TJX',
    'VRTX', 'SCHW', 'AXP', 'COP', 'AMT', 'NOW', 'PYPL', 'T', 'ZTS', 'IBM', 'ADI', 'CB', 'ETN',
    'SLB', 'MDLZ', 'CI', 'DUK', 'REGN', 'MMC', 'SO', 'PGR', 'MO', 'BDX', 'LMT', 'FISV', 'TGT',
    'NSC', 'SYK', 'EOG', 'ADP', 'AON', 'ITW', 'HCA', 'BSX', 'CMG', 'MU', 'CSX', 'CVS', 'CL',
    # This list can be expanded to the full 500. This is a representative sample.
]


# --- API Communication & Caching ---
# Caching is crucial for web apps to avoid re-fetching data on every interaction.

@st.cache_data(ttl=3600) # Cache for 1 hour
def get_coin_list():
    """Gets a list of all coins from CoinGecko and maps symbols to IDs."""
    try:
        url = "https://api.coingecko.com/api/v3/coins/list"
        response = requests.get(url)
        response.raise_for_status()
        # Handle multiple coins with the same symbol.
        # Structure: {'symbol': [('id1', 'name1'), ('id2', 'name2')]}
        coin_map = {}
        for coin in response.json():
            symbol = coin['symbol'].lower()
            if symbol not in coin_map:
                coin_map[symbol] = []
            coin_map[symbol].append((coin['id'], coin['name']))
        return coin_map
    except requests.exceptions.RequestException as e:
        st.error(f"Error fetching coin list: {e}")
        return None

@st.cache_data(ttl=3600) # Cache for 1 hour
def get_coin_data(coin_id):
    """Fetches detailed market data for a specific coin from CoinGecko."""
    try:
        # Construct the URL for the API endpoint
        url = f"https://api.coingecko.com/api/v3/coins/{coin_id}?localization=false&tickers=false&market_data=true&community_data=true&developer_data=false&sparkline=false"
        response = requests.get(url)
        response.raise_for_status()  # Raise an exception for bad status codes
        return response.json()
    except requests.exceptions.RequestException as e:
        st.error(f"Error fetching coin data for '{coin_id}': {e}")
        return None

def get_historical_data(coin_id, days=180):
    """Fetches historical market cap data for the past X days."""
    try:
        url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart?vs_currency=usd&days={days}&interval=daily"
        response = requests.get(url)
        response.raise_for_status()
        # We only need the market caps for our calculation
        return response.json()['market_caps']
    except requests.exceptions.RequestException as e:
        st.error(f"Error fetching historical data: {e}")
        return None

# --- Stock Market API Communication ---

def get_stock_data(ticker_symbol):
    """Fetches market data for a stock ticker from Yahoo Finance."""
    try:
        ticker = yf.Ticker(ticker_symbol)
        # .info can be slow and sometimes fails, so we have a check
        if not ticker.info or 'currentPrice' not in ticker.info:
            # Fallback for basic data if .info fails
            hist = ticker.history(period="5d")
            if hist.empty:
                return None
            
            # Create a minimal info dict
            info = {
                'shortName': ticker_symbol.upper(),
                'symbol': ticker_symbol.upper(),
                'currentPrice': hist['Close'][-1],
                'marketCap': ticker.info.get('marketCap'), # Might be None
                'trailingPE': ticker.info.get('trailingPE'), # Might be None
            }
            return info

        return ticker.info
    except Exception as e:
        st.error(f"Error fetching stock data for '{ticker_symbol}': {e}")
        return None

def get_stock_historical_data(ticker_symbol, days=180):
    """Fetches historical price data for a stock."""
    try:
        ticker = yf.Ticker(ticker_symbol)
        hist = ticker.history(period=f"{days}d", interval="1d")
        if hist.empty:
            return None
        # Return a list of closing prices
        return hist['Close'].tolist()
    except Exception as e:
        st.error(f"Error fetching stock historical data: {e}")
        return None

# --- Analysis & Calculation Engine ---

def calculate_scarcity_score(market_data):
    """Calculates a scarcity score based on supply metrics."""
    max_supply = market_data.get('max_supply')
    circulating_supply = market_data.get('circulating_supply')

    # If there's no max supply, scarcity is indeterminate.
    if not max_supply or max_supply == 0:
        return 0, "Indeterminate (No defined max supply)"

    # The score is higher the closer the circulating supply is to the max supply.
    # This indicates less new supply can enter the market ("supply shock" potential).
    percentage_circulated = (circulating_supply / max_supply) * 100
    score = round(percentage_circulated / 10)  # Scale to a 1-10 score

    return score, f"{percentage_circulated:.2f}% of max supply is in circulation."

def predict_time_to_target(historical_caps, current_market_cap, target_market_cap):
    """
    Predicts the time to reach a target market cap based on historical growth.
    Returns a string with the prediction.
    """
    if target_market_cap <= current_market_cap:
        return "Target price is at or below the current price."

    # Calculate daily growth rates from historical data
    daily_growth_rates = []
    # We look at pairs of days to find the growth rate between them
    for i in range(1, len(historical_caps)):
        # historical_caps[i] is a [timestamp, value] pair
        prev_cap = historical_caps[i-1][1]
        current_cap = historical_caps[i][1]
        if prev_cap > 0:
            daily_growth = (current_cap - prev_cap) / prev_cap
            daily_growth_rates.append(daily_growth)

    if not daily_growth_rates:
        return "Not enough historical data to calculate growth rate."

    avg_daily_growth = sum(daily_growth_rates) / len(daily_growth_rates)

    if avg_daily_growth <= 0:
        return "Historical growth rate is zero or negative. Target may not be reached on this trajectory."

    # Formula: target = current * (1 + growth)^t
    # Solving for t: t = log(target / current) / log(1 + growth)
    try:
        days_to_target = math.log(target_market_cap / current_market_cap) / math.log(1 + avg_daily_growth)
    except ValueError:
        return "Could not compute a time estimate due to a mathematical error (e.g., log of negative number)."


    if days_to_target > 365 * 25: # Cap at 25 years for sanity
        return "Over 25 years at current growth rate."
    elif days_to_target > 365:
        return f"Approx. {days_to_target / 365:.1f} years"
    elif days_to_target > 30:
        return f"Approx. {days_to_target / 30:.1f} months"
    else:
        return f"Approx. {days_to_target:.1f} days"

def generate_final_analysis(symbol, market_data, historical_caps):
    """Generates a final score and summary based on all collected data."""
    score = 0
    reasons = []

    # 1. Scarcity Analysis (Max 40 points)
    scarcity_score, _ = calculate_scarcity_score(market_data)
    score += scarcity_score * 4  # Scale 1-10 to 0-40
    if scarcity_score >= 8:
        reasons.append("[+] Strong Scarcity: Asset has a fixed supply, similar to Bitcoin.")
    elif scarcity_score >= 5:
        reasons.append("[~] Moderate Scarcity: Asset has a defined supply but much is yet to be released.")
    else:
        reasons.append("[-] Weak Scarcity: Asset is inflationary or has no defined max supply.")

    # 2. Network Growth Analysis (Max 40 points)
    current_market_cap = market_data.get('market_cap', {}).get('usd', 0)
    if historical_caps and current_market_cap > 0:
        daily_growth_rates = []
        for i in range(1, len(historical_caps)):
            prev_cap, current_cap = historical_caps[i-1][1], historical_caps[i][1]
            if prev_cap > 0:
                daily_growth_rates.append((current_cap - prev_cap) / prev_cap)
        
        if daily_growth_rates:
            avg_daily_growth = sum(daily_growth_rates) / len(daily_growth_rates)
            if avg_daily_growth > 0.005: # >0.5% daily growth
                score += 40
                reasons.append("[+] High Growth: Network value has shown strong positive momentum.")
            elif avg_daily_growth > 0:
                score += 20
                reasons.append("[~] Positive Growth: Network value is growing, but slowly.")
            else:
                score -= 20 # Penalize for negative growth
                reasons.append("[-] Negative Growth: Network value has been declining recently.")
    else:
        reasons.append("[-] Could not determine network growth.")

    # 3. Catalyst & Market Cap Modifier (Max 20 points)
    if symbol.lower() in ['btc', 'ltc', 'kas', 'bch']:
        score += 10
        reasons.append("[+] Built-in Catalyst: Has a supply-reduction event (halving).")
    
    if current_market_cap < 1_000_000_000: # Below $1B
        score += 10
        reasons.append("[+] High Reward Potential: Lower market cap allows for more explosive growth.")
    elif current_market_cap > 50_000_000_000: # Above $50B
        score -= 10
        reasons.append("[-] Limited Upside: Very large market cap may limit exponential returns.")

    score = max(0, min(100, score)) # Clamp score between 0 and 100

    if score >= 90: grade, summary = "A+", "Exceptional Potential. Displays very strong fundamentals across all key areas."
    elif score >= 80: grade, summary = "A", "Strong Potential. A solid candidate that scores well in most areas."
    elif score >= 70: grade, summary = "B+", "Good Potential. Shows positive signals but may have some weaknesses."
    elif score >= 60: grade, summary = "B", "Moderate Potential. An average candidate that warrants caution."
    elif score >= 50: grade, summary = "C", "Speculative. Lacks a solid foundation in key areas."
    else: grade, summary = "D", "High-Risk. Shows significant red flags in its fundamental data."

    return f"{int(score)}/100", grade, summary, reasons

def analyze_network_growth(market_data, target_price):
    """Analyzes the network growth required to meet a target price."""
    current_price = market_data.get('current_price', {}).get('usd', 0)
    current_market_cap = market_data.get('market_cap', {}).get('usd', 0)
    circulating_supply = market_data.get('circulating_supply', 0)
    
    if not circulating_supply or circulating_supply == 0 or current_price == 0:
        return "N/A", "N/A", "N/A"

    target_market_cap = target_price * circulating_supply
    required_growth_multiple = target_market_cap / current_market_cap if current_market_cap > 0 else float('inf')

    # Conceptual application of Metcalfe's Law:
    # Network Value is proportional to the square of the number of users (V ∝ n^2).
    # Therefore, the number of users is proportional to the square root of the value (n ∝ √V).
    required_user_growth_multiple = math.sqrt(required_growth_multiple) if required_growth_multiple > 0 else 1

    return f"${target_market_cap:,.2f}", f"{required_growth_multiple:.2f}x", f"{required_user_growth_multiple:.2f}x"

def analyze_billionaire_scenarios(market_data, target_price):
    """Calculates two hypothetical 'billionaire' scenarios."""
    current_price = market_data.get('current_price', {}).get('usd', 0)
    
    if current_price == 0 or target_price == 0:
        return "N/A", "N/A"

    # Scenario 1: How much a $1B investment today would be worth at the target price.
    investment_today = 1_000_000_000
    coins_bought_today = investment_today / current_price
    value_at_target = coins_bought_today * target_price

    # Scenario 2: How much it would cost today to own $1B worth of the asset at the target price.
    coins_needed_for_billion = 1_000_000_000 / target_price
    cost_today_for_billion = coins_needed_for_billion * current_price

    return f"${value_at_target:,.2f}", f"${cost_today_for_billion:,.2f}"

# --- Analysis & Calculation Engine (STOCKS) ---

def analyze_stock_growth_and_time(historical_prices, current_price, target_price):
    """Analyzes historical growth and predicts time to target for a stock."""
    if target_price <= current_price:
        return "Target is at or below current price.", "N/A"

    daily_growth_rates = []
    for i in range(1, len(historical_prices)):
        prev_price, current_p = historical_prices[i-1], historical_prices[i]
        if prev_price > 0:
            daily_growth_rates.append((current_p - prev_price) / prev_price)

    if not daily_growth_rates:
        return "Not enough data for prediction.", "N/A"

    avg_daily_growth = sum(daily_growth_rates) / len(daily_growth_rates)

    if avg_daily_growth <= 0:
        return "Negative historical growth.", "N/A"
    
    required_growth = (target_price / current_price)
    
    try:
        days_to_target = math.log(required_growth) / math.log(1 + avg_daily_growth)
    except ValueError:
        return "Could not compute time estimate.", "N/A"

    if days_to_target > 365 * 25: time_str = "Over 25 years"
    elif days_to_target > 365: time_str = f"Approx. {days_to_target / 365:.1f} years"
    elif days_to_target > 30: time_str = f"Approx. {days_to_target / 30:.1f} months"
    else: time_str = f"Approx. {days_to_target:.1f} days"

    return time_str, f"{required_growth:.2f}x"


def generate_stock_final_analysis(info, historical_prices):
    """Generates a final score and summary for a stock."""
    score = 0
    reasons = []

    # 1. Business Growth Analysis (Max 60 points)
    if historical_prices:
        daily_growth_rates = []
        for i in range(1, len(historical_prices)):
            prev_price, current_p = historical_prices[i-1], historical_prices[i]
            if prev_price > 0:
                daily_growth_rates.append((current_p - prev_price) / prev_price)
        
        if daily_growth_rates:
            avg_daily_growth = sum(daily_growth_rates) / len(daily_growth_rates)
            if avg_daily_growth > 0.003: # >0.3% daily growth
                score += 60
                reasons.append("[+] Strong Growth: Stock has shown strong positive momentum.")
            elif avg_daily_growth > 0:
                score += 30
                reasons.append("[~] Positive Growth: Stock has been growing, but slowly.")
            else:
                score -= 20 # Penalize for negative growth
                reasons.append("[-] Negative Growth: Stock price has been declining recently.")
    else:
        reasons.append("[-] Could not determine growth.")

    # 2. Valuation Analysis (Max 40 points)
    pe_ratio = info.get('trailingPE')
    if pe_ratio:
        if 0 < pe_ratio < 15:
            score += 40
            reasons.append(f"[+] Good Value (P/E {pe_ratio:.2f}): Stock appears undervalued.")
        elif 15 <= pe_ratio < 30:
            score += 20
            reasons.append(f"[~] Fair Value (P/E {pe_ratio:.2f}): Stock seems reasonably priced.")
        else: # P/E > 30 or negative
            score -= 10
            reasons.append(f"[-] High Valuation (P/E {pe_ratio:.2f}): Stock appears expensive.")
    else:
        reasons.append("[?] Unknown Valuation: P/E ratio is not available.")

    score = max(0, min(100, score)) # Clamp score

    if score >= 85: grade, summary = "A", "Strong Buy Candidate. Displays strong growth and good value."
    elif score >= 70: grade, summary = "B+", "Good Candidate. A solid company that scores well."
    elif score >= 50: grade, summary = "B", "Moderate Candidate. Shows potential but warrants caution."
    elif score >= 40: grade, summary = "C", "Speculative. Lacks a solid foundation in key areas."
    else: grade, summary = "D", "High-Risk. Shows significant red flags in its data."

    return f"{int(score)}/100", grade, summary, reasons

# --- UI Components ---

def set_page_config():
    st.set_page_config(
        page_title="Universal Asset Potential Tracker",
        page_icon="🚀",
        layout="centered",
        initial_sidebar_state="auto",
    )

def display_crypto_analysis(coin_id, symbol):
    """Fetches and displays the full analysis for a single crypto."""
    st.header(f"Full Analysis for {symbol.upper()}", divider='rainbow')

    target_price = st.number_input(f"Enter your target price for {symbol.upper()}", min_value=0.0, format="%.4f", key=f"target_{coin_id}")

    if st.button("Analyze 📈", key=f"analyze_{coin_id}"):
        with st.spinner(f"Fetching data and running analysis for {symbol.upper()}..."):
            data = get_coin_data(coin_id)
            if not data:
                st.error(f"Could not retrieve data for {coin_id}.")
                return

            market_data = data.get('market_data', {})
            current_price = market_data.get('current_price', {}).get('usd', 0)
            market_cap = market_data.get('market_cap', {}).get('usd', 0)
            circulating_supply = market_data.get('circulating_supply', 0)
            
            scarcity_score, scarcity_desc = calculate_scarcity_score(market_data)
            target_mcap, req_growth, req_user_growth = analyze_network_growth(market_data, target_price)
            historical_data = get_historical_data(coin_id)
            
            # Display Metrics
            col1, col2 = st.columns(2)
            col1.metric("Current Price", f"${current_price:,.4f}")
            col2.metric("Market Cap", f"${market_cap:,.2f}")

            # Scarcity
            with st.container(border=True):
                st.subheader("Scarcity Engine")
                st.metric("Scarcity Score (1-10)", f"{scarcity_score}/10")
                st.caption(scarcity_desc)

            # Network
            with st.container(border=True):
                st.subheader("Network & Time Engine")
                st.metric("Required Market Cap", target_mcap)
                st.text(f"Required Value Growth: {req_growth}")
                time_prediction = "N/A"
                if historical_data and market_cap > 0 and target_mcap.startswith('$'):
                    target_mcap_float = float(target_mcap.replace('$', '').replace(',', ''))
                    time_prediction = predict_time_to_target(historical_data, market_cap, target_mcap_float)
                st.metric("Est. Time to Target", time_prediction)

            # Final Analysis
            with st.container(border=True):
                st.subheader("Final Analysis (Not Financial Advice)")
                score, grade, summary, reasons = generate_final_analysis(symbol, market_data, historical_data)
                st.metric("Potential Score", f"{score}", help="Score out of 100 based on scarcity, growth, and catalysts.")
                st.metric("Grade", grade, help=summary)
                for reason in reasons:
                    st.markdown(f"* {reason}")

def display_stock_analysis(ticker):
    """Fetches and displays the full analysis for a single stock."""
    st.header(f"Full Analysis for {ticker}", divider='rainbow')

    target_price = st.number_input(f"Enter your target price for {ticker}", min_value=0.0, format="%.2f", key=f"target_{ticker}")

    if st.button("Analyze 📈", key=f"analyze_{ticker}"):
        with st.spinner(f"Fetching data for {ticker}..."):
            info = get_stock_data(ticker)
            if not info:
                st.error(f"Could not retrieve data for {ticker}.")
                return
            
            current_price = info.get('currentPrice', 0)
            market_cap = info.get('marketCap')
            pe_ratio = info.get('trailingPE')
            name = info.get('shortName', ticker)
            historical_prices = get_stock_historical_data(ticker)
            time_pred, growth_req = analyze_stock_growth_and_time(historical_prices, current_price, target_price)
            score, grade, summary, reasons = generate_stock_final_analysis(info, historical_prices)

            # Display Metrics
            col1, col2, col3 = st.columns(3)
            col1.metric("Current Price", f"${current_price:,.2f}")
            col2.metric("Market Cap", f"${market_cap:,.2f}" if market_cap else "N/A")
            col3.metric("P/E Ratio", f"{pe_ratio:.2f}" if pe_ratio else "N/A")

            # Growth
            with st.container(border=True):
                st.subheader("Growth & Time Engine")
                st.metric("Est. Time to Target", time_pred)
                st.text(f"Required Price Growth: {growth_req}")

            # Final Analysis
            with st.container(border=True):
                st.subheader("Final Analysis (Not Financial Advice)")
                st.metric("Potential Score", score, help="Score out of 100 based on growth and valuation.")
                st.metric("Grade", grade, help=summary)
                for reason in reasons:
                    st.markdown(f"* {reason}")

def run_crypto_analysis():
    """Handles the UI for analyzing a single crypto by name."""
    st.subheader("Analyze a Specific Cryptocurrency")
    coin_list = get_coin_list()
    if not coin_list:
        st.error("Could not load coin list. Please try again later.")
        return

    symbol = st.text_input("Enter a cryptocurrency symbol (e.g., btc, eth, kas)", "").lower().strip()

    if symbol:
        matches = coin_list.get(symbol)
        if not matches:
            st.warning(f"Could not find a coin with the symbol '{symbol}'.")
        elif len(matches) == 1:
            display_crypto_analysis(matches[0][0], matches[0][1])
        else:
            st.info(f"Multiple matches for '{symbol.upper()}'. Please choose one:")
            for i, (c_id, name) in enumerate(matches):
                if st.button(name, key=c_id):
                    st.session_state.selected_coin_id = c_id
                    st.session_state.selected_coin_name = name
            
            if 'selected_coin_id' in st.session_state:
                 display_crypto_analysis(st.session_state.selected_coin_id, st.session_state.selected_coin_name)

def run_stock_analysis():
    """Handles the UI for analyzing a single stock by ticker."""
    st.subheader("Analyze a Specific Stock")
    ticker = st.text_input("Enter a stock ticker (e.g., AAPL, TSLA)", "").upper().strip()
    if ticker:
        display_stock_analysis(ticker)

def run_crypto_screener():
    """UI for screening cryptos under a certain price."""
    st.subheader("Cryptocurrency Screener")
    max_price = st.number_input("Enter the maximum price to search for", min_value=0.0, value=1.0, format="%.2f")
    scan_limit = st.slider("How many top coins to scan?", min_value=100, max_value=1000, value=500, step=100)
    
    if st.button("Scan for Cryptos 🔎"):
        with st.spinner(f"Scanning the top {scan_limit} coins..."):
            top_coins = get_top_coins(scan_limit)
            if not top_coins:
                st.error("Could not fetch coin data.")
                return
            
            found_coins = [c for c in top_coins if c.get('current_price') is not None and c['current_price'] <= max_price]
            st.session_state.found_coins = found_coins

    if 'found_coins' in st.session_state:
        found_coins = st.session_state.found_coins
        if not found_coins:
            st.success("No coins found under your specified price in the scanned range.")
            return
        
        st.success(f"Found {len(found_coins)} Coins Under ${max_price:.2f}")
        
        # Create a dictionary for the selectbox
        coin_options = {f"{c['name']} ({c['symbol'].upper()}) - ${c['current_price']:.4f}": c for c in found_coins}
        
        selected_coin_str = st.selectbox("Select a coin to analyze", options=coin_options.keys())
        
        if selected_coin_str:
            selected_coin = coin_options[selected_coin_str]
            display_crypto_analysis(selected_coin['id'], selected_coin['symbol'])

def run_stock_screener():
    """UI for screening S&P 500 stocks under a certain price."""
    st.subheader("S&P 500 Stock Screener")
    max_price = st.number_input("Enter the maximum price to search for", min_value=0.0, value=50.0, format="%.2f")

    if st.button("Scan S&P 500 Stocks 🔎"):
        found_stocks = []
        progress_bar = st.progress(0, text="Starting S&P 500 Scan...")
        with st.spinner("Scanning S&P 500..."):
            for i, ticker in enumerate(SP500_TICKERS):
                progress_bar.progress((i+1)/len(SP500_TICKERS), text=f"Scanning {ticker}...")
                stock_data = get_stock_data(ticker)
                if stock_data and stock_data.get('currentPrice') and stock_data['currentPrice'] <= max_price:
                    found_stocks.append(stock_data)
        st.session_state.found_stocks = found_stocks
    
    if 'found_stocks' in st.session_state:
        found_stocks = st.session_state.found_stocks
        if not found_stocks:
            st.success("No S&P 500 stocks found under your specified price from the scanned list.")
            return

        st.success(f"Found {len(found_stocks)} S&P 500 Stocks Under ${max_price:.2f}")

        stock_options = {f"{s['shortName']} ({s['symbol']}) - ${s['currentPrice']:.2f}": s for s in found_stocks}
        selected_stock_str = st.selectbox("Select a stock to analyze", options=stock_options.keys())
        
        if selected_stock_str:
            selected_stock = stock_options[selected_stock_str]
            display_stock_analysis(selected_stock['symbol'])

@st.cache_data(ttl=600) # Cache for 10 minutes for screener
def get_top_coins(limit=250):
    """Gets market data for the top N coins by market cap."""
    try:
        url = f"https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc&per_page={limit}&page=1&sparkline=false"
        response = requests.get(url)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        st.error(f"Error fetching top coins: {e}")
        return None

def main():
    """Main function to run the Streamlit app."""
    set_page_config()
    st.title("🚀 Universal Asset Potential Tracker")
    st.caption("A data-driven tool for analyzing the potential of crypto and stock assets.")

    # Using session state to manage navigation
    if 'page' not in st.session_state:
        st.session_state.page = 'Home'

    # Sidebar for navigation
    with st.sidebar:
        st.header("Navigation")
        if st.button("Home", use_container_width=True):
            st.session_state.page = "Home"
        if st.button("Analyze Crypto", use_container_width=True):
            st.session_state.page = "Analyze Crypto"
        if st.button("Analyze Stock", use_container_width=True):
            st.session_state.page = "Analyze Stock"
        if st.button("Crypto Screener", use_container_width=True):
            st.session_state.page = "Crypto Screener"
        if st.button("Stock Screener", use_container_width=True):
            st.session_state.page = "Stock Screener"

    # Page routing
    if st.session_state.page == "Home":
        st.header("Welcome!")
        st.markdown("""
        This application is a powerful tool designed to help you analyze the potential of different assets based on fundamental data.
        
        **How it works:**
        - **For Cryptocurrencies:** It uses models based on scarcity (Stock-to-Flow) and network growth (Metcalfe's Law) to assess potential.
        - **For Stocks:** It analyzes historical business growth (price momentum) and current valuation (P/E Ratio).

        Use the navigation bar on the left to select a tool and get started.
        
        *Disclaimer: This is an analytical tool, not financial advice. All data is for informational purposes only.*
        """)
    elif st.session_state.page == "Analyze Crypto":
        run_crypto_analysis()
    elif st.session_state.page == "Analyze Stock":
        run_stock_analysis()
    elif st.session_state.page == "Crypto Screener":
        run_crypto_screener()
    elif st.session_state.page == "Stock Screener":
        run_stock_screener()

if __name__ == "__main__":
    main() 