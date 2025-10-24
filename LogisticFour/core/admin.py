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
    Sucursal, Bodega, AreaBodega, TipoUbicacion, Ubicacion,
    BitacoraAuditoria,
    Producto, ProductoUsuarioProveedor, LoteProducto, SerieProducto,
    Stock, TipoMovimiento, MovimientoStock,
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

# ===== Ajustes generales del admin =====
admin.site.site_header = "Logistic — Administración"
admin.site.site_title = "Logistic Admin"
admin.site.index_title = "Panel de Control"

# Textarea por defecto para JSONField
class JSONTextareaAdmin(admin.ModelAdmin):
    formfield_overrides = {
        models.JSONField: {"widget": AdminTextareaWidget(attrs={"rows": 6})},
        # Alternativa:
        # models.JSONField: {"widget": forms.Textarea(attrs={"rows": 6, "style": "font-family:monospace"})},
    }

# ===== User + Perfil (Inline) — único registro aquí =====
try:
    admin.site.unregister(User)
except admin.sites.NotRegistered:
    pass

class UsuarioPerfilInline(admin.StackedInline):
    model = UsuarioPerfil
    can_delete = False
    fk_name = "usuario"
    extra = 0
    autocomplete_fields = ["sucursal"]
    fieldsets = ((None, {"fields": (("rut", "telefono"), ("rol", "sucursal"))}),)

@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    inlines = [UsuarioPerfilInline]
    list_display = ("username", "first_name", "last_name", "email", "get_rol", "get_sucursal", "is_staff", "is_active")
    list_filter = ("is_active", "is_staff", "is_superuser", "perfil__rol", "perfil__sucursal")
    search_fields = ("username", "first_name", "last_name", "email", "perfil__rut", "perfil__telefono")
    ordering = ("username",)

    @admin.display(ordering="perfil__rol", description="Rol")
    def get_rol(self, obj):
        return getattr(getattr(obj, "perfil", None), "rol", "—")

    @admin.display(ordering="perfil__sucursal__codigo", description="Sucursal")
    def get_sucursal(self, obj):
        perf = getattr(obj, "perfil", None)
        return getattr(getattr(perf, "sucursal", None), "codigo", "—")

# ===== Catálogos =====
@admin.register(TasaImpuesto)
class TasaImpuestoAdmin(admin.ModelAdmin):
    list_display = ("nombre", "porcentaje", "activo", "creado_en")
    list_filter = ("activo",)
    search_fields = ("nombre",)
    list_editable = ("activo",)

@admin.register(UnidadMedida)
class UnidadMedidaAdmin(admin.ModelAdmin):
    list_display = ("codigo", "descripcion", "creado_en")
    search_fields = ("codigo", "descripcion")

@admin.register(ConversionUM)
class ConversionUMAdmin(admin.ModelAdmin):
    list_display = ("unidad_desde", "unidad_hasta", "factor")
    autocomplete_fields = ("unidad_desde", "unidad_hasta")
    search_fields = ("unidad_desde__codigo", "unidad_hasta__codigo")

@admin.register(Marca)
class MarcaAdmin(admin.ModelAdmin):
    list_display = ("nombre", "creado_en")
    search_fields = ("nombre",)

@admin.register(CategoriaProducto)
class CategoriaProductoAdmin(admin.ModelAdmin):
    list_display = ("nombre", "codigo", "padre", "creado_en")
    search_fields = ("nombre", "codigo")
    autocomplete_fields = ("padre",)

# ===== Organización / Ubicaciones =====
@admin.register(Sucursal)
class SucursalAdmin(admin.ModelAdmin):
    list_display = ("codigo", "nombre", "ciudad", "region", "pais", "activo", "creado_en")
    list_filter = ("activo", "ciudad", "region", "pais")
    search_fields = ("codigo", "nombre", "direccion", "ciudad", "region")
    list_editable = ("activo",)

