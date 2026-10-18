import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import F, Sum


class Cliente(models.Model):
    nome = models.CharField(max_length=120)
    telefone = models.CharField(max_length=30, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['nome']

    def __str__(self):
        return self.nome


class Veiculo(models.Model):
    placa = models.CharField(max_length=10, unique=True)
    marca = models.CharField(max_length=60, blank=True)
    modelo = models.CharField(max_length=60, blank=True)
    ano = models.CharField(max_length=10, blank=True)
    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name='veiculos')

    class Meta:
        ordering = ['placa']
        verbose_name = 'veículo'

    def __str__(self):
        return f'{self.placa} – {self.marca} {self.modelo}'.strip(' –')

    @staticmethod
    def normalizar_placa(placa):
        return ''.join(c for c in placa.upper() if c.isalnum())


class Loja(models.Model):
    nome = models.CharField(max_length=120, unique=True)
    telefone = models.CharField(max_length=30, blank=True)
    ativa = models.BooleanField(default=True)

    class Meta:
        ordering = ['nome']

    def __str__(self):
        return self.nome


def caminho_foto_nota(instance, filename):
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'jpg'
    return f'notas/loja{instance.loja_id}/{instance.data:%Y-%m}/{instance.data:%Y%m%d}_{uuid.uuid4().hex[:8]}.{ext}'


class Nota(models.Model):
    """Papel (geralmente escrito à mão) que a loja entrega junto com as peças.

    A foto original é guardada sem compressão: junto com os itens digitados,
    vira o dataset para treinar o OCR no futuro.
    """
    loja = models.ForeignKey(Loja, on_delete=models.PROTECT, related_name='notas')
    data = models.DateField()
    foto = models.ImageField(upload_to=caminho_foto_nota)
    criado_em = models.DateTimeField(auto_now_add=True)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, editable=False)

    class Meta:
        ordering = ['-data', '-criado_em']

    def __str__(self):
        return f'Nota {self.loja} {self.data:%d/%m/%Y}'


class PagamentoLoja(models.Model):
    """Cada vez que alguém acerta com a loja: quanto pagou e quais peças quitou (ItemOS.pagamento)."""
    loja = models.ForeignKey(Loja, on_delete=models.PROTECT, related_name='pagamentos')
    data = models.DateField()
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    criado_em = models.DateTimeField(auto_now_add=True)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, editable=False)

    class Meta:
        ordering = ['-data', '-id']
        verbose_name = 'pagamento à loja'
        verbose_name_plural = 'pagamentos às lojas'

    def __str__(self):
        return f'Pagamento {self.loja} {self.data:%d/%m/%Y}'


class OrdemServico(models.Model):
    ABERTA, FINALIZADA, PAGA, CANCELADA = 'aberta', 'finalizada', 'paga', 'cancelada'
    STATUS = [
        (ABERTA, 'Aberta'),
        (FINALIZADA, 'Pronta (falta pagar)'),
        (PAGA, 'Paga'),
        (CANCELADA, 'Cancelada'),
    ]
    FORMAS_PAGAMENTO = [
        ('dinheiro', 'Dinheiro'),
        ('pix', 'Pix'),
        ('cartao', 'Cartão'),
    ]

    veiculo = models.ForeignKey(Veiculo, on_delete=models.PROTECT, related_name='ordens')
    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name='ordens')
    km = models.PositiveIntegerField(null=True, blank=True)
    pedido = models.TextField('o que o cliente pediu', blank=True)
    status = models.CharField(max_length=12, choices=STATUS, default=ABERTA)
    forma_pagamento = models.CharField(max_length=10, choices=FORMAS_PAGAMENTO, blank=True)
    pago_em = models.DateTimeField(null=True, blank=True)
    motivo_cancelamento = models.TextField(blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, editable=False)

    class Meta:
        ordering = ['-id']
        verbose_name = 'ordem de serviço'
        verbose_name_plural = 'ordens de serviço'

    def __str__(self):
        return f'OS {self.numero} – {self.veiculo.placa}'

    @property
    def numero(self):
        # O id é sequencial e OS nunca é apagada (só cancelada), então não há buracos.
        return f'{self.id:05d}'

    @property
    def editavel(self):
        return self.status == self.ABERTA

    def total(self):
        r = self.itens.aggregate(t=Sum(F('quantidade') * F('preco_unitario')))
        return r['t'] or Decimal('0')

    def total_cartao(self):
        return (self.total() * Decimal(settings.ACRESCIMO_CARTAO)).quantize(Decimal('0.01'))

    def total_pecas(self):
        r = self.itens.filter(tipo=ItemOS.PECA).aggregate(t=Sum(F('quantidade') * F('preco_unitario')))
        return r['t'] or Decimal('0')

    def total_servicos(self):
        return self.total() - self.total_pecas()

    def custo(self):
        r = self.itens.aggregate(t=Sum(F('quantidade') * F('custo_unitario')))
        return r['t'] or Decimal('0')

    def divisao_mao_de_obra(self):
        """Quanto da mão de obra fica com cada um: {'dono': ..., 'mecanico': ...}."""
        soma = {'dono': Decimal('0'), 'mecanico': Decimal('0')}
        for item in self.itens.filter(tipo=ItemOS.SERVICO):
            for quem, valor in item.divisao().items():
                soma[quem] += valor
        return soma


