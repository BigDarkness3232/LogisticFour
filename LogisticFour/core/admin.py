# apps/inventario/admin.py
from django import forms
from django.contrib import admin
from django.contrib.admin.widgets import AdminTextareaWidget
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone
from django.utils.html import format_html

from .models import (
    UsuarioPerfil,
    TasaImpuesto, UnidadMedida, ConversionUM, Marca, CategoriaProducto,
    Sucursal, Bodega, TipoUbicacion, Ubicacion,
    BitacoraAuditoria,
    Producto, ProductoUsuarioProveedor, LoteProducto, SerieProducto
    , TipoMovimiento, MovimientoStock,
    AjusteInventario, LineaAjusteInventario,
    RecuentoInventario, LineaRecuentoInventario,
    Reserva, PoliticaReabastecimiento,
    Transferencia, LineaTransferencia,
    DevolucionProveedor, LineaDevolucionProveedor,
    OrdenCompra, LineaOrdenCompra,
    RecepcionMercaderia, LineaRecepcionMercaderia,
    FacturaProveedor,
    ReglaAlerta, Alerta, Notificacion,
    Documento, Adjunto,
)

# === Ajustes generales del admin ===
admin.site.site_header = "Logistic — Administración"
admin.site.site_title = "Logistic Admin"
admin.site.index_title = "Panel de Control"

# === Usuario + Perfil ===
# ============== UsuarioPerfil ==============
class UsuarioPerfilAdmin(admin.ModelAdmin):
    list_display = ("usuario", "telefono", "rol")
    search_fields = ("usuario__username", "usuario__first_name", "usuario__last_name", "telefono", "rol")
    list_filter = ("rol",)

admin.site.register(UsuarioPerfil, UsuarioPerfilAdmin)


# ============== Producto ==============
class ProductoAdmin(admin.ModelAdmin):
    list_display = ("sku", "nombre", "marca", "categoria", "unidad_base", "precio", "stock", "activo")
    search_fields = ("sku", "nombre", "marca__nombre", "categoria__nombre")
    list_filter = ("activo", "marca", "categoria")

admin.site.register(Producto, ProductoAdmin)


# ============== Bodega ==============
class BodegaAdmin(admin.ModelAdmin):
    list_display = ("codigo", "nombre", "direccion", "activo")
    search_fields = ("codigo", "nombre", "direccion")
    list_filter = ("activo",)

admin.site.register(Bodega, BodegaAdmin)


# ============== Sucursal ==============
class SucursalAdmin(admin.ModelAdmin):
    list_display = ("codigo", "nombre", "direccion", "ciudad", "pais", "activo")
    search_fields = ("codigo", "nombre", "direccion", "ciudad", "pais")
    list_filter = ("activo",)

admin.site.register(Sucursal, SucursalAdmin)


class TipoUbicacionAdmin(admin.ModelAdmin):
    search_fields = ["codigo", "descripcion"]

admin.site.register(TipoUbicacion, TipoUbicacionAdmin)


# ============== Ubicacion ==============
class UbicacionAdmin(admin.ModelAdmin):
    list_display = ("codigo", "area", "tipo", "nombre", "pickeable", "almacenable")
    search_fields = ("codigo", "nombre", "area")
    list_filter = ("pickeable", "almacenable")
    autocomplete_fields = ["tipo"]

admin.site.register(Ubicacion, UbicacionAdmin)


# ============== Marca ==============
class MarcaAdmin(admin.ModelAdmin):
    list_display = ("nombre",)
    search_fields = ("nombre",)

admin.site.register(Marca, MarcaAdmin)


# ============== CategoriaProducto ==============
class CategoriaProductoAdmin(admin.ModelAdmin):
    list_display = ("nombre", "codigo", "padre")
    search_fields = ("nombre", "codigo")
    list_filter = ("padre",)

admin.site.register(CategoriaProducto, CategoriaProductoAdmin)


# ============== TasaImpuesto ==============
class TasaImpuestoAdmin(admin.ModelAdmin):
    list_display = ("nombre", "porcentaje", "activo")
    search_fields = ("nombre",)
    list_filter = ("activo",)

admin.site.register(TasaImpuesto, TasaImpuestoAdmin)


# ============== LoteProducto ==============
class LoteProductoAdmin(admin.ModelAdmin):
    list_display = ("producto", "codigo_lote", "fecha_fabricacion", "fecha_vencimiento")
    search_fields = ("producto__nombre", "codigo_lote")
    list_filter = ("fecha_fabricacion", "fecha_vencimiento")

admin.site.register(LoteProducto, LoteProductoAdmin)


# ============== SerieProducto ==============
class SerieProductoAdmin(admin.ModelAdmin):
    list_display = ("producto", "numero_serie", "lote")
    search_fields = ("producto__nombre", "numero_serie")
    list_filter = ("lote",)

admin.site.register(SerieProducto, SerieProductoAdmin)


# ============== Transferencia ==============
class TransferenciaAdmin(admin.ModelAdmin):
    list_display = ("bodega_origen", "sucursal_destino", "estado", "creado_por")  # Usa los campos correctos
    search_fields = ("bodega_origen__codigo", "sucursal_destino__codigo", "estado")
    list_filter = ("estado",)
    autocomplete_fields = ["bodega_origen", "sucursal_destino"]  # Asegúrate de que los campos estén correctos

admin.site.register(Transferencia, TransferenciaAdmin)

# ============== ConversionUM ==============
class ConversionUMAdmin(admin.ModelAdmin):
    list_display = ("unidad_desde", "unidad_hasta", "factor")
    search_fields = ("unidad_desde__codigo", "unidad_hasta__codigo")
    list_filter = ("factor",)

admin.site.register(ConversionUM, ConversionUMAdmin)


# ============== ReglaAlerta ==============
class ReglaAlertaAdmin(admin.ModelAdmin):
    list_display = ("codigo", "nombre", "activo")
    search_fields = ("codigo", "nombre")
    list_filter = ("activo",)

admin.site.register(ReglaAlerta, ReglaAlertaAdmin)


# ============== Alerta ==============
class AlertaAdmin(admin.ModelAdmin):
    list_display = ("regla", "producto", "severidad", "mensaje", "reconocida_por")
    search_fields = ("mensaje", "regla__nombre", "producto__nombre")
    list_filter = ("severidad", "reconocida_por")

admin.site.register(Alerta, AlertaAdmin)


# ============== Notificacion ==============
class NotificacionAdmin(admin.ModelAdmin):
    list_display = ("usuario", "titulo", "leida")
    search_fields = ("titulo", "usuario__username")
    list_filter = ("leida",)

admin.site.register(Notificacion, NotificacionAdmin)


# ============== Documento ==============
class DocumentoAdmin(admin.ModelAdmin):
    list_display = ("tipo", "titulo", "creado_por")
    search_fields = ("titulo", "tipo")
    list_filter = ("tipo",)

admin.site.register(Documento, DocumentoAdmin)


# ============== Adjunto ==============
class AdjuntoAdmin(admin.ModelAdmin):
    list_display = ("documento", "producto", "proveedor", "url_archivo", "nombre_archivo")
    search_fields = ("documento__titulo", "producto__nombre", "proveedor__username")
    list_filter = ("documento",)

admin.site.register(Adjunto, AdjuntoAdmin)