# =============================================
#  LIBRERÍAS ESTÁNDAR DE PYTHON
# =============================================
import json
import logging
from datetime import timezone

from core.alerts.services import trigger_low_stock_alert

# Configurar el logger
logger = logging.getLogger(__name__)

from django.db.models import Sum, F



from django.db.models import (
    Sum, Value, DecimalField, F, Case, When, CharField
)
from django.db.models.functions import Coalesce

# =============================================
#  LIBRERÍAS DE DJANGO
# =============================================
from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.auth.models import User, Group
from django.contrib.messages.views import SuccessMessageMixin
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import (
    Q, Sum, F, Value, Count, DecimalField, ExpressionWrapper
)
from django.db.models.functions import Coalesce, Lower
from django.http import (
    HttpResponse, Http404, JsonResponse,
    HttpResponseBadRequest, HttpResponseRedirect
)
from django.core.mail import send_mail

from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse, reverse_lazy, NoReverseMatch
from django.views import View
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView
from django.db.models.functions import Lower
from django.db.models import Count
import requests
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST
from core.utils import ensure_ubicacion_bodega, ensure_ubicacion_sucursal



# =============================================
#  MÓDULOS DEL PROYECTO (CORE)
# =============================================
from core.forms import *
from core.forms import SignupUserForm, UsuarioPerfilForm
from core.models import *
from core.models import Producto, UsuarioPerfil
from core.utils import ensure_ubicacion_sucursal    
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings




def notificar_stock_bajo(producto, nombre_lugar, stock_actual):
    """
    Envía correo HTML cuando el stock en 'nombre_lugar' baja de 10.
    """
    if stock_actual is None or stock_actual >= 10:
        return

    context = {
        "producto": producto,
        "sku": producto.sku,
        "sucursal": nombre_lugar,   # puede ser sucursal o bodega
        "stock": stock_actual,
    }

    subject = f"⚠️ Alerta de stock bajo - {producto.nombre}"
    text_content = (
        f"El stock del producto {producto.nombre} (SKU {producto.sku}) en "
        f"{nombre_lugar} es inferior a 10 unidades. Quedan {stock_actual}."
    )
    html_content = render_to_string("emails/alerta_stock.html", context)

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_content,
        from_email=settings.EMAIL_HOST_USER,
        to=settings.TICKETS_NOTIFY_EMAILS,
    )
    msg.attach_alternative(html_content, "text/html")
    msg.send(fail_silently=False)



# -------------------- Vistas principales --------------------
def dashboard(request):
    return render(request, "core/dashboard.html")

@login_required
def products(request):
    q = (request.GET.get("q") or "").strip()

    queryset = (
        Producto.objects.select_related("marca", "categoria", "unidad_base", "tasa_impuesto")
        .annotate(
            proveedores_count=Count("usuarios_proveedor", distinct=True),
            lotes_count=Count("lotes", distinct=True),
            series_count=Count("series", distinct=True),
            total_stock=Coalesce(
                Sum("stocks__cantidad_disponible"),
                Value(0, output_field=DecimalField(max_digits=20, decimal_places=6)),
            ),
        )
        .order_by("nombre", "sku")
    )

    if q:
        terms = [t for t in q.replace("-", " ").split() if t]
        for t in terms:
            queryset = queryset.filter(
                Q(sku__icontains=t)
                | Q(nombre__icontains=t)
                | Q(marca__nombre__icontains=t)
                | Q(categoria__nombre__icontains=t)
            )

    paginator = Paginator(queryset, 20)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    return render(
        request,
        "core/products.html",
        {
            "q": q,
            "productos": page_obj.object_list,
            "page_obj": page_obj,
            "is_paginated": page_obj.has_other_pages(),
        },
    )

@login_required
def category(request, slug):
    return render(request, "core/category.html", {"category_name": slug.replace("-", " ").title()})






from django.apps import apps






def _get_or_create_default_location(bodega):
    """
    Si el proyecto NO tiene Stock.bodega, pero SÍ trabaja con ubicacion_bodega,
    buscamos (o creamos) una ubicación por defecto en esa bodega.
    """
    # intenta resolver el modelo UbicacionBodega de tu app (ajusta 'core' si tu app se llama distinto)
    UbicacionBodega = None
    for app_label in ("core",):  # agrega otros app_labels si aplica
        try:
            UbicacionBodega = apps.get_model(app_label, "UbicacionBodega")
            break
        except LookupError:
            continue

    if UbicacionBodega is None:
        return None  # no existe ese modelo → no podemos setear ubicación

    # Busca / crea ubicación por defecto
    ubi, _ = UbicacionBodega.objects.get_or_create(
        bodega=bodega,
        codigo="DEF",
        defaults={"nombre": "General"}
    )
    return ubi


@login_required
@transaction.atomic
def product_add_combined(request):
    if request.method == "POST":
        pform = ProductoForm(request.POST, include_stock=False)
        sform = StockInlineForm(request.POST)

        if pform.is_valid() and sform.is_valid():
            # Si marca vencimiento, exige fecha
            if pform.cleaned_data.get("tiene_vencimiento") and not sform.cleaned_data.get("fecha_vencimiento"):
                sform.add_error("fecha_vencimiento", "Debes indicar una fecha de vencimiento para este producto.")
            else:
                # 1) Crear el producto
                producto = pform.save()

                # 2) Stock inicial + bodega seleccionada
                bodega = sform.cleaned_data["bodega"]
                cantidad = sform.cleaned_data["cantidad_inicial"] or 0

                stock_field_names = {f.name for f in Stock._meta.get_fields()}
                stock_kwargs = dict(
                    producto=producto,
                    cantidad_disponible=cantidad,
                )

                if "bodega" in stock_field_names:
                    # Caso 1: FK directa a Bodega
                    stock_kwargs["bodega"] = bodega
                else:
                    # Caso 2: usar ubicacion_bodega por defecto en esa bodega
                    ubi = _get_or_create_default_location(bodega)
                    if ubi and "ubicacion_bodega" in stock_field_names:
                        stock_kwargs["ubicacion_bodega"] = ubi

                # Crear el stock para el producto en la bodega
                Stock.objects.create(**stock_kwargs)

                # 3) Asignar stock a todas las sucursales de la bodega
                sucursales = Sucursal.objects.filter(bodega=bodega)
                for sucursal in sucursales:
                    ubi_sucursal = ensure_ubicacion_sucursal(sucursal)
                    Stock.objects.get_or_create(
                        producto=producto,
                        ubicacion_sucursal=ubi_sucursal,
                        defaults={"cantidad_disponible": Decimal("0")}  # Inicializamos en 0 si no hay cantidad
                    )

                # (opcional) recalcula stock global
                try:
                    total = (Stock.objects
                             .filter(producto=producto)
                             .aggregate(total=Sum("cantidad_disponible"))["total"]) or 0
                    producto.stock = total
                    producto.save(update_fields=["stock"])
                except Exception:
                    pass

                messages.success(request, "Producto y stock inicial registrados correctamente.")
                return redirect(reverse("producto-detail", args=[producto.id]))
    else:
        pform = ProductoForm(include_stock=False)
        sform = StockInlineForm()

    return render(request, "core/product_add.html", {"pform": pform, "sform": sform})



def _redirect_url_by_role(perfil):
    if not perfil or not perfil.rol:
        return reverse('dashboard')
    mapping = {
        'ADMIN': reverse('dashboard'),
        'BODEGUERO': reverse('products'),
        'AUDITOR': reverse('auditor_home'),
        'PROVEEDOR': reverse('proveedor_home'),
    }
    return mapping.get(perfil.rol, reverse('dashboard'))






























# -------------------- Login / Logout --------------------
def login_view(request):
    # Si ya estÃ¡ logueado, redirige segÃºn su rol
    if request.user.is_authenticated:
        perfil = getattr(request.user, 'perfil', None)
        return redirect(_redirect_url_by_role(perfil))

    next_url = request.GET.get('next') or request.POST.get('next')

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        remember = request.POST.get('remember') == 'on'

        user = authenticate(request, username=username, password=password)
        if user is not None and user.is_active:
            login(request, user)

            # "Recordarme": si NO marca, expira al cerrar el navegador
            if not remember:
                request.session.set_expiry(0)

            perfil = getattr(user, 'perfil', None)
            return redirect(next_url or _redirect_url_by_role(perfil))
        else:
            return render(request, 'accounts/login.html', {
                'error': 'Usuario o contraseÃ±a incorrectos',
                'next': next_url,
            })

    return render(request, 'accounts/login.html', {'next': next_url})

def logout_view(request):
    logout(request)
    return redirect('login')


@login_required
def dashboard_view(request):
    perfil = getattr(request.user, 'perfil', None)
    return redirect(_redirect_url_by_role(perfil))

@login_required
def auditor_home(request):
    # Puedes crear accounts/auditor_home.html si quieres contenido propio
    return render(request, 'accounts/auditor_home.html')

@login_required
def proveedor_home(request):
    return render(request, 'accounts/proveedor_home.html')


# -------------------- Signup (opcional, solo ADMIN) --------------------
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
        fields = ("telefono",)  # aÃ±ade mÃ¡s campos si quieres capturarlos al alta


def _is_admin(user: User) -> bool:
    try:
        if not user or not user.is_authenticated:
            return False
        # Superusuario del sistema siempre tiene permisos de ADMIN
        if getattr(user, 'is_superuser', False):
            return True
        # Asegura que exista perfil para usuarios creados de forma externa
        perfil, _ = UsuarioPerfil.objects.get_or_create(usuario=user)
        return perfil.rol == UsuarioPerfil.Rol.ADMIN
    except Exception:
        return False
    
def _sync_user_groups_by_profile(user: User):
    """
    Sincroniza el Group del usuario segÃºn su perfil.rol.
    """
    try:
        perfil = user.perfil
        if perfil and perfil.rol:
            # Asegura que existan todos los grupos
            for code, _ in UsuarioPerfil.Rol.choices:
                Group.objects.get_or_create(name=code)
            user.groups.clear()
            user.groups.add(Group.objects.get(name=perfil.rol))
    except Exception:
        pass


def admin_required(view_func):
    """Decorador para views basadas en funciones que redirige con mensaje si no es admin."""
    def _wrapped(request, *args, **kwargs):
        if not _is_admin(request.user):
            messages.error(request, "No tienes permisos para realizar esa acciÃ³n.")
            return redirect('dashboard')
        return view_func(request, *args, **kwargs)
    return _wrapped

@admin_required
@transaction.atomic
def signup(request):
    if request.method == "POST":
        user_form = SignupUserForm(request.POST)
        perfil_form = UsuarioPerfilForm(request.POST)

        if user_form.is_valid() and perfil_form.is_valid():
            user = user_form.save(commit=True)
            perfil, _ = UsuarioPerfil.objects.get_or_create(usuario=user)

            for field, value in perfil_form.cleaned_data.items():
                setattr(perfil, field, value)
            perfil.save()

            login(request, user)
            messages.success(request, "âœ… Usuario creado correctamente.")
            try:
                return redirect(reverse("usuario-list"))
            except NoReverseMatch:
                return redirect("dashboard")
        else:
            messages.error(request, "âŒ Revisa los errores del formulario.")
    else:
        user_form = SignupUserForm()
        perfil_form = UsuarioPerfilForm()

    return render(request, "accounts/sign.html", {"user_form": user_form, "perfil_form": perfil_form})
@admin_required
@transaction.atomic
def user_create(request):
    """
    Alta de usuario (User + UsuarioPerfil).
    Usa: accounts/sign.html (tu formulario existente).
    Si viene ?role=PROVEEDOR, se preselecciona ese rol.
    """
    preset_role = request.GET.get("role")
    if request.method == "POST":
        user_form = SignupUserForm(request.POST)
        perfil_form = UsuarioPerfilForm(request.POST)
        if user_form.is_valid() and perfil_form.is_valid():
            user = user_form.save(commit=True)

            perfil, _ = UsuarioPerfil.objects.get_or_create(usuario=user)
            # copiar campos del form al perfil
            for field, value in perfil_form.cleaned_data.items():
                setattr(perfil, field, value)

            # si vino role por query y no se cambiÃ³ en el form, respÃ©talo
            if preset_role and not perfil_form.cleaned_data.get("rol"):
                perfil.rol = preset_role

            perfil.save()
            _sync_user_groups_by_profile(user)

            messages.success(request, "âœ… Usuario creado correctamente.")
            return redirect("usuario-list")
        messages.error(request, "âŒ Revisa los errores del formulario.")
    else:
        user_form = SignupUserForm()
        # inicializa el rol si viene por query
        initial = {}
        if preset_role in dict(UsuarioPerfil.Rol.choices):
            initial["rol"] = preset_role
        perfil_form = UsuarioPerfilForm(initial=initial)

    return render(request, "accounts/sign.html", {
        "user_form": user_form,
        "perfil_form": perfil_form,
    })

@admin_required
@transaction.atomic
def user_edit(request, user_id: int):
    obj = get_object_or_404(User.objects.select_related("perfil"), pk=user_id)

    # Evitar que un admin se desactive/elimine a sÃ­ mismo por accidente (opcional)
    editing_self = (request.user.pk == obj.pk)

    # Asegurar que tenga perfil
    perfil, _ = UsuarioPerfil.objects.get_or_create(usuario=obj)

    if request.method == "POST":
        uform = UserEditForm(request.POST, instance=obj)
        pform = UsuarioPerfilEditForm(request.POST, instance=perfil)

        if uform.is_valid() and pform.is_valid():
            # No permitir que un usuario se desactive a sÃ­ mismo (opcional, seguridad)
            if editing_self and not uform.cleaned_data.get("is_active", True):
                messages.error(request, "No puedes desactivar tu propio usuario.")
            else:
                uform.save()
                pform.save()
                _sync_user_groups_by_profile(obj)
                messages.success(request, "âœ… Usuario actualizado.")
                return redirect("usuario-list")
        else:
            messages.error(request, "âŒ Revisa los errores del formulario.")
    else:
        uform = UserEditForm(instance=obj)
        pform = UsuarioPerfilEditForm(instance=perfil)

    return render(request, "accounts/user_form.html", {
        "obj": obj,
        "user_form": uform,
        "perfil_form": pform,
    })

