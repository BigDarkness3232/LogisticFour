import io
import segno

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.urls import reverse, NoReverseMatch
from django.contrib import messages
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User, Group
from django.db import transaction
from django import forms
from core.forms import *
from core.models import *
from django.http import HttpResponse, Http404
from django.conf import settings
from django.views.generic import ListView, CreateView, UpdateView, DeleteView, DetailView
from django.contrib.auth.mixins import LoginRequiredMixin  # agrega PermissionRequiredMixin si ya manejas permisos
from django.contrib.messages.views import SuccessMessageMixin
from django.urls import reverse_lazy
from django.db.models import Q, Sum, F, Value, DecimalField
from django.db.models.functions import Coalesce
from django.shortcuts import redirect
from django.contrib import messages
from django.core.paginator import Paginator
from core.forms import SignupUserForm, UsuarioPerfilForm
from core.models import UsuarioPerfil
from django.contrib.auth.mixins import UserPassesTestMixin
from django.views import View
from django.db.models.functions import Lower
from django.db.models import Count





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


@login_required
def product_add(request):
    """
    versión nueva: el form de producto YA NO trae campo ubicacion.
    así que solo creamos el producto y listo.
    si quieres stock inicial por ubicación, hazlo en otra vista.
    """
    if request.method == "POST":
        form = ProductoForm(request.POST)
        if form.is_valid():
            producto = form.save()
            messages.success(request, "Producto creado.")
            return redirect("products")
    else:
        form = ProductoForm()

    return render(request, "core/product_add.html", {"form": form})





# -------------------- Login Helpers --------------------
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













from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST, require_GET
from django.contrib.auth.decorators import login_required

        
from .models import UsuarioPerfil          




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


from django.db.models import Prefetch



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


class SucursalDeleteView(LoginRequiredMixin, AdminOnlyMixin, SuccessMessageMixin, DeleteView):
    model = Sucursal
    template_name = "core/sucursal_confirm_delete.html"
    success_url = reverse_lazy("sucursal-list")

    def delete(self, request, *args, **kwargs):
        messages.success(request, "Sucursal eliminada correctamente.")
        return super().delete(request, *args, **kwargs)





class BodegaListView(LoginRequiredMixin, ListView):
    model = Bodega
    template_name = "core/bodega_list.html"
    context_object_name = "bodegas"
    paginate_by = 20

    def get_paginate_by(self, queryset):
        """Permite ?page_size= (1..100)."""
        try:
            size = int(self.request.GET.get("page_size", self.paginate_by))
        except (TypeError, ValueError):
            size = self.paginate_by
        return max(1, min(size, 100))

    def get_queryset(self):
        q = (self.request.GET.get("q") or "").strip()

        qs = (
            Bodega.objects
            .prefetch_related(
                "sucursales",                # relaciÃ³n inversa
                "ubicaciones",        # ubicaciones directas
                "ubicaciones__stocks",  # stocks en ubicaciones
            )
            .annotate(
                total_stock=Coalesce(
                    Sum("ubicaciones__stocks__cantidad_disponible"),
                    Value(0, output_field=DecimalField(max_digits=20, decimal_places=6)),
                ),
                sucursales_count=Count("sucursales", distinct=True),
                ubicaciones_count=Count("ubicaciones", distinct=True),
                productos_count=Count("ubicaciones__stocks__producto", distinct=True),
            )
            .only("id", "codigo", "nombre", "descripcion", "activo")
            .order_by(Lower("codigo").asc())
        )

        if q:
            qs = qs.filter(
                Q(codigo__icontains=q) |
                Q(nombre__icontains=q) |
                Q(descripcion__icontains=q) |
                Q(sucursales__codigo__icontains=q) |
                Q(sucursales__nombre__icontains=q)
            )

        return qs.distinct()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        q = (self.request.GET.get("q") or "").strip()
        qs = self.get_queryset()

        ctx["q"] = q
        ctx["has_filters"] = bool(q)
        ctx["total"] = qs.count()
        ctx["page_size"] = self.get_paginate_by(qs)
        # Precalcular stock_total por ubicaciÃ³n para usarlo en el template
        try:
            for b in qs:
                for u in getattr(b, "ubicaciones", []).all():
                    total = 0
                    for st in getattr(u, "stocks", []).all():
                        try:
                            total += float(st.cantidad_disponible or 0)
                        except Exception:
                            total += 0
                    u.stock_total = total
        except Exception:
            # Si algo falla, seguimos sin romper la pÃ¡gina
            pass

        ctx["bodegas"] = qs
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


