from decimal import Decimal, InvalidOperation


ZERO = Decimal("0")


def decimal_value(value, *, field_name="amount") -> Decimal:
    if value is None or value == "":
        return ZERO
    if isinstance(value, Decimal):
        return value
    text = str(value).strip().replace(" ", "")
    if not text:
        return ZERO
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        parts = text.split(",")
        text = "".join(parts) if all(len(p) == 3 for p in parts[1:]) else text.replace(",", ".")
    elif text.count(".") > 1:
        text = text.replace(".", "")
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        raise ValueError(f"{field_name} không phải là số hợp lệ")


def calculate_financials(values: dict) -> dict:
    amount = lambda key: decimal_value(values.get(key, ZERO), field_name=key)
    gross = amount("gross_revenue")
    refund = amount("refund_amount")
    net = gross - refund
    result = {
        "gross_revenue": gross,
        "seller_discount": amount("seller_discount"),
        "platform_discount": amount("platform_discount"),
        "refund_amount": refund,
        "net_revenue": net,
        "platform_fee": amount("platform_fee"),
        "affiliate_commission": amount("affiliate_commission"),
        "cost_of_goods": amount("cost_of_goods"),
        "shipping_cost_seller": amount("shipping_cost_seller"),
        "other_variable_cost": amount("other_variable_cost"),
        "allocated_ad_cost": amount("allocated_ad_cost"),
    }
    result["contribution_profit"] = net - (
        result["platform_fee"]
        + result["affiliate_commission"]
        + result["cost_of_goods"]
        + result["shipping_cost_seller"]
        + result["allocated_ad_cost"]
        + result["other_variable_cost"]
    )
    return result