@admin.register(Bodega)
class BodegaAdmin(admin.ModelAdmin):
    list_display = ("codigo", "nombre", "sucursal", "activo", "creado_en")
    list_filter = ("activo", "sucursal")
    search_fields = ("codigo", "nombre", "descripcion", "sucursal__codigo", "sucursal__nombre")
    autocomplete_fields = ("sucursal",)
    list_select_related = ("sucursal",)
    list_editable = ("activo",)

@admin.register(AreaBodega)
class AreaBodegaAdmin(admin.ModelAdmin):
    list_display = ("codigo", "nombre", "bodega")
    search_fields = ("codigo", "nombre", "bodega__codigo", "bodega__sucursal__codigo")
    autocomplete_fields = ("bodega",)
    list_select_related = ("bodega", "bodega__sucursal")

@admin.register(TipoUbicacion)
class TipoUbicacionAdmin(admin.ModelAdmin):
    list_display = ("codigo", "descripcion")
    search_fields = ("codigo", "descripcion")

@admin.register(Ubicacion)
class UbicacionAdmin(admin.ModelAdmin):
    list_display = ("codigo", "bodega", "area", "tipo", "pickeable", "almacenable", "creado_en")
    list_filter = ("pickeable", "almacenable", "bodega", "tipo", "area")
    search_fields = ("codigo", "nombre", "bodega__codigo", "bodega__sucursal__codigo")
    autocomplete_fields = ("bodega", "area", "tipo")
    list_select_related = ("bodega", "area", "tipo")

# ===== Auditoría =====
@admin.register(BitacoraAuditoria)
class BitacoraAuditoriaAdmin(JSONTextareaAdmin):
    list_display = ("creado_en", "usuario", "accion", "tabla", "entidad_id")
    list_filter = ("accion", "tabla", "usuario")
    search_fields = ("accion", "tabla", "entidad_id")
    autocomplete_fields = ("usuario",)
    readonly_fields = ("creado_en",)

# ===== Productos / Datos Maestros =====
class ProductoUsuarioProveedorInline(admin.TabularInline):
    model = ProductoUsuarioProveedor
    extra = 0
    autocomplete_fields = ("proveedor",)
    fields = ("proveedor", "sku_proveedor", "tiempo_entrega_dias", "cantidad_min_pedido")

class LoteProductoInline(admin.TabularInline):
    model = LoteProducto
    extra = 0
    fields = ("codigo_lote", "fecha_vencimiento", "fecha_fabricacion")

class SerieProductoInline(admin.TabularInline):
    model = SerieProducto
    extra = 0
    autocomplete_fields = ("lote",)
    fields = ("numero_serie", "lote")

@admin.register(Producto)
class ProductoAdmin(admin.ModelAdmin):
    list_display = ("sku", "nombre", "marca", "categoria", "unidad_base", "precio", "stock", "activo", "es_serializado", "tiene_vencimiento", "creado_en")
    list_filter = ("activo", "es_serializado", "tiene_vencimiento", "marca", "categoria", "unidad_base")
    search_fields = ("sku", "nombre", "marca__nombre", "categoria__nombre")
    autocomplete_fields = ("marca", "categoria", "unidad_base", "tasa_impuesto")
    inlines = [ProductoUsuarioProveedorInline, LoteProductoInline, SerieProductoInline]
    list_editable = ("precio", "activo")
    ordering = ("sku",)

@admin.register(ProductoUsuarioProveedor)
class ProductoUsuarioProveedorAdmin(admin.ModelAdmin):
    list_display = ("producto", "proveedor", "sku_proveedor", "tiempo_entrega_dias", "cantidad_min_pedido")
    search_fields = ("producto__sku", "producto__nombre", "proveedor__username", "proveedor__first_name", "proveedor__last_name", "sku_proveedor")
    autocomplete_fields = ("producto", "proveedor")