class BodegaDeleteView(LoginRequiredMixin, BodegaPermissionMixin, SuccessMessageMixin, DeleteView):
    model = Bodega
    template_name = "core/bodega_confirm_delete.html"
    success_url = reverse_lazy("bodega-list")

    def delete(self, request, *args, **kwargs):
        messages.success(request, "Bodega eliminada correctamente.")
        return super().delete(request, *args, **kwargs)

    def dispatch(self, request, *args, **kwargs):
        """BODEGUERO solo puede eliminar bodegas de su sucursal (salvo superuser)."""
        perfil = getattr(request.user, "perfil", None)
        if not request.user.is_superuser and perfil and perfil.rol == UsuarioPerfil.Rol.BODEGUERO:
            obj = self.get_object()
            if not obj or obj.sucursal_id != (perfil.sucursal.id if getattr(perfil, "sucursal", None) else None):
                messages.error(request, "No tienes permisos para eliminar esta bodega.")
                return redirect("bodega-list")
        return super().dispatch(request, *args, **kwargs)


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

class ProductDeleteView(LoginRequiredMixin, DeleteView):
    model = Producto
    template_name = "core/product_confirm_delete.html"  # fallback si navegas directo
    success_url = reverse_lazy("products")

    def delete(self, request, *args, **kwargs):
        messages.success(request, "Producto eliminado correctamente.")
        return super().delete(request, *args, **kwargs)


class ProductDetailView(LoginRequiredMixin, DetailView):
    model = Producto
    template_name = "core/product_detail.html"
    context_object_name = "producto"





























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











































from core.models import Producto            # o el app donde tengas Producto







from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Sum, Value, DecimalField, F
from django.db.models.functions import Coalesce
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

# Ajusta estos imports a tus modelos reales
from .models import Producto



from django.db.models import Sum, Value, DecimalField, ExpressionWrapper





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


def _recalcular_total_producto(producto):
    """
    VersiÃ³n sin tabla Stock.
    Asegura que 'stock' y 'reserva' existan y sean decimales >= 0.
    Ãštil como 'normalizador' tras operaciones.
    """
    disponible = Decimal(getattr(producto, "stock", 0) or 0)
    reservado  = _get_reserva(producto)

    if disponible < 0:
        disponible = Decimal(0)
    if reservado < 0:
        reservado = Decimal(0)

    producto.stock = disponible
    _set_reserva(producto, reservado)

    # Guardar solo los campos que existan
    update_fields = ["stock"]
    if hasattr(producto, RESERVA_FIELD):
        update_fields.append(RESERVA_FIELD)
    producto.save(update_fields=update_fields)


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

def ajustar_stock(producto, delta_disponible=0, delta_reservado=0, guardar=True):
    """
    Suma/resta cantidades directamente en Producto.
    Uso:
      ajustar_stock(prod, delta_disponible=+5)       # entrada de stock
      ajustar_stock(prod, delta_disponible=-2)       # salida de stock
      ajustar_stock(prod, delta_reservado=+3)        # reservar 3
      ajustar_stock(prod, delta_reservado=-1)        # liberar 1 de reserva
    """
    disponible = Decimal(getattr(producto, "stock", 0) or 0) + Decimal(delta_disponible or 0)
    reservado  = _get_reserva(producto) + Decimal(delta_reservado or 0)

    if disponible < 0:
        disponible = Decimal(0)
    if reservado < 0:
        reservado = Decimal(0)

    producto.stock = disponible
    _set_reserva(producto, reservado)

    if guardar:
        update_fields = ["stock"]
        if hasattr(producto, RESERVA_FIELD):
            update_fields.append(RESERVA_FIELD)
        producto.save(update_fields=update_fields)
    return producto


