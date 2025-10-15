from django.shortcuts import render
from django.contrib.auth.decorators import login_required

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