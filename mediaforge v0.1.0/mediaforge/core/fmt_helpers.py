def fmt_mb(n: int) -> str:
    """Bytes -> '12.3 MB' (for download progress text)."""
    return f"{n / (1024 * 1024):.1f} MB"
