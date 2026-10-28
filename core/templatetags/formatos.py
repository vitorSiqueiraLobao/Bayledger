from decimal import Decimal

from django import template

register = template.Library()


@register.filter
def brl(valor):
    """1234.5 -> 'R$ 1.234,50'"""
    if valor in (None, ''):
        return ''
    texto = f'{Decimal(valor):,.2f}'.replace(',', '_').replace('.', ',').replace('_', '.')
    return f'R$ {texto}'


@register.filter
def qtd(valor):
    """2.00 -> '2', 1.50 -> '1,5'"""
    texto = f'{Decimal(valor).normalize():f}'
    return texto.replace('.', ',')


@register.filter
def valor_os(valor):
    """Valor monetário sem o prefixo, conforme o formulário impresso."""
    return brl(valor).removeprefix('R$ ')