def executores():
    """Opções de "quem fez". Os nomes vêm da configuração (OFICINA_NOME_DONO / OFICINA_NOME_MECANICO)."""
    return [(ItemOS.DONO, settings.NOME_DONO), (ItemOS.MECANICO, settings.NOME_MECANICO), (ItemOS.AMBOS, 'Os dois')]


class ItemOS(models.Model):
    PECA, SERVICO = 'peca', 'servico'
    TIPOS = [(PECA, 'Peça'), (SERVICO, 'Mão de obra')]

    FIADO, PAGO_NA_HORA, INTERNET, CLIENTE, ESTOQUE = 'fiado', 'pago', 'internet', 'cliente', 'estoque'
    ORIGENS = [
        (FIADO, 'Loja – fiado'),
        (PAGO_NA_HORA, 'Loja – pago na hora'),
        (INTERNET, 'Internet / Mercado Livre'),
        (CLIENTE, 'Cliente trouxe'),
        (ESTOQUE, 'Estoque da oficina'),
    ]

    DONO, MECANICO, AMBOS = 'dono', 'mecanico', 'ambos'

    os = models.ForeignKey(OrdemServico, on_delete=models.PROTECT, related_name='itens')
    tipo = models.CharField(max_length=10, choices=TIPOS)
    descricao = models.CharField('descrição', max_length=200)
    quantidade = models.DecimalField(max_digits=8, decimal_places=2, default=1)
    preco_unitario = models.DecimalField('preço (cliente)', max_digits=10, decimal_places=2)
    custo_unitario = models.DecimalField('custo (loja)', max_digits=10, decimal_places=2, default=0)
    origem = models.CharField(max_length=10, choices=ORIGENS, blank=True)
    loja = models.ForeignKey(Loja, on_delete=models.PROTECT, null=True, blank=True, related_name='itens')
    nota = models.ForeignKey(Nota, on_delete=models.PROTECT, null=True, blank=True, related_name='itens')
    pago_loja_em = models.DateField('pago à loja em', null=True, blank=True)
    pagamento = models.ForeignKey(PagamentoLoja, on_delete=models.PROTECT, null=True, blank=True,
                                  related_name='itens')
    executor = models.CharField('quem fez', max_length=10, choices=executores, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['tipo', 'id']
        verbose_name = 'item da OS'
        verbose_name_plural = 'itens da OS'

    def __str__(self):
        return f'{self.quantidade:g}x {self.descricao}'

    def total(self):
        return self.quantidade * self.preco_unitario

    def custo_total(self):
        return self.quantidade * self.custo_unitario

    def comodidade(self):
        """Taxa de comodidade da peça: o que o cliente paga a mais do que custou na loja."""
        return self.total() - self.custo_total()

    def divisao(self):
        """Parte de cada um nesta mão de obra. Peça (ou serviço sem executor) não entra na divisão."""
        fracoes = settings.DIVISAO_MAO_DE_OBRA.get(self.executor)
        if self.tipo != self.SERVICO or not fracoes:
            return {}
        total = self.total().quantize(Decimal('0.01'))
        dono = (total * Decimal(fracoes['dono'])).quantize(Decimal('0.01'))
        return {'dono': dono, 'mecanico': total - dono}  # o mecânico fica com o resto: centavos não somem


class Registro(models.Model):
    """Histórico de alterações. Ninguém edita nem apaga (nem pelo admin)."""
    quando = models.DateTimeField(auto_now_add=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True)
    acao = models.CharField(max_length=10)
    modelo = models.CharField(max_length=40)
    objeto_id = models.PositiveIntegerField()
    descricao = models.CharField(max_length=200)
    mudancas = models.JSONField(default=dict)

    class Meta:
        ordering = ['-quando']
        verbose_name = 'registro de alteração'
        verbose_name_plural = 'histórico de alterações'

    def __str__(self):
        return f'{self.quando:%d/%m/%Y %H:%M} {self.usuario} {self.acao} {self.descricao}'
