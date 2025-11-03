# core/utils.py

from .models import (
    Sucursal,
    Bodega,
    UbicacionSucursal,
    UbicacionBodega,
)


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
