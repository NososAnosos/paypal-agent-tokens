"""Exact money handling (REVIEW P1-7). Never floats; never implicit currency."""
from decimal import Decimal, InvalidOperation

CURRENCIES = {"USD"}  # TODO: widen only with explicit per-currency tests


def parse_amount(value, currency: str) -> Decimal:
    if currency not in CURRENCIES:
        raise ValueError(f"unsupported currency {currency!r}")
    if isinstance(value, float):
        raise ValueError("float amounts are rejected; pass a string")
    try:
        d = Decimal(str(value))
    except InvalidOperation:
        raise ValueError(f"bad amount {value!r}") from None
    if not d.is_finite() or d <= 0 or d != d.quantize(Decimal("0.01")):
        raise ValueError(f"amount must be positive with at most 2 decimals: {value!r}")
    return d.quantize(Decimal("0.01"))
