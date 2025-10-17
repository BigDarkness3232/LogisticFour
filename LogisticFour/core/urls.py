from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    # App principal
    path("", views.dashboard, name="dashboard"),
    path("products/", views.products, name="products"),
    path("category/<slug:slug>/", views.category, name="category"),
    path("products/add/", views.product_add, name="product_add"),

    # Auth propias
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),

    # Redirección por rol (opcionales pero útiles)
    path('home/', views.dashboard_view, name='accounts_home'),
    path('home/auditor/', views.auditor_home, name='auditor_home'),
    path('home/proveedor/', views.proveedor_home, name='proveedor_home'),

    # Signup (si lo usas)
    path("signup/", views.signup, name="accounts-signup"),

    # Reset de contraseña (built-in views + tus plantillas)
    path('password-reset/',
         auth_views.PasswordResetView.as_view(template_name='accounts/password_reset.html'),
         name='password_reset'),
    path('password-reset/done/',
         auth_views.PasswordResetDoneView.as_view(template_name='accounts/password_reset_done.html'),
         name='password_reset_done'),
    path('reset/<uidb64>/<token>/',
         auth_views.PasswordResetConfirmView.as_view(template_name='accounts/password_reset_confirm.html'),
         name='password_reset_confirm'),
    path('reset/done/',
         auth_views.PasswordResetCompleteView.as_view(template_name='accounts/password_reset_complete.html'),
         name='password_reset_complete'),

    # Usuarios (solo ADMIN)
    path("users/", views.user_list, name="usuario-list"),
    path("users/create/", views.user_create, name="usuario-create"),

    #codigo QR producto
    path("productos/", views.ProductsListView.as_view(), name="products"),
    path("productos/agregar/", views.ProductCreateView.as_view(), name="product_add"),
    path("productos/<int:pk>/editar/",views.ProductUpdateView.as_view(), name="producto-update"),
    path("productos/<int:pk>/eliminar/", views.ProductDeleteView.as_view(), name="producto-delete"),
    path("productos/<int:pk>/", views.ProductDetailView.as_view(), name="producto-detail"),
    path("productos/<int:pk>/qr.png", views.qr_producto_png, name="producto-qr-png"),
]
