# apps/inventario/forms.py
from django import forms
from django.forms import inlineformset_factory, BaseInlineFormSet
from django.contrib.auth.models import User
from .models import *

# =========================================================
# Helpers
# =========================================================

