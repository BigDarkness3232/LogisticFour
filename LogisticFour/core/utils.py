# core/utils.py

from .models import (
    Sucursal,
    Bodega,
    UbicacionSucursal,
    UbicacionBodega,
)
from django.conf import settings
from django.contrib.auth import get_user_model

def ensure_ubicacion_sucursal(sucursal: Sucursal) -> UbicacionSucursal:
    """
    Devuelve la primera ubicación de la sucursal.
    Si no tiene, crea una ubicación predefinida.
    """
    ubi = sucursal.ubicaciones.first()
    if ubi:
        return ubi

    # crea la ubicación DEFAULT para esa sucursal
    return UbicacionSucursal.objects.create(
        sucursal=sucursal,
        nombre="GENERAL",
        codigo=f"SUC-{sucursal.id}-GEN",
    )


def ensure_ubicacion_bodega(bodega: Bodega) -> UbicacionBodega:
    """
    Devuelve la primera ubicación de la bodega.
    Si no tiene, crea una ubicación predefinida.
    """
    ubi = bodega.ubicaciones.first()
    if ubi:
        return ubi

    return UbicacionBodega.objects.create(
        bodega=bodega,
        nombre="GENERAL",
        codigo=f"BOD-{bodega.id}-GEN",
    )




def get_bodeguero_emails():
    """
    Devuelve emails de usuarios activos cuyo perfil tenga rol='bodeguero'.
    Asume relación OneToOne/ForeignKey con related_name='perfil' (ajusta si difiere).
    Fallback: ADMINS -> DEFAULT_FROM_EMAIL -> [].
    """
    User = get_user_model()

    # Cambia 'perfil__rol' si tu related_name o campo es distinto (p.ej. 'perfilusuario__rol')
    qs = (
        User.objects.filter(is_active=True)
        .filter(perfil__rol="bodeguero")
        .exclude(email__isnull=True)
        .exclude(email__exact="")
        .values_list("email", flat=True)
        .distinct()
    )
    emails = [e.strip() for e in qs if e and e.strip()]

    if emails:
        return emails

    # Fallbacks seguros si no hay bodegueros configurados
    if getattr(settings, "ADMINS", None):
        return [email for _, email in settings.ADMINS if email]

    if getattr(settings, "DEFAULT_FROM_EMAIL", None):
        return [settings.DEFAULT_FROM_EMAIL]

    return []