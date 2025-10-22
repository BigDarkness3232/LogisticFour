import os, sys, re
# Ajusta PYTHONPATH al proyecto
proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if proj_root not in sys.path:
    sys.path.insert(0, proj_root)
# Configura settings y arranca django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'bodega.settings')
import django
django.setup()
from django.test import Client
from django.contrib.auth.models import User

c = Client()
admin = User.objects.filter(is_superuser=True).first()
if not admin:
    print('NO SUPERUSER FOUND')
    sys.exit(1)

c.force_login(admin)
resp = c.get('/bodegas/agregar/', HTTP_HOST='localhost')
print('STATUS', resp.status_code)
content = resp.content.decode('utf-8')
print('HAS SELECT NAME SUCURSAL?', 'name="sucursal"' in content)
m = re.search(r'<select[^>]*name="sucursal".*?</select>', content, re.S)
if m:
    select_html = m.group(0)
    print('SELECT HTML SNIPPET:\n')
    print(select_html)
    # also print option values
    opts = re.findall(r'<option[^>]*value=[\"\']?([^\"\'>]+)[\"\']?[^>]*>(.*?)</option>', select_html, re.S)
    print('\nOPTIONS:')
    for val, text in opts:
        print(f"value={val} -> {re.sub('\s+', ' ', text).strip()}")
else:
    print('NO SELECT MATCH')

# Print a short snippet of the whole page for context
print('\nPAGE SNIPPET START:\n')
print(content[:4000])
print('\nPAGE SNIPPET END')
