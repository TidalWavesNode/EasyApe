from __future__ import annotations

def fmt_amount(x: float) -> str:
    # Keep btcli-friendly formatting.
    # Avoid scientific notation.
    s = f"{x:.8f}".rstrip("0").rstrip(".")
    return s if s else "0"
