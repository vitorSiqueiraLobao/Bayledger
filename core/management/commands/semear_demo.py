"""Dados de demonstração para dar uma olhada nas telas (OS em todas as situações, fiado, divisão da mão de obra).

Tudo é fácil de reconhecer: placas começam com DEM e os clientes têm "(demo)" no nome.
  manage.py semear_demo            cria
  manage.py semear_demo --apagar   remove só o que este comando criou
"""
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core.models import Cliente, ItemOS, Loja, OrdemServico, Veiculo

PREFIXO_PLACA = 'DEM'

CARROS = [
    # placa, marca, modelo, ano, cliente, telefone
    ('DEM1A01', 'Peugeot', '207', '2011', 'Ana (demo)', '(11) 99999-0001'),
    ('DEM2B02', 'Fiat', 'Palio', '2008', 'Marta (demo)', '(11) 99999-0002'),
    ('DEM3C03', 'VW', 'Gol', '2015', 'Seu Zé (demo)', '(11) 99999-0003'),
    ('DEM4D04', 'Chevrolet', 'Onix', '2019', 'Carla (demo)', ''),
    ('DEM5E05', 'Renault', 'Sandero', '2013', 'Marta (demo)', '(11) 99999-0002'),
]

LOJAS = ['Auto Peças Demo', 'Casa do Rolamento Demo']

# Cada OS: (placa, dias atrás, situação, forma de pagamento, km, pedido, itens)
# Peça: ('peca', descrição, qtd, preço, custo, origem, loja (índice em LOJAS ou None), pago à loja?)
# Serviço: ('servico', descrição, preço, executor)
ORDENS = [
    ('DEM1A01', 28, 'paga', 'pix', 120000, 'Revisão completa', [
        ('peca', 'Óleo 5w30', 4, '35.00', '22.00', 'fiado', 0, True),
        ('peca', 'Filtro de óleo', 1, '40.00', '25.00', 'fiado', 0, True),
        ('servico', 'Troca de óleo e filtros', '80.00', 'dono'),
    ]),
    ('DEM2B02', 21, 'paga', 'cartao', 98000, 'Barulho na suspensão', [
        ('peca', 'Bieleta', 2, '45.00', '29.50', 'fiado', 0, False),
        ('peca', 'Bucha da bandeja', 2, '30.00', '18.00', 'fiado', 1, False),
        ('servico', 'Troca de bieletas e buchas', '200.00', 'mecanico'),
    ]),
    ('DEM3C03', 14, 'paga', 'dinheiro', 210000, 'Motor falhando', [
        ('peca', 'Jogo de velas', 1, '120.00', '80.00', 'pago', 1, False),
        ('peca', 'Cabo de vela', 1, '150.00', '0.00', 'cliente', None, False),
        ('servico', 'Troca de velas e cabos', '150.00', 'ambos'),
        ('servico', 'Limpeza de bicos', '180.00', 'mecanico'),
    ]),
    ('DEM4D04', 10, 'cancelada', '', 45000, 'Orçamento de freio', [
        ('peca', 'Pastilha de freio', 1, '160.00', '95.00', 'fiado', 0, False),
        ('servico', 'Troca de pastilhas', '100.00', 'dono'),
    ]),
    ('DEM5E05', 6, 'paga', 'pix', 132000, 'Ar-condicionado não gela', [
        ('peca', 'Gás R134a', 1, '180.00', '110.00', 'internet', 1, False),
        ('servico', 'Carga de gás e teste', '150.00', 'ambos'),
    ]),
    ('DEM1A01', 3, 'finalizada', '', 121500, 'Luz da bateria acesa', [
        ('peca', 'Correia do alternador', 1, '90.00', '55.00', 'fiado', 1, False),
        ('peca', 'Fusível', 2, '5.00', '0.00', 'estoque', None, False),
        ('servico', 'Troca de correia', '120.00', 'mecanico'),
    ]),
    ('DEM2B02', 1, 'aberta', '', 98700, 'Revisão de 100 mil', [
        ('peca', 'Kit correia dentada', 1, '420.00', '290.00', 'fiado', 0, False),
        ('peca', 'Bomba d’água', 1, '260.00', '170.00', 'fiado', 0, False),
        ('servico', 'Troca de correia dentada e bomba', '450.00', 'ambos'),
    ]),
    ('DEM3C03', 0, 'aberta', '', 210400, 'Vazamento de óleo', [
        ('servico', 'Diagnóstico de vazamento', '60.00', 'dono'),
    ]),
]


