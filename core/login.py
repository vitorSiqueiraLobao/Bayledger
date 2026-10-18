"""Bloqueio de login depois de muitas senhas erradas, no app e no painel do dono."""
import hashlib

from django.conf import settings
from django.contrib.admin.forms import AdminAuthenticationForm
from django.contrib.auth.forms import AuthenticationForm
from django.core.cache import cache
from django.core.exceptions import ValidationError

BLOQUEIO_SEGUNDOS = 15 * 60
LIMITE_USUARIO = 5
# O IP tem limite maior: na oficina todo mundo sai pelo mesmo IP, e um funcionário errando a senha
# não pode trancar o dono junto.
LIMITE_IP = 20


def ip_real(request):
    # Atrás do Cloudflare Tunnel o REMOTE_ADDR é sempre 127.0.0.1 e o IP de verdade vem neste
    # cabeçalho. Só dá para confiar nele quando o app está mesmo atrás do Cloudflare e o gunicorn só
    # escuta em 127.0.0.1 (OFICINA_CLOUDFLARE=1); fora disso o cliente poderia forjar o cabeçalho.
    if settings.CONFIAR_IP_CLOUDFLARE and request.META.get('HTTP_CF_CONNECTING_IP'):
        return request.META['HTTP_CF_CONNECTING_IP']
    return request.META.get('REMOTE_ADDR', '')


def _contadores(request, username):
    usuario = hashlib.sha256(username.strip().lower().encode()).hexdigest()[:20]
    return [(f'login-falhas-usuario-{usuario}', LIMITE_USUARIO),
            (f'login-falhas-ip-{ip_real(request)}', LIMITE_IP)]


class BloqueioMixin:
    def clean(self):
        contadores = _contadores(self.request, self.data.get('username', ''))
        if any(cache.get(chave, 0) >= limite for chave, limite in contadores):
            raise ValidationError('Muitas tentativas erradas. Espere 15 minutos e tente de novo.',
                                  code='bloqueado')
        try:
            dados = super().clean()
        except ValidationError:
            for chave, _ in contadores:
                # get + set, e não incr: no cache em arquivo o incr volta para o timeout padrão.
                cache.set(chave, cache.get(chave, 0) + 1, BLOQUEIO_SEGUNDOS)
            raise
        cache.delete(contadores[0][0])
        return dados


class LoginForm(BloqueioMixin, AuthenticationForm):
    error_messages = {**AuthenticationForm.error_messages, 'invalid_login': 'Usuário ou senha errados.'}


class PainelLoginForm(BloqueioMixin, AdminAuthenticationForm):
    pass