@admin_required
@transaction.atomic
def user_delete(request, user_id: int):
    obj = get_object_or_404(User, pk=user_id)

    # Reglas de seguridad Ãºtiles:
    if request.user.pk == obj.pk:
        messages.error(request, "No puedes eliminar tu propio usuario.")
        return redirect("usuario-list")
    if obj.is_superuser:
        messages.error(request, "No puedes eliminar un superusuario.")
        return redirect("usuario-list")

    if request.method == "POST":
        obj.delete()
        messages.success(request, "ðŸ—‘ï¸ Usuario eliminado.")
        return redirect("usuario-list")

    return render(request, "accounts/user_confirm_delete.html", {"obj": obj})

@admin_required
@login_required
def user_list(request):
    """
    Listado con bÃºsqueda y filtro por rol.
    Template: accounts/user_list.html
    """
    q = (request.GET.get("q") or "").strip()
    rol = (request.GET.get("rol") or "").strip()

    qs = User.objects.select_related("perfil").order_by("username")

    if q:
        qs = qs.filter(
            Q(username__icontains=q)
            | Q(first_name__icontains=q)
            | Q(last_name__icontains=q)
            | Q(email__icontains=q)
        )

    if rol:
        # rol es un CharField con choices en UsuarioPerfil
        qs = qs.filter(perfil__rol=rol)

    paginator = Paginator(qs, 20)
    page = request.GET.get("page", 1)
    users_page = paginator.get_page(page)

    return render(
        request,
        "accounts/user_list.html",
        {
            "users": users_page,
            "q": q,
            "rol": rol,
            "roles": UsuarioPerfil.Rol.choices,  # (code, label)
        },
    )


@admin_required
@login_required
@require_POST
def usuario_set_rol(request, user_id: int):
    """
    Cambia el rol (perfil.rol) de un usuario vÃ­a fetch POST JSON.
    Espera: {"rol": "<CODE>"}   (donde CODE es uno de UsuarioPerfil.Rol.choices)
    Responde: {"ok": true, "rol_label": "<Etiqueta>"}  o {"ok": false, "error": "..."}
    """
    import json

    try:
        payload = json.loads(request.body or "{}")
        code = (payload.get("rol") or "").strip()
        if not code:
            return JsonResponse({"ok": False, "error": "Rol no especificado."}, status=400)

        # Validar que el code estÃ© en choices
        valid_map = dict(UsuarioPerfil.Rol.choices)   # {code: label}
        if code not in valid_map:
            return JsonResponse({"ok": False, "error": "CÃ³digo de rol invÃ¡lido."}, status=400)

        target = get_object_or_404(User, pk=user_id)

        # Protecciones: no tocar superuser ni al propio usuario
        if target.is_superuser or target.id == request.user.id:
            return JsonResponse({"ok": False, "error": "No puedes cambiar este rol."}, status=403)

        perfil = getattr(target, "perfil", None)
        if perfil is None:
            return JsonResponse({"ok": False, "error": "El usuario no tiene perfil."}, status=400)

        # Guardar el CharField
        perfil.rol = code
        perfil.save(update_fields=["rol"])

        return JsonResponse({"ok": True, "rol_label": valid_map[code]})
    except Exception as e:
        return JsonResponse({"ok": False, "error": str(e)}, status=400)

# -------------------- CRUD Sucursal / Bodega --------------------
class AdminOnlyMixin(UserPassesTestMixin):
    """Mixin para CBV que deja pasar sÃ³lo a ADMIN."""
    def test_func(self):
        return _is_admin(self.request.user)
    
    def handle_no_permission(self):
        # Redirige a dashboard con mensaje en lugar de mostrar 403
        messages.error(self.request, "No tienes permisos para realizar esa acciÃ³n.")
        return redirect('dashboard')


class BodegaPermissionMixin(UserPassesTestMixin):
    """Permite acceso si es ADMIN o BODEGUERO (validaciÃ³n por objeto aparte)."""
    def test_func(self):
        try:
            perfil = getattr(self.request.user, 'perfil', None)
            if not self.request.user.is_authenticated:
                return False
            if perfil and perfil.rol == UsuarioPerfil.Rol.ADMIN:
                return True
            if perfil and perfil.rol == UsuarioPerfil.Rol.BODEGUERO:
                return True
            return False
        except Exception:
            return False

    def handle_no_permission(self):
        messages.error(self.request, "No tienes permisos para realizar esa acciÃ³n.")
        return redirect('dashboard')


def admin_required(view_func):
    """Decorador para views basadas en funciones que redirige con mensaje si no es admin."""
    def _wrapped(request, *args, **kwargs):
        if not _is_admin(request.user):
            messages.error(request, "No tienes permisos para realizar esa acciÃ³n.")
            return redirect('dashboard')
        return view_func(request, *args, **kwargs)
    return _wrapped

class SucursalListView(LoginRequiredMixin, ListView):
    model = Sucursal
    template_name = "core/sucursal_list.html"
    context_object_name = "sucursales"
    paginate_by = 20  # por defecto

    def get_paginate_by(self, queryset):
        """
        Permite ?page_size= en la URL (mÃ¡x 100).
        """
        try:
            size = int(self.request.GET.get("page_size", self.paginate_by))
        except (TypeError, ValueError):
            size = self.paginate_by
        return max(1, min(size, 100))

    def get_queryset(self):
        q = (self.request.GET.get("q") or "").strip()

        # OJO con los related_name que tÃº dejaste en tus modelos:
        #   Sucursal  -> ubicaciones_sucursal   (FK en Ubicacion)
        #   Ubicacion -> stocks_ubicacion       (FK en Stock)
        #
        # Entonces el stock total por sucursal se puede sacar asÃ­:
        qs = (
            Sucursal.objects
            .select_related("bodega")  # para mostrar cÃ³digo/nombre de la bodega
            .prefetch_related(
                "ubicaciones",            # lista de ubicaciones de esa sucursal
                "ubicaciones__stocks",  # stocks por ubicación
            )
            .annotate(
                # suma de todas las cantidades en ESE sucursal
                total_stock=Coalesce(
                    Sum("ubicaciones__stocks__cantidad_disponible"),
                    Value(0, output_field=DecimalField(max_digits=20, decimal_places=6))
                ),
                # cuÃ¡ntas ubicaciones tiene esa sucursal
                ubicaciones_count=Count("ubicaciones", distinct=True),
                # cuÃ¡ntos productos tiene linkeados por M2M
                productos_count=Count("productos", distinct=True),
            )
            .only("id", "codigo", "nombre", "ciudad", "region", "pais", "activo", "bodega__codigo", "bodega__nombre")
            .order_by(Lower("codigo").asc())
        )

        if q:
            qs = qs.filter(
                Q(codigo__icontains=q) |
                Q(nombre__icontains=q) |
                Q(ciudad__icontains=q) |
                Q(region__icontains=q) |
                Q(bodega__codigo__icontains=q) |
                Q(bodega__nombre__icontains=q)
            )

        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        q = (self.request.GET.get("q") or "").strip()
        ctx["q"] = q
        ctx["has_filters"] = bool(q)
        ctx["total"] = self.get_queryset().count()
        ctx["page_size"] = self.get_paginate_by(self.get_queryset())
        return ctx

class SucursalCreateView(LoginRequiredMixin, AdminOnlyMixin, SuccessMessageMixin, CreateView):
    model = Sucursal
    form_class = SucursalForm
    template_name = "core/sucursal_form.html"
    success_message = "Sucursal creada correctamente."

    def get_success_url(self):
        return reverse_lazy("sucursal-list")


class SucursalUpdateView(LoginRequiredMixin, AdminOnlyMixin, SuccessMessageMixin, UpdateView):
    model = Sucursal
    form_class = SucursalForm
    template_name = "core/sucursal_form.html"
    success_message = "Sucursal actualizada correctamente."

    def get_success_url(self):
        return reverse_lazy("sucursal-list")



@login_required
@require_POST
def sucursal_delete_json(request, pk):
    suc = get_object_or_404(Sucursal, pk=pk)
    try:
        suc.delete()
        return JsonResponse({"ok": True})
    except ProtectedError:
        return JsonResponse({"ok": False, "error": "La sucursal tiene relaciones protegidas."}, status=400)
    except Exception as e:
        return JsonResponse({"ok": False, "error": str(e)}, status=400)
    





@login_required
def sucursal_dispositivos(request, pk):
    sucursal = get_object_or_404(Sucursal, pk=pk)
    q = (request.GET.get("q") or "").strip()

    # Filtrar por las ubicaciones que pertenecen a esta sucursal
    productos = (
        Stock.objects
        .filter(ubicacion_sucursal__sucursal_id=pk)
        .values("producto__id", "producto__sku", "producto__nombre")
        .annotate(
            stock_total=Coalesce(
                Sum("cantidad_disponible"),
                Value(0, output_field=DecimalField(max_digits=20, decimal_places=6)),
            )
        )
        .order_by("producto__sku")
    )

    if q:
        productos = productos.filter(
            Q(producto__sku__icontains=q) |
            Q(producto__nombre__icontains=q)
        )

    total_items = productos.count()
    # suma_stock puede venir en Decimal: convertir a float/int si lo necesitas
    suma_stock = sum([p["stock_total"] or 0 for p in productos])

    return render(
        request,
        "core/Movimientos/sucursal_productos.html",
        {
            "sucursal": sucursal,
            "q": q,
            "productos": productos,
            "total_items": total_items,
            "suma_stock": suma_stock,
        },
    )

@login_required
def ajax_ubicaciones_por_producto_sucursal(request):
    sucursal_id = request.GET.get("sucursal_id")
    producto_id = request.GET.get("producto_id")
    if not sucursal_id or not producto_id:
        return JsonResponse({"error": "Parámetros incompletos."}, status=400)

    filas = (
        Stock.objects
        .filter(
            ubicacion_sucursal__sucursal_id=sucursal_id,  # <- clave correcta
            producto_id=producto_id,
            cantidad_disponible__gt=0,
        )
        .values("ubicacion_sucursal__codigo", "ubicacion_sucursal__nombre")
        .annotate(
            cantidad=Coalesce(
                Sum("cantidad_disponible"),
                Value(0, output_field=DecimalField(max_digits=20, decimal_places=6)),
            )
        )
        .order_by("ubicacion_sucursal__codigo")
    )

    ubicaciones = [
        {
            "codigo": f["ubicacion_sucursal__codigo"],
            "nombre": f["ubicacion_sucursal__nombre"],
            "cantidad": float(f["cantidad"]),
        }
        for f in filas
    ]
    return JsonResponse({"ubicaciones": ubicaciones})



class BodegaListView(LoginRequiredMixin, ListView):
    model = Bodega
    template_name = "core/bodega_list.html"
    context_object_name = "bodegas"
    paginate_by = 20

    def get_paginate_by(self, queryset):
        try:
            size = int(self.request.GET.get("page_size", self.paginate_by))
        except (TypeError, ValueError):
            size = self.paginate_by
        return max(1, min(size, 100))

    def get_queryset(self):
        q = (self.request.GET.get("q") or "").strip()

        qs = (
            Bodega.objects
            .prefetch_related("ubicaciones", "sucursales")
            .order_by(Lower("codigo").asc())
        )

        if q:
            qs = qs.filter(
                Q(codigo__icontains=q) |
                Q(nombre__icontains=q) |
                Q(descripcion__icontains=q) |
                Q(sucursales__nombre__icontains=q)
            ).distinct()

        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        page_obj = ctx["page_obj"]
        bodegas_page = list(page_obj.object_list)

        # todas las ubicaciones de las bodegas de esta página
        ubi_ids = []
        for b in bodegas_page:
            for u in b.ubicaciones.all():
                ubi_ids.append(u.id)

        # traemos el stock de esas ubicaciones
        stock_qs = (
            Stock.objects
            .filter(ubicacion_bodega_id__in=ubi_ids)
            .select_related("producto", "ubicacion_bodega")
        )

        # indexar por id de ubicacion
        stock_por_ubi = {}
        for s in stock_qs:
            stock_por_ubi.setdefault(s.ubicacion_bodega_id, []).append(s)

        # inyectar a cada bodega
        for b in bodegas_page:
            detalle = []
            for u in b.ubicaciones.all():
                detalle.extend(stock_por_ubi.get(u.id, []))

            b.productos_con_stock = detalle
            b.total_stock = sum(d.cantidad_disponible for d in detalle)
            b.sucursales_count = b.sucursales.count()
            b.ubicaciones_count = b.ubicaciones.count()
            b.productos_count = len({d.producto_id for d in detalle})

        # para el <select> del modal
        ctx["productos"] = (
            Producto.objects
            .only("id", "sku", "nombre")
            .order_by("nombre")
        )

        ctx["q"] = (self.request.GET.get("q") or "").strip()
        return ctx

class BodegaCreateView(LoginRequiredMixin, BodegaPermissionMixin, SuccessMessageMixin, CreateView):
    model = Bodega
    form_class = BodegaForm
    template_name = "core/bodega_form.html"
    success_message = "Bodega creada correctamente."

    def get_success_url(self):
        return reverse_lazy("bodega-list")

    def get_form(self, form_class=None):
        """Restringe 'sucursal' para BODEGUERO (no para ADMIN/superuser)."""
        form = super().get_form(form_class)
        perfil = getattr(self.request.user, "perfil", None)

        # Superusuario o ADMIN: sin restricciÃ³n
        if self.request.user.is_superuser or (perfil and perfil.rol == UsuarioPerfil.Rol.ADMIN):
            return form

        # BODEGUERO: limitar queryset a su sucursal (o ninguno si no tiene)
        if perfil and perfil.rol == UsuarioPerfil.Rol.BODEGUERO:
            if getattr(perfil, "sucursal", None):
                form.fields["sucursal"].queryset = Sucursal.objects.filter(pk=perfil.sucursal.pk)
            else:
                form.fields["sucursal"].queryset = Sucursal.objects.none()
        return form

    def form_valid(self, form):
        """Fuerza la sucursal del BODEGUERO en el servidor (anti-manipulaciÃ³n)."""
        perfil = getattr(self.request.user, "perfil", None)
        if not self.request.user.is_superuser and perfil and perfil.rol == UsuarioPerfil.Rol.BODEGUERO:
            if getattr(perfil, "sucursal", None):
                form.instance.sucursal = perfil.sucursal
            else:
                messages.error(self.request, "No tienes una sucursal asignada.")
                return super().form_invalid(form)
        return super().form_valid(form)


