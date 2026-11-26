# Portfolio Hub

A dashboard of your portfolios that updates itself with market prices. It runs on GitHub for free and is viewable by anyone you send the link to.

**Your site's address will be:** `https://YOUR-USERNAME.github.io/portfolio-hub/`

---

## Setup (about 10 minutes, all in the browser)

### 1. Show the hidden `.github` folder
The `.github` folder holds the part that updates the prices, and your computer hides it by default.
- **Mac:** open the unzipped `portfolio-hub` folder in Finder and press **Cmd + Shift + .** (period)
- **Windows:** File Explorer → **View → Show → Hidden items**

### 2. Create the repository
1. On github.com, click **+** (top right) → **New repository**
2. Name it exactly `portfolio-hub`
3. Select **Public** (GitHub Pages is only free for public repositories)
4. Leave everything else unchecked → **Create repository**

### 3. Upload the files
1. On the new repository page, click **uploading an existing file**
2. Open the unzipped `portfolio-hub` folder, select **everything inside it** (including `.github`), and drag it into the browser
3. When the upload finishes, click **Commit changes**
4. Check that `.github` appears in the file list. If it doesn't, click **Add file → Upload files** and drag in the `.github` folder on its own.

### 4. Turn on the website (one setting)
**Settings** tab → **Pages** (left menu) → under **Build and deployment**, set **Source** to **GitHub Actions**.

### 5. Run it for the first time
**Actions** tab → **Update prices and publish site** (left) → **Run workflow** → green **Run workflow** button.
After about 2 minutes, a green check means it worked. Open `https://YOUR-USERNAME.github.io/portfolio-hub/`.

(A run may have already failed when you uploaded the files, because the website wasn't turned on yet. That's expected. Just run it again as described above.)

---

## Adding your investments

Edit `data/portfolios.json` on GitHub: click the file → pencil icon → edit → **Commit changes**. The site rebuilds about 2 minutes after you save.

```json
{
  "portfolios": [
    {
      "name": "Long-term",
      "description": "Optional one-line description",
      "start_date": "2025-01-02",
      "cash": 1200,
      "positions": [
        { "ticker": "AAPL", "shares": 10, "buy_price": 182.50, "buy_date": "2025-01-02" },
        { "ticker": "XOM",  "shares": 20, "buy_price": 104.00, "buy_date": "2025-02-03",
          "sell_price": 118.20, "sell_date": "2025-10-01" }
      ]
    }
  ]
}
```

- **One line per purchase.** If you bought the same stock twice, add two lines.
- **Selling:** add `sell_price` and `sell_date` to that line. To sell part of a position, split it into two lines and mark only one as sold.
- **Dates** are written `YYYY-MM-DD`. **Tickers** use Yahoo Finance symbols (for example `BRK-B`, not `BRK.B`).
- `start_date` is optional. It's the date returns are measured from, and it defaults to your first purchase.
- `cash` is the uninvested cash you hold now.
- Add more portfolios by adding more `{ ... }` blocks, separated by commas. Each portfolio gets its own tab.
- `data/portfolios.example.json` is a full example.

If the site stops updating after an edit, open the **Actions** tab and click the failed run (red X). The error message names the file and line that has the problem, usually a missing comma or quote.

## Adding research reports

1. Open the `reports` folder → **Add file → Upload files** → upload your PDF → **Commit changes**
2. Edit `data/reports.json` and add an entry:

```json
{
  "reports": [
    {
      "ticker": "AAPL",
      "title": "Apple: services carry the multiple",
      "date": "2025-06-01",
      "rating": "Buy",
      "target": 240,
      "summary": "One or two sentences on the thesis.",
      "file": "reports/apple-initiation.pdf"
    }
  ]
}
```

The card shows today's price, the upside to your target, and how the stock has moved since the report date.

---

## Good to know

- **Update schedule:** once an hour while the US market is open (Mon–Fri), once after the close, and whenever you edit a file. GitHub sometimes starts scheduled runs a few minutes late.
- **Prices** come from Yahoo Finance and are delayed about 15 minutes during the day.
- **Returns** are time-weighted, so adding new money doesn't count as a gain. They're price returns and don't include dividends. They're compared with SPY, an ETF that tracks the S&P 500.
- **Everything in this repository is public,** including `portfolios.json` (share counts and prices paid). Only list what you're comfortable showing.
- **Keep it active:** GitHub pauses scheduled updates in a public repository after 60 days with no commits, and emails you when it does. Any edit (even to this README) restarts the 60 days. If it gets paused, go to **Actions** → **Update prices and publish site** → **Enable workflow**.
- **Run it on demand:** Actions → Update prices and publish site → Run workflow.
- This site is for record-keeping only and isn't investment advice.
