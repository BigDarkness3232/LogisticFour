import os, sys
proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if proj_root not in sys.path:
    sys.path.insert(0, proj_root)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'bodega.settings')
import django
django.setup()
from django.test import Client
from django.contrib.auth.models import User

c = Client()
u = User.objects.filter(is_superuser=True).first()
if not u:
    print('NO SUPERUSER')
    sys.exit(1)

c.force_login(u)
r = c.get('/categorias/', HTTP_HOST='localhost')
print('sidebar link present?', '/categorias/' in r.content.decode('utf-8'))
r2 = c.get('/categorias/Deportes/', HTTP_HOST='localhost')
print('page length', len(r2.content))
print('sample snippet:')
print(r2.content.decode('utf-8')[:800])