class BodegaUpdateView(LoginRequiredMixin, BodegaPermissionMixin, SuccessMessageMixin, UpdateView):
    model = Bodega
    form_class = BodegaForm
    template_name = "core/bodega_form.html"
    success_message = "Bodega actualizada correctamente."

    def get_success_url(self):
        return reverse_lazy("bodega-list")

    def dispatch(self, request, *args, **kwargs):
        """BODEGUERO solo puede editar bodegas (salvo superuser)."""
        perfil = getattr(request.user, "perfil", None)
        if not request.user.is_superuser and perfil and perfil.rol == UsuarioPerfil.Rol.BODEGUERO:
            obj = self.get_object()
            if not obj or obj.sucursal_id != (perfil.sucursal.id if getattr(perfil, "sucursal", None) else None):
                messages.error(request, "No tienes permisos para editar esta bodega.")
                return redirect("bodega-list")
        return super().dispatch(request, *args, **kwargs)

    def get_form(self, form_class=None):
        """Restringe select de 'sucursal' para BODEGUERO; ADMIN/superuser ven todo."""
        form = super().get_form(form_class)
        perfil = getattr(self.request.user, "perfil", None)

        if self.request.user.is_superuser or (perfil and perfil.rol == UsuarioPerfil.Rol.ADMIN):
            return form

        if perfil and perfil.rol == UsuarioPerfil.Rol.BODEGUERO:
            if getattr(perfil, "sucursal", None):
                form.fields["sucursal"].queryset = Sucursal.objects.filter(pk=perfil.sucursal.pk)
            else:
                form.fields["sucursal"].queryset = Sucursal.objects.none()
        return form

from django.db.models.deletion import ProtectedError


@login_required
@require_POST
def bodega_delete(request, pk):
    bodega = get_object_or_404(Bodega, pk=pk)
    nombre = bodega.nombre
    try:
        bodega.delete()
        messages.success(request, f"Bodega “{nombre}” eliminada correctamente.")
    except ProtectedError:
        messages.error(request, f"No se puede eliminar “{nombre}” porque tiene elementos asociados.")
    return redirect('bodega-list')


class BodegaDetailView(LoginRequiredMixin, DetailView):
    model = Bodega
    template_name = "core/bodega_detail.html"
    context_object_name = "bodega"

#Area de productos

class ProductsListView(LoginRequiredMixin, ListView):
    model = Producto
    template_name = "core/products.html"
    context_object_name = "productos"
    paginate_by = 20

    def get_queryset(self):
        q = (self.request.GET.get("q") or "").strip()

        qs = (
            Producto.objects
            .select_related("marca", "categoria", "unidad_base")
            # para que no haga N+1 al mostrar la primera ubicaciÃ³n
            .prefetch_related(
                "stocks_producto",
                "stocks_producto__ubicacion",
                "stocks_producto__ubicacion__bodega",
                "stocks_producto__ubicacion__sucursal",
            )
            .annotate(
                # stock real = suma de las filas de Stock de ese producto
                total_stock=Coalesce(
                    Sum("stocks_producto__cantidad_disponible"),
                    Value(0, output_field=DecimalField(max_digits=20, decimal_places=6))
                ),
                proveedores_count=Count("usuarios_proveedor", distinct=True),
                lotes_count=Count("lotes", distinct=True),
                series_count=Count("series", distinct=True),
            )
            .order_by("nombre")
        )

        if q:
            qs = qs.filter(
                Q(sku__icontains=q)
                | Q(nombre__icontains=q)
                | Q(marca__nombre__icontains=q)
                | Q(categoria__nombre__icontains=q)
            )

        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["q"] = (self.request.GET.get("q") or "").strip()
        return ctx



class ProductCreateView(LoginRequiredMixin, SuccessMessageMixin, CreateView):
    model = Producto
    form_class = ProductoForm
    template_name = "core/product_add.html"
    success_message = "Producto creado correctamente."

    def get_success_url(self):
        return reverse_lazy("products")


class ProductUpdateView(LoginRequiredMixin, SuccessMessageMixin, UpdateView):
    model = Producto
    form_class = ProductoForm
    template_name = "core/product_add.html"
    success_message = "Producto actualizado correctamente."

    def form_valid(self, form):
        resp = super().form_valid(form)
        nxt = self.request.POST.get("next") or self.request.GET.get("next")
        if nxt:
            return redirect(nxt)
        return resp

    def get_success_url(self):
        return reverse_lazy("products")
    




class ProductUpdateView(LoginRequiredMixin, SuccessMessageMixin, UpdateView):

    model = Producto
    form_class = ProductoForm
    template_name = "core/product_update.html"
    context_object_name = "producto"
    success_message = "Producto actualizado correctamente."

    # ---------- Queryset “rápido” ----------
    def get_queryset(self):
        return (Producto.objects
                .select_related("marca", "categoria", "unidad_base", "tasa_impuesto"))

  
    pk_url_kwarg = "pk"
    slug_url_kwarg = "sku"
    slug_field = "sku"

    def get_object(self, queryset=None):
        qs = queryset or self.get_queryset()
        # 1) Prioridad: si hay <pk> en la URL, úsalo
        pk = self.kwargs.get(self.pk_url_kwarg)
        if pk is not None:
            try:
                return qs.get(pk=pk)
            except Producto.DoesNotExist:
                raise Http404("Producto no encontrado.")
        # 2) Si hay <sku> en la URL, úsalo
        sku_kw = self.kwargs.get(self.slug_url_kwarg)
        if sku_kw:
            try:
                return qs.get(sku=str(sku_kw).upper())
            except Producto.DoesNotExist:
                raise Http404("Producto no encontrado.")
        # 3) Fallback: si llega ?sku= en querystring
        sku_qs = (self.request.GET.get("sku") or "").strip().upper()
        if sku_qs:
            try:
                return qs.get(sku=sku_qs)
            except Producto.DoesNotExist:
                raise Http404("Producto no encontrado.")
        return super().get_object(qs)

    # ---------- Pasar flag al form ----------
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        # Editar solo metadatos del producto (no stock)
        kwargs["include_stock"] = False
        return kwargs

    # ---------- UX de errores ----------
    def form_invalid(self, form):
        # muestra un resumen arriba sin obligarte a inspeccionar campo por campo
        errors = []
        for name, field_errors in form.errors.items():
            for e in field_errors:
                errors.append(f"{name}: {e}")
        if errors:
            messages.error(self.request, "No se pudo actualizar el producto. Revisa los campos.")
        return super().form_invalid(form)

    # ---------- Redirecciones ----------
    def form_valid(self, form):
        resp = super().form_valid(form)
        nxt = self.request.POST.get("next") or self.request.GET.get("next")
        if nxt:
            return redirect(nxt)
        return resp

    def get_success_url(self):
        # Si hay ?next= úsalo, si no, vuelve al detalle del propio producto
        nxt = self.request.POST.get("next") or self.request.GET.get("next")
        if nxt:
            return nxt
        try:
            return reverse("producto-detail", args=[self.object.pk])
        except Exception:
            return reverse_lazy("products")



class ProductDeleteView(LoginRequiredMixin, DeleteView):
    model = Producto
    template_name = "core/product_confirm_delete.html"  # fallback si navegas directo
    success_url = reverse_lazy("products")

    def delete(self, request, *args, **kwargs):
        messages.success(request, "Producto eliminado correctamente.")
        return super().delete(request, *args, **kwargs)


class ProductDetailView(LoginRequiredMixin, DetailView):
    """
    Detalle de producto con:
      - info general del producto
      - métricas (stock total disponible, precio, estado)
      - desglose de stock por sucursal/bodega/ubicación
    """
    model = Producto
    template_name = "core/product_detail.html"
    context_object_name = "producto"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        producto = self.object

        # Totales (si no hay reservas, neto = disponible)
        agg = (
            Stock.objects
            .filter(producto=producto)
            .aggregate(
                total_disponible=Coalesce(
                    Sum("cantidad_disponible"),
                    Value(0, output_field=DecimalField(max_digits=20, decimal_places=6))
                )
            )
        )
        total_disponible = agg["total_disponible"] or 0
        ctx["totales"] = {
            "total_disponible": total_disponible,
            "total_neto": total_disponible,
        }

        # Desglose por sucursal/bodega/ubicación (campos opcionales seguros)
        resumen = (
            Stock.objects
            .filter(producto=producto)
            .annotate(
                sucursal_codigo=Case(
                    When(ubicacion_sucursal__isnull=False, then=F("ubicacion_sucursal__sucursal__codigo")),
                    default=Value("", output_field=CharField()),
                ),
                sucursal_nombre=Case(
                    When(ubicacion_sucursal__isnull=False, then=F("ubicacion_sucursal__sucursal__nombre")),
                    default=Value("", output_field=CharField()),
                ),
                bodega_codigo=Case(
                    When(ubicacion_bodega__isnull=False, then=F("ubicacion_bodega__bodega__codigo")),
                    default=Value("", output_field=CharField()),
                ),
                bodega_nombre=Case(
                    When(ubicacion_bodega__isnull=False, then=F("ubicacion_bodega__bodega__nombre")),
                    default=Value("", output_field=CharField()),
                ),
                # ubicación física (si existen esos campos)
                sucursal_ubi_codigo=Case(
                    When(ubicacion_sucursal__isnull=False, then=F("ubicacion_sucursal__codigo")),
                    default=Value("", output_field=CharField()),
                ),
                sucursal_ubi_nombre=Case(
                    When(ubicacion_sucursal__isnull=False, then=F("ubicacion_sucursal__nombre")),
                    default=Value("", output_field=CharField()),
                ),
                bodega_ubi_codigo=Case(
                    When(ubicacion_bodega__isnull=False, then=F("ubicacion_bodega__codigo")),
                    default=Value("", output_field=CharField()),
                ),
                bodega_ubi_nombre=Case(
                    When(ubicacion_bodega__isnull=False, then=F("ubicacion_bodega__nombre")),
                    default=Value("", output_field=CharField()),
                ),
            )
            .values(
                "sucursal_codigo", "sucursal_nombre",
                "bodega_codigo", "bodega_nombre",
                "sucursal_ubi_codigo", "sucursal_ubi_nombre",
                "bodega_ubi_codigo", "bodega_ubi_nombre",
            )
            .annotate(
                total_disponible=Coalesce(
                    Sum("cantidad_disponible"),
                    Value(0, output_field=DecimalField(max_digits=20, decimal_places=6))
                ),
                total_neto=F("total_disponible"),
            )
            .order_by(
                "sucursal_codigo",
                "bodega_codigo",
                "sucursal_ubi_codigo",
                "bodega_ubi_codigo",
            )
        )

        ctx["resumen_sucursales"] = resumen
        return ctx

# ----------------------
# CRUD Ubicacion (pÃ¡ginas)
# ----------------------
class UbicacionBodegaListView(LoginRequiredMixin, ListView):
    model = UbicacionBodega
    template_name = "core/ubicacion_bodega_list.html"
    context_object_name = "ubicaciones"
    paginate_by = 20

    def get_queryset(self):
        q = (self.request.GET.get("q") or "").strip()
        bodega_id = (self.request.GET.get("bodega") or "").strip()

        qs = (
            UbicacionBodega.objects.select_related("bodega", "tipo")
            .annotate(
                total_stock=Coalesce(
                    Sum("stocks__cantidad_disponible"),
                    Value(0, output_field=DecimalField(max_digits=20, decimal_places=6)),
                )
            )
            .order_by("bodega__codigo", "codigo")
        )

        if q:
            qs = qs.filter(Q(codigo__icontains=q) | Q(nombre__icontains=q) | Q(area__icontains=q))

        if bodega_id:
            qs = qs.filter(bodega_id=bodega_id)

        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["bodegas"] = Bodega.objects.all().order_by("codigo")
        ctx["q"] = (self.request.GET.get("q") or "").strip()
        ctx["f_bodega"] = (self.request.GET.get("bodega") or "").strip()
        return ctx


class UbicacionSucursalListView(LoginRequiredMixin, ListView):
    model = UbicacionSucursal
    template_name = "core/ubicacion_sucursal_list.html"
    context_object_name = "ubicaciones"
    paginate_by = 20

    def get_queryset(self):
        q = (self.request.GET.get("q") or "").strip()
        sucursal_id = (self.request.GET.get("sucursal") or "").strip()

        qs = (
            UbicacionSucursal.objects.select_related("sucursal", "tipo")
            .annotate(
                total_stock=Coalesce(
                    Sum("stocks__cantidad_disponible"),
                    Value(0, output_field=DecimalField(max_digits=20, decimal_places=6)),
                )
            )
            .order_by("sucursal__codigo", "codigo")
        )

        if q:
            qs = qs.filter(Q(codigo__icontains=q) | Q(nombre__icontains=q) | Q(area__icontains=q))

        if sucursal_id:
            qs = qs.filter(sucursal_id=sucursal_id)

        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["sucursales"] = Sucursal.objects.all().order_by("codigo")
        ctx["q"] = (self.request.GET.get("q") or "").strip()
        ctx["f_sucursal"] = (self.request.GET.get("sucursal") or "").strip()
        return ctx


class UbicacionBodegaCreateView(LoginRequiredMixin, SuccessMessageMixin, CreateView):
    model = UbicacionBodega
    form_class = UbicacionBodegaForm
    template_name = "core/ubicacion_form.html"
    success_message = "Ubicación de bodega creada."
    success_url = reverse_lazy("ubicacion-bodega-list")


class UbicacionBodegaUpdateView(LoginRequiredMixin, SuccessMessageMixin, UpdateView):
    model = UbicacionBodega
    form_class = UbicacionBodegaForm
    template_name = "core/ubicacion_form.html"
    success_message = "Ubicación de bodega actualizada."
    success_url = reverse_lazy("ubicacion-bodega-list")


class UbicacionBodegaDeleteView(LoginRequiredMixin, DeleteView):
    model = UbicacionBodega
    template_name = "core/confirm_delete.html"
    success_url = reverse_lazy("ubicacion-bodega-list")

    def delete(self, request, *args, **kwargs):
        messages.success(request, "Ubicación eliminada.")
        return super().delete(request, *args, **kwargs)