@admin.register(LoteProducto)
class LoteProductoAdmin(admin.ModelAdmin):
    list_display = ("producto", "codigo_lote", "fecha_vencimiento", "fecha_fabricacion")
    search_fields = ("producto__sku", "producto__nombre", "codigo_lote")
    autocomplete_fields = ("producto",)

@admin.register(SerieProducto)
class SerieProductoAdmin(admin.ModelAdmin):
    list_display = ("producto", "numero_serie", "lote")
    search_fields = ("producto__sku", "producto__nombre", "numero_serie", "lote__codigo_lote")
    autocomplete_fields = ("producto", "lote")

# ===== Inventario =====
@admin.register(Stock)
class StockAdmin(admin.ModelAdmin):
    list_display = ("producto", "ubicacion", "lote", "serie", "cantidad_disponible", "cantidad_reservada", "actualizado_en")
    list_filter = ("ubicacion__bodega", "ubicacion", "lote")
    search_fields = ("producto__sku", "producto__nombre", "ubicacion__codigo", "lote__codigo_lote", "serie__numero_serie")
    autocomplete_fields = ("producto", "ubicacion", "lote", "serie")
    readonly_fields = ("actualizado_en",)
    list_select_related = ("producto", "ubicacion", "lote", "serie")

@admin.register(TipoMovimiento)
class TipoMovimientoAdmin(admin.ModelAdmin):
    list_display = ("codigo", "nombre", "direccion", "afecta_costo")
    list_editable = ("nombre", "direccion", "afecta_costo")
    search_fields = ("codigo", "nombre")

@admin.register(MovimientoStock)
class MovimientoStockAdmin(admin.ModelAdmin):
    list_display = ("ocurrido_en", "tipo_movimiento", "producto", "ubicacion_desde", "ubicacion_hasta", "cantidad", "unidad", "creado_por")
    list_filter = ("tipo_movimiento", "producto", "unidad", "creado_por", ("ocurrido_en", admin.DateFieldListFilter))
    search_fields = ("producto__sku", "producto__nombre", "ubicacion_desde__codigo", "ubicacion_hasta__codigo", "tabla_referencia", "referencia_id")
    autocomplete_fields = ("tipo_movimiento", "producto", "ubicacion_desde", "ubicacion_hasta", "lote", "serie", "unidad", "creado_por")
    readonly_fields = ("ocurrido_en",)

class LineaAjusteInventarioInline(admin.TabularInline):
    model = LineaAjusteInventario
    extra = 0
    autocomplete_fields = ("producto", "ubicacion", "lote", "serie")
    fields = ("producto", "ubicacion", "lote", "serie", "cantidad_delta", "motivo")

@admin.register(AjusteInventario)
class AjusteInventarioAdmin(admin.ModelAdmin):
    list_display = ("id", "bodega", "motivo", "estado", "creado_por", "creado_en")
    list_filter = ("estado", "bodega", "creado_por", ("creado_en", admin.DateFieldListFilter))
    search_fields = ("id", "motivo", "bodega__codigo", "bodega__sucursal__codigo")
    autocomplete_fields = ("bodega", "creado_por")
    inlines = [LineaAjusteInventarioInline]
    list_editable = ("estado",)

class LineaRecuentoInventarioInline(admin.TabularInline):
    model = LineaRecuentoInventario
    extra = 0
    autocomplete_fields = ("producto", "ubicacion", "lote", "serie", "contado_por")
    fields = ("producto", "ubicacion", "lote", "serie", "cantidad_sistema", "cantidad_contada", "diferencia", "contado_por")

@admin.register(RecuentoInventario)
class RecuentoInventarioAdmin(admin.ModelAdmin):
    list_display = ("id", "bodega", "codigo_ciclo", "estado", "creado_por", "creado_en")
    list_filter = ("estado", "bodega", "creado_por", ("creado_en", admin.DateFieldListFilter))
    search_fields = ("id", "codigo_ciclo", "bodega__codigo", "bodega__sucursal__codigo")
    autocomplete_fields = ("bodega", "creado_por")
    inlines = [LineaRecuentoInventarioInline]
    list_editable = ("estado",)

