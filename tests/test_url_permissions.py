"""Toda vista del panel debe declarar su control de acceso (US-5)."""

from django.urls import URLPattern, URLResolver, get_resolver

# Prefijos fuera del panel: admin de Django (solo superusuarios), health, webhooks (firma del canal).
EXCLUDED_NAMESPACES = {"admin", "hooks", "tn_privacy"}
EXCLUDED_NAMES = {"health"}
# M8: la tienda mayorista tiene su propio control (StoreAccessMixin = "store"; ingreso, registro,
# recuperación y legales = "store_public").
VALID_ACCESS = {"login", "permission", "public", "webhook", "store", "store_public"}


def iter_patterns(patterns, namespace=None):
    for p in patterns:
        if isinstance(p, URLResolver):
            ns = p.namespace or namespace
            if ns in EXCLUDED_NAMESPACES:
                continue
            yield from iter_patterns(p.url_patterns, ns)
        elif isinstance(p, URLPattern):
            yield namespace, p


def test_every_panel_view_declares_access():
    missing = []
    for namespace, pattern in iter_patterns(get_resolver().url_patterns):
        if pattern.name in EXCLUDED_NAMES:
            continue
        view = getattr(pattern.callback, "view_class", None)
        access = getattr(view, "panel_access", None)
        if access not in VALID_ACCESS:
            missing.append(f"{namespace}:{pattern.name}")
            continue
        if access == "permission" and not getattr(view, "permission_required", None):
            missing.append(f"{namespace}:{pattern.name} (sin permission_required)")
    assert not missing, f"Vistas sin control de acceso declarado: {missing}"


def test_public_views_are_only_auth_screens():
    public = {
        f"{ns}:{p.name}"
        for ns, p in iter_patterns(get_resolver().url_patterns)
        if getattr(getattr(p.callback, "view_class", None), "panel_access", None) == "public"
    }
    assert public <= {
        "accounts:login",
        "accounts:logout",
        "accounts:password_reset",
        "accounts:password_reset_done",
        "accounts:password_reset_confirm",
        "accounts:password_reset_complete",
    }


def test_store_public_views_are_only_auth_and_legal_screens():
    """M8: sin sesión, la tienda muestra solo ingreso, registro, recuperación de contraseña y legales."""
    public = {
        f"{ns}:{p.name}"
        for ns, p in iter_patterns(get_resolver().url_patterns)
        if getattr(getattr(p.callback, "view_class", None), "panel_access", None) == "store_public"
    }
    assert public == {
        "store:login",
        "store:logout",
        "store:register",
        "store:register_done",
        "store:invitation",
        "store:invitation_request",
        "store:invitation_request_done",
        "store:pending",
        "store:password_reset",
        "store:password_reset_done",
        "store:password_reset_confirm",
        "store:password_reset_complete",
        "store:terms",
        "store:privacy",
    }
