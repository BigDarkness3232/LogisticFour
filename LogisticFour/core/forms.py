from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from core.models import *

class SignupUserForm(UserCreationForm):
    email = forms.EmailField(required=False, label="Email")
    first_name = forms.CharField(required=False, label="Nombre")
    last_name = forms.CharField(required=False, label="Apellido")

    class Meta:
        model = User
        fields = ("username", "first_name", "last_name", "email", "password1", "password2")

class UsuarioPerfilForm(forms.ModelForm):
    class Meta:
        model = UsuarioPerfil
        # incluimos rol para que el ADMIN asigne el rol al crear
        fields = ("telefono", "rol")
        widgets = {
            "telefono": forms.TextInput(attrs={"placeholder": "+56 9 1234 5678"}),
        }
        
class UserEditForm(forms.ModelForm):
    # opcional: permitir activar/desactivar
    is_active = forms.BooleanField(required=False, label="Activo")

    class Meta:
        model = User
        fields = ("username", "first_name", "last_name", "email", "is_active")
        widgets = {
            "username":   forms.TextInput(attrs={"class": "form-control"}),
            "first_name": forms.TextInput(attrs={"class": "form-control"}),
            "last_name":  forms.TextInput(attrs={"class": "form-control"}),
            "email":      forms.EmailInput(attrs={"class": "form-control"}),
        }

class UsuarioPerfilEditForm(forms.ModelForm):
    class Meta:
        model = UsuarioPerfil
        fields = ("telefono", "rol")
        widgets = {
            "telefono": forms.TextInput(attrs={"placeholder": "+56 9 1234 5678", "class": "form-control"}),
            "rol": forms.Select(attrs={"class": "form-select"}),
        }

