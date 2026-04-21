# Hashbidder9

Hashbidder9 is a tool designed to automatically manage bidding on the [Braiins Hashpower](https://academy.braiins.com/en/braiins-hashpower/about/) market. It continuously aligns your open bids with your desired target hashrate or manual specifications using the Hashpower API.

**⚠️ WARNING: This code is experimental and should be considered unstable. We strongly recommend users to evaluate the code for bugs and security risks before use. Use at your own risk.**

## Credits

This project is a fork of and owes a big thank you to: [counterweightoperator/hashbidder](https://github.com/counterweightoperator/hashbidder).

Created with gemini-3.1-pro-preview.

## Overview

Hashbidder9 is optimized for miners at the [OCEAN Pool](https://ocean.xyz/) running their own [DATUM gateway](https://github.com/OCEAN-xyz/datum_gateway). It features:
- **Async Engine:** High-performance background daemon for bid reconciliation.
- **Live Dashboard:** Real-time visualization of hashrate, market prices, and transmission quality.
- **Hybrid Metrics:** Combines official APIs with web scraping to provide comprehensive stats (including rewards and share windows).
- **StartOS Native:** Fully packaged for StartOS with easy configuration and persistent storage.

## Installation on StartOS

1. Build or download the `hashbidder9.s9pk` package.
2. Sideload the package onto your StartOS server.
3. Start the service.

## Configuration

### 1. API Keys & Credentials
On StartOS, your primary credentials must be set via the **Actions** tab:
- Go to the Hashbidder9 service page.
- Select **Actions > Configure API Keys**.
- Enter your **Braiins Pool API Key** (Owner key is required for bidding).
- Enter your **Ocean Bitcoin Address** for monitoring pool hashrate.
- (Optional) Customize your **Mempool API URL** or **Reconciliation Interval**.

### 2. Bidding Strategy
All remaining configurations are managed directly through the built-in **Web Dashboard**:
- Open the service's Web UI.
- Navigate to the **Settings** tab.
- Choose your mode (`manual` or `target-hashrate`) and define your bidding parameters (target hashrate, upstream URL, worker identity, etc.).
- Click **Save Config** to apply changes instantly.

## Mode Details

### Target-Hashrate Mode (Recommended)
Declare a target hashrate (e.g., 5.0 PH/s) and a max number of bids. Hashbidder reads your current hashrate from Ocean, computes the deficit, picks a competitive price by undercutting the cheapest served bid on the orderbook, and manages the bids while respecting Braiins' cooldown periods.

### Manual Mode
Declare exact bids with specific prices and speed limits. Ideal for users who want total control over every open order.

---

## Developer / CLI Usage

For local development or CLI-only usage, Hashbidder requires Python >= 3.13 and `uv`.

### Local Setup
```sh
git clone https://github.com/mdubore/Hashbidder9.git
cd Hashbidder9
cp .env.example .env
# Edit .env with your credentials
```

### Common Commands
```sh
# Fetch the order book
uv run hashbidder ping

# List active bids
uv run hashbidder bids

# Manual reconciliation (Dry run)
uv run hashbidder set-bids --bid-config bids.toml --dry-run

# Start the web dashboard locally
uv run hashbidder web
```

### Tests & Quality
```sh
make check    # Run format, lint, typecheck, and tests
make test     # Run test suite only
```

## Disclaimers

Hashbidder is severely under-tested and most probably has bugs. If used against the actual Braiins Hashpower market, it will use real funds. You use Hashbidder at your own risk.
