import re
from typing import Any, Dict, List, Optional


NUM_RE = re.compile(r"^-?\d+(?:\.\d+)?$")
EXP_RE = re.compile(r"^(?:\d{1,2}[/-]\d{2,4}|\d{2,4}[/-]\d{1,2})$")
HSN_RE = re.compile(r"^\d{4,8}$")
STOP_WORDS = {
    "note",
    "subtotal",
    "gst",
    "net",
    "t.rates",
    "total",
    "less",
    "rounding",
    "amount in words",
}


def _clean_token(token: str) -> str:
    return token.strip().strip("|:;,")


def _to_float(token: str) -> Optional[float]:
    token = _clean_token(token).replace(",", "")
    if not NUM_RE.match(token):
        return None
    try:
        return float(token)
    except ValueError:
        return None


def _tokenize(line: str) -> List[str]:
    # Handle markdown/ocr mixed separators robustly.
    cleaned = line.replace("|", " ")
    return [_clean_token(t) for t in cleaned.split() if _clean_token(t)]


def _numeric_tail(tokens: List[str]) -> List[float]:
    vals: List[float] = []
    for t in reversed(tokens):
        val = _to_float(t)
        if val is None:
            break
        vals.append(val)
    return list(reversed(vals))


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
        parts = [_clean_token(p) for p in line.split("|") if _clean_token(p)]
        if not parts:
            continue
        if header is None:
            header = parts
            continue
        if header and len(parts) == len(header):
            items.append(dict(zip(header, parts)))
    return items


def _parse_generic_row(tokens: List[str]) -> Optional[Dict[str, Any]]:
    if len(tokens) < 8:
        return None

    numeric = _numeric_tail(tokens)
    if len(numeric) < 5:
        return None

    # Prefer 7-number tail (qty,free,rate,amount,mrp,gst,discount), fallback gracefully.
    if len(numeric) >= 7:
        qty, free_qty, rate, amount, mrp, gst, discount = numeric[-7:]
    elif len(numeric) == 6:
        qty, free_qty, rate, amount, mrp, gst = numeric
        discount = 0.0
    else:  # len == 5 (rare OCR omission)
        qty, rate, amount, mrp, gst = numeric
        free_qty, discount = 0.0, 0.0

    head = tokens[: len(tokens) - len(numeric)]
    if len(head) < 4:
        return None

    exp_idx = next((i for i, t in enumerate(head) if EXP_RE.match(_clean_token(t))), None)
    if exp_idx is None or exp_idx < 2:
        return None

    expiry = _clean_token(head[exp_idx])
    batch = _clean_token(head[exp_idx - 1])
    pack = _clean_token(head[exp_idx - 2])

    hsn = None
    for t in head[: exp_idx - 1]:
        ct = _clean_token(t)
        if HSN_RE.match(ct):
            hsn = ct
            break

    company = _clean_token(head[0])

    filtered: List[str] = []
    for i, tok in enumerate(head[: exp_idx - 2]):
        ct = _clean_token(tok)
        if i == 0:
            continue
        if ct == hsn:
            continue
        filtered.append(ct)

    product_name = " ".join(filtered).strip()
    if not product_name:
        return None

    return {
        "company": company,
        "hsn": hsn,
        "product_name": product_name,
        "pack": pack,
        "batch": batch,
        "expiry": expiry,
        "quantity": qty,
        "free_quantity": free_qty,
        "rate": rate,
        "amount": amount,
        "mrp": mrp,
        "gst_percent": gst,
        "discount_percent": discount,
    }


def _split_ocr_table(lines: List[str]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        low = line.lower().strip("| ")
        if not line or any(low.startswith(w) for w in STOP_WORDS):
            i += 1
            continue
        if "product name" in low and "amount" in low:
            i += 1
            continue

        toks = _tokenize(line)
        nums = _numeric_tail(toks)
        has_exp = any(EXP_RE.match(_clean_token(t)) for t in toks)

        if len(nums) >= 5 and has_exp:
            row = _parse_generic_row(toks)
            if row:
                if i + 1 < len(lines):
                    nxt = lines[i + 1].strip()
                    nxt_toks = _tokenize(nxt)
                    if nxt_toks and HSN_RE.match(_clean_token(nxt_toks[0])) and (len(nxt_toks) == 1 or len(_numeric_tail(nxt_toks)) == 0):
                        if not row.get("hsn"):
                            row["hsn"] = _clean_token(nxt_toks[0])
                        if len(nxt_toks) > 1:
                            row["product_name"] = f"{row['product_name']} {' '.join(nxt_toks[1:])}".strip()
                        i += 1
                items.append(row)
        i += 1
    return items


def parse_markdown_input(text: str) -> Dict[str, Any]:
    lines = [ln.rstrip() for ln in text.splitlines()]

    items = _split_pipe_table(lines)
    if not items:
        items = _split_ocr_table(lines)

    gst_summary = _extract_gst_summary(lines)
    totals = _extract_totals(text)

    return {"items": items, "gst_summary": gst_summary, "totals": totals}
