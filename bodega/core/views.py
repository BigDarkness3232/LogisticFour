from django.shortcuts import render

# Create your views here.
def dashboard(request):
    return render(request, "core/dashboard.html")

def products(request):
    return render(request, "core/products.html")

def category(request, slug):
    # Para la demo, el slug no afecta; en real lo usarías
    return render(request, "core/category.html", {"category_name": slug.replace("-", " ").title()})

def product_add(request):
    return render(request, "core/product_add.html")