class ProductoForm(forms.ModelForm):
    # Opcional: forzar empty_label más claro en los FKs opcionales
    marca = forms.ModelChoiceField(
        queryset=Marca.objects.none(),
        required=False,
        empty_label="— Selecciona una marca —"
    )
    categoria = forms.ModelChoiceField(
        queryset=CategoriaProducto.objects.none(),
        required=False,
        empty_label="— Selecciona una categoría —"
    )
    unidad_base = forms.ModelChoiceField(
        queryset=UnidadMedida.objects.none(),
        required=True,
        empty_label=None  # obligatorio: sin opción vacía
    )
    tasa_impuesto = forms.ModelChoiceField(
        queryset=TasaImpuesto.objects.none(),
        required=False,
        empty_label="— Sin impuesto —"
    )

    class Meta:
        model = Producto
        fields = [
            "sku", "nombre", "marca", "categoria",
            "unidad_base", "tasa_impuesto", "activo",
            "es_serializado", "tiene_vencimiento",
        ]
        widgets = {
            "sku": forms.TextInput(attrs={"placeholder": "SKU o código interno"}),
            "nombre": forms.TextInput(attrs={"placeholder": "Nombre del producto"}),
        }
        help_texts = {
            "es_serializado": "Actívalo si cada unidad tiene número de serie.",
            "tiene_vencimiento": "Actívalo si el producto maneja fechas de vencimiento/lote.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Orden amigable en los selects
        self.fields["marca"].queryset = Marca.objects.all().order_by("nombre")
        self.fields["categoria"].queryset = CategoriaProducto.objects.all().order_by("nombre")
        self.fields["unidad_base"].queryset = UnidadMedida.objects.all().order_by("codigo")
        # Solo tasas activas (si usas el campo 'activo')
        self.fields["tasa_impuesto"].queryset = TasaImpuesto.objects.filter(activo=True).order_by("nombre")

        # Pequeños estilos genéricos (si usas tu CSS, serán inputs normales)
        for name, field in self.fields.items():
            if not isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault("class", "form-control")
            else:
                field.widget.attrs.setdefault("class", "form-check-input")

    def clean_sku(self):
        sku = (self.cleaned_data.get("sku") or "").strip()
        return sku.upper()  # normalizamos para evitar duplicados por mayúsc/minúsc

    def clean_nombre(self):
        return (self.cleaned_data.get("nombre") or "").strip()

    def clean(self):
        cd = super().clean()
        # Ejemplo: no restringimos que sea serializado y con vencimiento a la vez,
        # pero aquí podrías advertir o validar reglas de negocio si quisieras.
        # if cd.get("es_serializado") and cd.get("tiene_vencimiento"):
        #     self.add_error("tiene_vencimiento", "No combine serie y vencimiento (regla de negocio).")
        return cd

    def save(self, commit=True):
        obj = super().save(commit=False)
        # Asegura SKU normalizado
        obj.sku = (obj.sku or "").strip().upper()
        if commit:
            obj.save()
        return obj

class BaseModelForm(forms.ModelForm):
    """Pequeña utilidad para recortar espacios en CharFields."""
    def clean(self):
        cd = super().clean()
        for name, field in self.fields.items():
            if isinstance(field, forms.CharField) and cd.get(name) is not None:
                cd[name] = " ".join(cd[name].split())  # colapsa espacios
        return cd


# ============== TasaImpuesto ==============

class TasaImpuestoForm(BaseModelForm):
    class Meta:
        model = TasaImpuesto
        fields = ["nombre", "porcentaje", "activo"]
        widgets = {
            "nombre": forms.TextInput(attrs={"placeholder": "IVA, Exento, etc."}),
        }
        help_texts = {
            "porcentaje": "Ej: 19.000 para 19%. Usa 3 decimales.",
        }

    def clean_porcentaje(self):
        p = self.cleaned_data.get("porcentaje")
        # Acepta entre 0 y 1000 por seguridad (19.000 es típico)
        if p is None or p < 0 or p > 1000:
            raise forms.ValidationError("Porcentaje fuera de rango válido.")
        return p


# ============== UnidadMedida ==============

class UnidadMedidaForm(BaseModelForm):
    class Meta:
        model = UnidadMedida
        fields = ["codigo", "descripcion"]
        widgets = {
            "codigo": forms.TextInput(attrs={"placeholder": "EA, KG, LT…"}),
        }

    def clean_codigo(self):
        code = (self.cleaned_data.get("codigo") or "").strip()
        return code.upper()  # normalizamos a mayúsculas


# ============== ConversionUM ==============

class ConversionUMForm(BaseModelForm):
    class Meta:
        model = ConversionUM
        fields = ["unidad_desde", "unidad_hasta", "factor"]
        help_texts = {
            "factor": "Factor de conversión (ej: 1000 para KG→G si defines desde=KG, hasta=G).",
        }

    def clean(self):
        cd = super().clean()
        u_from = cd.get("unidad_desde")
        u_to = cd.get("unidad_hasta")
        factor = cd.get("factor")

        if u_from and u_to and u_from == u_to:
            self.add_error("unidad_hasta", "La unidad destino debe ser distinta a la unidad origen.")
        if factor is None or factor <= 0:
            self.add_error("factor", "El factor debe ser mayor a 0.")
        return cd


# ============== Marca ==============

class MarcaForm(BaseModelForm):
    class Meta:
        model = Marca
        fields = ["nombre"]
        widgets = {
            "nombre": forms.TextInput(attrs={"placeholder": "Nombre de la marca"}),
        }

    def clean_nombre(self):
        # Normaliza: quita espacios adicionales y aplica "title"
        nombre = (self.cleaned_data.get("nombre") or "").strip()
        # Si prefieres mantener mayúsculas exactas del usuario, quita la siguiente línea:
        nombre = " ".join(nombre.split())
        return nombre


# ============== CategoriaProducto ==============

class CategoriaProductoForm(BaseModelForm):
    padre = forms.ModelChoiceField(
        queryset=CategoriaProducto.objects.none(),
        required=False,
        empty_label="— Sin categoría padre —"
    )

    class Meta:
        model = CategoriaProducto
        fields = ["padre", "nombre", "codigo"]
        widgets = {
            "nombre": forms.TextInput(attrs={"placeholder": "Nombre de la categoría"}),
            "codigo": forms.TextInput(attrs={"placeholder": "Código interno opcional"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        qs = CategoriaProducto.objects.all().order_by("nombre")
        # Evitar que elija a sí misma como padre al editar:
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        self.fields["padre"].queryset = qs

    def clean_nombre(self):
        return (self.cleaned_data.get("nombre") or "").strip()

    def clean_codigo(self):
        return (self.cleaned_data.get("codigo") or "").strip()





class SucursalForm(forms.ModelForm):
    class Meta:
        model = Sucursal
        fields = ["codigo", "nombre", "direccion", "ciudad", "region", "pais", "activo"]
        labels = {
            "codigo": "Código",
            "nombre": "Nombre de la sucursal",
            "direccion": "Dirección",
            "ciudad": "Ciudad",
            "region": "Región / Estado",
            "pais": "País",
            "activo": "Activa",
        }
        help_texts = {
            "codigo": "Máximo 20 caracteres. Usa un código corto y único (p. ej. SCL-01).",
        }
        widgets = {
            "codigo": forms.TextInput(attrs={
                "class": "form-control",
                "maxlength": "20",
                "placeholder": "Ej: SCL-01",
                "autocomplete": "off",
            }),
            "nombre": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Nombre comercial de la sucursal",
            }),
            "direccion": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Calle, número, comuna/barrio",
            }),
            "ciudad": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Ej: Santiago",
            }),
            "region": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Ej: Metropolitana",
            }),
            "pais": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Ej: Chile",
            }),
            "activo": forms.CheckboxInput(attrs={
                "class": "form-check-input",
            }),
        }

    def clean_codigo(self):
        codigo = (self.cleaned_data.get("codigo") or "").strip().upper()
        if " " in codigo:
            # si quieres permitir espacios, elimina esta validación
            raise ValidationError("El código no debe contener espacios.")
        return codigo

    def clean_nombre(self):
        nombre = (self.cleaned_data.get("nombre") or "").strip()
        if len(nombre) < 3:
            raise ValidationError("El nombre debe tener al menos 3 caracteres.")
        return nombre
    