@admin.register(Reserva)
class ReservaAdmin(admin.ModelAdmin):
    list_display = ("producto", "ubicacion", "lote", "serie", "cantidad_reservada", "tabla_referencia", "referencia_id", "creado_en")
    list_filter = ("producto", "ubicacion__bodega")
    search_fields = ("producto__sku", "producto__nombre", "ubicacion__codigo", "tabla_referencia", "referencia_id")
    autocomplete_fields = ("producto", "ubicacion", "lote", "serie")

@admin.register(PoliticaReabastecimiento)
class PoliticaReabastecimientoAdmin(admin.ModelAdmin):
    list_display = ("producto", "ubicacion", "cantidad_min", "cantidad_max", "cantidad_reorden", "dias_cobertura", "activo")
    list_filter = ("activo", "ubicacion__bodega")
    search_fields = ("producto__sku", "producto__nombre", "ubicacion__codigo")
    autocomplete_fields = ("producto", "ubicacion")
    list_editable = ("activo",)

# ===== Transferencias / Devoluciones =====
class LineaTransferenciaInline(admin.TabularInline):
    model = LineaTransferencia
    extra = 0
    autocomplete_fields = ("producto", "lote", "serie", "unidad")
    fields = ("producto", "lote", "serie", "cantidad", "unidad")

@admin.register(Transferencia)
class TransferenciaAdmin(admin.ModelAdmin):
    list_display = ("id", "bodega_origen", "bodega_destino", "estado", "creado_por", "creado_en")
    list_filter = ("estado", "bodega_origen", "bodega_destino", "creado_por")
    search_fields = ("id", "bodega_origen__codigo", "bodega_destino__codigo")
    autocomplete_fields = ("bodega_origen", "bodega_destino", "creado_por")
    inlines = [LineaTransferenciaInline]
    list_editable = ("estado",)

class LineaDevolucionProveedorInline(admin.TabularInline):
    model = LineaDevolucionProveedor
    extra = 0
    autocomplete_fields = ("producto", "lote", "serie", "unidad")
    fields = ("producto", "lote", "serie", "cantidad", "unidad")

@admin.register(DevolucionProveedor)
class DevolucionProveedorAdmin(admin.ModelAdmin):
    list_display = ("id", "proveedor", "bodega", "estado", "motivo", "creado_por", "creado_en")
    list_filter = ("estado", "bodega", "proveedor", "creado_por")
    search_fields = ("id", "motivo", "proveedor__username", "bodega__codigo")
    autocomplete_fields = ("proveedor", "bodega", "creado_por")
    inlines = [LineaDevolucionProveedorInline]
    list_editable = ("estado",)

# ===== Compras =====
class LineaOrdenCompraInline(admin.TabularInline):
    model = LineaOrdenCompra
    extra = 0
    autocomplete_fields = ("producto", "unidad")
    fields = ("producto", "descripcion", "cantidad_pedida", "unidad", "precio", "descuento_pct")

@admin.register(OrdenCompra)
class OrdenCompraAdmin(admin.ModelAdmin):
    list_display = ("numero_orden", "proveedor", "bodega", "estado", "tasa_impuesto", "fecha_esperada", "creado_por", "creado_en")
    list_filter = ("estado", "bodega", "proveedor", ("fecha_esperada", admin.DateFieldListFilter))
    search_fields = ("numero_orden", "proveedor__username", "bodega__codigo")
    autocomplete_fields = ("proveedor", "tasa_impuesto", "bodega", "creado_por")
    inlines = [LineaOrdenCompraInline]
    list_editable = ("estado",)

class LineaRecepcionMercaderiaInline(admin.TabularInline):
    model = LineaRecepcionMercaderia
    extra = 0
    autocomplete_fields = ("producto", "lote", "serie", "unidad")
    fields = ("producto", "lote", "serie", "cantidad_recibida", "unidad", "fecha_vencimiento")