class UbicacionSucursalCreateView(LoginRequiredMixin, SuccessMessageMixin, CreateView):
    model = UbicacionSucursal
    form_class = UbicacionSucursalForm
    template_name = "core/ubicacion_form.html"
    success_message = "Ubicación de sucursal creada."
    success_url = reverse_lazy("ubicacion-sucursal-list")


class UbicacionSucursalUpdateView(LoginRequiredMixin, SuccessMessageMixin, UpdateView):
    model = UbicacionSucursal
    form_class = UbicacionSucursalForm
    template_name = "core/ubicacion_form.html"
    success_message = "Ubicación de sucursal actualizada."
    success_url = reverse_lazy("ubicacion-sucursal-list")


class UbicacionSucursalDeleteView(LoginRequiredMixin, DeleteView):
    model = UbicacionSucursal
    template_name = "core/confirm_delete.html"
    success_url = reverse_lazy("ubicacion-sucursal-list")

    def delete(self, request, *args, **kwargs):
        messages.success(request, "Ubicación eliminada.")
        return super().delete(request, *args, **kwargs)

# ------------------------------------
#   TipoUbicacion con modal
# ------------------------------------
# Los modales usan <dialog> y cargan estas vistas que devuelven la pÃ¡gina completa,
# pero con templates chicos pensados para presentarse en un modal.

class TipoUbicacionCreateModal(LoginRequiredMixin, SuccessMessageMixin, CreateView):
    model = TipoUbicacion
    form_class = TipoUbicacionForm
    template_name = "core/partials/tipo_form_modal.html"
    success_message = "Tipo de ubicaciÃ³n creado."

    def get_success_url(self):
        return self.request.GET.get("next") or reverse_lazy("bodega-list")


class TipoUbicacionUpdateModal(LoginRequiredMixin, SuccessMessageMixin, UpdateView):
    model = TipoUbicacion
    form_class = TipoUbicacionForm
    template_name = "core/partials/tipo_form_modal.html"
    success_message = "Tipo de ubicaciÃ³n actualizado."

    def get_success_url(self):
        return self.request.GET.get("next") or reverse_lazy("bodega-list")


class TipoUbicacionDeleteModal(LoginRequiredMixin, DeleteView):
    model = TipoUbicacion
    template_name = "core/partials/confirm_modal.html"
    success_url = reverse_lazy("bodega-list")

    def delete(self, request, *args, **kwargs):
        messages.success(request, "Tipo de ubicaciÃ³n eliminado.")
        return super().delete(request, *args, **kwargs)

# ======================
# Marca
# ======================
class MarcaCreateModal(LoginRequiredMixin, SuccessMessageMixin, CreateView):
    model = Marca
    form_class = MarcaForm
    template_name = "core/partials/marca_form_modal.html"
    success_message = "Marca creada."

    def get_success_url(self):
        return self.request.GET.get("next") or reverse_lazy("products")


class MarcaUpdateModal(LoginRequiredMixin, SuccessMessageMixin, UpdateView):
    model = Marca
    form_class = MarcaForm
    template_name = "core/partials/marca_form_modal.html"
    success_message = "Marca actualizada."

    def get_success_url(self):
        return self.request.GET.get("next") or reverse_lazy("products")


class MarcaDeleteModal(LoginRequiredMixin, DeleteView):
    model = Marca
    template_name = "core/partials/confirm_modal.html"
    success_url = reverse_lazy("products")

    def delete(self, request, *args, **kwargs):
        messages.success(request, "Marca eliminada.")
        return super().delete(request, *args, **kwargs)

# ======================
# Unidad de Medida
# ======================
class UnidadMedidaCreateModal(LoginRequiredMixin, SuccessMessageMixin, CreateView):
    model = UnidadMedida
    form_class = UnidadMedidaForm
    template_name = "core/partials/unidad_form_modal.html"
    success_message = "Unidad de medida creada."

    def get_success_url(self):
        return self.request.GET.get("next") or reverse_lazy("products")


class UnidadMedidaUpdateModal(LoginRequiredMixin, SuccessMessageMixin, UpdateView):
    model = UnidadMedida
    form_class = UnidadMedidaForm
    template_name = "core/partials/unidad_form_modal.html"
    success_message = "Unidad de medida actualizada."

    def get_success_url(self):
        return self.request.GET.get("next") or reverse_lazy("products")


class UnidadMedidaDeleteModal(LoginRequiredMixin, DeleteView):
    model = UnidadMedida
    template_name = "core/partials/confirm_modal.html"
    success_url = reverse_lazy("products")

    def delete(self, request, *args, **kwargs):
        messages.success(request, "Unidad de medida eliminada.")
        return super().delete(request, *args, **kwargs)

# ======================
# Tasa de Impuesto
# ======================
class TasaImpuestoCreateModal(LoginRequiredMixin, SuccessMessageMixin, CreateView):
    model = TasaImpuesto
    form_class = TasaImpuestoForm
    template_name = "core/partials/tasa_form_modal.html"
    success_message = "Tasa de impuesto creada."

    def get_success_url(self):
        return self.request.GET.get("next") or reverse_lazy("products")


class TasaImpuestoUpdateModal(LoginRequiredMixin, SuccessMessageMixin, UpdateView):
    model = TasaImpuesto
    form_class = TasaImpuestoForm
    template_name = "core/partials/tasa_form_modal.html"
    success_message = "Tasa de impuesto actualizada."

    def get_success_url(self):
        return self.request.GET.get("next") or reverse_lazy("products")


class TasaImpuestoDeleteModal(LoginRequiredMixin, DeleteView):
    model = TasaImpuesto
    template_name = "core/partials/confirm_modal.html"
    success_url = reverse_lazy("products")

    def delete(self, request, *args, **kwargs):
        messages.success(request, "Tasa de impuesto eliminada.")
        return super().delete(request, *args, **kwargs)

# ======================
# CategorÃ­a de Producto
# ======================
class CategoriaProductoCreateModal(LoginRequiredMixin, SuccessMessageMixin, CreateView):
    model = CategoriaProducto
    form_class = CategoriaProductoForm
    template_name = "core/partials/categoria_form_modal.html"
    success_message = "CategorÃ­a creada."

    def get_success_url(self):
        return self.request.GET.get("next") or reverse_lazy("products")


class CategoriaProductoUpdateModal(LoginRequiredMixin, SuccessMessageMixin, UpdateView):
    model = CategoriaProducto
    form_class = CategoriaProductoForm
    template_name = "core/partials/categoria_form_modal.html"
    success_message = "CategorÃ­a actualizada."

    def get_success_url(self):
        return self.request.GET.get("next") or reverse_lazy("products")


class CategoriaProductoDeleteModal(LoginRequiredMixin, DeleteView):
    model = CategoriaProducto
    template_name = "core/partials/confirm_modal.html"
    success_url = reverse_lazy("products")

    def delete(self, request, *args, **kwargs):
        messages.success(request, "CategorÃ­a eliminada.")
        return super().delete(request, *args, **kwargs)
    
# ===== LoteProducto (modales) =====
class LoteCreateModal(LoginRequiredMixin, SuccessMessageMixin, CreateView):
    model = LoteProducto
    form_class = LoteProductoForm
    template_name = "core/partials/lote_form_modal.html"
    success_message = "Lote creado."

    def get_success_url(self):
        return self.request.GET.get("next") or reverse_lazy("products")

class LoteUpdateModal(LoginRequiredMixin, SuccessMessageMixin, UpdateView):
    model = LoteProducto
    form_class = LoteProductoForm
    template_name = "core/partials/lote_form_modal.html"
    success_message = "Lote actualizado."

    def get_success_url(self):
        return self.request.GET.get("next") or reverse_lazy("products")

class LoteDeleteModal(LoginRequiredMixin, SuccessMessageMixin, DeleteView):
    model = LoteProducto
    template_name = "core/partials/confirm_delete_modal.html"
    success_message = "Lote eliminado."
    # messages en DeleteView requieren manejo en form_valid o post_delete signal; si usas messages en template, puedes mostrar el texto allÃ­.

# ===== SerieProducto (modales) =====
class SerieCreateModal(LoginRequiredMixin, SuccessMessageMixin, CreateView):
    model = SerieProducto
    form_class = SerieProductoForm
    template_name = "core/partials/serie_form_modal.html"
    success_message = "Serie creada."

    def get_success_url(self):
        return self.request.GET.get("next") or reverse_lazy("products")

class SerieUpdateModal(LoginRequiredMixin, SuccessMessageMixin, UpdateView):
    model = SerieProducto
    form_class = SerieProductoForm
    template_name = "core/partials/serie_form_modal.html"
    success_message = "Serie actualizada."

    def get_success_url(self):
        return self.request.GET.get("next") or reverse_lazy("products")

class SerieDeleteModal(LoginRequiredMixin, SuccessMessageMixin, DeleteView):
    model = SerieProducto
    template_name = "core/partials/confirm_delete_modal.html"
    success_message = "Serie eliminada."

def test_scanner(request):
    return render(request, "core/test_scanner.html")


@login_required
def products(request):
    productos = (
        Producto.objects
        .select_related("marca", "categoria", "unidad_base", "tasa_impuesto")
        .annotate(
            lotes_count=Count("lotes", distinct=True),
            series_count=Count("series", distinct=True),
            proveedores_count=Count("productousuarioproveedor", distinct=True),
        )
        .order_by("nombre")
    )
    return render(request, "core/products.html", {
        "productos": productos,
        "q": (request.GET.get("q") or "").strip(),
    })

@login_required
def productos_por_bodega(request, bodega_id):
    try:
        bodega = Bodega.objects.get(id=bodega_id)
    except Bodega.DoesNotExist:
        return render(request, "core/error.html", {"error": "Bodega no encontrada."})

    # ubicaciones de esa bodega
    ubicaciones_en_bodega = bodega.ubicaciones.all()

    if not ubicaciones_en_bodega:
        return render(
            request,
            "core/error.html",
            {"error": "No se encontraron ubicaciones asociadas a esta bodega."},
        )

    # productos que tienen stock en alguna de esas ubicaciones
    productos = (
        Producto.objects.filter(stocks__ubicacion_bodega__bodega=bodega)
        .distinct()
        .annotate(
            stock_total=Coalesce(
                Sum("stocks__cantidad_disponible"),
                Value(0, output_field=DecimalField(max_digits=20, decimal_places=6)),
            )
        )
    )

    return render(
        request,
        "core/productos_por_bodega.html",
        {
            "bodega": bodega,
            "ubicaciones_en_bodega": ubicaciones_en_bodega,
            "productos": productos,
        },
    )


@login_required
def product_list(request):
    q = (request.GET.get("q") or "").strip()

    qs = (
        Producto.objects
        .all()
        .annotate(
            # usa los nombres REALES que tienes en el modelo
            proveedores_count=Count("usuarios_proveedor", distinct=True),
            lotes_count=Count("lotes", distinct=True),
            series_count=Count("series", distinct=True),
        )
        .order_by("sku")
    )

    if q:
        qs = qs.filter(
            Q(sku__icontains=q) |
            Q(nombre__icontains=q) |
            Q(marca__nombre__icontains=q) |
            Q(categoria__nombre__icontains=q)
        )

    paginator = Paginator(qs, 20)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    return render(
        request,
        "core/products.html",     # tu template
        {
            "q": q,
            "productos": page_obj.object_list,
            "page_obj": page_obj,
            "is_paginated": page_obj.has_other_pages(),
        },
    )

# ---------- Utilidades comunes ----------

def _is_fetch(request):
    # Tu helper JS manda 'X-Requested-With: fetch'
    return request.headers.get("X-Requested-With") == "fetch"

def _json_or_redirect(request, ok: bool, msg: str, redirect_to: str = None, extra: dict | None = None):
    payload = {"ok": ok, "message": msg}
    if extra:
        payload.update(extra)
    if _is_fetch(request):
        status = 200 if ok else 400
        return JsonResponse(payload, status=status)
    if ok:
        messages.success(request, msg)
    else:
        messages.error(request, msg)
    return redirect(redirect_to or request.META.get("HTTP_REFERER", "/"))
from decimal import Decimal

# === Config: pon aquÃ­ el nombre real del campo de reserva en Producto (si existe)
RESERVA_FIELD = "reserva"   # ej. "reservado" si tu modelo lo llama asÃ­


def _get_reserva(producto):
    """Obtiene la reserva desde Producto (0 si no existe el campo)."""
    return Decimal(getattr(producto, RESERVA_FIELD, 0) or 0)


def _set_reserva(producto, value):
    """Setea la reserva en Producto (si el campo existe). Ignora si no existe."""
    if hasattr(producto, RESERVA_FIELD):
        setattr(producto, RESERVA_FIELD, Decimal(value or 0))




class _ProductoStockProxy:
    """
    Proxy de compatibilidad para cÃ³digo legacy que esperaba un objeto Stock.
    Lee/escribe directamente en Producto.stock y Producto.<RESERVA_FIELD>.
    Tiene un mÃ©todo .save(update_fields=...) para imitar la API.
    """
    def __init__(self, producto):
        self._p = producto

    @property
    def producto(self):
        return self._p

    @property
    def cantidad_disponible(self):
        return Decimal(self._p.stock or 0)

    @cantidad_disponible.setter
    def cantidad_disponible(self, value):
        self._p.stock = Decimal(value or 0)

    @property
    def cantidad_reservada(self):
        return _get_reserva(self._p)

    @cantidad_reservada.setter
    def cantidad_reservada(self, value):
        _set_reserva(self._p, value)

    def save(self, update_fields=None):
        # Mapea update_fields del "Stock" a campos reales de Producto
        fields = set(update_fields or [])
        mapped = set()
        if not fields:
            # Guardar ambos si existen
            mapped.add("stock")
            if hasattr(self._p, RESERVA_FIELD):
                mapped.add(RESERVA_FIELD)
        else:
            if "cantidad_disponible" in fields or "stock" in fields:
                mapped.add("stock")
            if "cantidad_reservada" in fields or RESERVA_FIELD in fields:
                if hasattr(self._p, RESERVA_FIELD):
                    mapped.add(RESERVA_FIELD)

        if not mapped:
            # fallback por seguridad
            mapped.add("stock")
            if hasattr(self._p, RESERVA_FIELD):
                mapped.add(RESERVA_FIELD)

        self._p.save(update_fields=list(mapped))


