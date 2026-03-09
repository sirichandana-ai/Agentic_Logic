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


def _to_float(token: str) -> Optional[float]:
    token = token.replace(",", "").strip()
    return float(token) if NUM_RE.match(token) else None


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
        parts = [p.strip() for p in line.split("|") if p.strip()]
        if not parts:
            continue
        if header is None:
            header = parts
            continue
        if header and len(parts) == len(header):
            items.append(dict(zip(header, parts)))
    return items


def _parse_generic_row(tokens: List[str]) -> Optional[Dict[str, Any]]:
    if len(tokens) < 10:
        return None

    numeric = _numeric_tail(tokens)
    if len(numeric) < 6:
        return None

    # Map from right: qty, free, rate, amount, mrp, gst, [discount]
    discount = numeric[-1] if len(numeric) >= 7 else 0.0
    gst = numeric[-2] if len(numeric) >= 6 else 0.0
    mrp = numeric[-3] if len(numeric) >= 5 else 0.0
    amount = numeric[-4] if len(numeric) >= 4 else 0.0
    rate = numeric[-5] if len(numeric) >= 3 else 0.0
    free_qty = numeric[-6] if len(numeric) >= 2 else 0.0
    qty = numeric[-7] if len(numeric) >= 7 else numeric[0]

    head = tokens[: len(tokens) - len(numeric)]
    if len(head) < 4:
        return None

    exp_idx = next((i for i, t in enumerate(head) if EXP_RE.match(t)), None)
    if exp_idx is None or exp_idx < 2:
        return None

    expiry = head[exp_idx]
    batch = head[exp_idx - 1]
    pack = head[exp_idx - 2]

    # HSN can appear anywhere before pack/expiry in broken OCR lines.
    hsn = None
    for t in head[: exp_idx - 1]:
        if HSN_RE.match(t):
            hsn = t
            break

    company = head[0]

    filtered: List[str] = []
    for i, tok in enumerate(head[: exp_idx - 2]):
        if i == 0:
            continue
        if tok == hsn:
            continue
        filtered.append(tok)

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
        low = line.lower()
        if not line or any(low.startswith(w) for w in STOP_WORDS):
            i += 1
            continue
        if "product name" in low and "amount" in low:
            i += 1
            continue

        toks = line.split()
        nums = _numeric_tail(toks)
        has_exp = any(EXP_RE.match(t) for t in toks)

        if len(nums) >= 6 and has_exp:
            row = _parse_generic_row(toks)
            if row:
                # OCR often puts HSN/product tail on next line: "30059098 15CM"
                if i + 1 < len(lines):
                    nxt = lines[i + 1].strip()
                    nxt_toks = nxt.split()
                    if nxt_toks and HSN_RE.match(nxt_toks[0]) and (len(nxt_toks) == 1 or len(_numeric_tail(nxt_toks)) == 0):
                        if not row.get("hsn"):
                            row["hsn"] = nxt_toks[0]
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
