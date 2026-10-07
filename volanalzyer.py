"""Tkinter straddle scenario analyzer with Interactive Brokers stock prices.

IV is a user-supplied assumption (default 30%), not fetched option-chain IV.
Black-Scholes assumes European exercise, no dividends, a constant 5% rate,
and unchanged time to expiry in scenarios. Prices and P&L are per share;
vega is per one percentage-point change in IV and theta is per calendar day.
"""

import tkinter as tk

from tkinter import ttk, messagebox

import threading

import time

from scipy.stats import norm

import numpy as np

from ibapi.client import EClient

from ibapi.wrapper import EWrapper

from ibapi.contract import Contract

from datetime import datetime

import sys

class IBApp(EWrapper, EClient):

    def __init__(self):

        EClient.__init__(self, self)

        self.connected = False

        self.market_data = {}

        self.historical_data = {}

        self.data_received = {}  

        self.request_errors = {}  

    def error(self, reqId, errorCode, errorString, *args):

        if errorCode == 2176 and "fractional share" in errorString.lower():

            return

        print(f"IB Error {errorCode} (ReqID {reqId}): {errorString}")

        if reqId is not None and reqId >= 0:

            self.request_errors[reqId] = (errorCode, errorString)

            if reqId in self.data_received and not self.data_received.get(reqId, False):

                self.data_received[reqId] = True

    def nextValidId(self, orderId):

        self.connected = True

        print("Connected to IBTWS")

    def historicalData(self, reqId, bar):

        if reqId not in self.historical_data:

            self.historical_data[reqId] = []

        self.historical_data[reqId].append({

            'date': bar.date,

            'open': bar.open,

            'high': bar.high,

            'low': bar.low,

            'close': bar.close,

            'volume': bar.volume

        })

    def historicalDataEnd(self, reqId, start, end):

        print(f"Historical data received for reqID {reqId}")

        self.data_received[reqId] = True  

    def tickPrice(self, reqId, tickType, price, attrib):

        if reqId not in self.market_data:

            self.market_data[reqId] = {}

        if price is None or price <= 0:

            return

        if tickType in (4, 68):

            self.market_data[reqId]["last"] = price

        elif tickType in (9, 75):

            self.market_data[reqId]["close"] = price

    def tickSnapshotEnd(self, reqId: int):

        self.data_received[reqId] = True