def _get_or_create_stock(producto, ubicacion_id: int | None = None):
    """
    Compatibilidad sin tabla Stock:
    Ignora la ubicaciÃ³n y devuelve un proxy ligado al Producto.
    AsÃ­ tu cÃ³digo legacy (que hacÃ­a .cantidad_disponible += x; .save()) sigue funcionando.
    """
    return _ProductoStockProxy(producto)


# ====== Helpers â€œnuevosâ€ para operar stock directamente en Producto ======


def ajustar_stock(producto, cantidad):
    """
    Ajusta el stock de un producto y dispara una alerta si el stock es bajo.
    """
    producto.stock += cantidad
    
    # No permitir que el stock sea negativo
    if producto.stock < 0:
        logger.error(f"Intento de ajuste de stock que resulta en valor negativo para {producto.sku}. Ajuste: {cantidad}")
        producto.stock = 0  # Asignamos 0 si el stock es negativo

    producto.save()  # Guarda el producto con el nuevo stock
    
    if producto.stock <= 10:  # Verifica si el stock es bajo
        trigger_low_stock_alert(
            producto=producto,
            stock_actual=producto.stock,
            ubicacion_bodega=None,  # O ajusta según el caso
            ubicacion_sucursal=None  # O ajusta según el caso
        )





def set_stock(producto, disponible=None, reservado=None, guardar=True):
    """
    Seteo directo (absoluto) de stock/reserva en Producto.
    """
    if disponible is not None:
        d = Decimal(disponible or 0)
        producto.stock = max(0, d)  # No permitir valores negativos

    if reservado is not None and hasattr(producto, RESERVA_FIELD):
        r = Decimal(reservado or 0)
        _set_reserva(producto, max(0, r))  # No permitir valores negativos

    if guardar:
        update_fields = ["stock"]
        if hasattr(producto, RESERVA_FIELD):
            update_fields.append(RESERVA_FIELD)
        producto.save(update_fields=update_fields)
    return producto


@login_required
def stock_por_producto(request):
    """
    Consulta de stock por SKU.
    Muestra:
      - totales globales
      - desglose por sucursal/bodega
      - incluye la ubicación física (código/nombre) tanto en sucursal como en bodega
    """
    sku = (request.GET.get("sku") or "").strip().upper()
    producto = None
    totales = None
    resumen_sucursales = []

    if sku:
        try:
            producto = (
                Producto.objects
                .select_related("marca", "categoria")
                .get(sku=sku)
            )

            # 1) TOTAL GLOBAL DEL PRODUCTO
            agg = (
                Stock.objects
                .filter(producto=producto)
                .aggregate(
                    total_disponible=Coalesce(
                        Sum("cantidad_disponible"),
                        Value(0, output_field=DecimalField(max_digits=20, decimal_places=6))
                    )
                )
            )
            disponible = agg["total_disponible"] or 0

            totales = {
                "total_disponible": disponible,
                # neto = disponible (no hay reservas en el modelo de Stock)
                "total_neto": disponible,
            }

            # 2) DESGLOSE POR UBICACIÓN (sucursal/bodega + ubicación física)
            # Se anotan sucursal/bodega y además el detalle de la ubicación física.
            resumen_sucursales = (
                Stock.objects
                .filter(producto=producto)
                .annotate(
                    # Datos de Sucursal
                    sucursal_codigo=Case(
                        When(ubicacion_sucursal__isnull=False, then=F("ubicacion_sucursal__sucursal__codigo")),
                        default=Value("", output_field=CharField()),
                    ),
                    sucursal_nombre=Case(
                        When(ubicacion_sucursal__isnull=False, then=F("ubicacion_sucursal__sucursal__nombre")),
                        default=Value("", output_field=CharField()),
                    ),
                    # Datos de Bodega
                    bodega_codigo=Case(
                        When(ubicacion_bodega__isnull=False, then=F("ubicacion_bodega__bodega__codigo")),
                        default=Value("", output_field=CharField()),
                    ),
                    bodega_nombre=Case(
                        When(ubicacion_bodega__isnull=False, then=F("ubicacion_bodega__bodega__nombre")),
                        default=Value("", output_field=CharField()),
                    ),
                    # Ubicación física dentro de sucursal / bodega
                    sucursal_ubi_codigo=Case(
                        When(ubicacion_sucursal__isnull=False, then=F("ubicacion_sucursal__codigo")),
                        default=Value("", output_field=CharField()),
                    ),
                    sucursal_ubi_nombre=Case(
                        When(ubicacion_sucursal__isnull=False, then=F("ubicacion_sucursal__nombre")),
                        default=Value("", output_field=CharField()),
                    ),
                    bodega_ubi_codigo=Case(
                        When(ubicacion_bodega__isnull=False, then=F("ubicacion_bodega__codigo")),
                        default=Value("", output_field=CharField()),
                    ),
                    bodega_ubi_nombre=Case(
                        When(ubicacion_bodega__isnull=False, then=F("ubicacion_bodega__nombre")),
                        default=Value("", output_field=CharField()),
                    ),
                )
                .values(
                    "sucursal_codigo", "sucursal_nombre",
                    "bodega_codigo", "bodega_nombre",
                    "sucursal_ubi_codigo", "sucursal_ubi_nombre",
                    "bodega_ubi_codigo", "bodega_ubi_nombre",
                )
                .annotate(
                    total_disponible=Coalesce(
                        Sum("cantidad_disponible"),
                        Value(0, output_field=DecimalField(max_digits=20, decimal_places=6))
                    ),
                    total_neto=F("total_disponible"),
                )
                .order_by(
                    "sucursal_codigo", "bodega_codigo",
                    "sucursal_ubi_codigo", "bodega_ubi_codigo"
                )
            )

        except Producto.DoesNotExist:
            messages.error(request, f"No se encontró ningún producto con SKU '{sku}'.")

    return render(
        request,
        "core/stock_producto.html",
        {
            "sku": sku,
            "producto": producto,
            "totales": totales,
            "resumen_sucursales": resumen_sucursales,
        },
    )



@login_required
@transaction.atomic
def stock_ajuste(request):
    if request.method != "POST":
        return HttpResponseBadRequest("Método no permitido")

    # Obtener el id del producto
    try:
        pid = int(request.POST.get("producto_id"))
    except (TypeError, ValueError):
        return _json_or_redirect(request, False, "Producto inválido.")

    # Obtener la cantidad a ajustar
    try:
        cantidad = float(request.POST.get("cantidad"))
    except (TypeError, ValueError):
        return _json_or_redirect(request, False, "Cantidad inválida.")

    ubicacion_id = request.POST.get("ubicacion")  # Puede ser de bodega o de sucursal
    producto = get_object_or_404(Producto, pk=pid)

    if ubicacion_id:
        # Si hay ubicación (bodega o sucursal)
        stock, _, _, _ = _get_or_create_stock(producto, int(ubicacion_id))
        stock.cantidad_disponible += Decimal(cantidad)
        stock.save(update_fields=["cantidad_disponible"])
    else:
        # Si no hay ubicación, ajustamos el stock global del producto
        producto.stock = max(0, int((producto.stock or 0) + cantidad))
        producto.save(update_fields=["stock"])

    _recalcular_stock_global(producto)

    # Verificar si el stock bajo de 10 y enviar la alerta
    if ubicacion_id:
        trigger_low_stock_alert(
            producto=producto,
            stock_actual=stock.cantidad_disponible,
            ubicacion_bodega=None,  # Si es bodega, usa este campo
            ubicacion_sucursal=None  # Si es sucursal, usa este campo
        )
    else:
        trigger_low_stock_alert(
            producto=producto,
            stock_actual=producto.stock,
            ubicacion_bodega=None,  # Si no es bodega, usa None
            ubicacion_sucursal=None  # Si no es sucursal, usa None
        )

    return _json_or_redirect(
        request,
        True,
        f"Ajuste aplicado: {cantidad:+g} {producto.sku}",
        redirect_to=reverse("products"),
    )




@login_required
@transaction.atomic
def stock_entrada(request):
    if request.method != "POST":
        return HttpResponseBadRequest("Método no permitido")

    try:
        pid = int(request.POST.get("producto_id"))
    except (TypeError, ValueError):
        return _json_or_redirect(request, False, "Producto inválido.")

    try:
        cantidad = float(request.POST.get("cantidad"))
    except (TypeError, ValueError):
        return _json_or_redirect(request, False, "Cantidad inválida.")

    if cantidad <= 0:
        return _json_or_redirect(request, False, "La cantidad debe ser mayor a 0.")

    ubicacion_id = request.POST.get("ubicacion")
    producto = get_object_or_404(Producto, pk=pid)

    if ubicacion_id:
        stock, _, _, _ = _get_or_create_stock(producto, int(ubicacion_id))
        stock.cantidad_disponible = F("cantidad_disponible") + Decimal(cantidad)
        stock.save(update_fields=["cantidad_disponible"])
    else:
        producto.stock = max(0, int((producto.stock or 0) + cantidad))
        producto.save(update_fields=["stock"])

    _recalcular_stock_global(producto)

    # Verificar si el stock bajo de 10 y enviar la alerta
    if ubicacion_id:
        trigger_low_stock_alert(
            producto=producto,
            stock_actual=stock.cantidad_disponible,
            ubicacion_bodega=None,  # Usa este campo si es de bodega
            ubicacion_sucursal=None  # Usa este campo si es de sucursal
        )
    else:
        trigger_low_stock_alert(
            producto=producto,
            stock_actual=producto.stock,
            ubicacion_bodega=None,  # Si no es bodega, usa None
            ubicacion_sucursal=None  # Si no es sucursal, usa None
        )

    return _json_or_redirect(
        request,
        True,
        f"Entrada registrada (+{cantidad:g}) para {producto.sku}",
        redirect_to=reverse("products"),
    )

@login_required
@transaction.atomic
def stock_transferir(request):
    """
    Transfiere stock entre ubicaciones (pueden ser de tablas distintas).
    """
    if request.method != "POST":
        return HttpResponseBadRequest("Método no permitido")

    try:
        pid = int(request.POST.get("producto_id"))
        origen = int(request.POST.get("origen"))
        destino = int(request.POST.get("destino"))
    except (TypeError, ValueError):
        return _json_or_redirect(request, False, "Parámetros inválidos.")

    if origen == destino:
        return _json_or_redirect(request, False, "Origen y destino no pueden ser iguales.")

    try:
        cantidad = float(request.POST.get("cantidad"))
    except (TypeError, ValueError):
        return _json_or_redirect(request, False, "Cantidad inválida.")

    if cantidad <= 0:
        return _json_or_redirect(request, False, "La cantidad debe ser mayor a 0.")

    producto = get_object_or_404(Producto, pk=pid)

    stock_origen, _, _, _ = _get_or_create_stock(producto, origen)
    stock_destino, _, _, _ = _get_or_create_stock(producto, destino)

    # necesitamos el valor real
    stock_origen.refresh_from_db()

    if stock_origen.cantidad_disponible < cantidad:
        return _json_or_redirect(request, False, "Stock insuficiente en origen.")

    stock_origen.cantidad_disponible = Decimal(stock_origen.cantidad_disponible) - Decimal(cantidad)
    stock_origen.save(update_fields=["cantidad_disponible"])

    stock_destino.cantidad_disponible = Decimal(stock_destino.cantidad_disponible) + Decimal(cantidad)
    stock_destino.save(update_fields=["cantidad_disponible"])

    _recalcular_stock_global(producto)

    # Verificar si el stock bajo de 10 y enviar la alerta
    trigger_low_stock_alert(
        producto=producto,
        stock_actual=stock_origen.cantidad_disponible,
        ubicacion_bodega=None,  # Si es bodega, usa esto
        ubicacion_sucursal=None  # Si es sucursal, usa esto
    )

    return _json_or_redirect(
        request,
        True,
        f"Transferidos {cantidad:g} de {producto.sku}",
        redirect_to=reverse("products"),
    )


@login_required
@transaction.atomic
def stock_recuento(request):
    if request.method != "POST":
        return HttpResponseBadRequest("Método no permitido")

    try:
        pid = int(request.POST.get("producto_id"))
    except (TypeError, ValueError):
        return _json_or_redirect(request, False, "Producto inválido.")

    try:
        cantidad_real = float(request.POST.get("cantidad_real"))
    except (TypeError, ValueError):
        return _json_or_redirect(request, False, "Cantidad inválida.")

    ubicacion_id = request.POST.get("ubicacion")
    producto = get_object_or_404(Producto, pk=pid)

    if ubicacion_id:
        # Obtener o crear el stock para la ubicación de bodega o sucursal
        stock, _, _, _ = _get_or_create_stock(producto, int(ubicacion_id))
        stock.cantidad_disponible = Decimal(cantidad_real)
        stock.save(update_fields=["cantidad_disponible"])
    else:
        # Si no se especifica la ubicación, actualizamos el stock global del producto
        producto.stock = max(0, int(cantidad_real))
        producto.save(update_fields=["stock"])

    # Recalcular el stock global después de realizar el recuento
    _recalcular_stock_global(producto)

    # Verificar si el stock bajo de 10 y enviar la alerta
    trigger_low_stock_alert(producto=producto, stock_actual=producto.stock)

    return _json_or_redirect(
        request,
        True,
        f"Recuento guardado ({cantidad_real:g}) para {producto.sku}",
        redirect_to=reverse("products"),
    )




def _recalcular_stock_global(producto: Producto) -> None:
    """
    Suma TODO el stock por ubicaciones y lo deja en producto.stock.
    Evita el error de 'mixed types' forzando DecimalField.
    """
    agg = (
        Stock.objects
        .filter(producto=producto)
        .aggregate(
            total=Coalesce(
                Sum("cantidad_disponible"),
                Value(0, output_field=DecimalField(max_digits=20, decimal_places=6)),
            )
        )
    )
    total = agg["total"] or 0
    producto.stock = total  # Asignamos el stock global al producto
    producto.save(update_fields=["stock"])





