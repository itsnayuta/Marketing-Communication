def ui_shell(request):
    """Return only the replaceable content shell for HTMX navigation."""
    is_htmx = request.headers.get("HX-Request") == "true"
    return {"base_template": "partial_base.html" if is_htmx else "base.html"}

