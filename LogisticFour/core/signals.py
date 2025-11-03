# core/signals.py
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver
from django.template.loader import render_to_string
import logging
from .models import Producto, Sucursal,UbicacionSucursal, UbicacionBodega,Bodega

logger = logging.getLogger(__name__)

# =====================================================
# 🛠️ Utilidades comunes
# =====================================================

def _send_html_email(subject, to, template_txt, template_html, ctx):
    """Envía email con versión texto + HTML."""
    if not to:
        logger.info("No se envía correo (lista 'to' vacía) para asunto: %s", subject)
        return

    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", None)
    text_body = render_to_string(template_txt, ctx)
    html_body = render_to_string(template_html, ctx)

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=from_email,
        to=to,
    )
    msg.attach_alternative(html_body, "text/html")
    logger.info("📩 Enviando correo a %s | Asunto: %s", to, subject)
    msg.send(fail_silently=False)

# =====================================================
# 📦 Producto: snapshot pre-save (stock previo)
# =====================================================

@receiver(pre_save, sender=Producto)
def producto_snapshot_before_save(sender, instance: Producto, **kwargs):
    """Guarda el stock anterior para comparar luego."""
    if instance.pk:
        try:
            prev = sender.objects.get(pk=instance.pk)
            instance._old_stock = prev.stock
        except sender.DoesNotExist:
            instance._old_stock = None
    else:
        instance._old_stock = None

# =====================================================
# 📦 Producto: post-save (notificación por cambios de stock)
# =====================================================

@receiver(post_save, sender=Producto)
def producto_stock_notificaciones(sender, instance: Producto, created: bool, **kwargs):
    """Envía notificación si se agrega stock o si el stock está bajo."""
    admin_list = list(getattr(settings, "TICKETS_NOTIFY_EMAILS", []))
    if not admin_list:
        return

    ctx = {"p": instance}
    stock_actual = instance.stock
    stock_anterior = getattr(instance, "_old_stock", None)
    UMBRAL_BAJO = 5  # <-- puedes ajustar este valor o hacerlo configurable

    # 1️⃣ Producto creado con stock inicial
    if created and stock_actual > 0:
        subject = f"[Stock] Nuevo producto con stock inicial: {instance.nombre}"
        _send_html_email(
            subject,
            admin_list,
            "emails/stock_nuevo.txt",
            "emails/stock_nuevo.html",
            ctx,
        )
        return

    # 2️⃣ Stock agregado (aumenta)
    if stock_anterior is not None and stock_actual > stock_anterior:
        diff = stock_actual - stock_anterior
        ctx["cantidad_agregada"] = diff
        subject = f"[Stock] Se agregó stock a {instance.nombre} (+{diff} unidades)"
        _send_html_email(
            subject,
            admin_list,
            "emails/stock_agregado.txt",
            "emails/stock_agregado.html",
            ctx,
        )

    # 3️⃣ Bajo stock
    if stock_actual <= UMBRAL_BAJO:
        subject = f"[Alerta] Bajo stock: {instance.nombre} ({stock_actual} unidades)"
        _send_html_email(
            subject,
            admin_list,
            "emails/stock_bajo.txt",
            "emails/stock_bajo.html",
            ctx,
        )






@receiver(post_save, sender=Sucursal)
def crear_ubicacion_sucursal_default(sender, instance: Sucursal, created, **kwargs):
    if created and not instance.ubicaciones.exists():
        UbicacionSucursal.objects.create(
            sucursal=instance,
            nombre="GENERAL",
            codigo=f"SUC-{instance.id}-GEN",
        )


@receiver(post_save, sender=Bodega)
def crear_ubicacion_bodega_default(sender, instance: Bodega, created, **kwargs):
    if created and not instance.ubicaciones.exists():
        UbicacionBodega.objects.create(
            bodega=instance,
            nombre="GENERAL",
            codigo=f"BOD-{instance.id}-GEN",
        )