@require_GET
def ajax_sucursales_y_productos(request):
    bodega_id = request.GET.get("bodega_id")
    if not bodega_id:
        return JsonResponse({"error": "Falta bodega_id"}, status=400)

    try:
        bodega = Bodega.objects.get(pk=bodega_id)
    except Bodega.DoesNotExist:
        return JsonResponse({"error": "Bodega no encontrada"}, status=404)

    sucursales = list(
        bodega.sucursales.all()
        .order_by("codigo")
        .values("id", "codigo", "nombre")
    )

    productos = (
        Producto.objects.filter(stocks__ubicacion_bodega__bodega=bodega)
        .annotate(
            stock_total=Coalesce(
                Sum("stocks__cantidad_disponible"),
                Value(0, output_field=DecimalField(max_digits=20, decimal_places=6)),
            )
        )
        .values("id", "sku", "nombre", "stock_total")
        .distinct()
    )

    return JsonResponse({"sucursales": sucursales, "productos": list(productos)})


def _resolver_ubicacion(pk: int):
    """
    Recibe un PK y trata de adivinar si es una ubicacion de bodega o de sucursal.
    Devuelve ('bodega', obj) o ('sucursal', obj).
    Lanza Http404 si no existe.
    """
    try:
        ub_bod = UbicacionBodega.objects.get(pk=pk)
        return "bodega", ub_bod
    except UbicacionBodega.DoesNotExist:
        pass
    try:
        ub_suc = UbicacionSucursal.objects.get(pk=pk)
        return "sucursal", ub_suc
    except UbicacionSucursal.DoesNotExist:
        raise Http404("Ubicación no encontrada")


def _get_or_create_stock(producto: Producto, ubicacion_pk: int | None = None):
    """
    Devuelve (stock, creado, tipo, ubicacion_instance)
    - si viene ubicacion_pk, intenta en bodega, luego sucursal
    - si NO viene ubicacion_pk → trabajamos solo en producto.stock (compat)
    """
    if ubicacion_pk is None:
        # modo compat: no hay ubicación → operamos en el campo producto.stock
        # devolvemos un "fake" con la misma API que Stock
        class _Proxy:
            def __init__(self, prod):
                self._p = prod

            @property
            def cantidad_disponible(self):
                return Decimal(self._p.stock or 0)

            @cantidad_disponible.setter
            def cantidad_disponible(self, val):
                self._p.stock = int(Decimal(val or 0))
                self._p.save(update_fields=["stock"])

            def save(self, update_fields=None):
                self._p.save(update_fields=["stock"])

        return _Proxy(producto), False, "producto", producto

    tipo, ubi = _resolver_ubicacion(ubicacion_pk)
    if tipo == "bodega":
        stock, created = Stock.objects.get_or_create(
            producto=producto,
            ubicacion_bodega=ubi,
            defaults={"cantidad_disponible": 0},
        )
        return stock, created, tipo, ubi
    else:
        stock, created = Stock.objects.get_or_create(
            producto=producto,
            ubicacion_sucursal=ubi,
            defaults={"cantidad_disponible": 0},
        )
        return stock, created, tipo, ubi


from core.utils import get_bodeguero_emails


@login_required
def bodega_a_sucursal(request):
    bodegas = Bodega.objects.prefetch_related("sucursales", "ubicaciones").order_by("codigo")

    if request.method == "POST":
        bodega_id    = request.POST.get("bodega")
        sucursal_id  = request.POST.get("sucursal")
        producto_id  = request.POST.get("producto")
        cantidad_raw = request.POST.get("cantidad")

        if not all([bodega_id, sucursal_id, producto_id, cantidad_raw]):
            return render(
                request, "core/Movimientos/bodega_a_sucursal.html",
                {"bodegas": bodegas, "error": "Faltan datos en el formulario."}
            )

        # cantidad
        try:
            cantidad = int(cantidad_raw)
        except (TypeError, ValueError):
            return render(
                request, "core/Movimientos/bodega_a_sucursal.html",
                {"bodegas": bodegas, "error": "La cantidad debe ser un número entero."}
            )

        if cantidad <= 0:
            return render(
                request, "core/Movimientos/bodega_a_sucursal.html",
                {"bodegas": bodegas, "error": "La cantidad debe ser mayor que 0."}
            )

        # instancias firmes
        bodega   = get_object_or_404(Bodega, pk=bodega_id)
        sucursal = get_object_or_404(Sucursal, pk=sucursal_id, bodega=bodega)
        producto = get_object_or_404(Producto, pk=producto_id)

        # Asegura que la sucursal tenga al menos 1 ubicación
        try:
            ubi_destino = ensure_ubicacion_sucursal(sucursal)  # si tienes este helper
        except NameError:
            ubi_destino = sucursal.ubicaciones.first()

        if not ubi_destino:
            return render(
                request, "core/Movimientos/bodega_a_sucursal.html",
                {"bodegas": bodegas, "error": "Faltan ubicaciones en la sucursal."}
            )

        with transaction.atomic():
            # Mayor disponible en la bodega (no dependemos de una única ubicación)
            stock_origen = (
                Stock.objects
                .select_for_update()
                .filter(producto=producto, ubicacion_bodega__bodega=bodega)
                .order_by("-cantidad_disponible")
                .first()
            )

            if not stock_origen:
                disp_total = (
                    Stock.objects
                    .filter(producto=producto, ubicacion_bodega__bodega=bodega)
                    .aggregate(t=Coalesce(
                        Sum("cantidad_disponible"),
                        Value(0, output_field=DecimalField(max_digits=20, decimal_places=6))
                    ))["t"] or 0
                )
                return render(
                    request, "core/Movimientos/bodega_a_sucursal.html",
                    {"bodegas": bodegas, "error": f"No hay stock en la bodega. Disponible: {disp_total}."}
                )

            # Si una sola fila no alcanza, consumimos de varias (en orden descendente)
            if stock_origen.cantidad_disponible < cantidad:
                disp_total = (
                    Stock.objects
                    .filter(producto=producto, ubicacion_bodega__bodega=bodega)
                    .aggregate(t=Coalesce(
                        Sum("cantidad_disponible"),
                        Value(0, output_field=DecimalField(max_digits=20, decimal_places=6))
                    ))["t"] or 0
                )
                if disp_total < cantidad:
                    return render(
                        request, "core/Movimientos/bodega_a_sucursal.html",
                        {"bodegas": bodegas, "error": f"No hay stock suficiente en la bodega. Disponible: {disp_total}."}
                    )

                faltante = Decimal(cantidad)
                filas = list(
                    Stock.objects
                    .select_for_update()
                    .filter(producto=producto, ubicacion_bodega__bodega=bodega, cantidad_disponible__gt=0)
                    .order_by("-cantidad_disponible")
                )
                stock_destino, _ = (
                    Stock.objects
                    .select_for_update()
                    .get_or_create(
                        producto=producto,
                        ubicacion_sucursal=ubi_destino,
                        defaults={"cantidad_disponible": Decimal("0")}
                    )
                )

                for fila in filas:
                    if faltante <= 0:
                        break
                    mueve = min(faltante, fila.cantidad_disponible)
                    fila.cantidad_disponible -= mueve
                    stock_destino.cantidad_disponible += mueve
                    fila.save(update_fields=["cantidad_disponible"])
                    stock_destino.save(update_fields=["cantidad_disponible"])
                    faltante -= mueve

                stock_origen.refresh_from_db()

            else:
                # Una sola fila alcanza
                stock_destino, _ = (
                    Stock.objects
                    .select_for_update()
                    .get_or_create(
                        producto=producto,
                        ubicacion_sucursal=ubi_destino,
                        defaults={"cantidad_disponible": Decimal("0")}
                    )
                )
                stock_origen.cantidad_disponible -= Decimal(cantidad)
                stock_destino.cantidad_disponible += Decimal(cantidad)
                stock_origen.save(update_fields=["cantidad_disponible"])
                stock_destino.save(update_fields=["cantidad_disponible"])

        # ——— Recalcular stock global del producto ———
        total_prod = (
            Stock.objects
            .filter(producto=producto)
            .aggregate(t=Coalesce(
                Sum("cantidad_disponible"),
                Value(0, output_field=DecimalField(max_digits=20, decimal_places=6))
            ))["t"] or 0
        )
        producto.stock = int(total_prod)
        producto.save(update_fields=["stock"])

        # ——— Stock total que queda en ESA bodega (para el correo) ———
        rem_total_bodega = (
            Stock.objects
            .filter(producto=producto, ubicacion_bodega__bodega=bodega)
            .aggregate(t=Coalesce(
                Sum("cantidad_disponible"),
                Value(0, output_field=DecimalField(max_digits=20, decimal_places=6))
            ))["t"] or 0
        )

        # === Alerta por correo HTML mediante helper ===
        notificar_stock_bajo(
            producto=producto,
            nombre_lugar=bodega.nombre,               # origen = bodega
            stock_actual=rem_total_bodega,
        )

        # Recargar combos para que el usuario siga operando
        sucursales_de_bodega = bodega.sucursales.all().order_by("codigo")
        productos_de_bodega = (
            Producto.objects
            .filter(stocks__ubicacion_bodega__bodega=bodega)
            .annotate(stock_total=Coalesce(
                Sum("stocks__cantidad_disponible"),
                Value(0, output_field=DecimalField(max_digits=20, decimal_places=6))
            ))
            .distinct()
        )

        return render(
            request,
            "core/Movimientos/bodega_a_sucursal.html",
            {
                "bodegas": bodegas,
                "sucursales": sucursales_de_bodega,
                "productos": productos_de_bodega,
                "success": f"Movimiento realizado: {cantidad} de {producto.nombre} → {sucursal.nombre}.",
                "bodega_sel": bodega.id,
            },
        )

    # GET
    return render(request, "core/Movimientos/bodega_a_sucursal.html", {"bodegas": bodegas})





@login_required
def sucursal_a_sucursal(request):
    # 1) Selects base
    sucursales = Sucursal.objects.prefetch_related("ubicaciones").order_by("nombre")

    # 2) Origen puede venir por GET (cuando cambias el select) o POST (autosubmit)
    suc_origen_id = request.GET.get("sucursal_origen") or request.POST.get("sucursal_origen")

    sucursales_destino = None
    productos_de_origen = None
    suc_origen = None

    # ========= Precarga cuando hay origen =========
    if suc_origen_id:
        try:
            suc_origen = Sucursal.objects.get(pk=suc_origen_id)
        except Sucursal.DoesNotExist:
            suc_origen = None
        else:
            ensure_ubicacion_sucursal(suc_origen)

            sucursales_destino = (
                Sucursal.objects.exclude(pk=suc_origen.pk).order_by("nombre")
            )

            productos_de_origen = (
                Producto.objects
                .filter(
                    stocks__ubicacion_sucursal__sucursal=suc_origen,
                    stocks__cantidad_disponible__gt=0,
                )
                .annotate(
                    stock_total=Coalesce(
                        Sum("stocks__cantidad_disponible"),
                        Value(0, output_field=DecimalField(max_digits=20, decimal_places=6)),
                    )
                )
                .distinct()
            )

    # ========= POST PARCIAL (solo cambió el origen por autosubmit) =========
    if (
        request.method == "POST"
        and "sucursal_origen" in request.POST
        and not all([
            request.POST.get("sucursal_destino"),
            request.POST.get("producto"),
            request.POST.get("cantidad"),
        ])
    ):
        return render(
            request,
            "core/Movimientos/sucursal_a_sucursal.html",
            {
                "sucursales": sucursales,
                "sucursal_sel": suc_origen.id if suc_origen else None,
                "sucursales_destino": sucursales_destino,
                "productos": productos_de_origen,
            },
        )

    # ========= POST COMPLETO → ejecutar movimiento =========
    if request.method == "POST":
        suc_destino_id = request.POST.get("sucursal_destino")
        producto_id    = request.POST.get("producto")
        cantidad_raw   = request.POST.get("cantidad")

        if not all([suc_origen_id, suc_destino_id, producto_id, cantidad_raw]):
            return render(
                request,
                "core/Movimientos/sucursal_a_sucursal.html",
                {
                    "sucursales": sucursales,
                    "sucursal_sel": suc_origen_id,
                    "sucursales_destino": sucursales_destino,
                    "productos": productos_de_origen,
                    "error": "Faltan datos en el formulario.",
                },
            )

        if suc_origen_id == suc_destino_id:
            return render(
                request,
                "core/Movimientos/sucursal_a_sucursal.html",
                {
                    "sucursales": sucursales,
                    "sucursal_sel": suc_origen_id,
                    "sucursales_destino": sucursales_destino,
                    "productos": productos_de_origen,
                    "error": "La sucursal de origen y destino no pueden ser la misma.",
                },
            )

        try:
            cantidad = int(cantidad_raw)
        except (ValueError, TypeError):
            cantidad = 0

        if cantidad <= 0:
            return render(
                request,
                "core/Movimientos/sucursal_a_sucursal.html",
                {
                    "sucursales": sucursales,
                    "sucursal_sel": suc_origen_id,
                    "sucursales_destino": sucursales_destino,
                    "productos": productos_de_origen,
                    "error": "La cantidad debe ser mayor que 0.",
                },
            )

        # Instancias firmes
        suc_origen  = get_object_or_404(Sucursal, pk=suc_origen_id)
        suc_destino = get_object_or_404(Sucursal, pk=suc_destino_id)
        producto    = get_object_or_404(Producto, pk=producto_id)

        # Garantiza ubicaciones
        ubi_origen  = ensure_ubicacion_sucursal(suc_origen)
        ubi_destino = ensure_ubicacion_sucursal(suc_destino)

        with transaction.atomic():
            # ORIGEN
            stock_origen = (
                Stock.objects
                .select_for_update()
                .filter(producto=producto, ubicacion_sucursal=ubi_origen)
                .first()
            )

            if not stock_origen or stock_origen.cantidad_disponible < cantidad:
                return render(
                    request,
                    "core/Movimientos/sucursal_a_sucursal.html",
                    {
                        "sucursales": sucursales,
                        "sucursal_sel": suc_origen.id,
                        "sucursales_destino": sucursales_destino,
                        "productos": productos_de_origen,
                        "error": f"No hay stock suficiente en {suc_origen.nombre}.",
                    },
                )

            # DESTINO
            stock_destino, _ = (
                Stock.objects
                .select_for_update()
                .get_or_create(
                    producto=producto,
                    ubicacion_sucursal=ubi_destino,
                    defaults={"cantidad_disponible": Decimal("0")},
                )
            )

            # Aplicar movimiento
            stock_origen.cantidad_disponible -= Decimal(cantidad)
            stock_destino.cantidad_disponible += Decimal(cantidad)
            stock_origen.save(update_fields=["cantidad_disponible"])
            stock_destino.save(update_fields=["cantidad_disponible"])

        # ========= Recalcular stock global del producto =========
        total_prod = (
            Stock.objects
            .filter(producto=producto)
            .aggregate(
                total=Coalesce(
                    Sum("cantidad_disponible"),
                    Value(0, output_field=DecimalField(max_digits=20, decimal_places=6)),
                )
            )["total"]
        ) or 0
        producto.stock = int(total_prod)
        producto.save(update_fields=["stock"])

        # ========= Alerta por correo HTML si queda bajo 10 en ORIGEN =========
        if stock_origen.cantidad_disponible < 10:
            notificar_stock_bajo(
                producto=producto,
                nombre_lugar=suc_origen.nombre,
                stock_actual=stock_origen.cantidad_disponible,
            )

        # ========= Recargar combos para seguir moviendo desde la misma sucursal =========
        productos_disponibles = (
            Producto.objects
            .filter(
                stocks__ubicacion_sucursal__sucursal=suc_origen,
                stocks__cantidad_disponible__gt=0,
            )
            .annotate(
                stock_total=Coalesce(
                    Sum("stocks__cantidad_disponible"),
                    Value(0, output_field=DecimalField(max_digits=20, decimal_places=6)),
                )
            )
            .distinct()
        )

        return render(
            request,
            "core/Movimientos/sucursal_a_sucursal.html",
            {
                "sucursales": sucursales,
                "sucursal_sel": suc_origen.id,
                "sucursales_destino": Sucursal.objects.exclude(pk=suc_origen.id).order_by("nombre"),
                "productos": productos_disponibles,
                "success": f"Movimiento realizado: {cantidad} de {producto.nombre} → {suc_destino.nombre}.",
            },
        )

    # ========= GET normal =========
    return render(
        request,
        "core/Movimientos/sucursal_a_sucursal.html",
        {
            "sucursales": sucursales,
            "sucursal_sel": suc_origen.id if suc_origen else None,
            "sucursales_destino": sucursales_destino,
            "productos": productos_de_origen,
        },
    )