class Command(BaseCommand):
    help = 'Cria (ou, com --apagar, remove) dados de demonstração.'

    def add_arguments(self, parser):
        parser.add_argument('--apagar', action='store_true', help='remove os dados de demonstração')

    @transaction.atomic
    def handle(self, *args, apagar=False, verbosity=1, **opcoes):
        if apagar:
            self.apagar()
            aviso = 'Dados de demonstração removidos.'
        elif Veiculo.objects.filter(placa__startswith=PREFIXO_PLACA).exists():
            aviso = 'Os dados de demonstração já existem; nada a fazer.'
        else:
            self.criar()
            aviso = self.style.SUCCESS(f'{len(ORDENS)} OS de demonstração criadas.')
        if verbosity:
            self.stdout.write(aviso)

    def criar(self):
        clientes, veiculos = {}, {}
        for placa, marca, modelo, ano, nome, fone in CARROS:
            if nome not in clientes:
                clientes[nome] = Cliente.objects.create(nome=nome, telefone=fone)
            veiculos[placa] = Veiculo.objects.create(placa=placa, marca=marca, modelo=modelo, ano=ano,
                                                     cliente=clientes[nome])
        lojas = [Loja.objects.get_or_create(nome=nome)[0] for nome in LOJAS]

        agora = timezone.now()
        for placa, dias, status, forma, km, pedido, itens in ORDENS:
            quando = agora - timedelta(days=dias, hours=2)
            v = veiculos[placa]
            os_ = OrdemServico.objects.create(
                veiculo=v, cliente=v.cliente, km=km, pedido=pedido, status=status, forma_pagamento=forma,
                pago_em=quando + timedelta(hours=1) if status == OrdemServico.PAGA else None,
                motivo_cancelamento='Cliente achou caro (demo)' if status == OrdemServico.CANCELADA else '',
            )
            OrdemServico.objects.filter(pk=os_.pk).update(criado_em=quando)  # auto_now_add ignora o valor passado
            for item in itens:
                if item[0] == 'peca':
                    _, desc, qtd, preco, custo, origem, loja, pago_loja = item
                    novo = ItemOS.objects.create(
                        os=os_, tipo=ItemOS.PECA, descricao=desc, quantidade=qtd, preco_unitario=Decimal(preco),
                        custo_unitario=Decimal(custo), origem=origem,
                        loja=lojas[loja] if loja is not None else None,
                        pago_loja_em=(quando + timedelta(days=5)).date() if pago_loja else None,
                    )
                else:
                    _, desc, preco, executor = item
                    novo = ItemOS.objects.create(os=os_, tipo=ItemOS.SERVICO, descricao=desc, quantidade=1,
                                                 preco_unitario=Decimal(preco), executor=executor)
                ItemOS.objects.filter(pk=novo.pk).update(criado_em=quando)

    def apagar(self):
        veiculos = Veiculo.objects.filter(placa__startswith=PREFIXO_PLACA)
        ordens = OrdemServico.objects.filter(veiculo__in=veiculos)
        ItemOS.objects.filter(os__in=ordens).delete()
        ordens.delete()
        clientes = list(Cliente.objects.filter(veiculos__in=veiculos).distinct().values_list('pk', flat=True))
        veiculos.delete()
        Cliente.objects.filter(pk__in=clientes, veiculos__isnull=True, ordens__isnull=True).delete()
        Loja.objects.filter(nome__in=LOJAS, itens__isnull=True, notas__isnull=True).delete()
