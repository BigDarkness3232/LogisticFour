# apps/inventario/forms.py
from django import forms
from django.forms import inlineformset_factory, BaseInlineFormSet
from django.contrib.auth.models import User
from .models import (
    # Usuarios / Perfil
    UsuarioPerfil,
    # Catálogos
    TasaImpuesto, UnidadMedida, ConversionUM, Marca, CategoriaProducto,
    # Organización / ubicaciones
    Sucursal, Bodega, AreaBodega, TipoUbicacion, Ubicacion,
    # Productos y maestros
    Producto, PrecioProducto, DefinicionAtributo, AtributoProducto, ImagenProducto, ProductoUsuarioProveedor,
    LoteProducto, SerieProducto,
    # Inventario (procesos con líneas)
    AjusteInventario, LineaAjusteInventario,
    RecuentoInventario, LineaRecuentoInventario,
    Transferencia, LineaTransferencia,
    DevolucionProveedor, LineaDevolucionProveedor,
    OrdenCompra, LineaOrdenCompra,
    RecepcionMercaderia, LineaRecepcionMercaderia,
    # Documentos
    Documento, Adjunto,
    # Políticas / reglas
    PoliticaReabastecimiento, ReglaAlerta,
    # Alertas / Notificaciones
    Alerta, Notificacion,
    # Apoyo
    AreaBodega, Bodega, Ubicacion, LoteProducto, SerieProducto, Producto
)

# =========================================================
# Helpers
# =========================================================

class ProveedorQuerysetMixin:
    """Filtra campos de usuario a los que tienen perfil PROVEEDOR."""
    def _filtrar_proveedores(self, field_name: str):
        if field_name in self.fields:
            # Optimización: filtrar por usuarios que tengan perfil con rol PROVEEDOR
            self.fields[field_name].queryset = User.objects.filter(
                perfil__rol=UsuarioPerfil.Rol.PROVEEDOR
            ).select_related("perfil").order_by("username")


class UbicacionCoherenteMixin:
    """Valida que area.bodega == bodega y que ubicaciones pertenezcan a la bodega esperada."""
    def _validar_area_vs_bodega(self, cleaned_data, area_field="area", bodega_field="bodega"):
        area = cleaned_data.get(area_field)
        bodega = cleaned_data.get(bodega_field)
        if area and bodega and area.bodega_id != bodega.id:
            self.add_error(area_field, "El área seleccionada no pertenece a la bodega.")

    def _validar_ubicacion_vs_bodega(self, cleaned_data, ubicacion_field="ubicacion", bodega_field="bodega"):
        ubicacion = cleaned_data.get(ubicacion_field)
        bodega = cleaned_data.get(bodega_field)
        if ubicacion and bodega and ubicacion.bodega_id != bodega.id:
            self.add_error(ubicacion_field, "La ubicación seleccionada no pertenece a la bodega.")

class BaseModelForm(forms.ModelForm):
    """Configura widgets comunes y limpia strings."""
    def clean(self):
        cd = super().clean()
        # Limpieza leve de espacios
        for name, field in self.fields.items():
            if isinstance(field, forms.CharField) and cd.get(name) is not None:
                cd[name] = cd[name].strip()
        return cd

# =========================================================
# 1) Usuarios / Perfil
# =========================================================

class UsuarioPerfilForm(BaseModelForm):
    class Meta:
        model = UsuarioPerfil
        fields = ["usuario", "rut", "telefono", "rol"]
        widgets = {
            "rut": forms.TextInput(attrs={"placeholder": "11.111.111-1"}),
            "telefono": forms.TextInput(attrs={"placeholder": "+56 9 1234 5678"}),
        }

# =========================================================
# 2) Catálogos
# =========================================================

class TasaImpuestoForm(BaseModelForm):
    class Meta:
        model = TasaImpuesto
        fields = ["nombre", "porcentaje", "activo"]


class UnidadMedidaForm(BaseModelForm):
    class Meta:
        model = UnidadMedida
        fields = ["codigo", "descripcion"]


class ConversionUMForm(BaseModelForm):
    class Meta:
        model = ConversionUM
        fields = ["unidad_desde", "unidad_hasta", "factor"]


