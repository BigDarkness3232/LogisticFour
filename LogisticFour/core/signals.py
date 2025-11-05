# core/signals.py
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver
from django.template.loader import render_to_string
import logging
from .models import Producto, Sucursal,UbicacionSucursal, UbicacionBodega,Bodega
from core.alerts.services import trigger_low_stock_alert

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






@receiver(post_save, sender=Producto)
def verificar_stock(sender, instance, created, **kwargs):
    """
    Esta señal se dispara cada vez que un producto es guardado.
    Verifica si el stock es bajo (≤10).
    """
    if instance.stock <= 10:  # Verifica si el stock del producto es menor o igual a 10
        trigger_low_stock_alert(
            producto=instance,
            stock_actual=instance.stock,
            ubicacion_bodega=None,  # O ajusta según el caso
            ubicacion_sucursal=None  # O ajusta según el caso
        )

