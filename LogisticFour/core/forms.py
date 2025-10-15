from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from core.models import UsuarioPerfil

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
