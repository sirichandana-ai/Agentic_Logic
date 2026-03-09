def is_major_difference(a, b):
    if a is None or b is None:
        return False
    diff = abs(a - b)
    if diff <= 1:
        return False
    return diff / max(abs(a), abs(b), 1) > 0.01


def aggregate_invoice(rows, provided_totals):
    flags = []

    computed_subtotal = round(sum(r.get("subtotal", {}).get("value", 0) or 0 for r in rows), 2)
    computed_gst_total = round(sum(r.get("gst_amount", {}).get("value", 0) or 0 for r in rows), 2)
    computed_total = round(computed_subtotal + computed_gst_total, 2)

    provided_subtotal = provided_totals.get("subtotal")
    provided_gst = provided_totals.get("gst_amount")
    provided_net = provided_totals.get("net_payable")

    if provided_subtotal is not None and is_major_difference(provided_subtotal, computed_subtotal):
        flags.append("Invoice subtotal auto-corrected from row totals")

    if provided_gst is not None and is_major_difference(provided_gst, computed_gst_total):
        flags.append("Invoice GST total auto-corrected from row totals")

    if provided_net is not None and is_major_difference(provided_net, computed_total):
        flags.append("Invoice total auto-corrected from subtotal + GST")

    return {
        "invoice_subtotal": computed_subtotal,
        "invoice_gst_total": computed_gst_total,
        "invoice_total": computed_total,
        "flags": flags,
    }