@login_required
def bodega_a_bodega(request):
    bodegas = Bodega.objects.prefetch_related("ubicaciones").order_by("nombre")

    # Resolver id de bodega origen desde GET/POST y conservar con autosubmit
    def _get_bod_sel(req):
        return (
            req.GET.get("bodega_origen")
            or req.GET.get("bodega")
            or req.POST.get("bodega_origen")
            or req.POST.get("bodega")
        )

    bodega_sel = _get_bod_sel(request)

    productos = None
    bodegas_destino = None

    # ===== GET con origen seleccionado (primer render o cambio por querystring) =====
    if request.method == "GET" and bodega_sel:
        bodega = get_object_or_404(Bodega, pk=bodega_sel)

        productos = (
            Producto.objects
            .filter(
                stocks__ubicacion_bodega__bodega=bodega,
                stocks__cantidad_disponible__gt=0,
            )
            .annotate(
                stock_total=Coalesce(
                    Sum(
                        "stocks__cantidad_disponible",
                        filter=Q(stocks__ubicacion_bodega__bodega=bodega),
                    ),
                    Value(0, output_field=DecimalField(max_digits=20, decimal_places=6)),
                )
            )
            .distinct()
        )
        bodegas_destino = bodegas.exclude(pk=bodega.id)

        return render(
            request,
            "core/Movimientos/bodega_a_bodega.html",
            {
                "bodegas": bodegas,
                "bodega_sel": bodega.id,
                "productos": productos,
                "bodegas_destino": bodegas_destino,
            },
        )

    # ===== POST PARCIAL (autosubmit al cambiar origen) =====
    if (
        request.method == "POST"
        and ("bodega_origen" in request.POST or "bodega" in request.POST)
        and not all([
            request.POST.get("bodega_destino"),
            request.POST.get("producto"),
            request.POST.get("cantidad"),
        ])
    ):
        bodega_sel = _get_bod_sel(request)
        if not bodega_sel:
            return render(request, "core/Movimientos/bodega_a_bodega.html", {"bodegas": bodegas})

        bodega = get_object_or_404(Bodega, pk=bodega_sel)

        productos = (
            Producto.objects
            .filter(
                stocks__ubicacion_bodega__bodega=bodega,
                stocks__cantidad_disponible__gt=0,
            )
            .annotate(
                stock_total=Coalesce(
                    Sum(
                        "stocks__cantidad_disponible",
                        filter=Q(stocks__ubicacion_bodega__bodega=bodega),
                    ),
                    Value(0, output_field=DecimalField(max_digits=20, decimal_places=6)),
                )
            )
            .distinct()
        )
        bodegas_destino = bodegas.exclude(pk=bodega.id)

        return render(
            request,
            "core/Movimientos/bodega_a_bodega.html",
            {
                "bodegas": bodegas,
                "bodega_sel": bodega.id,
                "productos": productos,
                "bodegas_destino": bodegas_destino,
            },
        )

    # ===== POST COMPLETO → mover =====
    if request.method == "POST":
        bodega_origen_id  = _get_bod_sel(request)
        bodega_destino_id = request.POST.get("bodega_destino")
        producto_id       = request.POST.get("producto")
        cantidad_raw      = request.POST.get("cantidad")

        # Validaciones base
        if not all([bodega_origen_id, bodega_destino_id, producto_id, cantidad_raw]):
            return render(
                request, "core/Movimientos/bodega_a_bodega.html",
                {"bodegas": bodegas, "error": "Faltan datos en el formulario."}
            )

        if bodega_origen_id == bodega_destino_id:
            return render(
                request, "core/Movimientos/bodega_a_bodega.html",
                {
                    "bodegas": bodegas,
                    "bodega_sel": bodega_origen_id,
                    "error": "La bodega de origen y destino no pueden ser la misma.",
                },
            )

        try:
            cantidad = int(cantidad_raw)
        except (ValueError, TypeError):
            cantidad = 0

        if cantidad <= 0:
            return render(
                request, "core/Movimientos/bodega_a_bodega.html",
                {
                    "bodegas": bodegas,
                    "bodega_sel": bodega_origen_id,
                    "error": "La cantidad debe ser mayor que 0.",
                },
            )

        # Instancias firmes
        bodega_origen  = get_object_or_404(Bodega, pk=bodega_origen_id)
        bodega_destino = get_object_or_404(Bodega, pk=bodega_destino_id)
        producto       = get_object_or_404(Producto, pk=producto_id)

        # Garantizar al menos 1 ubicación en destino (y en origen si hiciera falta)
        ubi_destino = ensure_ubicacion_bodega(bodega_destino)
        ensure_ubicacion_bodega(bodega_origen)

        with transaction.atomic():
            # ORIGEN: tomamos la fila con mayor disponible
            stock_origen = (
                Stock.objects
                .select_for_update()
                .filter(
                    producto=producto,
                    ubicacion_bodega__bodega=bodega_origen,
                    cantidad_disponible__gt=0,
                )
                .order_by("-cantidad_disponible", "id")
                .first()
            )

            if not stock_origen or stock_origen.cantidad_disponible < cantidad:
                # Volvemos a cargar combos para continuar
                productos = (
                    Producto.objects
                    .filter(stocks__ubicacion_bodega__bodega=bodega_origen, stocks__cantidad_disponible__gt=0)
                    .annotate(
                        stock_total=Coalesce(
                            Sum(
                                "stocks__cantidad_disponible",
                                filter=Q(stocks__ubicacion_bodega__bodega=bodega_origen),
                            ),
                            Value(0, output_field=DecimalField(max_digits=20, decimal_places=6)),
                        )
                    )
                    .distinct()
                )
                bodegas_destino = bodegas.exclude(pk=bodega_origen.id)

                return render(
                    request,
                    "core/Movimientos/bodega_a_bodega.html",
                    {
                        "bodegas": bodegas,
                        "bodega_sel": bodega_origen.id,
                        "productos": productos,
                        "bodegas_destino": bodegas_destino,
                        "error": f"No hay stock suficiente en {bodega_origen.nombre}.",
                    },
                )

            # DESTINO
            stock_destino, _ = (
                Stock.objects
                .select_for_update()
                .get_or_create(
                    producto=producto,
                    ubicacion_bodega=ubi_destino,
                    defaults={"cantidad_disponible": Decimal("0")},
                )
            )

            # Aplicar movimiento
            stock_origen.cantidad_disponible  -= Decimal(cantidad)
            stock_destino.cantidad_disponible += Decimal(cantidad)
            stock_origen.save(update_fields=["cantidad_disponible"])
            stock_destino.save(update_fields=["cantidad_disponible"])

            # Aviso por correo si origen queda bajo 10
            if stock_origen.cantidad_disponible < 10:
                try:
                    # Si existe helper HTML, úsalo
                    if "notificar_stock_bajo" in globals():
                        notificar_stock_bajo(
                            producto=producto,
                            nombre_lugar=bodega_origen.nombre,
                            stock_actual=stock_origen.cantidad_disponible,
                        )
                    else:
                        # Fallback: texto plano
                        send_mail(
                            subject="Alerta de stock bajo",
                            message=(
                                f"El stock del producto {producto.nombre} (SKU: {producto.sku}) "
                                f"en la bodega {bodega_origen.nombre} es inferior a 10 unidades. "
                                f"Disponible: {stock_origen.cantidad_disponible}."
                            ),
                            from_email=settings.EMAIL_HOST_USER,
                            recipient_list=settings.TICKETS_NOTIFY_EMAILS,
                            fail_silently=False,
                        )
                except Exception:
                    # No romper el flujo por un problema de correo
                    pass

        # Recalcular stock global para el producto
        total_prod = (
            Stock.objects
            .filter(producto=producto)
            .aggregate(
                t=Coalesce(
                    Sum("cantidad_disponible"),
                    Value(0, output_field=DecimalField(max_digits=20, decimal_places=6)),
                )
            )["t"]
        ) or 0
        producto.stock = int(total_prod)
        producto.save(update_fields=["stock"])

        # Recargar combos para seguir moviendo desde la MISMA bodega de origen
        productos = (
            Producto.objects
            .filter(stocks__ubicacion_bodega__bodega=bodega_origen, stocks__cantidad_disponible__gt=0)
            .annotate(
                stock_total=Coalesce(
                    Sum(
                        "stocks__cantidad_disponible",
                        filter=Q(stocks__ubicacion_bodega__bodega=bodega_origen),
                    ),
                    Value(0, output_field=DecimalField(max_digits=20, decimal_places=6)),
                )
            )
            .distinct()
        )
        bodegas_destino = bodegas.exclude(pk=bodega_origen.id)

        return render(
            request,
            "core/Movimientos/bodega_a_bodega.html",
            {
                "bodegas": bodegas,
                "bodega_sel": bodega_origen.id,
                "productos": productos,
                "bodegas_destino": bodegas_destino,
                "success": f"Movimiento realizado: {cantidad} de {producto.nombre} → {bodega_destino.nombre}.",
            },
        )

    # ===== GET normal (primera carga) =====
    return render(request, "core/Movimientos/bodega_a_bodega.html", {"bodegas": bodegas})






