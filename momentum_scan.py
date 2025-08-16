
# momentum_scan.py
# Automated scanner: flags tickers with 3 consecutive days >5% gains.

import os, io, sys, time, math, requests, pandas as pd, yfinance as yf
from datetime import datetime, timezone

EXCHANGES = os.getenv("EXCHANGES", "NASDAQ,NYSE,AMEX").split(",")
MIN_PRICE = float(os.getenv("MIN_PRICE", "2"))
MIN_AVG_DOLLAR_VOL = float(os.getenv("MIN_AVG_DOLLAR_VOL", "2000000"))
MIN_LAST_DAY_VOL = float(os.getenv("MIN_LAST_DAY_VOL", "500000"))
DAYS_REQUIRED = int(os.getenv("DAYS_REQUIRED", "3"))
PCT_PER_DAY = float(os.getenv("PCT_PER_DAY", "5.0"))
LIMIT_TICKERS = os.getenv("LIMIT_TICKERS")
EXTRA_TICKERS = [t.strip() for t in os.getenv("EXTRA_TICKERS", "").split(",") if t.strip()]

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def fetch_symbol_list():
    urls = {
        "NASDAQ": "https://ftp.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt",
        "NYSE":   "https://ftp.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt",
        "AMEX":   "https://ftp.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt",
    }
    frames = []
    for ex in EXCHANGES:
        ex = ex.strip().upper()
        url = urls.get(ex)
        if not url: continue
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        data = r.text.strip().splitlines()
        data = [ln for ln in data if "File Creation Time" not in ln]
        df = pd.read_csv(io.StringIO("\n".join(data)), sep="|")
        if ex == "NASDAQ":
            symbols = df["Symbol"].astype(str).tolist()
        else:
            col = "ACT Symbol" if "ACT Symbol" in df.columns else df.columns[0]
            symbols = df[col].astype(str).tolist()
        frames.append(pd.DataFrame({"symbol": symbols}))
    if not frames: syms = []
    else:
        all_syms = pd.concat(frames, ignore_index=True)["symbol"].dropna().unique().tolist()
        syms = [s for s in all_syms if s.isupper() and s.isascii()]
    syms = [s for s in syms if s not in {"TEST","ZZZZ","N/A"}]
    syms.extend(EXTRA_TICKERS)
    if LIMIT_TICKERS:
        try: syms = syms[:int(LIMIT_TICKERS)]
        except: pass
    return sorted(set(syms))

def chunk(lst,n): 
    for i in range(0,len(lst),n): yield lst[i:i+n]

def compute_signals(df_prices):
    rows = []
    if isinstance(df_prices.columns,pd.MultiIndex): tickers=sorted({c[0] for c in df_prices.columns})
    else: tickers=["SINGLE"]
    for t in tickers:
        try:
            sub = df_prices if t=="SINGLE" else df_prices[t]
            sub=sub.dropna()
            if sub.empty or "Close" not in sub: continue
            last_close=float(sub["Close"].iloc[-1])
            if math.isnan(last_close) or last_close<MIN_PRICE: continue
            sub["DollarVol"]=sub["Close"]*sub["Volume"]
            avg_dollar_vol=float(sub["DollarVol"].tail(20).mean() or 0)
            if avg_dollar_vol<MIN_AVG_DOLLAR_VOL: continue
            if float(sub["Volume"].iloc[-1] or 0)<MIN_LAST_DAY_VOL: continue
            sub["pct_change"]=sub["Close"].pct_change()*100
            last_n=sub["pct_change"].dropna().tail(DAYS_REQUIRED)
            if len(last_n)<DAYS_REQUIRED: continue
            if (last_n>PCT_PER_DAY).all():
                three_day_return=(sub["Close"].iloc[-1]/sub["Close"].iloc[-(DAYS_REQUIRED+1)]-1)*100
                row={"ticker":t if t!="SINGLE" else "UNKNOWN",
                     "last_close":round(last_close,4),
                     "3_day_return_%":round(three_day_return,2)}
                rows.append(row)
        except: continue
    return rows

def send_telegram(msg):
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID): return False
    try:
        url=f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url,json={"chat_id":TELEGRAM_CHAT_ID,"text":msg},timeout=20)
        return True
    except: return False

def main():
    start=time.time()
    syms=fetch_symbol_list()
    results=[]
    for batch in chunk(syms,250):
        try:
            data=yf.download(tickers=batch,period="35d",interval="1d",
                             auto_adjust=False,group_by="ticker",threads=True,progress=False)
            results.extend(compute_signals(data))
        except: continue
    df=pd.DataFrame(results)
    out_dir=os.getenv("OUTPUT_DIR","."); os.makedirs(out_dir,exist_ok=True)
    csv_path=os.path.join(out_dir,f"momentum_3x5_{datetime.now().strftime('%Y%m%d')}.csv")
    df.to_csv(csv_path,index=False)
    msg="No tickers found." if df.empty else f"Found {len(df)} tickers meeting 3x>{PCT_PER_DAY}% rule."
    send_telegram(msg)
    print(msg,"CSV saved to",csv_path)

if __name__=="__main__": main()