@admin.register(RecepcionMercaderia)
class RecepcionMercaderiaAdmin(admin.ModelAdmin):
    list_display = ("numero_recepcion", "orden_compra", "bodega", "estado", "recibido_en", "recibido_por")
    list_filter = ("estado", "bodega", "recibido_por", ("recibido_en", admin.DateFieldListFilter))
    search_fields = ("numero_recepcion", "orden_compra__numero_orden", "bodega__codigo")
    autocomplete_fields = ("orden_compra", "bodega", "recibido_por")
    inlines = [LineaRecepcionMercaderiaInline]
    readonly_fields = ("recibido_en",)

@admin.register(FacturaProveedor)
class FacturaProveedorAdmin(admin.ModelAdmin):
    list_display = ("proveedor", "numero_factura", "monto_total", "tasa_impuesto", "fecha_factura", "fecha_vencimiento", "estado")
    list_filter = ("estado", ("fecha_factura", admin.DateFieldListFilter))
    search_fields = ("numero_factura", "proveedor__username", "proveedor__first_name", "proveedor__last_name")
    autocomplete_fields = ("proveedor", "tasa_impuesto")
    list_editable = ("estado",)

# ===== Alertas / Notificaciones =====
@admin.action(description="Marcar como reconocidas (fecha ahora)")
def marcar_alertas_reconocidas(modeladmin, request, queryset):
    queryset.update(reconocida_en=timezone.now())

@admin.register(ReglaAlerta)
class ReglaAlertaAdmin(JSONTextareaAdmin):
    list_display = ("codigo", "nombre", "activo", "creado_en")
    list_filter = ("activo",)
    search_fields = ("codigo", "nombre")
    list_editable = ("activo",)

@admin.register(Alerta)
class AlertaAdmin(admin.ModelAdmin):
    list_display = ("creado_en", "severidad", "mensaje_corto", "producto", "ubicacion", "regla", "reconocida_por", "reconocida_en")
    list_filter = ("severidad", "regla", "reconocida_por", ("creado_en", admin.DateFieldListFilter))
    search_fields = ("mensaje", "producto__sku", "producto__nombre", "ubicacion__codigo", "regla__codigo")
    autocomplete_fields = ("producto", "ubicacion", "regla", "reconocida_por")
    actions = [marcar_alertas_reconocidas]

    @admin.display(description="Mensaje")
    def mensaje_corto(self, obj):
        return (obj.mensaje[:80] + "…") if obj.mensaje and len(obj.mensaje) > 80 else obj.mensaje

@admin.register(Notificacion)
class NotificacionAdmin(admin.ModelAdmin):
    list_display = ("usuario", "titulo", "leida", "creado_en")
    list_filter = ("leida", "usuario")
    search_fields = ("titulo", "cuerpo", "usuario__username")
    autocomplete_fields = ("usuario",)
    list_editable = ("leida",)

# ===== Documentos / Adjuntos =====
@admin.register(Documento)
class DocumentoAdmin(admin.ModelAdmin):
    list_display = ("tipo", "titulo", "creado_por", "creado_en")
    list_filter = ("tipo", "creado_por")
    search_fields = ("tipo", "titulo", "descripcion")
    autocomplete_fields = ("creado_por",)

@admin.register(Adjunto)
class AdjuntoAdmin(admin.ModelAdmin):
    list_display = ("nombre_archivo", "tipo_contenido", "url_click", "documento", "producto", "proveedor", "creado_en")
    list_filter = ("tipo_contenido", "proveedor")
    search_fields = ("nombre_archivo", "url_archivo", "tipo_contenido", "producto__sku", "producto__nombre", "documento__titulo", "proveedor__username")
    autocomplete_fields = ("documento", "producto", "proveedor")

    @admin.display(description="URL")
    def url_click(self, obj):
        if obj.url_archivo:
            return format_html('<a href="{}" target="_blank" rel="noopener">abrir</a>', obj.url_archivo)
        return "—"
