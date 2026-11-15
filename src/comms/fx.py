from __future__ import annotations

from comms.config import CurrencyConfig


def to_usd(amount: int | float | None, currency: str, config: CurrencyConfig) -> float | None:
    if amount is None:
        return None
    code = (currency or "").upper()
    if code == "USD":
        rate = config.usd_per_usd
    elif code == "JPY":
        rate = config.usd_per_jpy
    elif code == "KRW":
        rate = config.usd_per_krw
    else:
        return None
    return round(float(amount) * rate, 4)
