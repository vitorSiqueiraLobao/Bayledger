from io import BytesIO

from django.conf import settings
from django.core.files.base import ContentFile
from PIL import Image, ImageOps


def reduzir_foto(arquivo):
    """Gira conforme o EXIF, limita o lado maior e regrava como JPEG.

    Tira também os metadados do celular (GPS etc.); o horário que vale é o do servidor.
    """
    img = Image.open(arquivo)
    img = ImageOps.exif_transpose(img).convert('RGB')
    lado = settings.FOTO_NOTA_LADO_MAX
    img.thumbnail((lado, lado), Image.LANCZOS)
    buf = BytesIO()
    img.save(buf, 'JPEG', quality=settings.FOTO_NOTA_QUALIDADE, optimize=True)
    return ContentFile(buf.getvalue(), name='nota.jpg')
