"""Registra toda criação, alteração e exclusão nos modelos importantes.

O usuário logado vem de um middleware; assim nenhuma view precisa lembrar de
registrar nada, e alterações feitas pelo admin também ficam gravadas.
"""
from contextvars import ContextVar

from django.db.models.fields.files import FieldFile
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

_usuario_atual = ContextVar('usuario_atual', default=None)


class UsuarioAtualMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = _usuario_atual.set(request.user if request.user.is_authenticated else None)
        try:
            return self.get_response(request)
        finally:
            _usuario_atual.reset(token)


def usuario_atual():
    return _usuario_atual.get()


def _valores(instance):
    dados = {}
    for f in instance._meta.concrete_fields:
        v = getattr(instance, f.attname)
        if isinstance(v, FieldFile):
            v = v.name or None
        dados[f.attname] = None if v is None else str(v)
    return dados


def _modelos_auditados():
    from .models import Cliente, ItemOS, Loja, Nota, OrdemServico, PagamentoLoja, Veiculo
    return (Cliente, Veiculo, Loja, Nota, OrdemServico, ItemOS, PagamentoLoja)


def _registrar(instance, acao, mudancas):
    from .models import Registro
    Registro.objects.create(
        usuario=usuario_atual(),
        acao=acao,
        modelo=instance._meta.verbose_name,
        objeto_id=instance.pk,
        descricao=str(instance)[:200],
        mudancas=mudancas,
    )


@receiver(pre_save)
def _guardar_antes(sender, instance, **kwargs):
    if sender not in _modelos_auditados() or not instance.pk:
        return
    antigo = sender.objects.filter(pk=instance.pk).first()
    instance._valores_antes = _valores(antigo) if antigo else None


@receiver(post_save)
def _registrar_salvo(sender, instance, created, **kwargs):
    if sender not in _modelos_auditados():
        return
    depois = _valores(instance)
    if created:
        _registrar(instance, 'criou', depois)
        return
    antes = getattr(instance, '_valores_antes', None) or {}
    mudancas = {k: [antes.get(k), v] for k, v in depois.items() if antes.get(k) != v}
    if mudancas:
        _registrar(instance, 'alterou', mudancas)


@receiver(post_delete)
def _registrar_apagado(sender, instance, **kwargs):
    if sender in _modelos_auditados():
        _registrar(instance, 'apagou', _valores(instance))
