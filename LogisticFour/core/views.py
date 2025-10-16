from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.urls import reverse
from .models import *
from .forms import *


from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.urls import reverse_lazy
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView
from django.db.models import Q
from django.contrib import messages


# Create your views here.
def dashboard(request):
    return render(request, "core/dashboard.html")

@login_required
def products(request):
    return render(request, "core/products.html")

@login_required
def category(request, slug):
    # Para la demo, el slug no afecta; en real lo usarías
    return render(request, "core/category.html", {"category_name": slug.replace("-", " ").title()})

@login_required
def product_add(request):
    return render(request, "core/product_add.html")


def _redirect_url_by_role(perfil):
    if not perfil or not perfil.rol:
        return reverse('dashboard')                # core "/"
    mapping = {
        'ADMIN': reverse('dashboard'),            # core
        'BODEGUERO': reverse('products'),         # core
        'AUDITOR': reverse('auditor_home'),       # accounts
        'PROVEEDOR': reverse('proveedor_home'),   # accounts
    }
    return mapping.get(perfil.rol, reverse('dashboard'))

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
                request.session.set_expiry(0)  # sesión de navegador
            # Si marca, usa el tiempo por defecto (SESSION_COOKIE_AGE)

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

# Homes por rol (placeholders)
@login_required
def auditor_home(request):
    return render(request, 'accounts/auditor_home.html')

@login_required
def proveedor_home(request):
    return render(request, 'accounts/proveedor_home.html')


class ProductoListView(LoginRequiredMixin, ListView):
    model = Producto
    template_name = "inventario/producto_list.html"
    context_object_name = "productos"
    paginate_by = 20

    def get_queryset(self):
        qs = Producto.objects.select_related("marca", "categoria", "unidad_base", "tasa_impuesto").order_by("nombre")
        q = self.request.GET.get("q", "").strip()
        activo = self.request.GET.get("activo", "").strip()

        if q:
            qs = qs.filter(
                Q(nombre__icontains=q) |
                Q(sku__icontains=q) |
                Q(marca__nombre__icontains=q) |
                Q(categoria__nombre__icontains=q)
            )
        if activo in {"1", "0"}:
            qs = qs.filter(activo=(activo == "1"))

        # Orden dinámico opcional ?o=campo o ?o=-campo
        o = self.request.GET.get("o")
        if o:
            qs = qs.order_by(o, "id")
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["q"] = self.request.GET.get("q", "").strip()
        ctx["activo"] = self.request.GET.get("activo", "")
        ctx["o"] = self.request.GET.get("o", "")
        return ctx


class ProductoDetailView(LoginRequiredMixin, DetailView):
    model = Producto
    template_name = "inventario/producto_detail.html"
    context_object_name = "producto"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        p = self.object
        # Relacionados útiles
        ctx["precios"] = p.precios.order_by("-vigente_desde")[:10]
        ctx["imagenes"] = p.imagenes.all()[:12]
        ctx["atributos"] = p.atributos.select_related("atributo").all()
        ctx["stocks"] = p.stocks.select_related("ubicacion", "ubicacion__bodega").all()[:50]
        return ctx


class ProductoCreateView(LoginRequiredMixin, PermissionRequiredMixin, SuccessMessageMixin, CreateView):
    model = Producto
    form_class = ProductoForm
    template_name = "inventario/producto_form.html"
    permission_required = "inventario.add_producto"
    success_message = "Producto creado correctamente."

    def get_success_url(self):
        return reverse_lazy("producto-detail", kwargs={"pk": self.object.pk})


class ProductoUpdateView(LoginRequiredMixin, PermissionRequiredMixin, SuccessMessageMixin, UpdateView):
    model = Producto
    form_class = ProductoForm
    template_name = "inventario/producto_form.html"
    permission_required = "inventario.change_producto"
    success_message = "Producto actualizado correctamente."

    def get_success_url(self):
        return reverse_lazy("producto-detail", kwargs={"pk": self.object.pk})


class ProductoDeleteView(LoginRequiredMixin, PermissionRequiredMixin, DeleteView):
    model = Producto
    template_name = "inventario/producto_confirm_delete.html"
    permission_required = "inventario.delete_producto"
    success_url = reverse_lazy("producto-list")

    def delete(self, request, *args, **kwargs):
        messages.success(request, "Producto eliminado correctamente.")
        return super().delete(request, *args, **kwargs)
