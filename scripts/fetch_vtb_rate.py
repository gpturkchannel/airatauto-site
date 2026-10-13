#!/usr/bin/env python3
"""
Курс ВТБ CNY/RUB для airatauto.ru.

Источник: открытый JSON-API сайта ВТБ (тот же, что рисует таблицу на
vtb.ru/personal/platezhi-i-perevody/obmen-valjuty/):
  категория 3 = «В ВТБ Онлайн (и в офисе безналично)»,
  строка «до 500 000 ¥», колонка «Продаем» (offer) — по этому курсу клиент
  покупает юани.

Пишет rates.json только если курс получен и выглядит правдоподобно.
Запускается GitHub Actions каждый час.
"""
import json
import sys
import time
from datetime import datetime, timezone

import requests

API = "https://siteapi.vtb.ru/api/currencyrates/table/optimized"
CATEGORY = 3          # ВТБ Онлайн (и в офисе безналично)
TIER = "до 500000"    # тариф «до 500 000 ¥»
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Referer": "https://www.vtb.ru/personal/platezhi-i-perevody/obmen-valjuty/",
}


def fetch():
    last = None
    for attempt in range(3):
        try:
            r = requests.get(API, params={"category": CATEGORY, "type": 1},
                             headers=HEADERS, timeout=30, verify=False)
            r.raise_for_status()
            d = r.json()
            rows = [x for x in d.get("rates", [])
                    if x.get("currency1", {}).get("code") == "CNY"
                    and x.get("currency2", {}).get("code") == "RUB"]
            row = next((x for x in rows if TIER in (x.get("tooltip") or "")), None)
            if not row:
                raise ValueError(f"нет строки {TIER!r}: {[x.get('tooltip') for x in rows]}")
            scale = row.get("scale") or 1
            offer = round(float(row["offer"]) / scale, 4)
            bid = round(float(row["bid"]) / scale, 4)
            return offer, bid, d.get("dateFrom")
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(5)
    print(f"VTB API error: {last}", file=sys.stderr)
    return None, None, None


def main():
    try:
        import urllib3
        urllib3.disable_warnings()
    except Exception:
        pass

    offer, bid, vtb_time = fetch()
    if not offer or not (8 < offer < 25):
        print(f"Курс не получен или неправдоподобен ({offer}) — rates.json не трогаю",
              file=sys.stderr)
        sys.exit(0)

    try:
        with open("rates.json", encoding="utf-8") as f:
            rates = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        rates = {}

    old = (rates.get("vtb_cny") or {})
    rates["vtb_cny"] = {
        "offer": offer,
        "bid": bid,
        "vtb_time": vtb_time,
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "vtb-online-500k",
    }
    with open("rates.json", "w", encoding="utf-8") as f:
        json.dump(rates, f, ensure_ascii=False, indent=2)
    print(f"✓ ВТБ CNY offer={offer} bid={bid} (ВТБ {vtb_time}); было {old.get('offer')}")


if __name__ == "__main__":
    main()
