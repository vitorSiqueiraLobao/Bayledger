"""Identidade visual local da OS, mantida junto aos dados privados da oficina."""
import base64
from pathlib import Path

from django.conf import settings


def imagens_impressao():
    pasta = Path(settings.DIRETORIO_IMPRESSAO)
    imagens = {}
    for nome in ('logo', 'endereco', 'telefone', 'pix'):
        caminho = pasta / f'{nome}.png'
        if caminho.is_file():
            imagens[nome] = 'data:image/png;base64,' + base64.b64encode(caminho.read_bytes()).decode('ascii')
    return imagens
