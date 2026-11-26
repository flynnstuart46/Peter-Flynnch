"""Portfolio Hub updater.

Reads data/portfolios.json and data/reports.json, pulls market prices from
Yahoo Finance (via yfinance), and writes data/snapshot.json, which the web
page (index.html) displays.

Run locally:   python scripts/update.py
Test offline:  python scripts/update.py --mock --data path/to/test-data
"""

import argparse
import datetime as dt
import json
import math
import pathlib
import sys

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent.parent
BENCHMARK = "SPY"  # tracks the S&P 500
BENCHMARK_NAME = "S&P 500 (SPY)"


# ---------------------------------------------------------------- helpers

def parse_date(value, field, where):
    try:
        return pd.Timestamp(dt.date.fromisoformat(str(value).strip()))
    except Exception:
        sys.exit(f"ERROR: {where}: '{field}' must be a date like 2025-03-14, got {value!r}")


def num(value, field, where, allow_none=False):
    if value is None and allow_none:
        return None
    try:
        out = float(value)
        if math.isnan(out):
            raise ValueError
        return out
    except Exception:
        sys.exit(f"ERROR: {where}: '{field}' must be a number, got {value!r}")


def clean(x):
    """Make values JSON-safe (no NaN / numpy types)."""
    if isinstance(x, dict):
        return {k: clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [clean(v) for v in x]
    if hasattr(x, "item"):
        x = x.item()
    if isinstance(x, float):
        return None if (math.isnan(x) or math.isinf(x)) else round(x, 6)
    return x


def load_json(path, default):
    if not path.exists():
        return default
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        sys.exit(f"ERROR: {path.name} is not valid JSON (line {e.lineno}, column {e.colno}): {e.msg}. "
                 "Check for a missing comma, an extra comma before ] or }, or a missing quote.")


# ---------------------------------------------------------------- inputs

def read_inputs(data_dir):
    raw = load_json(data_dir / "portfolios.json", {"portfolios": []})
    portfolios = []
    for i, p in enumerate(raw.get("portfolios", [])):
        name = str(p.get("name") or f"Portfolio {i + 1}")
        where = f"portfolios.json, portfolio '{name}'"
        lots = []
        for j, lot in enumerate(p.get("positions", [])):
            w = f"{where}, position {j + 1}"
            ticker = str(lot.get("ticker", "")).strip().upper()
            if not ticker:
                sys.exit(f"ERROR: {w}: missing 'ticker'")
            entry = {
                "ticker": ticker,
                "shares": num(lot.get("shares"), "shares", w),
                "buy_price": num(lot.get("buy_price"), "buy_price", w),
                "buy_date": parse_date(lot.get("buy_date"), "buy_date", w),
                "sell_price": None,
                "sell_date": None,
            }
            if lot.get("sell_date") or lot.get("sell_price") is not None:
                entry["sell_date"] = parse_date(lot.get("sell_date"), "sell_date", w)
                entry["sell_price"] = num(lot.get("sell_price"), "sell_price", w)
                if entry["sell_date"] < entry["buy_date"]:
                    sys.exit(f"ERROR: {w}: sell_date is before buy_date")
            lots.append(entry)
        flows = []
        for j, f in enumerate(p.get("cash_flows", [])):
            w = f"{where}, cash_flows entry {j + 1}"
            flows.append({"date": parse_date(f.get("date"), "date", w),
                          "amount": num(f.get("amount"), "amount", w),
                          "note": str(f.get("note") or "")})
        flows.sort(key=lambda f: f["date"])
        start = p.get("start_date")
        if start:
            start = parse_date(start, "start_date", where)
        elif lots:
            start = min(l["buy_date"] for l in lots)
        else:
            start = pd.Timestamp(dt.date.today())
        portfolios.append({
            "id": f"p{i}",
            "name": name,
            "description": str(p.get("description") or ""),
            "cash": num(p.get("cash", 0) or 0, "cash", where),
            "start": start,
            "lots": lots,
            "flows": flows,
        })
    reports = load_json(data_dir / "reports.json", {"reports": []}).get("reports", [])
    return portfolios, reports


# ---------------------------------------------------------------- market data

def fetch_market(tickers, start):
    import yfinance as yf

    tickers = sorted(set(tickers))
    daily = yf.download(tickers, start=(start - pd.Timedelta(days=10)).date(),
                        auto_adjust=False, progress=False, group_by="column",
                        threads=True)
    if daily is None or daily.empty:
        sys.exit("ERROR: could not download prices from Yahoo Finance.")
    close = daily["Close"]
    if isinstance(close, pd.Series):
        close = close.to_frame(tickers[0])
    close.index = pd.to_datetime(close.index).tz_localize(None).normalize()

    # Freshest intraday prices (about 15 minutes delayed) for today's row.
    try:
        intra = yf.download(tickers, period="5d", interval="15m", auto_adjust=False,
                            progress=False, group_by="column", threads=True, prepost=False)
        if intra is not None and not intra.empty:
            ic = intra["Close"]
            if isinstance(ic, pd.Series):
                ic = ic.to_frame(tickers[0])
            ic.index = pd.to_datetime(ic.index)
            if ic.index.tz is not None:
                ic.index = ic.index.tz_convert("America/New_York").tz_localize(None)
            for t in ic.columns:
                s = ic[t].dropna()
                if s.empty:
                    continue
                day = s.index[-1].normalize()
                if day not in close.index:
                    close.loc[day] = float("nan")
                close.loc[day, t] = float(s.iloc[-1])
            close = close.sort_index()
    except Exception as e:  # intraday is a nice-to-have
        print(f"note: intraday prices unavailable ({e}); using daily closes")

    meta = {}
    for t in tickers:
        info = {}
        try:
            info = yf.Ticker(t).info or {}
        except Exception:
            pass
        qtype = (info.get("quoteType") or "").upper()
        sector = info.get("sector") or ("ETF / Fund" if qtype in ("ETF", "MUTUALFUND") else "Other")
        meta[t] = {"name": info.get("shortName") or info.get("longName") or t, "sector": sector}
    return close, meta


def mock_market(tickers, start):
    """Deterministic fake prices for offline testing."""
    import numpy as np

    tickers = sorted(set(tickers))
    days = pd.bdate_range(start - pd.Timedelta(days=10), pd.Timestamp(dt.date.today()))
    frame = {}
    for k, t in enumerate(tickers):
        rng = np.random.default_rng(sum(ord(c) * 31 ** n for n, c in enumerate(t)) % 2**32)
        drift = 0.0004 if t == BENCHMARK else 0.0002 + 0.0001 * (k % 5)
        steps = rng.normal(drift, 0.012 if t == BENCHMARK else 0.018, len(days))
        frame[t] = (100 + 20 * k) * np.exp(np.cumsum(steps))
    sectors = ["Technology", "Financial Services", "Energy", "Healthcare", "Consumer Cyclical"]
    meta = {t: {"name": f"{t} Inc." if t != BENCHMARK else "SPDR S&P 500 ETF",
                "sector": "ETF / Fund" if t == BENCHMARK else sectors[k % len(sectors)]}
            for k, t in enumerate(tickers)}
    return pd.DataFrame(frame, index=days), meta


# ---------------------------------------------------------------- calculations

def build_portfolio(p, close, bench_close, meta):
    lots = p["lots"]
    days = bench_close.index[bench_close.index >= p["start"]]
    if len(days) == 0:
        days = bench_close.index[-1:]
    prices = close.reindex(close.index.union(days)).ffill().reindex(days)

    start = p["start"]
    # If the start date has no trading day yet (e.g. a holiday), value at the latest close.
    anchor = days[0] if days[0] >= start else None
    before = close[close.index < days[0]].ffill() if anchor is not None else close[close.index <= days[0]].ffill()

    def start_price(l):
        t = l["ticker"]
        if t in before and len(before) and not pd.isna(before[t].iloc[-1]):
            return float(before[t].iloc[-1])
        return l["buy_price"]

    flows = p["flows"]
    # Positions already held on the start date (entered with an average cost).
    initial = [l for l in lots if l["buy_date"] < start
               and (l["sell_date"] is None or l["sell_date"] >= start)]
    # Cash on the start date: starting cash plus any deposits/withdrawals dated before it.
    cash0 = p["cash"] + sum(f["amount"] for f in flows if f["date"] < start)

    def cash_on(d):
        """Cash ledger: deposits/withdrawals, minus buys, plus sales (from the start date on)."""
        c = cash0 + sum(f["amount"] for f in flows if start <= f["date"] <= d)
        for l in lots:
            if start <= l["buy_date"] <= d:
                c -= l["shares"] * l["buy_price"]
            if l["sell_date"] is not None and start <= l["sell_date"] <= d:
                c += l["shares"] * l["sell_price"]
        return c

    values, returns, cash_series = [], [], []
    prev_value = cash0
    for k, d in enumerate(days):
        cash = cash_on(d)
        value = cash
        for l in lots:
            held = l["buy_date"] <= d and (l["sell_date"] is None or l["sell_date"] > d)
            if held:
                px = prices.at[d, l["ticker"]] if l["ticker"] in prices else float("nan")
                if pd.isna(px):
                    px = l["buy_price"]
                value += l["shares"] * px
        # Only deposits and withdrawals count as money in/out; trades just move cash.
        inflow = sum(f["amount"] for f in flows if f["date"] == d and f["amount"] > 0)
        outflow = -sum(f["amount"] for f in flows if f["date"] == d and f["amount"] < 0)
        if k == 0:
            inflow += sum(l["shares"] * start_price(l) for l in initial)
        # Time-weighted return: money in at start of day, money out at end of day.
        base = prev_value + inflow
        r = (value + outflow) / base - 1 if base > 0 else 0.0
        values.append(value)
        returns.append(r)
        cash_series.append(cash)
        prev_value = value

    index = (pd.Series(returns, index=days) + 1).cumprod() * 100
    base_day = bench_close.index[bench_close.index < days[0]]
    dates = list(days)
    idx = list(index.values)
    vals = list(values)
    if len(base_day):  # anchor both lines at 100 the trading day before the start
        dates = [base_day[-1]] + dates
        idx = [100.0] + idx
        vals = [None] + vals

    last = days[-1]
    prev = days[-2] if len(days) > 1 else None
    holdings, closed = {}, []
    for l in lots:
        t = l["ticker"]
        if l["sell_date"] is not None and l["sell_date"] <= last:
            cost = l["shares"] * l["buy_price"]
            proceeds = l["shares"] * l["sell_price"]
            closed.append({
                "ticker": t, "name": meta.get(t, {}).get("name", t), "shares": l["shares"],
                "buy_date": l["buy_date"].date().isoformat(), "buy_price": l["buy_price"],
                "sell_date": l["sell_date"].date().isoformat(), "sell_price": l["sell_price"],
                "gain": proceeds - cost, "gain_pct": proceeds / cost - 1 if cost else None,
            })
            continue
        if l["buy_date"] > last:
            continue
        h = holdings.setdefault(t, {"ticker": t, "shares": 0.0, "cost": 0.0,
                                    "first_buy": l["buy_date"]})
        h["shares"] += l["shares"]
        h["cost"] += l["shares"] * l["buy_price"]
        h["first_buy"] = min(h["first_buy"], l["buy_date"])

    cash_now = cash_series[-1]
    total = values[-1] if values else cash_now
    rows = []
    for t, h in holdings.items():
        px = prices.at[last, t] if t in prices else float("nan")
        px_prev = prices.at[prev, t] if (prev is not None and t in prices) else float("nan")
        if pd.isna(px):
            px = h["cost"] / h["shares"] if h["shares"] else float("nan")
        value = h["shares"] * px
        rows.append({
            "ticker": t, "name": meta.get(t, {}).get("name", t),
            "sector": meta.get(t, {}).get("sector", "Other"),
            "shares": h["shares"], "avg_cost": h["cost"] / h["shares"] if h["shares"] else None,
            "price": px, "day_pct": (px / px_prev - 1) if (not pd.isna(px_prev) and px_prev) else None,
            "value": value, "weight": value / total if total else None,
            "gain": value - h["cost"], "gain_pct": value / h["cost"] - 1 if h["cost"] else None,
            "first_buy": h["first_buy"].date().isoformat(),
        })
    rows.sort(key=lambda r: -(r["value"] or 0))

    sectors = {}
    for r in rows:
        sectors[r["sector"]] = sectors.get(r["sector"], 0) + (r["value"] or 0)
    if abs(cash_now) > 0.005:
        sectors["Cash"] = sectors.get("Cash", 0) + cash_now
    allocation = [{"sector": k, "value": v, "weight": v / total if total else None}
                  for k, v in sorted(sectors.items(), key=lambda kv: -kv[1])]

    invested = sum(h["cost"] for h in holdings.values())
    return {
        "id": p["id"], "name": p["name"], "description": p["description"],
        "start_date": p["start"].date().isoformat(), "cash": cash_now,
        "cash_activity": [{"date": f["date"].date().isoformat(), "amount": f["amount"], "note": f["note"]}
                          for f in reversed(flows)],
        "net_deposits": sum(f["amount"] for f in flows),
        "min_cash": (min(cash_series), days[cash_series.index(min(cash_series))].date().isoformat()),
        "value": total, "invested": invested,
        "unrealized": sum(r["gain"] for r in rows),
        "realized": sum(c["gain"] for c in closed),
        "day_pct": returns[-1] if len(days) > 1 else None,
        "series": {"dates": [d.date().isoformat() for d in dates], "index": idx, "value": vals},
        "holdings": rows, "closed": closed, "allocation": allocation,
        "has_positions": bool(lots),
    }


def period_returns(dates, index, bench_close):
    """1M / 3M / YTD / 1Y / since-start returns for a portfolio and the benchmark."""
    s = pd.Series(index, index=pd.to_datetime(dates))
    b = bench_close.reindex(s.index).ffill()
    end = s.index[-1]
    windows = {
        "1M": end - pd.DateOffset(months=1),
        "3M": end - pd.DateOffset(months=3),
        "YTD": pd.Timestamp(year=end.year, month=1, day=1) - pd.Timedelta(days=1),
        "1Y": end - pd.DateOffset(years=1),
    }
    out = {}
    for k, w in windows.items():
        if k == "YTD":
            w = max(w, s.index[0])
        if w < s.index[0]:
            out[k] = {"port": None, "bench": None}
            continue
        i = s.index[s.index <= w][-1]
        out[k] = {"port": s.iloc[-1] / s.loc[i] - 1, "bench": b.iloc[-1] / b.loc[i] - 1}
    out["Start"] = {"port": s.iloc[-1] / s.iloc[0] - 1, "bench": b.iloc[-1] / b.iloc[0] - 1}
    return out


def build_reports(reports, close, meta):
    out = []
    for i, r in enumerate(reports):
        t = str(r.get("ticker", "")).strip().upper()
        where = f"reports.json, report {i + 1}"
        target = num(r.get("target"), "target", where, allow_none=True)
        series = close[t].dropna() if t in close else pd.Series(dtype=float)
        price = float(series.iloc[-1]) if len(series) else None
        price_then = None
        if r.get("date") and len(series):
            d = parse_date(r.get("date"), "date", where)
            before = series[series.index <= d]
            price_then = float(before.iloc[-1]) if len(before) else None
        out.append({
            "ticker": t, "name": meta.get(t, {}).get("name", t),
            "title": r.get("title") or f"{t} report", "date": r.get("date"),
            "rating": r.get("rating"), "target": target, "summary": r.get("summary") or "",
            "file": r.get("file"), "price": price, "price_at_report": price_then,
            "upside": (target / price - 1) if (target and price) else None,
            "since_report": (price / price_then - 1) if (price and price_then) else None,
        })
    return out


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ROOT / "data"))
    ap.add_argument("--mock", action="store_true", help="use fake prices (offline test)")
    args = ap.parse_args()
    data_dir = pathlib.Path(args.data)

    portfolios, reports = read_inputs(data_dir)
    tickers = {BENCHMARK}
    tickers |= {l["ticker"] for p in portfolios for l in p["lots"]}
    tickers |= {str(r.get("ticker", "")).strip().upper() for r in reports if r.get("ticker")}
    one_year_ago = pd.Timestamp(dt.date.today()) - pd.DateOffset(years=1, days=10)
    earliest = min([one_year_ago] + [p["start"] for p in portfolios]
                   + [l["buy_date"] for p in portfolios for l in p["lots"]])

    close, meta = (mock_market if args.mock else fetch_market)(tickers, earliest)
    if args.mock:  # line fake prices up with the first buy price so test output looks sane
        for p in portfolios:
            for l in sorted(p["lots"], key=lambda l: l["buy_date"]):
                s = close[l["ticker"]]
                at = s[s.index <= l["buy_date"]]
                if len(at) and not getattr(close, "_scaled_" + l["ticker"], False):
                    close[l["ticker"]] = s * (l["buy_price"] / at.iloc[-1])
                    setattr(close, "_scaled_" + l["ticker"], True)
    missing = [t for t in tickers if t not in close or close[t].dropna().empty]
    if BENCHMARK in missing:
        sys.exit("ERROR: no S&P 500 (SPY) prices came back; try again later.")
    warnings = [f"No price data for {t}. Check the ticker symbol." for t in sorted(missing)]
    bench = close[BENCHMARK].dropna()

    built = []
    for p in portfolios:
        bp = build_portfolio(p, close, bench, meta)
        bp["periods"] = period_returns(bp["series"]["dates"], bp["series"]["index"], bench)
        low, low_day = bp.pop("min_cash")
        if low < -0.5:
            warnings.append(f"{bp['name']}: cash drops below zero (${low:,.2f}) on {low_day}. "
                            "Add the deposit that paid for that purchase under cash_flows.")
        built.append(bp)

    snapshot = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "prices_as_of": bench.index[-1].date().isoformat(),
        "mock": args.mock,
        "benchmark": {"ticker": BENCHMARK, "name": BENCHMARK_NAME,
                      "dates": [d.date().isoformat() for d in bench.index],
                      "close": list(bench.values)},
        "portfolios": built,
        "reports": build_reports(reports, close, meta),
        "warnings": warnings,
    }
    (data_dir / "snapshot.json").write_text(json.dumps(clean(snapshot), indent=1), encoding="utf-8")
    print(f"Wrote snapshot: {len(built)} portfolio(s), {len(snapshot['reports'])} report(s), "
          f"prices as of {snapshot['prices_as_of']}")
    for w in warnings:
        print("WARNING:", w)


if __name__ == "__main__":
    main()