@login_required
def sucursal_a_bodega(request):
    # 1) Siempre carga las sucursales para el select de origen
    sucursales = (
        Sucursal.objects
        .select_related("bodega")
        .prefetch_related("ubicaciones")
        .order_by("nombre")
    )

    # ---- Helpers de contexto para que el template nunca falle ----
    def base_ctx(**extra):
        ctx = {
            "sucursales": sucursales,
            "sucursal_sel": None,
            "bodega_actual": None,
            "productos": None,
            "error": None,
            "success": None,
        }
        ctx.update(extra)
        return ctx

    def ctx_para_sucursal(suc):
        """
        Asegura ubicaciones, calcula productos disponibles en la sucursal
        y entrega las claves que el template necesita para no bloquear la UI.
        """
        # Garantiza al menos 1 ubicación en ambos lados
        ubi_suc = ensure_ubicacion_sucursal(suc)
        if suc.bodega:
            ensure_ubicacion_bodega(suc.bodega)

        # Productos disponibles en esa sucursal (stock > 0)
        productos = (
            Producto.objects
            .filter(
                stocks__ubicacion_sucursal=ubi_suc,
                stocks__cantidad_disponible__gt=0,
            )
            .annotate(
                stock_total=Coalesce(
                    Sum(
                        "stocks__cantidad_disponible",
                        filter=Q(stocks__ubicacion_sucursal=ubi_suc),
                    ),
                    Value(0, output_field=DecimalField(max_digits=20, decimal_places=6)),
                )
            )
            .distinct()
        )
        return {
            "sucursal_sel": suc.id,
            "bodega_actual": suc.bodega,
            "productos": productos,
        }

    # Sucursal de origen puede venir por GET o POST (autosubmit)
    suc_id = (request.GET.get("sucursal_origen") or request.POST.get("sucursal_origen") or "").strip()

    # =========================
    #   PRE-CARGA (GET / POST parcial)
    # =========================
    if request.method == "GET" or (
        request.method == "POST"
        and "sucursal_origen" in request.POST
        and not all([request.POST.get("producto"), request.POST.get("cantidad")])
    ):
        if suc_id:
            try:
                suc = Sucursal.objects.select_related("bodega").get(pk=suc_id)
            except Sucursal.DoesNotExist:
                return render(
                    request,
                    "core/Movimientos/sucursal_a_bodega.html",
                    base_ctx(error="La sucursal seleccionada no existe."),
                )

            return render(
                request,
                "core/Movimientos/sucursal_a_bodega.html",
                base_ctx(**ctx_para_sucursal(suc)),
            )

        # Primera carga sin selección
        return render(request, "core/Movimientos/sucursal_a_bodega.html", base_ctx())

    # =========================
    #   POST completo → mover
    # =========================
    if request.method == "POST":
        producto_id  = request.POST.get("producto")
        cantidad_raw = request.POST.get("cantidad")

        # Validaciones base: si faltan datos, mantener UI con sucursal/bodega/productos.
        if not all([suc_id, producto_id, cantidad_raw]):
            if suc_id:
                try:
                    suc = Sucursal.objects.select_related("bodega").get(pk=suc_id)
                    return render(
                        request,
                        "core/Movimientos/sucursal_a_bodega.html",
                        base_ctx(
                            error="Faltan datos en el formulario.",
                            **ctx_para_sucursal(suc),
                        ),
                    )
                except Sucursal.DoesNotExist:
                    pass  # cae al render base
            return render(
                request,
                "core/Movimientos/sucursal_a_bodega.html",
                base_ctx(error="Faltan datos en el formulario."),
            )

        # Parse cantidad
        try:
            cantidad = int(cantidad_raw)
        except (TypeError, ValueError):
            cantidad = 0
        if cantidad <= 0:
            # Mantener UI consistente
            suc = get_object_or_404(Sucursal.objects.select_related("bodega"), pk=suc_id)
            return render(
                request,
                "core/Movimientos/sucursal_a_bodega.html",
                base_ctx(
                    error="La cantidad debe ser mayor que 0.",
                    **ctx_para_sucursal(suc),
                ),
            )

        # Instancias
        suc = get_object_or_404(Sucursal.objects.select_related("bodega"), pk=suc_id)
        if not suc.bodega:
            return render(
                request,
                "core/Movimientos/sucursal_a_bodega.html",
                base_ctx(error="La sucursal no tiene bodega asociada.", **ctx_para_sucursal(suc)),
            )

        producto = get_object_or_404(Producto, pk=producto_id)

        # Ubicaciones firmes
        ubi_suc = ensure_ubicacion_sucursal(suc)
        ubi_bod = ensure_ubicacion_bodega(suc.bodega)

        # Movimiento atómico
        with transaction.atomic():
            # ORIGEN (sucursal)
            stock_origen = (
                Stock.objects
                .select_for_update()
                .filter(producto=producto, ubicacion_sucursal=ubi_suc)
                .first()
            )
            if not stock_origen or stock_origen.cantidad_disponible < cantidad:
                # Recargar combos consistentes
                return render(
                    request,
                    "core/Movimientos/sucursal_a_bodega.html",
                    base_ctx(
                        error=f"No hay stock suficiente en {suc.nombre}.",
                        **ctx_para_sucursal(suc),
                    ),
                )

            # DESTINO (bodega)
            stock_destino, _ = (
                Stock.objects
                .select_for_update()
                .get_or_create(
                    producto=producto,
                    ubicacion_bodega=ubi_bod,
                    defaults={"cantidad_disponible": Decimal("0")},
                )
            )

            # Aplicar movimiento
            stock_origen.cantidad_disponible  -= Decimal(cantidad)
            stock_destino.cantidad_disponible += Decimal(cantidad)
            stock_origen.save(update_fields=["cantidad_disponible"])
            stock_destino.save(update_fields=["cantidad_disponible"])

            # 📧 Notificación si la sucursal queda bajo 10
            try:
                if stock_origen.cantidad_disponible < 10:
                    if "notificar_stock_bajo" in globals():
                        # Usa tu helper HTML si lo tienes disponible
                        notificar_stock_bajo(
                            producto=producto,
                            nombre_lugar=suc.nombre,
                            stock_actual=stock_origen.cantidad_disponible,
                        )
                    else:
                        # Fallback texto plano
                        send_mail(
                            subject="Alerta de stock bajo",
                            message=(
                                f"El stock del producto {producto.nombre} (SKU: {producto.sku}) "
                                f"en la sucursal {suc.nombre} es inferior a 10 unidades. "
                                f"Disponible: {stock_origen.cantidad_disponible}."
                            ),
                            from_email=settings.EMAIL_HOST_USER,
                            recipient_list=settings.TICKETS_NOTIFY_EMAILS,
                            fail_silently=False,
                        )
            except Exception:
                # No romper el flujo por problemas de correo
                pass

        # Recalcular stock global del producto
        total_prod = (
            Stock.objects
            .filter(producto=producto)
            .aggregate(
                t=Coalesce(
                    Sum("cantidad_disponible"),
                    Value(0, output_field=DecimalField(max_digits=20, decimal_places=6)),
                )
            )["t"]
        ) or 0
        producto.stock = int(total_prod)
        producto.save(update_fields=["stock"])

        # Recargar combos para seguir moviendo desde la misma sucursal
        return render(
            request,
            "core/Movimientos/sucursal_a_bodega.html",
            base_ctx(
                **ctx_para_sucursal(suc),
                success=f"Devueltos {cantidad} de {producto.nombre} a {suc.bodega.nombre}.",
            ),
        )

    # Fallback (por si acaso)
    return render(request, "core/Movimientos/sucursal_a_bodega.html", base_ctx())










def movimientos_index(request):
    return render(request, "core/Movimientos/movimientos_index.html")





@require_GET
def geocode(request):
    q = (request.GET.get("q") or "").strip()
    if not q:
        return JsonResponse({"error": "missing query"}, status=400)

    url = "https://nominatim.openstreetmap.org/search"
    params = {
        "format": "json",
        "limit": 1,
        "q": q,
        "countrycodes": "cl",
    }
    headers = {
        # Nominatim pide User-Agent
        "User-Agent": "LogisticFour/1.0 (https://example.com)"
    }

    try:
        r = requests.get(url, params=params, headers=headers, timeout=5)
        r.raise_for_status()
    except requests.RequestException as e:
        return JsonResponse({"error": "upstream_error", "detail": str(e)}, status=502)

    data = r.json()
    if not data:
        return JsonResponse({"error": "not_found"}, status=404)

    item = data[0]
    return JsonResponse({
        "lat": item["lat"],
        "lon": item["lon"],
        "display_name": item.get("display_name", q),
    })
    
from django.utils import timezone



@require_POST
@login_required
@transaction.atomic
def paypal_stock_in(request):
    """
    Llega desde el JS de PayPal cuando el pago fue APROBADO.
    Hace TODO automático y si algo falla devuelve el error en JSON.
    """
    try:
        # -------------------------------------------------
        # 1) leer JSON
        # -------------------------------------------------
        try:
            data = json.loads(request.body.decode("utf-8"))
        except Exception as e:
            return JsonResponse({"ok": False, "error": f"JSON inválido: {e}"}, status=400)

        bodega_id = data.get("bodega_id")
        producto_id = data.get("producto_id")
        cantidad_raw = data.get("cantidad")
        paypal_id = data.get("paypal_id") or "SIN-ID"
        monto_usd_raw = data.get("monto_usd") or "0"

        if not bodega_id or not producto_id or not cantidad_raw:
            return JsonResponse({"ok": False, "error": "Faltan datos"}, status=400)

        # -------------------------------------------------
        # 2) cantidad válida
        # -------------------------------------------------
        try:
            cantidad = Decimal(str(cantidad_raw))
            if cantidad <= 0:
                raise ValueError
        except Exception:
            return JsonResponse({"ok": False, "error": "Cantidad inválida"}, status=400)

        # -------------------------------------------------
        # 3) buscar bodega y producto
        # -------------------------------------------------
        try:
            bodega = Bodega.objects.get(pk=bodega_id)
            producto = Producto.objects.get(pk=producto_id)
        except Bodega.DoesNotExist:
            return JsonResponse({"ok": False, "error": "Bodega no encontrada"}, status=404)
        except Producto.DoesNotExist:
            return JsonResponse({"ok": False, "error": "Producto no encontrado"}, status=404)

        # -------------------------------------------------
        # 4) asegurar UNA ubicación en esa bodega
        # -------------------------------------------------
        ubi = bodega.ubicaciones.filter(activo=True).order_by("id").first()
        if not ubi:
            ubi = UbicacionBodega.objects.create(
                bodega=bodega,
                codigo="AUTO-PP",
                nombre="Ubicación generada por PayPal",
                activo=True,
            )

        # -------------------------------------------------
        # 5) sumar stock en ESA ubicación
        # -------------------------------------------------
        stock_obj, created = Stock.objects.get_or_create(
            producto=producto,
            ubicacion_bodega=ubi,
            defaults={"cantidad_disponible": Decimal("0")}
        )
        Stock.objects.filter(pk=stock_obj.pk).update(
            cantidad_disponible=F("cantidad_disponible") + cantidad
        )
        stock_obj.refresh_from_db()

        # -------------------------------------------------
        # 6) usuario proveedor PayPal (rol = PROVEEDOR)
        # -------------------------------------------------
        proveedor_user, _ = User.objects.get_or_create(
            username="paypal_proveedor",
            defaults={
                "first_name": "Proveedor",
                "last_name": "PayPal",
                "email": "paypal@example.com",
            },
        )
        UsuarioPerfil.objects.get_or_create(
            usuario=proveedor_user,
            defaults={"rol": UsuarioPerfil.Rol.PROVEEDOR},
        )

        # -------------------------------------------------
        # 7) unidad de medida segura
        # -------------------------------------------------
        um = getattr(producto, "unidad_base", None)
        if not um:
            # intentamos agarrar una existente
            um = UnidadMedida.objects.first()
        if not um:
            # si no hay ninguna en la bd, creamos una por defecto
            um, _ = UnidadMedida.objects.get_or_create(
                codigo="UN-PP",
                defaults={"descripcion": "Unidad por PayPal"},
            )

        # -------------------------------------------------
        # 8) crear ORDEN DE COMPRA
        # -------------------------------------------------
        numero_orden = f"OC-PAYPAL-{timezone.now().strftime('%Y%m%d%H%M%S')}"
        oc = OrdenCompra.objects.create(
            proveedor=proveedor_user,
            tasa_impuesto=None,
            bodega=bodega,
            numero_orden=numero_orden,
            estado="COMPLETED",
            fecha_esperada=timezone.now().date(),
            creado_por=request.user,
        )

         # 6) responder al JS
        return JsonResponse({
            "ok": True,
            "nuevo_stock": str(stock_obj.cantidad_disponible),
            "msg": "Stock agregado correctamente",
        })
    except Exception as e:
        return JsonResponse({"ok": False, "error": f"Error inesperado: {e}"}, status=500)

@login_required
def bodega_agregar_sucursal(request, bodega_id):
    bodega = get_object_or_404(Bodega, pk=bodega_id)

    # traemos TODAS las sucursales para mostrarlas
    sucursales = (
        Sucursal.objects
        .select_related("bodega")
        .order_by("nombre")
    )

    if request.method == "POST":
        # puede venir 1 o muchas
        seleccionadas = request.POST.getlist("sucursales")
        if not seleccionadas:
            return render(
                request,
                "core/Bodega/bodega_agregar_sucursal.html",
                {
                    "bodega": bodega,
                    "sucursales": sucursales,
                    "error": "Debes seleccionar al menos una sucursal.",
                },
            )

        # reasignamos todas las seleccionadas a ESTA bodega
        Sucursal.objects.filter(pk__in=seleccionadas).update(bodega=bodega)

        return redirect("bodega-list")

    return render(
        request,
        "core/bodega_agregar_sucursal.html",
        {
            "bodega": bodega,
            "sucursales": sucursales,
        },
    )



















































@login_required
def bodega_productos(request, bodega_id: int):
    bodega = get_object_or_404(Bodega, pk=bodega_id)
    q = (request.GET.get("q") or "").strip()

    ubi_ids = UbicacionBodega.objects.filter(bodega=bodega).values_list("id", flat=True)

    productos = (
        Producto.objects
        .filter(stocks__ubicacion_bodega_id__in=ubi_ids)
        .annotate(
            stock_total=Coalesce(
                Sum("stocks__cantidad_disponible"),
                Value(0, output_field=DecimalField(max_digits=20, decimal_places=6)),
            )
        )
        .distinct()
        .order_by("nombre")
    )

    if q:
        productos = productos.filter(Q(nombre__icontains=q) | Q(sku__icontains=q))

    total_items = productos.count()
    suma_stock = (
        productos.aggregate(
            s=Coalesce(
                Sum("stock_total"),
                Value(0, output_field=DecimalField(max_digits=20, decimal_places=6)),
            )
        )["s"] or 0
    )

    return render(
        request,
        "core/Movimientos/bodega_productos.html",
        {
            "bodega": bodega,
            "productos": productos,
            "q": q,
            "total_items": total_items,
            "suma_stock": suma_stock,
        },
    )



@login_required
@require_GET
def ajax_ubicaciones_por_producto(request):
  bodega_id = request.GET.get("bodega_id")
  producto_id = request.GET.get("producto_id")

  try:
      bodega = Bodega.objects.get(pk=bodega_id)
      producto = Producto.objects.get(pk=producto_id)
  except (Bodega.DoesNotExist, Producto.DoesNotExist):
      return JsonResponse({"error": "Parámetros inválidos"}, status=400)

  # ubicaciones de esa bodega con cantidad
  rows = (
      Stock.objects
      .filter(producto=producto, ubicacion_bodega__bodega=bodega)
      .values("ubicacion_bodega__codigo", "ubicacion_bodega__nombre")
      .annotate(
          cantidad=Coalesce(
              Sum("cantidad_disponible"),
              Value(0, output_field=DecimalField(max_digits=20, decimal_places=6)),
          )
      )
      .order_by("ubicacion_bodega__codigo")
  )

  data = {
      "ubicaciones": [
          {
              "codigo": r["ubicacion_bodega__codigo"],
              "nombre": r["ubicacion_bodega__nombre"],
              "cantidad": str(r["cantidad"]).rstrip("0").rstrip(".") if "." in str(r["cantidad"]) else str(r["cantidad"]),
          }
          for r in rows
      ]
  }
  return JsonResponse(data)


@login_required
def paypal_ingresos_view(request):
    ordenes = (
        OrdenCompra.objects
        .filter(numero_orden__startswith="OC-PAYPAL-")
        .select_related("bodega")
        .prefetch_related("lineas__producto")
        .order_by("-id")
    )
    return render(request, "core/paypal_ingresos.html", {"ordenes": ordenes})
