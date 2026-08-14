import json
from decimal import Decimal

from django import template


register = template.Library()


@register.filter
def vnd(value):
    try:
        return f"{Decimal(value):,.0f}".replace(",", ".") + " ₫"
    except (TypeError, ValueError):
        return "0 ₫"


@register.filter
def json_pretty(value):
    return json.dumps(value, ensure_ascii=False, indent=2)


@register.filter
def get_item(mapping, key):
    return mapping.get(key, "") if mapping else ""

