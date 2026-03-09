import re
from typing import Any, Dict, List, Optional


NUM_RE = re.compile(r"^-?\d+(?:\.\d+)?$")
EXP_RE = re.compile(r"^(?:\d{1,2}[/-]\d{2,4}|\d{2,4}[/-]\d{1,2})$")
STOP_WORDS = {"note", "subtotal", "gst", "net", "t.rates", "total", "less", "rounding", "amount in words"}


def _to_float(token: str) -> Optional[float]:
    token = token.replace(",", "").strip()
    return float(token) if NUM_RE.match(token) else None


def _extract_totals(text: str) -> Dict[str, float]:
    totals: Dict[str, float] = {}
    patterns = {
        "subtotal": r"(?:Sub\s*Total|SubTotal)\s*[:\-]?\s*(-?\d+(?:\.\d+)?)",
        "gst_amount": r"(?:GST\s*Amt|GST\s*Amount)\s*[:\-]?\s*(-?\d+(?:\.\d+)?)",
        "net_payable": r"(?:NET\s*PAYABLE|Net\s*Payable)\s*[:\-]?\s*(-?\d+(?:\.\d+)?)",
    }
    for key, pattern in patterns.items():
        m = re.search(pattern, text, flags=re.IGNORECASE)
        if m:
            totals[key] = float(m.group(1))
    return totals


def _extract_gst_summary(lines: List[str]) -> Dict[str, Dict[str, float]]:
    gst_summary: Dict[str, Dict[str, float]] = {}
    for line in lines:
        m = re.search(
            r"(\d{1,2}%)\s*[:\-]?\s*(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)",
            line,
        )
        if m:
            gst_summary[m.group(1)] = {
                "taxable_value": float(m.group(2)),
                "cgst": float(m.group(3)),
                "sgst": float(m.group(4)),
            }
    return gst_summary


def _split_pipe_table(lines: List[str]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    header = None
    for line in lines:
        if "|" not in line or "---" in line:
            continue
        parts = [p.strip() for p in line.split("|") if p.strip()]
        if not parts:
            continue
        if header is None:
            header = parts
            continue
        if header and len(parts) == len(header):
            items.append(dict(zip(header, parts)))
    return items


def _parse_row_tokens(tokens: List[str]) -> Optional[Dict[str, Any]]:
    if len(tokens) < 12:
        return None

    right = []
    idx = len(tokens) - 1
    while idx >= 0 and len(right) < 7:
        val = _to_float(tokens[idx])
        if val is None:
            return None
        right.append(val)
        idx -= 1

    if len(right) < 7 or idx < 3:
        return None

    discount, gst, mrp, amount, rate, free_qty, qty = right

    exp = tokens[idx]
    idx -= 1
    batch = tokens[idx]
    idx -= 1
    pack = tokens[idx]
    idx -= 1

    if idx < 2:
        return None

    company = tokens[0]
    hsn = tokens[1]
    product_name = " ".join(tokens[2 : idx + 1]).strip()

    if not product_name or not EXP_RE.match(exp):
        return None

    return {
        "company": company,
        "hsn": hsn,
        "product_name": product_name,
        "pack": pack,
        "batch": batch,
        "expiry": exp,
        "quantity": qty,
        "free_quantity": free_qty,
        "rate": rate,
        "amount": amount,
        "mrp": mrp,
        "gst_percent": gst,
        "discount_percent": discount,
    }


def _split_space_table(lines: List[str]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    in_table = False

    for line in lines:
        stripped = line.strip()
        low = stripped.lower()

        if not stripped:
            if in_table and items:
                break
            continue

        if not in_table and (("product name" in low and "qty" in low) or ("mfg" in low and "hsn" in low and "amount" in low)):
            in_table = True
            continue

        if not in_table:
            continue

        if any(low.startswith(w) for w in STOP_WORDS):
            break

        row = _parse_row_tokens(stripped.split())
        if row:
            items.append(row)

    return items


def _parse_compact_rows(lines: List[str]) -> List[Dict[str, Any]]:
    """Fallback for OCR where header and rows are not perfectly aligned."""
    items: List[Dict[str, Any]] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or any(stripped.lower().startswith(w) for w in STOP_WORDS):
            continue
        tokens = stripped.split()
        # compact row usually starts with company+hsn and ends with 6-7 numerics
        if len(tokens) >= 12 and _to_float(tokens[-1]) is not None and _to_float(tokens[-2]) is not None:
            row = _parse_row_tokens(tokens)
            if row:
                items.append(row)
    return items


def parse_markdown_input(text: str) -> Dict[str, Any]:
    lines = [ln.rstrip() for ln in text.splitlines()]

    items = _split_pipe_table(lines)
    if not items:
        items = _split_space_table(lines)
    if not items:
        items = _parse_compact_rows(lines)

    gst_summary = _extract_gst_summary(lines)
    totals = _extract_totals(text)

    return {"items": items, "gst_summary": gst_summary, "totals": totals}