def set_stock(producto, disponible=None, reservado=None, guardar=True):
    """
    Seteo directo (absoluto) de stock/reserva en Producto.
    """
    if disponible is not None:
        d = Decimal(disponible or 0)
        producto.stock = d if d > 0 else Decimal(0)

    if reservado is not None and hasattr(producto, RESERVA_FIELD):
        r = Decimal(reservado or 0)
        _set_reserva(producto, r if r > 0 else Decimal(0))

    if guardar:
        update_fields = ["stock"]
        if hasattr(producto, RESERVA_FIELD):
            update_fields.append(RESERVA_FIELD)
        producto.save(update_fields=update_fields)
    return producto

# ---------- Consulta: ver stock por producto (tu lÃ³gica, con pequeÃ±os ajustes) ----------
from django.db.models import Sum, F



from django.db.models import (
    Sum, Value, DecimalField, F, Case, When, CharField
)
from django.db.models.functions import Coalesce


@login_required
def stock_por_producto(request):
    """
    Consulta de stock por SKU.
    Muestra:
      - totales globales
      - desglose por sucursal (si viene de ubicacion_sucursal)
      - desglose por bodega (si viene de ubicacion_bodega)
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
                # como no tienes reservas en Stock, el neto es igual al disponible
                "total_neto": disponible,
            }

            # 2) DESGLOSE POR ORIGEN DE LA UBICACIÓN
            # Creamos columnas "virtuales" para poder agrupar aunque haya
            # registros que vienen SOLO de bodega o SOLO de sucursal
            resumen_sucursales = (
                Stock.objects
                .filter(producto=producto)
                .annotate(
                    # si viene de sucursal
                    sucursal_codigo=Case(
                        When(ubicacion_sucursal__isnull=False,
                             then=F("ubicacion_sucursal__sucursal__codigo")),
                        default=Value("", output_field=CharField()),
                    ),
                    sucursal_nombre=Case(
                        When(ubicacion_sucursal__isnull=False,
                             then=F("ubicacion_sucursal__sucursal__nombre")),
                        default=Value("", output_field=CharField()),
                    ),
                    # si viene de bodega
                    bodega_codigo=Case(
                        When(ubicacion_bodega__isnull=False,
                             then=F("ubicacion_bodega__bodega__codigo")),
                        default=Value("", output_field=CharField()),
                    ),
                    bodega_nombre=Case(
                        When(ubicacion_bodega__isnull=False,
                             then=F("ubicacion_bodega__bodega__nombre")),
                        default=Value("", output_field=CharField()),
                    ),
                )
                .values(
                    "sucursal_codigo",
                    "sucursal_nombre",
                    "bodega_codigo",
                    "bodega_nombre",
                )
                .annotate(
                    total_disponible=Coalesce(
                        Sum("cantidad_disponible"),
                        Value(0, output_field=DecimalField(max_digits=20, decimal_places=6))
                    ),
                    # neto = disponible, porque no hay reservas en el modelo
                    total_neto=F("total_disponible"),
                )
                .order_by("sucursal_codigo", "bodega_codigo")
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

    try:
        pid = int(request.POST.get("producto_id"))
    except (TypeError, ValueError):
        return _json_or_redirect(request, False, "Producto inválido.")

    try:
        cantidad = float(request.POST.get("cantidad"))
    except (TypeError, ValueError):
        return _json_or_redirect(request, False, "Cantidad inválida.")

    ubicacion_id = request.POST.get("ubicacion")  # puede ser de bodega o de sucursal
    producto = get_object_or_404(Producto, pk=pid)

    if ubicacion_id:
        stock, _, _, _ = _get_or_create_stock(producto, int(ubicacion_id))
        stock.cantidad_disponible = F("cantidad_disponible") + Decimal(cantidad)
        stock.save(update_fields=["cantidad_disponible"])
    else:
        # sin ubicación → directo al producto
        producto.stock = max(0, int((producto.stock or 0) + cantidad))
        producto.save(update_fields=["stock"])

    _recalcular_stock_global(producto)

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
        stock, _, _, _ = _get_or_create_stock(producto, int(ubicacion_id))
        stock.cantidad_disponible = Decimal(cantidad_real)
        stock.save(update_fields=["cantidad_disponible"])
    else:
        producto.stock = max(0, int(cantidad_real))
        producto.save(update_fields=["stock"])

    _recalcular_stock_global(producto)

    return _json_or_redirect(
        request,
        True,
        f"Recuento guardado ({cantidad_real:g}) para {producto.sku}",
        redirect_to=reverse("products"),
    )











































import logging
from django.shortcuts import render
from .models import Producto, Bodega, Sucursal, Stock

# Configurar el logger



# Configurar el logger
logger = logging.getLogger(__name__)


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
    producto.stock = int(total)
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


def _recalcular_stock_global(producto: Producto) -> None:
    """
    Suma TODO el stock por ubicaciones (bodega + sucursal) y lo deja en producto.stock.
    """
    agg = (
        Stock.objects.filter(producto=producto)
        .aggregate(
            total=Coalesce(
                Sum("cantidad_disponible"),
                Value(0, output_field=DecimalField(max_digits=20, decimal_places=6)),
            )
        )
    )
    total = agg["total"] or 0
    producto.stock = int(total)
    producto.save(update_fields=["stock"])








@login_required
def bodega_a_sucursal(request):
    bodegas = (
        Bodega.objects.prefetch_related("sucursales", "ubicaciones").order_by("codigo")
    )

    if request.method == "POST":
        bodega_id = request.POST.get("bodega")
        sucursal_id = request.POST.get("sucursal")
        producto_id = request.POST.get("producto")
        cantidad_raw = request.POST.get("cantidad")

        print("[MOV] POST →", {
            "bodega": bodega_id,
            "sucursal": sucursal_id,
            "producto": producto_id,
            "cantidad": cantidad_raw,
        })

        if not all([bodega_id, sucursal_id, producto_id, cantidad_raw]):
            return render(
                request,
                "core/Movimientos/bodega_a_sucursal.html",
                {"bodegas": bodegas, "error": "Faltan datos en el formulario."},
            )

        # validar cantidad
        try:
            cantidad = int(cantidad_raw)
        except (ValueError, TypeError):
            return render(
                request,
                "core/Movimientos/bodega_a_sucursal.html",
                {"bodegas": bodegas, "error": "La cantidad debe ser un número entero."},
            )

        if cantidad <= 0:
            return render(
                request,
                "core/Movimientos/bodega_a_sucursal.html",
                {"bodegas": bodegas, "error": "La cantidad debe ser mayor que 0."},
            )

        # instancias base
        try:
            bodega = Bodega.objects.get(pk=bodega_id)
        except Bodega.DoesNotExist:
            return render(
                request,
                "core/Movimientos/bodega_a_sucursal.html",
                {"bodegas": bodegas, "error": "La bodega seleccionada no existe."},
            )

        try:
            sucursal = Sucursal.objects.get(pk=sucursal_id, bodega=bodega)
        except Sucursal.DoesNotExist:
            return render(
                request,
                "core/Movimientos/bodega_a_sucursal.html",
                {"bodegas": bodegas, "error": "La sucursal no pertenece a esa bodega."},
            )

        try:
            producto = Producto.objects.get(pk=producto_id)
        except Producto.DoesNotExist:
            return render(
                request,
                "core/Movimientos/bodega_a_sucursal.html",
                {"bodegas": bodegas, "error": "El producto seleccionado no existe."},
            )

        ubi_origen = bodega.ubicaciones.first()
        ubi_destino = sucursal.ubicaciones.first()

        if not ubi_origen or not ubi_destino:
            return render(
                request,
                "core/Movimientos/bodega_a_sucursal.html",
                {"bodegas": bodegas, "error": "Faltan ubicaciones en bodega o sucursal."},
            )

        print(f"[MOV] mover {cantidad} de {producto.sku} "
              f"ORIGEN BOD({bodega.id})/ubi:{ubi_origen.id} "
              f"→ DEST SUC({sucursal.id})/ubi:{ubi_destino.id}")

        with transaction.atomic():
            # 1) ORIGEN (bodega)
            stock_origen = (
                Stock.objects
                .select_for_update()
                .filter(producto=producto, ubicacion_bodega=ubi_origen)
                .first()
            )
            if not stock_origen:
                stock_origen = Stock.objects.create(
                    producto=producto,
                    ubicacion_bodega=ubi_origen,
                    cantidad_disponible=Decimal("0"),
                )
                print("[MOV] stock_origen creado:", stock_origen.id)

            print("[MOV] stock_origen ANTES:", stock_origen.id, stock_origen.cantidad_disponible)

            if stock_origen.cantidad_disponible < cantidad:
                return render(
                    request,
                    "core/Movimientos/bodega_a_sucursal.html",
                    {
                        "bodegas": bodegas,
                        "error": (
                            f"No hay stock suficiente en la bodega. Disponible: "
                            f"{stock_origen.cantidad_disponible}."
                        ),
                    },
                )

            # 2) DESTINO (sucursal)
            stock_destino = (
                Stock.objects
                .select_for_update()
                .filter(producto=producto, ubicacion_sucursal=ubi_destino)
                .first()
            )

            # 🔥 CASO PROBLEMÁTICO:
            # hay un stock que tiene ambas FK llenas y además es el mismo que el de origen
            if stock_destino and stock_destino.id == stock_origen.id:
                print("[WARN] origen y destino son la MISMA fila con 2 FK → la saneo")
                # esta fila debe representar la BODEGA, así que le quitamos la sucursal
                stock_origen.ubicacion_sucursal = None
                stock_origen.save(update_fields=["ubicacion_sucursal"])
                print("[FIX] limpié la sucursal de la fila origen:", stock_origen.id)
                # ahora sí puedo crear la fila de destino sin romper UNIQUE
                stock_destino = Stock.objects.create(
                    producto=producto,
                    ubicacion_sucursal=ubi_destino,
                    cantidad_disponible=Decimal("0"),
                )
                print("[FIX] fila de destino creada:", stock_destino.id)

            elif not stock_destino:
                # no existía stock en esa sucursal → lo creo
                stock_destino = Stock.objects.create(
                    producto=producto,
                    ubicacion_sucursal=ubi_destino,
                    cantidad_disponible=Decimal("0"),
                )
                print("[MOV] stock_destino creado:", stock_destino.id)

            print("[MOV] stock_destino ANTES:", stock_destino.id, stock_destino.cantidad_disponible)

            # 3) aplicar movimiento
            stock_origen.cantidad_disponible = (
                stock_origen.cantidad_disponible - Decimal(cantidad)
            )
            stock_origen.save(update_fields=["cantidad_disponible"])

            stock_destino.cantidad_disponible = (
                stock_destino.cantidad_disponible + Decimal(cantidad)
            )
            stock_destino.save(update_fields=["cantidad_disponible"])

            print("[MOV] stock_origen DESPUÉS:", stock_origen.id, stock_origen.cantidad_disponible)
            print("[MOV] stock_destino DESPUÉS:", stock_destino.id, stock_destino.cantidad_disponible)

        # 4) recalcular stock global
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
        print(f"[MOV] stock global de {producto.sku} = {producto.stock}")

        sucursales_de_bodega = bodega.sucursales.all().order_by("codigo")
        productos_de_bodega = (
            Producto.objects.filter(stocks__ubicacion_bodega__bodega=bodega)
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
            "core/Movimientos/bodega_a_sucursal.html",
            {
                "bodegas": bodegas,
                "sucursales": sucursales_de_bodega,
                "productos": productos_de_bodega,
                "success": (
                    f"Movimiento realizado: {cantidad} de {producto.nombre} → {sucursal.nombre}."
                ),
                "bodega_sel": bodega.id,
            },
        )

    return render(request, "core/Movimientos/bodega_a_sucursal.html", {"bodegas": bodegas})





from .utils import ensure_ubicacion_sucursal



@login_required
def sucursal_a_sucursal(request):
    # 1) siempre cargamos todas las sucursales para el select de ORIGEN
    sucursales = (
        Sucursal.objects
        .prefetch_related("ubicaciones")
        .order_by("nombre")
    )

    # 2) la sucursal de origen puede venir por GET (cuando solo cambias el select)
    #    o por POST (cuando ya mandas el formulario)
    suc_origen_id = request.GET.get("sucursal_origen") or request.POST.get("sucursal_origen")

    sucursales_destino = None      # se llena cuando hay origen
    productos_de_origen = None     # se llena cuando hay origen
    suc_origen = None

    # ============================
    #   PRE-CARGA POR ORIGEN
    # ============================
    if suc_origen_id:
        try:
            suc_origen = Sucursal.objects.get(pk=suc_origen_id)
        except Sucursal.DoesNotExist:
            suc_origen = None
        else:
            # si la sucursal no tiene ubicación, la creamos acá mismo
            ensure_ubicacion_sucursal(suc_origen)

            # sucursales destino = TODAS menos la de origen
            sucursales_destino = (
                Sucursal.objects
                .exclude(pk=suc_origen.pk)
                .order_by("nombre")
            )

            # productos con stock > 0 en la sucursal de origen
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

    # ============================
    #   POST → mover
    # ============================
    if request.method == "POST":
        suc_destino_id = request.POST.get("sucursal_destino")
        producto_id = request.POST.get("producto")
        cantidad_raw = request.POST.get("cantidad")

        # validación rápida
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

        # cantidad
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

        # instancias firmes
        suc_origen = get_object_or_404(Sucursal, pk=suc_origen_id)
        suc_destino = get_object_or_404(Sucursal, pk=suc_destino_id)
        producto = get_object_or_404(Producto, pk=producto_id)

        # garantiza que las 2 sucursales tengan al menos 1 ubicación
        ubi_origen = ensure_ubicacion_sucursal(suc_origen)
        ubi_destino = ensure_ubicacion_sucursal(suc_destino)

        # ============================
        #   MOVIMIENTO ATÓMICO
        # ============================
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
                        "sucursal_sel": suc_origen_id,
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

            # aplicar movimiento
            stock_origen.cantidad_disponible -= Decimal(cantidad)
            stock_destino.cantidad_disponible += Decimal(cantidad)
            stock_origen.save(update_fields=["cantidad_disponible"])
            stock_destino.save(update_fields=["cantidad_disponible"])

        # ============================
        #   RECALCULAR STOCK GLOBAL
        # ============================
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

        # recargar combos ya filtrados por la misma sucursal de origen
        sucursales_destino = (
            Sucursal.objects
            .exclude(pk=suc_origen.pk)
            .order_by("nombre")
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

        return render(
            request,
            "core/Movimientos/sucursal_a_sucursal.html",
            {
                "sucursales": sucursales,
                "sucursal_sel": suc_origen.id,
                "sucursales_destino": sucursales_destino,
                "productos": productos_de_origen,
                "success": "Movimiento realizado.",
            },
        )

    # ============================
    #   GET inicial / sin mover
    # ============================
    return render(
        request,
        "core/Movimientos/sucursal_a_sucursal.html",
        {
            "sucursales": sucursales,
            "sucursal_sel": suc_origen_id,
            "sucursales_destino": sucursales_destino,
            "productos": productos_de_origen,
        },
    )

@login_required
def bodega_a_bodega(request):
    bodegas = (
        Bodega.objects
        .prefetch_related("ubicaciones")
        .order_by("codigo")
    )

    if request.method == "POST":
        bodega_origen_id = request.POST.get("bodega_origen")
        bodega_destino_id = request.POST.get("bodega_destino")
        producto_id = request.POST.get("producto")
        cantidad_raw = request.POST.get("cantidad")

        if not all([bodega_origen_id, bodega_destino_id, producto_id, cantidad_raw]):
            return render(
                request,
                "core/Movimientos/bodega_a_bodega.html",
                {"bodegas": bodegas, "error": "Faltan datos en el formulario."},
            )

        if bodega_origen_id == bodega_destino_id:
            return render(
                request,
                "core/Movimientos/bodega_a_bodega.html",
                {"bodegas": bodegas, "error": "La bodega de origen y destino no pueden ser la misma."},
            )

        try:
            cantidad = int(cantidad_raw)
        except (ValueError, TypeError):
            return render(
                request,
                "core/Movimientos/bodega_a_bodega.html",
                {"bodegas": bodegas, "error": "La cantidad debe ser un número entero."},
            )

        if cantidad <= 0:
            return render(
                request,
                "core/Movimientos/bodega_a_bodega.html",
                {"bodegas": bodegas, "error": "La cantidad debe ser mayor que 0."},
            )

        try:
            bodega_origen = Bodega.objects.get(pk=bodega_origen_id)
        except Bodega.DoesNotExist:
            return render(
                request,
                "core/Movimientos/bodega_a_bodega.html",
                {"bodegas": bodegas, "error": "La bodega de origen no existe."},
            )

        try:
            bodega_destino = Bodega.objects.get(pk=bodega_destino_id)
        except Bodega.DoesNotExist:
            return render(
                request,
                "core/Movimientos/bodega_a_bodega.html",
                {"bodegas": bodegas, "error": "La bodega de destino no existe."},
            )

        try:
            producto = Producto.objects.get(pk=producto_id)
        except Producto.DoesNotExist:
            return render(
                request,
                "core/Movimientos/bodega_a_bodega.html",
                {"bodegas": bodegas, "error": "El producto seleccionado no existe."},
            )

        ubi_origen = bodega_origen.ubicaciones.first()
        ubi_destino = bodega_destino.ubicaciones.first()
        if not ubi_origen or not ubi_destino:
            return render(
                request,
                "core/Movimientos/bodega_a_bodega.html",
                {"bodegas": bodegas, "error": "Faltan ubicaciones en alguna bodega."},
            )

        with transaction.atomic():
            # ORIGEN
            stock_origen = (
                Stock.objects
                .select_for_update()
                .filter(producto=producto, ubicacion_bodega=ubi_origen)
                .first()
            )
            if not stock_origen:
                stock_origen = Stock.objects.create(
                    producto=producto,
                    ubicacion_bodega=ubi_origen,
                    cantidad_disponible=Decimal("0"),
                )

            if stock_origen.cantidad_disponible < cantidad:
                return render(
                    request,
                    "core/Movimientos/bodega_a_bodega.html",
                    {
                        "bodegas": bodegas,
                        "error": f"No hay stock suficiente en la bodega de origen. Disponible: {stock_origen.cantidad_disponible}.",
                    },
                )

            # DESTINO
            stock_destino = (
                Stock.objects
                .select_for_update()
                .filter(producto=producto, ubicacion_bodega=ubi_destino)
                .first()
            )

            if stock_destino and stock_destino.id == stock_origen.id:
                # lo saneamos: esta fila será la de origen
                stock_origen.ubicacion_sucursal = None
                stock_origen.save(update_fields=["ubicacion_sucursal"])
                stock_destino = Stock.objects.create(
                    producto=producto,
                    ubicacion_bodega=ubi_destino,
                    cantidad_disponible=Decimal("0"),
                )
            elif not stock_destino:
                stock_destino = Stock.objects.create(
                    producto=producto,
                    ubicacion_bodega=ubi_destino,
                    cantidad_disponible=Decimal("0"),
                )

            # aplicar
            stock_origen.cantidad_disponible = stock_origen.cantidad_disponible - Decimal(cantidad)
            stock_origen.save(update_fields=["cantidad_disponible"])

            stock_destino.cantidad_disponible = stock_destino.cantidad_disponible + Decimal(cantidad)
            stock_destino.save(update_fields=["cantidad_disponible"])

        # recalcular global
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

        productos_de_origen = (
            Producto.objects.filter(stocks__ubicacion_bodega__bodega=bodega_origen)
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
            "core/Movimientos/bodega_a_bodega.html",
            {
                "bodegas": bodegas,
                "productos": productos_de_origen,
                "success": f"Movimiento realizado: {cantidad} de {producto.nombre} → {bodega_destino.nombre}.",
                "bodega_sel": bodega_origen.id,
            },
        )

    return render(request, "core/Movimientos/bodega_a_bodega.html", {"bodegas": bodegas})






@login_required
def sucursal_a_bodega(request):
    # necesitamos bodegas porque la sucursal igual cuelga de una
    bodegas = (
        Bodega.objects
        .prefetch_related("sucursales", "ubicaciones")
        .order_by("codigo")
    )

    if request.method == "POST":
        sucursal_id = request.POST.get("sucursal")
        bodega_id = request.POST.get("bodega")
        producto_id = request.POST.get("producto")
        cantidad_raw = request.POST.get("cantidad")

        if not all([sucursal_id, bodega_id, producto_id, cantidad_raw]):
            return render(
                request,
                "core/Movimientos/sucursal_a_bodega.html",
                {"bodegas": bodegas, "error": "Faltan datos en el formulario."},
            )

        try:
            cantidad = int(cantidad_raw)
        except (ValueError, TypeError):
            return render(
                request,
                "core/Movimientos/sucursal_a_bodega.html",
                {"bodegas": bodegas, "error": "La cantidad debe ser un número entero."},
            )
        if cantidad <= 0:
            return render(
                request,
                "core/Movimientos/sucursal_a_bodega.html",
                {"bodegas": bodegas, "error": "La cantidad debe ser mayor que 0."},
            )

        # instancias
        try:
            bodega = Bodega.objects.get(pk=bodega_id)
        except Bodega.DoesNotExist:
            return render(
                request,
                "core/Movimientos/sucursal_a_bodega.html",
                {"bodegas": bodegas, "error": "La bodega seleccionada no existe."},
            )

        try:
            sucursal = Sucursal.objects.get(pk=sucursal_id, bodega=bodega)
        except Sucursal.DoesNotExist:
            return render(
                request,
                "core/Movimientos/sucursal_a_bodega.html",
                {"bodegas": bodegas, "error": "La sucursal no pertenece a esa bodega."},
            )

        try:
            producto = Producto.objects.get(pk=producto_id)
        except Producto.DoesNotExist:
            return render(
                request,
                "core/Movimientos/sucursal_a_bodega.html",
                {"bodegas": bodegas, "error": "El producto seleccionado no existe."},
            )

        ubi_origen = sucursal.ubicaciones.first()
        ubi_destino = bodega.ubicaciones.first()
        if not ubi_origen or not ubi_destino:
            return render(
                request,
                "core/Movimientos/sucursal_a_bodega.html",
                {"bodegas": bodegas, "error": "Faltan ubicaciones en bodega o sucursal."},
            )

        with transaction.atomic():
            # ORIGEN: sucursal
            stock_origen = (
                Stock.objects
                .select_for_update()
                .filter(producto=producto, ubicacion_sucursal=ubi_origen)
                .first()
            )
            if not stock_origen:
                stock_origen = Stock.objects.create(
                    producto=producto,
                    ubicacion_sucursal=ubi_origen,
                    cantidad_disponible=Decimal("0"),
                )

            if stock_origen.cantidad_disponible < cantidad:
                return render(
                    request,
                    "core/Movimientos/sucursal_a_bodega.html",
                    {
                        "bodegas": bodegas,
                        "error": f"No hay stock suficiente en la sucursal. Disponible: {stock_origen.cantidad_disponible}.",
                    },
                )

            # DESTINO: bodega
            stock_destino = (
                Stock.objects
                .select_for_update()
                .filter(producto=producto, ubicacion_bodega=ubi_destino)
                .first()
            )

            # caso raro
            if stock_destino and stock_destino.id == stock_origen.id:
                # esta fila la dejamos como sucursal (origen)
                stock_origen.ubicacion_bodega = None
                stock_origen.save(update_fields=["ubicacion_bodega"])
                stock_destino = Stock.objects.create(
                    producto=producto,
                    ubicacion_bodega=ubi_destino,
                    cantidad_disponible=Decimal("0"),
                )
            elif not stock_destino:
                stock_destino = Stock.objects.create(
                    producto=producto,
                    ubicacion_bodega=ubi_destino,
                    cantidad_disponible=Decimal("0"),
                )

            # aplicar
            stock_origen.cantidad_disponible = stock_origen.cantidad_disponible - Decimal(cantidad)
            stock_origen.save(update_fields=["cantidad_disponible"])

            stock_destino.cantidad_disponible = stock_destino.cantidad_disponible + Decimal(cantidad)
            stock_destino.save(update_fields=["cantidad_disponible"])

        # recalcular global
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

        sucursales_de_bodega = bodega.sucursales.all().order_by("codigo")
        productos_de_sucursal = (
            Producto.objects.filter(stocks__ubicacion_sucursal__sucursal=sucursal)
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
            "core/Movimientos/sucursal_a_bodega.html",
            {
                "bodegas": bodegas,
                "sucursales": sucursales_de_bodega,
                "productos": productos_de_sucursal,
                "success": f"Movimiento realizado: {cantidad} de {producto.nombre} → {bodega.nombre}.",
                "bodega_sel": bodega.id,
            },
        )

    return render(request, "core/Movimientos/sucursal_a_bodega.html", {"bodegas": bodegas})
