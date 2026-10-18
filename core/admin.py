from django.contrib import admin
from django.utils.html import format_html

from .models import Cliente, ItemOS, Loja, Nota, OrdemServico, PagamentoLoja, Registro, Veiculo
from .templatetags.formatos import brl


class SemApagar:
    """OS, itens de notas e histórico nunca somem: no máximo são cancelados."""
    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ['nome', 'telefone', 'criado_em']
    search_fields = ['nome', 'telefone']


@admin.register(Veiculo)
class VeiculoAdmin(admin.ModelAdmin):
    list_display = ['placa', 'marca', 'modelo', 'ano', 'cliente']
    search_fields = ['placa', 'modelo', 'cliente__nome']
    autocomplete_fields = ['cliente']


@admin.register(Loja)
class LojaAdmin(admin.ModelAdmin):
    list_display = ['nome', 'telefone', 'ativa']
    list_filter = ['ativa']
    search_fields = ['nome']


class ItemInline(admin.TabularInline):
    model = ItemOS
    extra = 0
    fields = ['tipo', 'descricao', 'quantidade', 'preco_unitario', 'custo_unitario', 'executor', 'origem', 'loja',
              'nota', 'pago_loja_em', 'pagamento']
    autocomplete_fields = ['loja']
    raw_id_fields = ['nota', 'pagamento']

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(OrdemServico)
class OrdemServicoAdmin(SemApagar, admin.ModelAdmin):
    list_display = ['numero', 'criado_em', 'veiculo', 'cliente', 'status', 'forma_pagamento', 'valor', 'margem']
    list_filter = ['status', 'forma_pagamento', 'criado_em']
    search_fields = ['id', 'veiculo__placa', 'cliente__nome']
    date_hierarchy = 'criado_em'
    inlines = [ItemInline]
    readonly_fields = ['criado_em', 'criado_por']

    @admin.display(description='total')
    def valor(self, obj):
        return brl(obj.total())

    @admin.display(description='lucro')
    def margem(self, obj):
        return brl(obj.total() - obj.custo())


@admin.register(ItemOS)
class ItemOSAdmin(SemApagar, admin.ModelAdmin):
    list_display = ['os', 'tipo', 'descricao', 'quantidade', 'preco_unitario', 'custo_unitario', 'executor',
                    'origem', 'loja', 'nota', 'pago_loja_em', 'pagamento']
    raw_id_fields = ['nota', 'pagamento']
    list_filter = ['tipo', 'executor', 'origem', 'loja', 'pago_loja_em']
    search_fields = ['descricao', 'os__veiculo__placa']


class ItemPagoInline(admin.TabularInline):
    model = ItemOS
    fk_name = 'pagamento'
    extra = 0
    fields = ['os', 'descricao', 'quantidade', 'custo_unitario', 'pago_loja_em']
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PagamentoLoja)
class PagamentoLojaAdmin(SemApagar, admin.ModelAdmin):
    list_display = ['data', 'loja', 'valor_brl', 'qtd_itens', 'criado_por']
    list_filter = ['loja', 'data']
    date_hierarchy = 'data'
    readonly_fields = ['criado_em', 'criado_por']
    inlines = [ItemPagoInline]

    @admin.display(description='valor')
    def valor_brl(self, obj):
        return brl(obj.valor)

    @admin.display(description='peças')
    def qtd_itens(self, obj):
        return obj.itens.count()


@admin.register(Nota)
class NotaAdmin(SemApagar, admin.ModelAdmin):
    list_display = ['data', 'loja', 'miniatura', 'qtd_itens', 'criado_por']
    list_filter = ['loja', 'data']
    readonly_fields = ['foto_grande', 'criado_em', 'criado_por']

    @admin.display(description='foto')
    def miniatura(self, obj):
        return format_html('<img src="{}" style="height:60px">', obj.foto.url) if obj.foto else ''

    @admin.display(description='foto')
    def foto_grande(self, obj):
        return format_html('<img src="{}" style="max-width:600px">', obj.foto.url) if obj.foto else ''

    @admin.display(description='itens')
    def qtd_itens(self, obj):
        return obj.itens.count()


@admin.register(Registro)
class RegistroAdmin(admin.ModelAdmin):
    list_display = ['quando', 'usuario', 'acao', 'modelo', 'descricao']
    list_filter = ['acao', 'modelo', 'usuario']
    search_fields = ['descricao']
    date_hierarchy = 'quando'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
