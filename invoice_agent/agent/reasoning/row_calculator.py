from datetime import datetime

ALLOWED_GST_SLABS = [5.0, 12.0, 18.0, 28.0]


def is_major_difference(a, b):
    if a is None or b is None:
        return False
    diff = abs(a - b)
    if diff <= 1:
        return False
    return diff / max(abs(a), abs(b), 1) > 0.01


def _parse_expiry(expiry):
    if not expiry or not isinstance(expiry, str):
        return None

    value = expiry.strip()
    patterns = ["%m/%y", "%m/%Y", "%m-%y", "%m-%Y", "%y/%m", "%Y/%m"]
    for p in patterns:
        try:
            dt = datetime.strptime(value, p)
            if p in {"%y/%m", "%Y/%m"}:
                dt = datetime(year=dt.year, month=int(value.split("/")[1]), day=1)
            return dt
        except ValueError:
            continue
    return None


def _nearest_gst_slab(gst: float) -> float:
    return min(ALLOWED_GST_SLABS, key=lambda s: abs(s - gst))


def calculate_row(normalized_row: dict):
    flags = []

    def safe_float(value):
        try:
            if value is None:
                return None
            return float(value)
        except Exception:
            return None

    qty = safe_float(normalized_row["quantity"]["value"])
    rate = safe_float(normalized_row["rate"]["value"])
    gst_percent = safe_float(normalized_row["gst_percent"]["value"])
    discount = safe_float(normalized_row["discount_percent"]["value"]) or 0.0
    provided_amount = safe_float(normalized_row["amount"]["value"])
    mrp = safe_float(normalized_row["mrp"]["value"])

    if qty is None and rate not in (None, 0) and provided_amount is not None:
        qty = round(provided_amount / rate, 4)
        normalized_row["quantity"] = {"value": qty, "confidence": 0.7}
        flags.append("Quantity inferred from amount / rate")

    if rate is None and qty not in (None, 0) and provided_amount is not None:
        rate = round(provided_amount / qty, 4)
        normalized_row["rate"] = {"value": rate, "confidence": 0.7}
        flags.append("Rate inferred from amount / quantity")

    if qty is None:
        qty = 0.0
        flags.append("Missing quantity")
    if rate is None:
        rate = 0.0
        flags.append("Missing rate")

    if qty < 0:
        qty = abs(qty)
        normalized_row["quantity"] = {"value": qty, "confidence": 0.5}
        flags.append("Negative quantity corrected to absolute value")

    gst_summary = normalized_row.get("_gst_summary", {})

    if gst_percent is None:
        buckets = [k for k, v in gst_summary.items() if v.get("taxable_value", 0) > 0]
        if len(buckets) == 1:
            gst_percent = float(buckets[0].replace("%", ""))
            normalized_row["gst_percent"] = {"value": gst_percent, "confidence": 0.8}
            flags.append("GST inferred from summary bucket")
        else:
            gst_percent = 0.0
            flags.append("Missing GST percent")

    # enforce allowed GST slabs: 5/12/18/28
    if gst_percent not in ALLOWED_GST_SLABS:
        snapped = _nearest_gst_slab(gst_percent)
        if abs(snapped - gst_percent) > 0.001:
            flags.append(f"GST percent normalized from {gst_percent} to {snapped}")
        gst_percent = snapped
        normalized_row["gst_percent"] = {"value": gst_percent, "confidence": 0.7}

    if discount < 0:
        discount = 0.0
        normalized_row["discount_percent"] = {"value": discount, "confidence": 0.5}
        flags.append("Negative discount corrected to 0")

    subtotal = round(qty * rate, 2)

    if provided_amount is not None and is_major_difference(subtotal, provided_amount):
        qty_conf = normalized_row["quantity"].get("confidence", 0.0)
        rate_conf = normalized_row["rate"].get("confidence", 0.0)
        if qty_conf < rate_conf and rate != 0:
            qty = round(provided_amount / rate, 4)
            normalized_row["quantity"] = {"value": qty, "confidence": 0.6}
            subtotal = round(qty * rate, 2)
            flags.append("Quantity auto-corrected from amount / rate")
        else:
            normalized_row["amount"] = {"value": subtotal, "confidence": 0.6}
            flags.append("Amount auto-corrected from quantity × rate")

    # validate GST bucket against summary per row
    bucket = f"{int(gst_percent)}%"
    if gst_summary and bucket not in gst_summary:
        active = [k for k, v in gst_summary.items() if v.get("taxable_value", 0) > 0]
        if len(active) == 1:
            gst_percent = float(active[0].replace("%", ""))
            normalized_row["gst_percent"] = {"value": gst_percent, "confidence": 0.6}
            flags.append("GST percent aligned to active summary bucket")
            bucket = active[0]
        else:
            flags.append("GST bucket not found in summary")

    gst_amount = round(subtotal * gst_percent / 100, 2)

    if gst_percent > 0:
        cgst = round(subtotal * (gst_percent / 2) / 100, 2)
        sgst = round(subtotal * (gst_percent / 2) / 100, 2)
    else:
        cgst = 0.0
        sgst = 0.0

    row_total = round(subtotal + gst_amount - discount, 2)

    exp = normalized_row.get("expiry", {}).get("value")
    parsed_exp = _parse_expiry(exp)
    if exp and parsed_exp is None:
        flags.append("Invalid expiry format")

    if mrp is not None and rate is not None and mrp > 0 and rate > mrp * 1.2:
        flags.append("Rate significantly higher than MRP")

    if qty == 0 and subtotal > 0:
        flags.append("Subtotal present but quantity is zero")

    normalized_row["subtotal"] = {"value": subtotal, "confidence": 1.0}
    normalized_row["gst_amount"] = {"value": gst_amount, "confidence": 1.0}
    normalized_row["cgst"] = {"value": cgst, "confidence": 1.0}
    normalized_row["sgst"] = {"value": sgst, "confidence": 1.0}
    normalized_row["row_total"] = {"value": row_total, "confidence": 1.0}

    return normalized_row, flags