class BodegaForm(forms.ModelForm):
    class Meta:
        model = Bodega
        fields = ["sucursal", "codigo", "nombre", "descripcion", "activo"]
        labels = {
            "sucursal": "Sucursal",
            "codigo": "Código de bodega",
            "nombre": "Nombre de la bodega",
            "descripcion": "Descripción",
            "activo": "Activa",
        }
        help_texts = {
            "codigo": "Código corto y único dentro de la sucursal. Ej: BOD-01",
        }
        widgets = {
            "sucursal": forms.Select(attrs={"class": "form-select"}),
            "codigo": forms.TextInput(attrs={
                "class": "form-control", "maxlength": "20", "placeholder": "Ej: BOD-01",
            }),
            "nombre": forms.TextInput(attrs={
                "class": "form-control", "placeholder": "Nombre visible de la bodega",
            }),
            "descripcion": forms.Textarea(attrs={
                "class": "form-control", "rows": 3, "placeholder": "Opcional",
            }),
            "activo": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def clean_codigo(self):
        codigo = (self.cleaned_data.get("codigo") or "").strip().upper()
        if " " in codigo:
            raise ValidationError("El código no debe contener espacios.")
        return codigo

    def clean_nombre(self):
        nombre = (self.cleaned_data.get("nombre") or "").strip()
        if len(nombre) < 3:
            raise ValidationError("El nombre debe tener al menos 3 caracteres.")
        return nombre
    
class AreaBodegaForm(forms.ModelForm):
    class Meta:
        model = AreaBodega
        fields = ["bodega", "codigo", "nombre"]
        widgets = {
            "codigo": forms.TextInput(attrs={"placeholder": "Código interno del área (único por bodega)"}),
            "nombre": forms.TextInput(attrs={"placeholder": "Nombre descriptivo del área"}),
        }

    def clean(self):
        cd = super().clean()
        bodega = cd.get("bodega")
        codigo = (cd.get("codigo") or "").strip()
        if bodega and codigo:
            # evita confundir mayúsculas/minúsculas
            if AreaBodega.objects.filter(bodega=bodega, codigo__iexact=codigo)\
                                 .exclude(pk=self.instance.pk if self.instance.pk else None).exists():
                self.add_error("codigo", "Ya existe un área con este código en la misma bodega.")
        return cd


class TipoUbicacionForm(forms.ModelForm):
    class Meta:
        model = TipoUbicacion
        fields = ["codigo", "descripcion"]
        widgets = {
            "codigo": forms.TextInput(attrs={"placeholder": "BIN, RACK, FLOOR, STAGE…"}),
            "descripcion": forms.TextInput(attrs={"placeholder": "Descripción corta"}),
        }


class UbicacionForm(forms.ModelForm):
    class Meta:
        model = Ubicacion
        fields = ["bodega", "area", "tipo", "codigo", "nombre", "pickeable", "almacenable"]
        widgets = {
            "codigo": forms.TextInput(attrs={"placeholder": "Ej: R01-A2-B3"}),
            "nombre": forms.TextInput(attrs={"placeholder": "Nombre visible (opcional)"}),
        }


    

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # si llega una bodega preseleccionada, limitamos el queryset de Area a esa bodega
        bodega = None
        if self.is_bound:
            try:
                bodega_id = int(self.data.get("bodega") or 0)
                from .models import Bodega as _B
                bodega = _B.objects.filter(pk=bodega_id).first()
            except Exception:
                bodega = None
        elif self.instance and self.instance.pk:
            bodega = self.instance.bodega

        if bodega:
            self.fields["area"].queryset = AreaBodega.objects.filter(bodega=bodega).order_by("codigo")
        else:
            self.fields["area"].queryset = AreaBodega.objects.none()

    def clean(self):
        cd = super().clean()
        bodega = cd.get("bodega")
        codigo = (cd.get("codigo") or "").strip()
        if bodega and codigo:
            if Ubicacion.objects.filter(bodega=bodega, codigo__iexact=codigo)\
                                .exclude(pk=self.instance.pk if self.instance.pk else None).exists():
                self.add_error("codigo", "Ya existe una ubicación con ese código en esta bodega.")
        return cd
    

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # filtrar áreas por bodega seleccionada (ya lo tienes)
        ...
        # etiquetas bonitas:
        self.fields["area"].label_from_instance = lambda obj: (
            f"{obj.bodega.sucursal.codigo}/{obj.bodega.codigo} · {obj.codigo} — {obj.nombre}"
            if obj.bodega and obj.bodega.sucursal else f"{obj.codigo} — {obj.nombre}"
        )
        self.fields["tipo"].label_from_instance = lambda obj: (
            f"{obj.codigo} — {obj.descripcion}"
        )