class MarcaForm(BaseModelForm):
    class Meta:
        model = Marca
        fields = ["nombre"]


class CategoriaProductoForm(BaseModelForm):
    class Meta:
        model = CategoriaProducto
        fields = ["padre", "nombre", "codigo"]

# =========================================================
# 3) Organización / Ubicaciones
# =========================================================

class SucursalForm(BaseModelForm):
    class Meta:
        model = Sucursal
        fields = ["codigo", "nombre", "direccion", "ciudad", "region", "pais", "activo"]


class BodegaForm(BaseModelForm):
    class Meta:
        model = Bodega
        fields = ["sucursal", "codigo", "nombre", "descripcion", "activo"]


class AreaBodegaForm(BaseModelForm, UbicacionCoherenteMixin):
    class Meta:
        model = AreaBodega
        fields = ["bodega", "codigo", "nombre"]

    def clean(self):
        cd = super().clean()
        # nada adicional: bodega viene explícita
        return cd


class TipoUbicacionForm(BaseModelForm):
    class Meta:
        model = TipoUbicacion
        fields = ["codigo", "descripcion"]


class UbicacionForm(BaseModelForm, UbicacionCoherenteMixin):
    class Meta:
        model = Ubicacion
        fields = ["bodega", "area", "tipo", "codigo", "nombre", "pickeable", "almacenable"]

    def clean(self):
        cd = super().clean()
        self._validar_area_vs_bodega(cd, area_field="area", bodega_field="bodega")
        return cd

# =========================================================
# 4) Productos y maestros
# =========================================================

class ProductoForm(BaseModelForm):
    class Meta:
        model = Producto
        fields = [
            "sku", "nombre", "marca", "categoria",
            "unidad_base", "tasa_impuesto", "activo",
            "es_serializado", "tiene_vencimiento"
        ]


class PrecioProductoForm(BaseModelForm):
    class Meta:
        model = PrecioProducto
        fields = ["producto", "precio", "vigente_desde", "vigente_hasta", "activo"]
        widgets = {
            "vigente_desde": forms.DateInput(attrs={"type": "date"}),
            "vigente_hasta": forms.DateInput(attrs={"type": "date"}),
        }

    def clean(self):
        cd = super().clean()
        # Regla útil: evitar dos precios activos simultáneos
        producto = cd.get("producto")
        activo = cd.get("activo")
        if producto and activo:
            qs = PrecioProducto.objects.filter(producto=producto, activo=True)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                self.add_error("activo", "Ya existe un precio activo para este producto.")
        return cd


class DefinicionAtributoForm(BaseModelForm):
    class Meta:
        model = DefinicionAtributo
        fields = ["codigo", "nombre", "tipo_dato"]


class AtributoProductoForm(BaseModelForm):
    class Meta:
        model = AtributoProducto
        fields = [
            "producto", "atributo",
            "valor_texto", "valor_numero", "valor_booleano", "valor_fecha"
        ]
        widgets = {
            "valor_fecha": forms.DateInput(attrs={"type": "date"}),
        }


class ImagenProductoForm(BaseModelForm):
    class Meta:
        model = ImagenProducto
        fields = ["producto", "url", "texto_alternativo"]


