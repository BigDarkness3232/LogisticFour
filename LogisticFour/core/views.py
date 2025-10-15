from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.urls import reverse


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
