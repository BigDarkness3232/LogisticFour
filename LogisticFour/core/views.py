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


def products(request):
    q = (request.GET.get("q") or "").strip()

    queryset = (
        Producto.objects
        .select_related("marca", "categoria")  # quita/ajusta si no tienes estas FKs
    )

    if q:
        # puedes dividir por espacios y encadenar filtros para “contener todos los términos”
        terms = [t for t in q.replace("-", " ").split() if t]
        for t in terms:
            queryset = queryset.filter(
                Q(sku__icontains=t) |
                Q(nombre__icontains=t) |
                Q(marca__nombre__icontains=t) |
                Q(categoria__nombre__icontains=t)
            )

    # Opcional: contadores (borra estas 3 líneas si no tienes esas relaciones)
    queryset = queryset.annotate(
        proveedores_count=Count("proveedores", distinct=True),
        lotes_count=Count("lotes", distinct=True),
        series_count=Count("series", distinct=True),
    )

    queryset = queryset.order_by("nombre", "sku")

    # Paginación
    paginator = Paginator(queryset, 20)  # 20 por página
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    return render(
        request,
        "core/products.html",  # tu template
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
    return render(request, "core/product_add.html")


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
    # Si ya está logueado, redirige según su rol
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
                'error': 'Usuario o contraseña incorrectos',
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
        fields = ("telefono",)  # añade más campos si quieres capturarlos al alta


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
    Sincroniza el Group del usuario según su perfil.rol.
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
            messages.error(request, "No tienes permisos para realizar esa acción.")
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
            messages.success(request, "✅ Usuario creado correctamente.")
            try:
                return redirect(reverse("usuario-list"))
            except NoReverseMatch:
                return redirect("dashboard")
        else:
            messages.error(request, "❌ Revisa los errores del formulario.")
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

            # si vino role por query y no se cambió en el form, respétalo
            if preset_role and not perfil_form.cleaned_data.get("rol"):
                perfil.rol = preset_role

            perfil.save()
            _sync_user_groups_by_profile(user)

            messages.success(request, "✅ Usuario creado correctamente.")
            return redirect("usuario-list")
        messages.error(request, "❌ Revisa los errores del formulario.")
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

    # Evitar que un admin se desactive/elimine a sí mismo por accidente (opcional)
    editing_self = (request.user.pk == obj.pk)

    # Asegurar que tenga perfil
    perfil, _ = UsuarioPerfil.objects.get_or_create(usuario=obj)

    if request.method == "POST":
        uform = UserEditForm(request.POST, instance=obj)
        pform = UsuarioPerfilEditForm(request.POST, instance=perfil)

        if uform.is_valid() and pform.is_valid():
            # No permitir que un usuario se desactive a sí mismo (opcional, seguridad)
            if editing_self and not uform.cleaned_data.get("is_active", True):
                messages.error(request, "No puedes desactivar tu propio usuario.")
            else:
                uform.save()
                pform.save()
                _sync_user_groups_by_profile(obj)
                messages.success(request, "✅ Usuario actualizado.")
                return redirect("usuario-list")
        else:
            messages.error(request, "❌ Revisa los errores del formulario.")
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

    # Reglas de seguridad útiles:
    if request.user.pk == obj.pk:
        messages.error(request, "No puedes eliminar tu propio usuario.")
        return redirect("usuario-list")
    if obj.is_superuser:
        messages.error(request, "No puedes eliminar un superusuario.")
        return redirect("usuario-list")

    if request.method == "POST":
        obj.delete()
        messages.success(request, "🗑️ Usuario eliminado.")
        return redirect("usuario-list")

    return render(request, "accounts/user_confirm_delete.html", {"obj": obj})













from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required

        
from .models import UsuarioPerfil          




@admin_required
@login_required
def user_list(request):
    """
    Listado con búsqueda y filtro por rol.
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
    Cambia el rol (perfil.rol) de un usuario vía fetch POST JSON.
    Espera: {"rol": "<CODE>"}   (donde CODE es uno de UsuarioPerfil.Rol.choices)
    Responde: {"ok": true, "rol_label": "<Etiqueta>"}  o {"ok": false, "error": "..."}
    """
    import json

    try:
        payload = json.loads(request.body or "{}")
        code = (payload.get("rol") or "").strip()
        if not code:
            return JsonResponse({"ok": False, "error": "Rol no especificado."}, status=400)

        # Validar que el code esté en choices
        valid_map = dict(UsuarioPerfil.Rol.choices)   # {code: label}
        if code not in valid_map:
            return JsonResponse({"ok": False, "error": "Código de rol inválido."}, status=400)

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
    """Mixin para CBV que deja pasar sólo a ADMIN."""
    def test_func(self):
        return _is_admin(self.request.user)
    
    def handle_no_permission(self):
        # Redirige a dashboard con mensaje en lugar de mostrar 403
        messages.error(self.request, "No tienes permisos para realizar esa acción.")
        return redirect('dashboard')


class BodegaPermissionMixin(UserPassesTestMixin):
    """Permite acceso si es ADMIN o BODEGUERO (validación por objeto aparte)."""
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
        messages.error(self.request, "No tienes permisos para realizar esa acción.")
        return redirect('dashboard')


def admin_required(view_func):
    """Decorador para views basadas en funciones que redirige con mensaje si no es admin."""
    def _wrapped(request, *args, **kwargs):
        if not _is_admin(request.user):
            messages.error(request, "No tienes permisos para realizar esa acción.")
            return redirect('dashboard')
        return view_func(request, *args, **kwargs)
    return _wrapped



class SucursalListView(LoginRequiredMixin, ListView):
    model = Sucursal
    template_name = "core/sucursal_list.html"
    context_object_name = "sucursales"
    paginate_by = 20  # valor por defecto

    def get_paginate_by(self, queryset):
        """Permite ?page_size= en la URL (máx 100)."""
        try:
            size = int(self.request.GET.get("page_size", self.paginate_by))
        except (TypeError, ValueError):
            size = self.paginate_by
        return max(1, min(size, 100))

    def get_queryset(self):
        q = (self.request.GET.get("q") or "").strip()
        qs = (
            Sucursal.objects
            .only("id", "codigo", "nombre", "ciudad", "activo")  # optimiza consulta de la lista
            .order_by(Lower("codigo").asc())
        )
        if q:
            qs = qs.filter(
                Q(codigo__icontains=q) |
                Q(nombre__icontains=q) |
                Q(ciudad__icontains=q)
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
    paginate_by = 20  # por defecto

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
            .select_related("sucursal")
            .only(
                "id", "codigo", "nombre", "descripcion", "activo",
                "sucursal__id", "sucursal__codigo", "sucursal__nombre"
            )
            .order_by(Lower("sucursal__codigo").asc(), Lower("codigo").asc())
        )

        if q:
            qs = qs.filter(
                Q(codigo__icontains=q) |
                Q(nombre__icontains=q) |
                Q(descripcion__icontains=q) |
                Q(sucursal__nombre__icontains=q) |
                Q(sucursal__codigo__icontains=q)
            )
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        q = (self.request.GET.get("q") or "").strip()
        base_qs = self.get_queryset()
        ctx["q"] = q
        ctx["has_filters"] = bool(q)
        ctx["total"] = base_qs.count()
        ctx["page_size"] = self.get_paginate_by(base_qs)
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

        # Superusuario o ADMIN: sin restricción
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
        """Fuerza la sucursal del BODEGUERO en el servidor (anti-manipulación)."""
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
        """BODEGUERO solo puede editar bodegas de su sucursal (salvo superuser)."""
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
    template_name = "core/products.html"     # tu listado
    context_object_name = "productos"
    paginate_by = 20

def get_queryset(self):
    return (
        Producto.objects
        .select_related("marca", "categoria", "unidad_base", "tasa_impuesto")
        .annotate(
            lotes_count=Count("lotes", distinct=True),
            series_count=Count("series", distinct=True),
            proveedores_count=Count("productousuarioproveedor", distinct=True),  # si corresponde
        )
        .order_by("nombre")
    )




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
    template_name = "core/product_add.html"  # fallback si entras directo
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

class UbicacionListView(LoginRequiredMixin, ListView):
    model = Ubicacion
    template_name = "core/ubicacion_list.html"
    context_object_name = "ubicaciones"
    paginate_by = 25

    def get_queryset(self):
        qs = (Ubicacion.objects
              .select_related("bodega__sucursal", "area", "tipo")
              .order_by("bodega__sucursal__codigo", "bodega__codigo", "codigo"))
        q = (self.request.GET.get("q") or "").strip()
        if q:
            qs = qs.filter(codigo__icontains=q) | qs.filter(nombre__icontains=q)
        bodega_id = self.request.GET.get("bodega")
        if bodega_id:
            qs = qs.filter(bodega_id=bodega_id)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["bodegas"] = Bodega.objects.select_related("sucursal").order_by("sucursal__codigo", "codigo")
        ctx["q"] = (self.request.GET.get("q") or "").strip()
        ctx["bodega_sel"] = self.request.GET.get("bodega") or ""
        return ctx


# ----------------------
# CRUD Ubicacion (páginas)
# ----------------------
class UbicacionCreateView(LoginRequiredMixin, SuccessMessageMixin, CreateView):
    model = Ubicacion
    form_class = UbicacionForm
    template_name = "core/ubicacion_form.html"
    success_message = "Ubicación creada."
    success_url = reverse_lazy("ubicacion-list")


class UbicacionUpdateView(LoginRequiredMixin, SuccessMessageMixin, UpdateView):
    model = Ubicacion
    form_class = UbicacionForm
    template_name = "core/ubicacion_form.html"
    success_message = "Ubicación actualizada."
    success_url = reverse_lazy("ubicacion-list")


class UbicacionDeleteView(LoginRequiredMixin, DeleteView):
    model = Ubicacion
    template_name = "core/confirm_delete.html"
    success_url = reverse_lazy("ubicacion-list")

    def delete(self, request, *args, **kwargs):
        messages.success(request, "Ubicación eliminada.")
        return super().delete(request, *args, **kwargs)


# ------------------------------------
# AreaBodega + TipoUbicacion con modal
# ------------------------------------
# Los modales usan <dialog> y cargan estas vistas que devuelven la página completa,
# pero con templates chicos pensados para presentarse en un modal.

class AreaBodegaCreateModal(LoginRequiredMixin, SuccessMessageMixin, CreateView):
    model = AreaBodega
    form_class = AreaBodegaForm
    template_name = "core/partials/area_form_modal.html"
    success_message = "Área creada."

    def get_success_url(self):
        # tras guardar, vuelve a la página previa (bodegas) o a listado de ubicaciones
        return self.request.GET.get("next") or reverse_lazy("bodega-list")


class AreaBodegaUpdateModal(LoginRequiredMixin, SuccessMessageMixin, UpdateView):
    model = AreaBodega
    form_class = AreaBodegaForm
    template_name = "core/partials/area_form_modal.html"
    success_message = "Área actualizada."

    def get_success_url(self):
        return self.request.GET.get("next") or reverse_lazy("bodega-list")


class AreaBodegaDeleteModal(LoginRequiredMixin, DeleteView):
    model = AreaBodega
    template_name = "core/partials/confirm_modal.html"
    success_url = reverse_lazy("bodega-list")

    def delete(self, request, *args, **kwargs):
        messages.success(request, "Área eliminada.")
        return super().delete(request, *args, **kwargs)


class TipoUbicacionCreateModal(LoginRequiredMixin, SuccessMessageMixin, CreateView):
    model = TipoUbicacion
    form_class = TipoUbicacionForm
    template_name = "core/partials/tipo_form_modal.html"
    success_message = "Tipo de ubicación creado."

    def get_success_url(self):
        return self.request.GET.get("next") or reverse_lazy("bodega-list")


class TipoUbicacionUpdateModal(LoginRequiredMixin, SuccessMessageMixin, UpdateView):
    model = TipoUbicacion
    form_class = TipoUbicacionForm
    template_name = "core/partials/tipo_form_modal.html"
    success_message = "Tipo de ubicación actualizado."

    def get_success_url(self):
        return self.request.GET.get("next") or reverse_lazy("bodega-list")


class TipoUbicacionDeleteModal(LoginRequiredMixin, DeleteView):
    model = TipoUbicacion
    template_name = "core/partials/confirm_modal.html"
    success_url = reverse_lazy("bodega-list")

    def delete(self, request, *args, **kwargs):
        messages.success(request, "Tipo de ubicación eliminado.")
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
# Categoría de Producto
# ======================
class CategoriaProductoCreateModal(LoginRequiredMixin, SuccessMessageMixin, CreateView):
    model = CategoriaProducto
    form_class = CategoriaProductoForm
    template_name = "core/partials/categoria_form_modal.html"
    success_message = "Categoría creada."

    def get_success_url(self):
        return self.request.GET.get("next") or reverse_lazy("products")


class CategoriaProductoUpdateModal(LoginRequiredMixin, SuccessMessageMixin, UpdateView):
    model = CategoriaProducto
    form_class = CategoriaProductoForm
    template_name = "core/partials/categoria_form_modal.html"
    success_message = "Categoría actualizada."

    def get_success_url(self):
        return self.request.GET.get("next") or reverse_lazy("products")


class CategoriaProductoDeleteModal(LoginRequiredMixin, DeleteView):
    model = CategoriaProducto
    template_name = "core/partials/confirm_modal.html"
    success_url = reverse_lazy("products")

    def delete(self, request, *args, **kwargs):
        messages.success(request, "Categoría eliminada.")
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
    # messages en DeleteView requieren manejo en form_valid o post_delete signal; si usas messages en template, puedes mostrar el texto allí.


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



def productos_por_bodega(request, bodega_id):
    # Obtener la bodega especificada
    bodega = Bodega.objects.get(id=bodega_id)
    
    # Obtener todas las ubicaciones asociadas a la bodega
    ubicaciones_en_bodega = Ubicacion.objects.filter(bodega=bodega)
    
    # Obtener los productos asociados a las ubicaciones de esa bodega
    productos_en_bodega = Producto.objects.filter(ubicacion__in=ubicaciones_en_bodega)
    
    # Parámetro para búsqueda
    q = request.GET.get('q', '')

    # Si hay un término de búsqueda, filtrar los productos
    if q:
        productos_en_bodega = productos_en_bodega.filter(
            sku__icontains=q ,
            nombre__icontains=q ,
            marca__nombre__icontains=q ,
            categoria__nombre__icontains=q
        )
    
    # Paginación
    paginator = Paginator(productos_en_bodega, 10)  # 10 productos por página
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Pasar los datos al template
    return render(request, 'core/productos_por_bodega.html', {
        'bodega': bodega,
        'productos': page_obj,
        'q': q,
        'page_obj': page_obj
    })




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

# === Config: pon aquí el nombre real del campo de reserva en Producto (si existe)
RESERVA_FIELD = "reserva"   # ej. "reservado" si tu modelo lo llama así


def _get_reserva(producto):
    """Obtiene la reserva desde Producto (0 si no existe el campo)."""
    return Decimal(getattr(producto, RESERVA_FIELD, 0) or 0)


def _set_reserva(producto, value):
    """Setea la reserva en Producto (si el campo existe). Ignora si no existe."""
    if hasattr(producto, RESERVA_FIELD):
        setattr(producto, RESERVA_FIELD, Decimal(value or 0))


def _recalcular_total_producto(producto):
    """
    Versión sin tabla Stock.
    Asegura que 'stock' y 'reserva' existan y sean decimales >= 0.
    Útil como 'normalizador' tras operaciones.
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
    Proxy de compatibilidad para código legacy que esperaba un objeto Stock.
    Lee/escribe directamente en Producto.stock y Producto.<RESERVA_FIELD>.
    Tiene un método .save(update_fields=...) para imitar la API.
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
    Ignora la ubicación y devuelve un proxy ligado al Producto.
    Así tu código legacy (que hacía .cantidad_disponible += x; .save()) sigue funcionando.
    """
    return _ProductoStockProxy(producto)


# ====== Helpers “nuevos” para operar stock directamente en Producto ======

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

# ---------- Consulta: ver stock por producto (tu lógica, con pequeños ajustes) ----------

@login_required
def stock_por_producto(request):
    """
    Busca un producto por SKU y muestra su stock global.
    Ahora la fuente es la tabla Producto (campos: stock y reserva),
    no se consulta la tabla Stock ni se desglosa por sucursal/bodega.
    """
    sku = (request.GET.get("sku") or "").strip().upper()
    producto = None
    totales = None
    resumen_sucursales = []   # no se usan con la nueva lógica
    resultados_bodegas = []   # no se usan con la nueva lógica

    if sku:
        try:
            producto = Producto.objects.select_related("marca", "categoria").get(sku=sku)

            # Campos esperados en Producto:
            # - stock: disponible total
            # - reserva: reservado total (si tu campo se llama distinto, ajusta abajo)
            disponible = getattr(producto, "stock", 0) or 0
            reservado  = getattr(producto, "reserva", 0) or 0  # si tu campo es 'reservado', cámbialo aquí
            totales = {
                "total_disponible": disponible,
                "total_reservado":  reservado,
                "total_neto":       (disponible - reservado),
            }

        except Producto.DoesNotExist:
            messages.error(request, f"No se encontró ningún producto con SKU '{sku}'.")

    return render(request, "core/stock_producto.html", {
        "sku": sku,
        "producto": producto,
        "totales": totales,
        "resumen_sucursales": resumen_sucursales,
        "resultados_bodegas": resultados_bodegas,
    })


# ---------- Endpoints de gestión desde productos ----------

@login_required
@transaction.atomic
def stock_ajuste(request):
    """
    Suma/resta stock del producto. Si se envía ubicacion (opcional), ajusta ese registro.
    POST: producto_id, cantidad (+/-), motivo, nota, [ubicacion]
    """
    if request.method != "POST":
        return HttpResponseBadRequest("Método no permitido")

    try:
        pid = int(request.POST.get("producto_id"))
    except (TypeError, ValueError):
        return _json_or_redirect(request, False, "Producto inválido.")

    cantidad = request.POST.get("cantidad")
    motivo = (request.POST.get("motivo") or "").strip()
    nota = (request.POST.get("nota") or "").strip()
    ubicacion_id = request.POST.get("ubicacion")  # opcional

    try:
        cantidad = float(cantidad)
    except (TypeError, ValueError):
        return _json_or_redirect(request, False, "Cantidad inválida.")

    if cantidad == 0:
        return _json_or_redirect(request, False, "La cantidad no puede ser 0.")

    producto = get_object_or_404(Producto, pk=pid)
    stock = _get_or_create_stock(producto, ubicacion_id if ubicacion_id else None)

    # Aplica ajuste sobre cantidad_disponible (permite negativos)
    stock.cantidad_disponible = F("cantidad_disponible") + cantidad
    stock.save(update_fields=["cantidad_disponible"])
    stock.refresh_from_db(fields=["cantidad_disponible"])

    # (Opcional) registrar movimiento en bitácora si tienes un modelo de Movimientos

    # Recalcular total del Producto
    _recalcular_total_producto(producto)

    return _json_or_redirect(
        request,
        True,
        f"Ajuste aplicado: {cantidad:+g} {producto.sku}",
        redirect_to=reverse("products"),
        extra={"stock_disponible": float(stock.cantidad_disponible), "producto_stock": float(producto.stock)}
    )


@login_required
@transaction.atomic
def stock_entrada(request):
    """
    Entrada (recepción) de stock. Si se envía ubicacion (opcional), suma allí.
    POST: producto_id, cantidad (>0), doc_ref, nota, [ubicacion]
    """
    if request.method != "POST":
        return HttpResponseBadRequest("Método no permitido")

    try:
        pid = int(request.POST.get("producto_id"))
    except (TypeError, ValueError):
        return _json_or_redirect(request, False, "Producto inválido.")

    cantidad = request.POST.get("cantidad")
    doc_ref = (request.POST.get("doc_ref") or "").strip()
    nota = (request.POST.get("nota") or "").strip()
    ubicacion_id = request.POST.get("ubicacion")  # opcional

    try:
        cantidad = float(cantidad)
    except (TypeError, ValueError):
        return _json_or_redirect(request, False, "Cantidad inválida.")

    if cantidad <= 0:
        return _json_or_redirect(request, False, "La cantidad debe ser mayor a 0.")

    producto = get_object_or_404(Producto, pk=pid)
    stock = _get_or_create_stock(producto, ubicacion_id if ubicacion_id else None)

    stock.cantidad_disponible = F("cantidad_disponible") + cantidad
    stock.save(update_fields=["cantidad_disponible"])
    stock.refresh_from_db(fields=["cantidad_disponible"])

    _recalcular_total_producto(producto)

    return _json_or_redirect(
        request, True,
        f"Entrada registrada (+{cantidad:g}) para {producto.sku}",
        redirect_to=reverse("products"),
        extra={"stock_disponible": float(stock.cantidad_disponible), "producto_stock": float(producto.stock)}
    )


@login_required
@transaction.atomic
def stock_transferir(request):
    """
    Transfiere stock entre ubicaciones del mismo producto.
    POST: producto_id, origen, destino, cantidad, [nota]
    """
    if request.method != "POST":
        return HttpResponseBadRequest("Método no permitido")

    try:
        pid = int(request.POST.get("producto_id"))
        origen = int(request.POST.get("origen"))
        destino = int(request.POST.get("destino"))
    except (TypeError, ValueError):
        return _json_or_redirect(request, False, "Parámetros de transferencia inválidos.")

    if origen == destino:
        return _json_or_redirect(request, False, "Origen y destino no pueden ser iguales.")

    try:
        cantidad = float(request.POST.get("cantidad"))
    except (TypeError, ValueError):
        return _json_or_redirect(request, False, "Cantidad inválida.")

    if cantidad <= 0:
        return _json_or_redirect(request, False, "La cantidad debe ser mayor a 0.")

    nota = (request.POST.get("nota") or "").strip()

    producto = get_object_or_404(Producto, pk=pid)

    # Valida que existan ubicaciones si tu modelo lo requiere
    # get_object_or_404(Ubicacion, pk=origen)
    # get_object_or_404(Ubicacion, pk=destino)

    stock_origen = _get_or_create_stock(producto, origen)
    stock_destino = _get_or_create_stock(producto, destino)

    # Verifica disponibilidad en origen
    stock_origen.refresh_from_db()
    if stock_origen.cantidad_disponible < cantidad:
        return _json_or_redirect(request, False, "Stock insuficiente en origen.")

    # Aplica movimientos
    stock_origen.cantidad_disponible = F("cantidad_disponible") - cantidad
    stock_origen.save(update_fields=["cantidad_disponible"])
    stock_destino.cantidad_disponible = F("cantidad_disponible") + cantidad
    stock_destino.save(update_fields=["cantidad_disponible"])

    # No cambia el total del producto; aun así lo recalculamos por consistencia
    _recalcular_total_producto(producto)

    return _json_or_redirect(
        request, True,
        f"Transferidos {cantidad:g} de {producto.sku}",
        redirect_to=reverse("products"),
        extra={"producto_stock": float(producto.stock)}
    )


@login_required
@transaction.atomic
def stock_recuento(request):
    """
    Recuento: fija la cantidad real (por ubicación opcional).
    POST: producto_id, cantidad_real, [nota], [ubicacion]
    """
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

    nota = (request.POST.get("nota") or "").strip()
    ubicacion_id = request.POST.get("ubicacion")  # opcional

    producto = get_object_or_404(Producto, pk=pid)
    stock = _get_or_create_stock(producto, ubicacion_id if ubicacion_id else None)

    stock.cantidad_disponible = cantidad_real
    stock.save(update_fields=["cantidad_disponible"])

    _recalcular_total_producto(producto)

    return _json_or_redirect(
        request, True,
        f"Recuento guardado ({cantidad_real:g}) para {producto.sku}",
        redirect_to=reverse("products"),
        extra={"stock_disponible": float(stock.cantidad_disponible), "producto_stock": float(producto.stock)}
    )