class ProductoUsuarioProveedorForm(BaseModelForm, ProveedorQuerysetMixin):
    class Meta:
        model = ProductoUsuarioProveedor
        fields = ["producto", "proveedor", "sku_proveedor", "tiempo_entrega_dias", "cantidad_min_pedido"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._filtrar_proveedores("proveedor")

# Opcionales si quieres mantenimiento manual de lotes/series:
class LoteProductoForm(BaseModelForm):
    class Meta:
        model = LoteProducto
        fields = ["producto", "codigo_lote", "fecha_vencimiento", "fecha_fabricacion"]
        widgets = {
            "fecha_vencimiento": forms.DateInput(attrs={"type": "date"}),
            "fecha_fabricacion": forms.DateInput(attrs={"type": "date"}),
        }

class SerieProductoForm(BaseModelForm):
    class Meta:
        model = SerieProducto
        fields = ["producto", "numero_serie", "lote"]

# =========================================================
# 5) Políticas / Reglas
# =========================================================

class PoliticaReabastecimientoForm(BaseModelForm):
    class Meta:
        model = PoliticaReabastecimiento
        fields = [
            "producto", "ubicacion",
            "cantidad_min", "cantidad_max", "cantidad_reorden",
            "dias_cobertura", "activo"
        ]


class ReglaAlertaForm(BaseModelForm):
    class Meta:
        model = ReglaAlerta
        fields = ["codigo", "nombre", "configuracion", "activo"]
        widgets = {
            "configuracion": forms.Textarea(attrs={"rows": 4}),
        }

# =========================================================
# 6) Documentos
# =========================================================

class DocumentoForm(BaseModelForm):
    class Meta:
        model = Documento
        fields = ["tipo", "titulo", "descripcion", "creado_por"]


class AdjuntoForm(BaseModelForm, ProveedorQuerysetMixin):
    class Meta:
        model = Adjunto
        fields = ["documento", "producto", "proveedor", "url_archivo", "nombre_archivo", "tipo_contenido"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._filtrar_proveedores("proveedor")

# =========================================================
# 7) Compras (padre + líneas con inline formset)
# =========================================================

class OrdenCompraForm(BaseModelForm, ProveedorQuerysetMixin):
    class Meta:
        model = OrdenCompra
        fields = ["proveedor", "tasa_impuesto", "bodega", "numero_orden", "estado", "fecha_esperada", "creado_por"]
        widgets = {
            "fecha_esperada": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._filtrar_proveedores("proveedor")


class LineaOrdenCompraForm(BaseModelForm):
    class Meta:
        model = LineaOrdenCompra
        fields = ["producto", "descripcion", "cantidad_pedida", "unidad", "precio", "descuento_pct"]


class BaseLineasOrdenCompraFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        total = 0
        for form in self.forms:
            if form.cleaned_data.get("DELETE"):
                continue
            cant = form.cleaned_data.get("cantidad_pedida") or 0
            total += cant
        if total <= 0:
            raise forms.ValidationError("Debes ingresar al menos una línea con cantidad > 0.")

LineasOrdenCompraFormSet = inlineformset_factory(
    OrdenCompra, LineaOrdenCompra,
    form=LineaOrdenCompraForm,
    formset=BaseLineasOrdenCompraFormSet,
    extra=1, can_delete=True
)

# Recepción
class RecepcionMercaderiaForm(BaseModelForm):
    class Meta:
        model = RecepcionMercaderia
        fields = ["orden_compra", "bodega", "numero_recepcion", "estado", "recibido_por"]


class LineaRecepcionMercaderiaForm(BaseModelForm):
    class Meta:
        model = LineaRecepcionMercaderia
        fields = ["producto", "lote", "serie", "cantidad_recibida", "unidad", "fecha_vencimiento"]
        widgets = {
            "fecha_vencimiento": forms.DateInput(attrs={"type": "date"}),
        }

class BaseLineasRecepcionFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        if not any(
            (not f.cleaned_data.get("DELETE") and (f.cleaned_data.get("cantidad_recibida") or 0) > 0)
            for f in self.forms
        ):
            raise forms.ValidationError("La recepción debe tener al menos una línea con cantidad > 0.")

LineasRecepcionFormSet = inlineformset_factory(
    RecepcionMercaderia, LineaRecepcionMercaderia,
    form=LineaRecepcionMercaderiaForm,
    formset=BaseLineasRecepcionFormSet,
    extra=1, can_delete=True
)

# =========================================================
# 8) Ajuste / Recuento / Transferencia / Devolución (padre + líneas)
# =========================================================

class AjusteInventarioForm(BaseModelForm):
    class Meta:
        model = AjusteInventario
        fields = ["bodega", "motivo", "estado", "creado_por"]


class LineaAjusteInventarioForm(BaseModelForm):
    class Meta:
        model = LineaAjusteInventario
        fields = ["producto", "ubicacion", "lote", "serie", "cantidad_delta", "motivo"]

class BaseLineasAjusteFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        # al menos una línea con delta != 0
        if not any(
            (not f.cleaned_data.get("DELETE") and (f.cleaned_data.get("cantidad_delta") or 0) != 0)
            for f in self.forms
        ):
            raise forms.ValidationError("El ajuste debe tener al menos una línea con un delta distinto de 0.")

LineasAjusteFormSet = inlineformset_factory(
    AjusteInventario, LineaAjusteInventario,
    form=LineaAjusteInventarioForm,
    formset=BaseLineasAjusteFormSet,
    extra=1, can_delete=True
)


class RecuentoInventarioForm(BaseModelForm):
    class Meta:
        model = RecuentoInventario
        fields = ["bodega", "codigo_ciclo", "estado", "creado_por"]


class LineaRecuentoInventarioForm(BaseModelForm):
    class Meta:
        model = LineaRecuentoInventario
        fields = [
            "producto", "ubicacion", "lote", "serie",
            "cantidad_sistema", "cantidad_contada", "contado_por", "diferencia"
        ]


class BaseLineasRecuentoFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        # al menos una línea
        if not any(not f.cleaned_data.get("DELETE") for f in self.forms):
            raise forms.ValidationError("El recuento debe tener al menos una línea.")

LineasRecuentoFormSet = inlineformset_factory(
    RecuentoInventario, LineaRecuentoInventario,
    form=LineaRecuentoInventarioForm,
    formset=BaseLineasRecuentoFormSet,
    extra=1, can_delete=True
)


class TransferenciaForm(BaseModelForm):
    class Meta:
        model = Transferencia
        fields = ["bodega_origen", "bodega_destino", "estado", "creado_por"]

    def clean(self):
        cd = super().clean()
        if cd.get("bodega_origen") and cd.get("bodega_destino") and cd["bodega_origen"] == cd["bodega_destino"]:
            self.add_error("bodega_destino", "La bodega destino debe ser distinta de la bodega origen.")
        return cd


class LineaTransferenciaForm(BaseModelForm):
    class Meta:
        model = LineaTransferencia
        fields = ["producto", "lote", "serie", "cantidad", "unidad"]


class BaseLineasTransferenciaFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        # al menos una línea con cantidad > 0
        if not any(
            (not f.cleaned_data.get("DELETE") and (f.cleaned_data.get("cantidad") or 0) > 0)
            for f in self.forms
        ):
            raise forms.ValidationError("La transferencia debe tener al menos una línea con cantidad > 0.")

LineasTransferenciaFormSet = inlineformset_factory(
    Transferencia, LineaTransferencia,
    form=LineaTransferenciaForm,
    formset=BaseLineasTransferenciaFormSet,
    extra=1, can_delete=True
)


class DevolucionProveedorForm(BaseModelForm, ProveedorQuerysetMixin):
    class Meta:
        model = DevolucionProveedor
        fields = ["proveedor", "bodega", "estado", "motivo", "creado_por"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._filtrar_proveedores("proveedor")


class LineaDevolucionProveedorForm(BaseModelForm):
    class Meta:
        model = LineaDevolucionProveedor
        fields = ["producto", "lote", "serie", "cantidad", "unidad"]


class BaseLineasDevolucionFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        if not any(
            (not f.cleaned_data.get("DELETE") and (f.cleaned_data.get("cantidad") or 0) > 0)
            for f in self.forms
        ):
            raise forms.ValidationError("La devolución debe tener al menos una línea con cantidad > 0.")

LineasDevolucionFormSet = inlineformset_factory(
    DevolucionProveedor, LineaDevolucionProveedor,
    form=LineaDevolucionProveedorForm,
    formset=BaseLineasDevolucionFormSet,
    extra=1, can_delete=True
)

# =========================================================
# 9) Alertas / Notificaciones (operativos simples)
# =========================================================

class AlertaReconocerForm(forms.ModelForm):
    """Form mínimo para reconocer una alerta."""
    class Meta:
        model = Alerta
        fields = ["reconocida_por", "reconocida_en"]


class NotificacionLeerForm(forms.ModelForm):
    """Marcar una notificación como leída."""
    class Meta:
        model = Notificacion
        fields = ["leida"]