class VolatilityCrushAnalyzer:

    def __init__(self, root):

        self.root = root

        self.root.title("Volatility Crush Analyzer")

        self.root.geometry("1200x800")

        self.ib_app = IBApp()

        self.connected = False

        self.fetching = False  

        self.current_spot = None

        self.current_iv = None

        self.ticker = None
        self.current_straddle_price = None

        self.risk_free_rate = 0.05  # Default risk-free rate

        self.setup_ui()

    def create_equity_contract(self, symbol):

        contract = Contract()

        contract.symbol = symbol.upper()

        contract.secType = "STK"

        contract.exchange = "SMART"

        contract.currency = "USD"

        return contract

    def setup_ui(self):

        main_frame = ttk.Frame(self.root, padding="15")

        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        self.root.columnconfigure(0, weight=1)

        self.root.rowconfigure(0, weight=1)

        main_frame.columnconfigure(0, weight=1)

        main_frame.rowconfigure(1, weight=1)

        title_label = ttk.Label(main_frame, text="Volatility Crush Analyzer", 

                                font=('Arial', 16, 'bold'))

        title_label.grid(row=0, column=0, columnspan=2, pady=(0, 20))

        left_frame = ttk.Frame(main_frame)

        left_frame.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), padx=(0, 10))

        left_frame.columnconfigure(0, weight=1)

        right_frame = ttk.Frame(main_frame)

        right_frame.grid(row=1, column=1, sticky=(tk.W, tk.E, tk.N, tk.S), padx=(10, 0))

        right_frame.columnconfigure(0, weight=1)

        self.setup_connection_section(left_frame, 0)

        self.setup_market_data_section(left_frame, 1)

        self.setup_current_straddle_section(left_frame, 2)

        self.setup_current_greeks_section(left_frame, 3)

        self.setup_scenario_section(right_frame, 0)

        self.setup_pnl_section(right_frame, 1)

        self.setup_new_greeks_section(right_frame, 2)

        self.setup_status_section(right_frame, 3)

    def setup_current_straddle_section(self, parent, row):

        pricing_frame = ttk.LabelFrame(parent, text="Current Straddle Pricing", padding="10")

        pricing_frame.grid(row=row, column=0, sticky=(tk.W, tk.E), pady=(0, 15))

        pricing_frame.columnconfigure(1, weight=1)

        ttk.Label(pricing_frame, text="Call Price:").grid(row=0, column=0, padx=(0, 10), pady=(0, 5), sticky=tk.W)

        self.call_price_label = ttk.Label(pricing_frame, text="$0.00", font=('Arial', 11, 'bold'), foreground="green")

        self.call_price_label.grid(row=0, column=1, sticky=tk.W, pady=(0, 5))

        ttk.Label(pricing_frame, text="Put Price:").grid(row=1, column=0, padx=(0, 10), pady=(0, 5), sticky=tk.W)

        self.put_price_label = ttk.Label(pricing_frame, text="$0.00", font=('Arial', 11, 'bold'), foreground="red")

        self.put_price_label.grid(row=1, column=1, sticky=tk.W, pady=(0, 5))

        separator = ttk.Separator(pricing_frame, orient='horizontal')

        separator.grid(row=2, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=8)

        ttk.Label(pricing_frame, text="Straddle Price:").grid(row=3, column=0, padx=(0, 10), pady=(0, 5), sticky=tk.W)

        self.straddle_price_label = ttk.Label(pricing_frame, text="$0.00", font=('Arial', 14, 'bold'), foreground="blue")

        self.straddle_price_label.grid(row=3, column=1, sticky=tk.W, pady=(0, 5))

    def setup_current_greeks_section(self, parent, row):

        greeks_frame = ttk.LabelFrame(parent, text="Current Greeks", padding="10")

        greeks_frame.grid(row=row, column=0, sticky=(tk.W, tk.E), pady=(0, 15))

        greeks_frame.columnconfigure(1, weight=1)

        greeks_frame.columnconfigure(3, weight=1)

        ttk.Label(greeks_frame, text="Delta:").grid(row=0, column=0, padx=(0, 5), pady=(0, 5), sticky=tk.W)

        self.delta_label = ttk.Label(greeks_frame, text="0.00", font=('Arial', 10, 'bold'))

        self.delta_label.grid(row=0, column=1, sticky=tk.W, pady=(0, 5))

        ttk.Label(greeks_frame, text="Gamma:").grid(row=0, column=2, padx=(0, 5), pady=(0, 5), sticky=tk.W)

        self.gamma_label = ttk.Label(greeks_frame, text="0.00", font=('Arial', 10, 'bold'))

        self.gamma_label.grid(row=0, column=3, sticky=tk.W, pady=(0, 5))

        ttk.Label(greeks_frame, text="Vega:").grid(row=1, column=0, padx=(0, 5), pady=(0, 5), sticky=tk.W)

        self.vega_label = ttk.Label(greeks_frame, text="0.00", font=('Arial', 10, 'bold'))

        self.vega_label.grid(row=1, column=1, sticky=tk.W, pady=(0, 5))

        ttk.Label(greeks_frame, text="Theta:").grid(row=1, column=2, padx=(0, 5), pady=(0, 5), sticky=tk.W)

        self.theta_label = ttk.Label(greeks_frame, text="0.00", font=('Arial', 10, 'bold'))

        self.theta_label.grid(row=1, column=3, sticky=tk.W, pady=(0, 5))

    def setup_scenario_section(self, parent, row):

        scenario_frame = ttk.LabelFrame(parent, text="Scenario Analysis", padding="10")

        scenario_frame.grid(row=row, column=0, sticky=(tk.W, tk.E), pady=(0, 15))

        scenario_frame.columnconfigure(1, weight=1)

        ttk.Label(scenario_frame, text='New Spot Price:').grid(row=0, column=0, padx=(0, 10), pady=(0, 8), sticky=tk.W)

        self.new_spot_price = tk.StringVar()

        ttk.Entry(scenario_frame, textvariable=self.new_spot_price, width=15, font=('Arial', 10, 'bold')).grid(row=0, column=1, sticky=(tk.W, tk.E), pady=(0, 8))

        ttk.Label(scenario_frame, text='New IV(%)').grid(row=1, column=0, padx=(0, 10), pady=(0, 8), sticky=tk.W)

        self.new_iv_var = tk.StringVar()

        ttk.Entry(scenario_frame, textvariable=self.new_iv_var, width=15, font=('Arial', 10, 'bold')).grid(row=1, column=1, sticky=(tk.W, tk.E), pady=(0, 8))

        self.analyze_btn = ttk.Button(scenario_frame, text="Analyze Scenario", command=self.analyze_scenario, state='disabled')

        self.analyze_btn.grid(row=2, column=0, columnspan=2, pady=(10, 0))

    def setup_connection_section(self, parent, row):

        conn_frame = ttk.LabelFrame(parent, text="Interactive Brokers Connection", padding="15")

        conn_frame.grid(row=row, column=0, sticky=(tk.W, tk.E), pady=(0, 15))

        conn_frame.columnconfigure(1, weight=1)

        conn_frame.columnconfigure(3, weight=1)

        ttk.Label(conn_frame, text="Host:").grid(row=0, column=0, padx=(0, 5), sticky=tk.W)

        self.host_var = tk.StringVar(value='127.0.0.1')

        ttk.Entry(conn_frame, textvariable=self.host_var, width=15).grid(row=0, column=1, padx=(0, 15), sticky=(tk.W, tk.E))

        ttk.Label(conn_frame, text="Port:").grid(row=0, column=2, padx=(0, 5), sticky=(tk.W, tk.E))

        self.port_var = tk.StringVar(value='7497')

        ttk.Entry(conn_frame, textvariable=self.port_var, width=10).grid(row=0, column=3, padx=(0, 15), sticky=(tk.W, tk.E))

        self.connect_btn = ttk.Button(conn_frame, text="Connect to IB", command=self.connect_ib)

        self.connect_btn.grid(row=1, column=0, padx=(0, 10), pady=(10, 0), sticky=tk.W)

        self.disconnect_btn = ttk.Button(conn_frame, text="Disconnect", command=self.disconnect_ib, state=tk.DISABLED)

        self.disconnect_btn.grid(row=1, column=1, padx=(0, 10), pady=(10, 0), sticky=tk.W)

        self.status_label = ttk.Label(conn_frame, text="Status: Disconnected", foreground="red")

        self.status_label.grid(row=2, column=0, columnspan=4, pady=(5, 0), sticky=tk.W)

    def setup_market_data_section(self, parent, row):

        data_frame = ttk.LabelFrame(parent, text="Market Data & Parameters", padding="10")

        data_frame.grid(row=row, column=0, sticky=(tk.W, tk.E), pady=(0, 15))

        data_frame.columnconfigure(1, weight=1)

        ttk.Label(data_frame, text="Ticker:").grid(row=0, column=0, padx=(0, 10), pady=(0, 8), sticky=tk.W)

        ticker_frame = ttk.Frame(data_frame)

        ticker_frame.grid(row=0, column=1, sticky=(tk.W, tk.E), pady=(0, 8))

        ticker_frame.columnconfigure(0, weight=1)

        self.ticket_var = tk.StringVar(value="NVDA")

        ttk.Entry(ticker_frame, textvariable=self.ticket_var, width=12, font=('Arial', 10, 'bold')).pack(side=tk.LEFT)

        self.fetch_btn = ttk.Button(ticker_frame, text="Fetch Data", command=self.fetch_market_data, state='disabled')

        self.fetch_btn.pack(side=tk.RIGHT, padx=(10, 0))

        ttk.Label(data_frame, text= 'Spot Price:').grid(row=1, column=0, padx=(0, 10), pady=(0, 8), sticky=tk.W)

        self.spot_price_var = tk.StringVar()

        ttk.Entry(data_frame, textvariable=self.spot_price_var, width=15, font=('Arial', 10, 'bold')).grid(row=1, column=1, sticky=(tk.W, tk.E), pady=(0, 8))

        ttk.Label(data_frame, text= 'Strike Price:').grid(row=2, column=0, padx=(0, 10), pady=(0, 8), sticky=tk.W)

        self.strike_var = tk.StringVar()

        ttk.Entry(data_frame, textvariable=self.strike_var, width=15, font=('Arial', 10, 'bold')).grid(row=2, column=1, sticky=(tk.W, tk.E), pady=(0, 8))

        ttk.Label(data_frame, text= 'Assumed IV (%):').grid(row=3, column=0, padx=(0, 10), pady=(0, 8), sticky=tk.W)

        self.iv_var = tk.StringVar()

        ttk.Entry(data_frame, textvariable=self.iv_var, width=15, font=('Arial', 10, 'bold')).grid(row=3, column=1, sticky=(tk.W, tk.E), pady=(0, 8))

        ttk.Label(data_frame, text= 'Days to Expiry:').grid(row=4, column=0, padx=(0, 10), pady=(0, 8), sticky=tk.W)

        self.days_var = tk.StringVar(value="30")

        ttk.Entry(data_frame, textvariable=self.days_var, width=15, font=('Arial', 10, 'bold')).grid(row=4, column=1, sticky=(tk.W, tk.E), pady=(0, 8))

        self.price_btn = ttk.Button(data_frame, text="Price Straddle", command=self.price_current_straddle, state='disabled')

        self.price_btn.grid(row=5, column=0, columnspan=2, pady=(10, 0))

    def setup_pnl_section(self, parent, row):

        pnl_frame = ttk.LabelFrame(parent, text="P&L Analysis", padding="10")

        pnl_frame.grid(row=row, column=0, sticky=(tk.W, tk.E), pady=(0, 15))

        pnl_frame.columnconfigure(1, weight=1)

        ttk.Label(pnl_frame, text="New Straddle Price").grid(row=0, column=0, padx=(0, 10), pady=(0, 8), sticky=tk.W)

        self.new_straddle_label = ttk.Label(pnl_frame, text="$0.00", font=('Arial', 12, 'bold'), foreground="blue")

        self.new_straddle_label.grid(row=0, column=1, sticky=tk.W, pady=(0, 8))

        separator = ttk.Separator(pnl_frame, orient='horizontal')

        separator.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=8)

        ttk.Label(pnl_frame, text="Long Straddle P&L (per share)").grid(row=2, column=0, padx=(0, 10), pady=(0, 8), sticky=tk.W)

        self.pnl_long_label = ttk.Label(pnl_frame, text="$0.00", font=('Arial', 12, 'bold'))

        self.pnl_long_label.grid(row=2, column=1, sticky=tk.W, pady=(0, 8))

        ttk.Label(pnl_frame, text="Short Straddle P&L (per share)").grid(row=3, column=0, padx=(0, 10), pady=(0, 8), sticky=tk.W)

        self.pnl_short_label = ttk.Label(pnl_frame, text="$0.00", font=('Arial', 12, 'bold'))

        self.pnl_short_label.grid(row=3, column=1, sticky=tk.W)

    def setup_new_greeks_section(self, parent, row):

        new_greeks_frame = ttk.LabelFrame(parent, text="New Scenario Greeks", padding="10")

        new_greeks_frame.grid(row=row, column=0, sticky=(tk.W, tk.E), pady=(0, 15))

        new_greeks_frame.columnconfigure(1, weight=1)

        new_greeks_frame.columnconfigure(3, weight=1)

        ttk.Label(new_greeks_frame, text="Delta:").grid(row=0, column=0, padx=(0, 5), pady=(0, 5), sticky=tk.W)

        self.new_delta_label = ttk.Label(new_greeks_frame, text="0.00", font=('Arial', 10, 'bold'))

        self.new_delta_label.grid(row=0, column=1, sticky=tk.W, pady=(0, 5))

        ttk.Label(new_greeks_frame, text="Gamma:").grid(row=0, column=2, padx=(0, 5), pady=(0, 5), sticky=tk.W)

        self.new_gamma_label = ttk.Label(new_greeks_frame, text="0.00", font=('Arial', 10, 'bold'))

        self.new_gamma_label.grid(row=0, column=3, sticky=tk.W, pady=(0, 5))

        ttk.Label(new_greeks_frame, text="Vega:").grid(row=1, column=0, padx=(0, 5), pady=(0, 5), sticky=tk.W)

        self.new_vega_label = ttk.Label(new_greeks_frame, text="0.00", font=('Arial', 10, 'bold'))

        self.new_vega_label.grid(row=1, column=1, sticky=tk.W, pady=(0, 5))

        ttk.Label(new_greeks_frame, text="Theta:").grid(row=1, column=2, padx=(0, 5), pady=(0, 5), sticky=tk.W)

        self.new_theta_label = ttk.Label(new_greeks_frame, text="0.00", font=('Arial', 10, 'bold'))

        self.new_theta_label.grid(row=1, column=3, sticky=tk.W, pady=(0, 5))

    def setup_status_section(self, parent, row):

        status_frame = ttk.LabelFrame(parent, text="Status", padding="10")

        status_frame.grid(row=row, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 15))

        status_frame.columnconfigure(0, weight=1)

        status_frame.rowconfigure(0, weight=1)

        parent.rowconfigure(row, weight=1)

        self.status_var = tk.StringVar(value="Ready to connect to Interactive Brokers...")

        self.status_display = ttk.Label(status_frame, textvariable=self.status_var,

                                        wraplength=300, justify=tk.LEFT, font=('Arial', 9))

        self.status_display.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N,))

    def update_status(self, message):

        timestamp = datetime.now().strftime("%H:%M:%S")

        self.status_var.set(f"{timestamp} - {message}")

        self.root.update_idletasks()

    def connect_ib(self):

        try:

            host = self.host_var.get()

            port = int(self.port_var.get())

            self.update_status(f"Connecting to IB at {host}:{port}...")

            print(f"Attempting connection to {host}:{port}")

            def connect_thread():

                try:

                    print(f"Thread: Calling connect({host}, {port}, 0)")

                    self.ib_app.connect(host, port, 0)

                    print("Thread: connect() succeeded, starting run()")

                    self.ib_app.run()

                except Exception as e:

                    print(f"Thread: Connection error: {e}")

                    self.update_status(f"Connection error: {e}")

            thread = threading.Thread(target=connect_thread, daemon=True)

            thread.start()

            for i in range(200):  # Wait up to 20 seconds

                if self.ib_app.connected:

                    print(f"Connected flag set at iteration {i}")

                    break

                time.sleep(0.1)

            if self.ib_app.connected:

                try:

                    server_version = self.ib_app.serverVersion()

                    print(f"Server version: {server_version}")

                    if server_version is not None and server_version > 0:

                        self.connected = True

                        self.connect_btn.config(state='disabled')

                        self.disconnect_btn.config(state='normal')

                        self.fetch_btn.config(state='normal')

                        self.price_btn.config(state='normal')

                        self.status_label.config(text="Connected", foreground='green')

                        self.update_status(f"Successfully connected to IB TWS (Server: {server_version})")

                        print("Connection successful!")

                    else:

                        self.update_status("Connected but server version is not available.")

                except Exception as e:

                    self.update_status(f"Connection established but server version check failed: {e}")

            else:

                self.update_status("Failed to connect to IB TWS. Make sure TWS is running on the specified host/port.")

                print("Connection failed - nextValidId not received")

        except Exception as e:

            self.update_status(f"Connection error: {e}")

            print(f"Exception in connect_ib: {e}")

    def disconnect_ib(self):

        try:

            self.ib_app.disconnect()

            self.connected = False
            self.ib_app.connected = False

            self.connect_btn.config(state='normal')

            self.disconnect_btn.config(state='disabled')

            self.fetch_btn.config(state='disabled')

            self.price_btn.config(state='disabled')

            self.analyze_btn.config(state='disabled')

            self.status_label.config(text="Disconnected", foreground='red')

            self.clear_data()

            self.update_status("Disconnected from IB TWS")

        except Exception as e:

            self.update_status(f"Disconnection error: {e}")

    def clear_data(self):

        self.current_spot = None

        self.current_iv = None

        labels_to_reset = [

            self.call_price_label, self.put_price_label, self.straddle_price_label,

            self.delta_label, self.gamma_label, self.vega_label, self.theta_label,

            self.new_straddle_label, self.pnl_long_label, self.pnl_short_label,

            self.new_delta_label, self.new_gamma_label, self.new_vega_label, self.new_theta_label

        ]

        self.spot_price_var.set("")

        self.strike_var.set("")

        self.iv_var.set("")

        self.new_spot_price.set("")

        self.new_iv_var.set("")

        for label in labels_to_reset:

            if 'price' in str(label):

                label.config(text="$0.00", foreground="black")

            else:

                label.config(text="0.00", foreground="black")

        if hasattr(self, 'ib_app') and self.ib_app:

            self.ib_app.historical_data.clear()

    def fetch_market_data(self):

        if self.fetching:

            messagebox.showwarning("Warning", "Already fetching data. Please wait...")

            return

        if not self.connected or not self.ib_app.connected:

            messagebox.showerror("Error", "Not connected to Interactive Brokers.\n\nPlease ensure:\n1. IB TWS is running\n2. Connection details are correct (Host/Port)\n3. Click 'Connect to IB' button")

            return

        self.ticker = self.ticket_var.get().upper()

        if not self.ticker:

            messagebox.showerror("Error", "Please enter a ticker symbol.")

            return

        self.current_spot = None
        self.current_straddle_price = None
        self.spot_price_var.set("")
        self.strike_var.set("")
        self.analyze_btn.config(state='disabled')
        self.fetching = True

        self.update_status(f"Fetching market data for {self.ticker}...")

        self.ib_app.market_data.clear()

        self.ib_app.historical_data.clear()

        self.ib_app.request_errors.clear()

        self.ib_app.data_received[1] = False  # historical

        self.ib_app.data_received[2] = False  # snapshot market price

        contract = self.create_equity_contract(self.ticker)

        try:

            print(f"Requesting snapshot price for {self.ticker}")

            self.ib_app.reqMarketDataType(3)  # 3=delayed

            self.ib_app.reqMktData(

                reqId=2,

                contract=contract,

                genericTickList="",

                snapshot=True,

                regulatorySnapshot=False,

                mktDataOptions=[]

            )

        except Exception as e:

            self.update_status(f"Error requesting snapshot market data: {e}")

            print(f"Exception in snapshot request: {e}")

        try:

            print(f"Requesting historical close for {self.ticker}")

            self.ib_app.reqHistoricalData(

                reqId=1,

                contract=contract,

                endDateTime="", 

                durationStr="5 D",

                barSizeSetting="1 day",

                whatToShow="TRADES",

                useRTH=1,

                formatDate=1,

                keepUpToDate=False,

                chartOptions=[]

            )

        except Exception as e:

            self.update_status(f"Error requesting historical data: {e}")

            print(f"Exception in historical request: {e}")

        self.wait_for_market_price(reqId=2, max_wait=10000)

        self.wait_for_historical_data(reqId=1, max_wait=30000)

    def wait_for_market_price(self, reqId, max_wait=10000, poll_interval=100):

        """

        Wait for snapshot market price to arrive with timeout.

        max_wait: milliseconds to wait

        poll_interval: milliseconds between checks

        """

        start_time = time.time()

        max_wait_seconds = max_wait / 1000.0

        def check_data():

            elapsed = time.time() - start_time

            if self.current_spot is not None and self.spot_price_var.get():

                return

            md = self.ib_app.market_data.get(reqId, {})

            price = md.get("last") or md.get("close")

            if price is not None and price > 0:

                self.process_spot_price(float(price), source="snapshot")

                return

            if self.ib_app.data_received.get(reqId, False):

                err = self.ib_app.request_errors.get(reqId)

                if err:

                    self.update_status(f"Snapshot data error ({err[0]}): {err[1]}")

                return

            if elapsed > max_wait_seconds:

                err = self.ib_app.request_errors.get(reqId)

                if err:

                    self.update_status(f"Snapshot timeout with error ({err[0]}): {err[1]}")

                else:

                    self.update_status(f"Snapshot price timeout after {elapsed:.1f}s; falling back to historical close...")

                return

            self.root.after(poll_interval, check_data)

        check_data()

    def wait_for_historical_data(self, reqId, max_wait=30000, poll_interval=100):

        """

        Wait for historical data to arrive with timeout.

        max_wait: milliseconds to wait

        poll_interval: milliseconds between checks

        """

        start_time = time.time()

        max_wait_seconds = max_wait / 1000.0

        poll_interval_seconds = poll_interval / 1000.0

        def check_data():

            elapsed = time.time() - start_time

            if reqId in self.ib_app.data_received and self.ib_app.data_received[reqId]:

                self.process_market_data()

                if not self.spot_price_var.get():

                    self.fetching = False

                return

            if elapsed > max_wait_seconds:

                self.fetching = False

                self.update_status(f"Timeout waiting for historical data after {elapsed:.1f}s. Check IB connection and market hours.")

                print(f"Historical data request {reqId} timed out after {elapsed:.1f} seconds")

                if reqId in self.ib_app.historical_data:

                    print(f"Received {len(self.ib_app.historical_data[reqId])} bars before timeout")

                return

            # Show progress every 2 seconds

            if int(elapsed) % 2 == 0 and int(elapsed) != int(elapsed - 0.1):

                self.update_status(f"Fetching data... {elapsed:.0f}s elapsed (may take longer during off-hours)")

            self.root.after(poll_interval, check_data)

        check_data()

    def process_spot_price(self, spot_price: float, source: str):

        self.current_spot = float(spot_price)

        self.update_status(f"Spot price ({source}): ${self.current_spot:.2f}")

        self.spot_price_var.set(f"{self.current_spot:.2f}")

        self.strike_var.set(f"{self.current_spot:.2f}")

        if not self.iv_var.get():

            self.iv_var.set("30")

        self.fetching = False

        self.price_current_straddle()

    def process_market_data(self):

        if self.current_spot is not None and self.spot_price_var.get():

            return

        if 1 not in self.ib_app.historical_data or len(self.ib_app.historical_data[1]) == 0:

            err = self.ib_app.request_errors.get(1)

            if err:

                self.update_status(f"Historical data error ({err[0]}): {err[1]}")

            self.update_status("No historical price data received. Check ticker symbol and IB connection.")

            messagebox.showerror("Error", "Failed to retrieve historical data.\n\nPlease verify:\n1. IB TWS is running\n2. Ticker symbol is correct\n3. Market data subscription is active")

            self.fetching = False

            return

        price_data = self.ib_app.historical_data[1]

        latest_bar = price_data[-1]

        self.process_spot_price(float(latest_bar["close"]), source="historical close")

    def price_current_straddle(self):

        try:

            spot_price = float(self.spot_price_var.get())

            strike_price = float(self.strike_var.get())

            iv_percent = float(self.iv_var.get())

            days_to_expiry = int(self.days_var.get())

        except ValueError:

            messagebox.showerror("Error", "Please enter a valid number for all parameters.")

            return

        if not all(np.isfinite(v) and v > 0 for v in
                   (spot_price, strike_price, iv_percent, days_to_expiry)):
            messagebox.showerror("Error", "Spot, strike, IV and days to expiry must be positive finite numbers.")
            return False

        iv_decimal = iv_percent / 100

        T = days_to_expiry / 365.0

        r = self.risk_free_rate

        call_price = self.black_scholes_call(spot_price, strike_price, T, r, iv_decimal)

        put_price = self.black_scholes_put(spot_price, strike_price, T, r, iv_decimal)

        straddle_price = call_price + put_price
        self.current_straddle_price = straddle_price

        delta = self.calculate_delta(spot_price, strike_price, T, r, iv_decimal, 'call') + self.calculate_delta(spot_price, strike_price, T, r, iv_decimal, 'put')

        gamma = 2 * self.calculate_gamma(spot_price, strike_price, T, r, iv_decimal)

        vega = self.calculate_vega(spot_price, strike_price, T, r, iv_decimal) * 2

        theta = self.calculate_theta(spot_price, strike_price, T, r, iv_decimal, 'call') + self.calculate_theta(spot_price, strike_price, T, r, iv_decimal, 'put')

        self.call_price_label.config(text=f"${call_price:.2f}", foreground="green")

        self.put_price_label.config(text=f"${put_price:.2f}", foreground="red")

        self.straddle_price_label.config(text=f"${straddle_price:.2f}", foreground="blue")

        self.delta_label.config(text=f"{delta:.3f}")

        self.gamma_label.config(text=f"{gamma:.3f}")

        self.vega_label.config(text=f"{vega:.2f}")

        self.theta_label.config(text=f"{theta:.2f}")

        self.analyze_btn.config(state='normal')

        if not self.new_spot_price.get():

            self.new_spot_price.set(f"{spot_price:.2f}")

        if not self.new_iv_var.get():

            self.new_iv_var.set(f"{iv_percent:.2f}")

        self.update_status(f"Straddle priced: ${straddle_price:.2f}, Call: ${call_price:.2f} + Put: ${put_price:.2f}")
        return True

    def analyze_scenario(self):
        # Reprice the baseline from the current inputs before comparing scenarios.
        if not self.price_current_straddle():
            return

        try:

            new_spot = float(self.new_spot_price.get())

            new_iv_percent = float(self.new_iv_var.get()) / 100

        except ValueError:

            messagebox.showerror("Error", "Please enter valid numbers for new spot price and IV.")

            return

        try:

            K = float(self.strike_var.get())

            days_to_expiry = int(self.days_var.get())

        except ValueError:

            messagebox.showerror("Error", "Please enter valid numbers for strike price and days to expiry.")

            return

        T = days_to_expiry / 365.0

        r = self.risk_free_rate

        if not all(np.isfinite(v) and v > 0 for v in (new_spot, new_iv_percent)):
            messagebox.showerror("Error", "Scenario spot and IV must be positive finite numbers.")
            return

        new_call_price = self.black_scholes_call(new_spot, K, T, r, new_iv_percent)

        new_put_price = self.black_scholes_put(new_spot, K, T, r, new_iv_percent)

        new_straddle_price = new_call_price + new_put_price

        original_straddle_price = self.current_straddle_price

        pnl_long = new_straddle_price - original_straddle_price

        pnl_short = original_straddle_price - new_straddle_price

        self.new_straddle_label.config(text=f"${new_straddle_price:.2f}", foreground="blue")

        long_color = "green" if pnl_long >= 0 else "red"

        short_color = "green" if pnl_short >= 0 else "red"

        self.pnl_long_label.config(text=f"${pnl_long:+.2f}", foreground=long_color)

        self.pnl_short_label.config(text=f"${pnl_short:+.2f}", foreground=short_color)

        new_delta = self.calculate_delta(new_spot, K, T, r, new_iv_percent, 'call') + self.calculate_delta(new_spot, K, T, r, new_iv_percent, 'put')

        new_gamma = 2 * self.calculate_gamma(new_spot, K, T, r, new_iv_percent)

        new_vega = self.calculate_vega(new_spot, K, T, r, new_iv_percent) * 2

        new_theta = self.calculate_theta(new_spot, K, T, r, new_iv_percent, 'call') + self.calculate_theta(new_spot, K, T, r, new_iv_percent, 'put')

        self.new_delta_label.config(text=f"{new_delta:.3f}")

        self.new_gamma_label.config(text=f"{new_gamma:.3f}")

        self.new_vega_label.config(text=f"{new_vega:.2f}")

        self.new_theta_label.config(text=f"{new_theta:.2f}")

        self.update_status(f"Scenario completed: ${new_straddle_price:.2f}")

    def black_scholes_call(self, S, K, T, r, sigma):

        d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))

        d2 = d1 - sigma * np.sqrt(T)

        return S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)

    def black_scholes_put(self, S, K, T, r, sigma):

        d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))

        d2 = d1 - sigma * np.sqrt(T)

        return K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)

    def calculate_delta(self, S, K, T, r, sigma, option_type='call'):

        d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))

        if option_type == 'call':

            return norm.cdf(d1)

        else:

            return norm.cdf(d1) - 1

    def calculate_gamma(self, S, K, T, r, sigma):

        d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))

        return norm.pdf(d1) / (S * sigma * np.sqrt(T))

    def calculate_vega(self, S, K, T, r, sigma):

        d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))

        return S * norm.pdf(d1) * np.sqrt(T) / 100

    def calculate_theta(self, S, K, T, r, sigma, option_type='call'):

        d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))

        d2 = d1 - sigma * np.sqrt(T)

        if option_type == 'call':

            theta = (-(S * norm.pdf(d1) * sigma) / (2 * np.sqrt(T)) - r * K * np.exp(-r * T) * norm.cdf(d2)) / 365

        else:

            theta = (-(S * norm.pdf(d1) * sigma) / (2 * np.sqrt(T)) + r * K * np.exp(-r * T) * norm.cdf(-d2)) / 365

        return theta

def main():

    root = tk.Tk()

    app = VolatilityCrushAnalyzer(root)

    root.update_idletasks()

    width = root.winfo_width()

    height = root.winfo_height()

    x = (root.winfo_screenwidth() // 2) - (width // 2)

    y = (root.winfo_screenheight() // 2) - (height // 2)

    root.geometry(f'{width}x{height}+{x}+{y}')

    try:

        import ctypes

        ctypes.windll.kernel32.SetThreadExecutionState(0x80000002)  

    except:

        pass

    root.deiconify()

    root.update()

    root.lift()

    root.attributes('-topmost', True)

    root.focus_force()

    time.sleep(0.1)

    root.attributes('-topmost', False)

    print("Window created and displayed")

    sys.stdout.flush()

    root.mainloop()

if __name__ == "__main__":

    main()

