ALIASES = {
    "hsn": ["hsn", "hsncode", "hsnno"],
    "product_name": ["product", "productname", "item", "description", "descrption", "medicine"],
    "company": ["mfg", "manufacturer", "company", "brand"],
    "batch": ["batch", "batchno", "batchnumber"],
    "expiry": ["exp", "expiry", "expdate", "expirydate"],
    "pack": ["pack", "packing", "size"],
    "barcode": ["barcode", "bar_code"],
    "code": ["code", "itemcode"],
    "quantity": ["quantity", "qty", "qnty", "quantty", "units", "pcs"],
    "free_quantity": ["free", "freeqty", "freequantity", "bonus"],
    "rate": ["rate", "price", "unitrate", "unitprice"],
    "amount": ["amount", "total", "taxablevalue", "value"],
    "mrp": ["mrp", "mrpprice"],
    "gst_percent": ["gst", "gstpercent", "gst%", "tax", "tax%"],
    "discount_percent": ["discount", "discountpercent", "disc", "disc%"],
    "cgst": ["cgst"],
    "sgst": ["sgst"],
    "igst": ["igst"],
}

CANONICAL_FIELDS = list(ALIASES.keys())
