#!/usr/bin/env python3
"""
Fetch CNY/RUB rate from VTB or CBR fallback.
Updates rates.json in the repo root.
Runs in GitHub Actions every hour.
"""
import requests
import json
import re
import sys
from datetime import datetime, timezone

try:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except Exception:
    pass


HEADERS = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept-Language': 'ru-RU,ru;q=0.9,en;q=0.8',
}


def fetch_vtb_cny():
    """Try to get VTB CNY commercial rate (до 500 000 ¥, ВТБ Онлайн)."""
    # VTB uses Next.js — try to find embedded __NEXT_DATA__ with rates
    try:
        r = requests.get(
            'https://www.vtb.ru/personal/platezhi-i-perevody/obmen-valjuty/',
            headers=HEADERS,
            verify=False,
            timeout=30,
        )
        text = r.text

        # Look for __NEXT_DATA__ JSON blob
        match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(\{.+?\})</script>', text, re.DOTALL)
        if match:
            data = json.loads(match.group(1))
            # Recursively search for CNY offer rate
            offer, bid = _find_cny_in_dict(data)
            if offer:
                return offer, bid, 'vtb-web'

        # Try to find rates in any JSON-like block
        for m in re.finditer(r'"CNY"[^}]{0,300}"sell"\s*:\s*([\d.]+)', text):
            offer = float(m.group(1))
            if 8 < offer < 20:
                return offer, None, 'vtb-html'

    except Exception as e:
        print(f"VTB fetch error: {e}", file=sys.stderr)

    return None, None, None


def _find_cny_in_dict(obj, depth=0):
    """Recursively search for CNY sell/buy rates in a nested dict."""
    if depth > 15:
        return None, None
    if isinstance(obj, dict):
        # Check if this node looks like a currency rate entry
        code = obj.get('code') or obj.get('charCode') or obj.get('currency', '')
        if str(code).upper() == 'CNY':
            sell = obj.get('sell') or obj.get('offer') or obj.get('saleRate')
            buy = obj.get('buy') or obj.get('bid') or obj.get('purchaseRate')
            if sell:
                try:
                    return float(sell), float(buy) if buy else None
                except (TypeError, ValueError):
                    pass
        for v in obj.values():
            result = _find_cny_in_dict(v, depth + 1)
            if result[0]:
                return result
    elif isinstance(obj, list):
        for item in obj:
            result = _find_cny_in_dict(item, depth + 1)
            if result[0]:
                return result
    return None, None


def fetch_cbr_cny():
    """Fetch CNY rate from Central Bank of Russia (official, updates daily ~11:30 MSK)."""
    try:
        r = requests.get(
            'https://www.cbr.ru/scripts/XML_daily.asp',
            headers=HEADERS,
            timeout=30,
        )
        import xml.etree.ElementTree as ET
        root = ET.fromstring(r.content)
        for valute in root.findall('Valute'):
            if valute.find('CharCode').text == 'CNY':
                nominal = int(valute.find('Nominal').text)
                value = float(valute.find('Value').text.replace(',', '.'))
                rate = round(value / nominal, 4)
                return rate, None, 'cbr'
    except Exception as e:
        print(f"CBR fetch error: {e}", file=sys.stderr)
    return None, None, None


def main():
    print("Fetching CNY/RUB rate...")

    # Try VTB first
    offer, bid, source = fetch_vtb_cny()
    if offer:
        print(f"✓ VTB rate: offer={offer}, bid={bid} (source: {source})")
    else:
        print("VTB not available, trying CBR...", file=sys.stderr)
        offer, bid, source = fetch_cbr_cny()
        if offer:
            print(f"✓ CBR rate: {offer} (official, updates daily)")
        else:
            print("ERROR: Could not fetch rate from any source!", file=sys.stderr)
            sys.exit(1)

    now = datetime.now(timezone.utc)
    fetched_at = now.strftime('%Y-%m-%dT%H:%M:%S')

    # Estimate bid if not available (CBR doesn't have bid/offer split)
    if bid is None:
        bid = round(offer * 0.978, 4)

    # Update rates.json (repo root)
    rates_path = 'rates.json'
    try:
        with open(rates_path, 'r', encoding='utf-8') as f:
            rates = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        rates = {}

    rates['vtb_cny'] = {
        'offer': offer,
        'bid': bid,
        'fetched_at': fetched_at,
        'source': source,
    }

    with open(rates_path, 'w', encoding='utf-8') as f:
        json.dump(rates, f, ensure_ascii=False, indent=2)

    print(f"✓ Updated {rates_path}: CNY offer={offer}, source={source}")


if __name__ == '__main__':
    main()
