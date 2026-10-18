import io
import shutil
import tempfile
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase as _TestCase, override_settings
from django.utils import timezone
from PIL import Image

from .models import Cliente, ItemOS, Loja, Mecanico, Nota, OrdemServico, PagamentoLoja, Registro, Veiculo

MEDIA = tempfile.mkdtemp()

# Nome do dono e acréscimo do cartão ficam fixos aqui: os testes não dependem do .env de quem os roda.
CONFIG_TESTE = dict(NOME_OFICINA='Oficina Teste', NOME_DONO='Dono Teste', ACRESCIMO_CARTAO='1.10',
                    CODIGO_PAIS_TELEFONE='55')


@override_settings(**CONFIG_TESTE)
class TestCase(_TestCase):
    pass


def foto():
    buf = io.BytesIO()
    Image.new('RGB', (20, 20), 'white').save(buf, 'JPEG')
    return SimpleUploadedFile('nota.jpg', buf.getvalue(), content_type='image/jpeg')


@override_settings(MEDIA_ROOT=MEDIA)
class FluxoCompleto(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        self.atendente = User.objects.create_user('atendente', password='x')
        self.client.force_login(self.atendente)

    def abrir_os(self):
        r = self.client.post('/os/nova/', {'placa': 'abc-1d23', 'marca': 'Peugeot', 'modelo': '207',
                                           'cliente_nome': 'Cliente Teste', 'cliente_telefone': '(11) 99999-0000',
                                           'km': '120000'})
        self.assertEqual(r.status_code, 302)
        return OrdemServico.objects.get()

    def test_os_peca_fiado_com_foto_pagamento_e_acerto(self):
        os_ = self.abrir_os()
        self.assertEqual(os_.veiculo.placa, 'ABC1D23')

        r = self.client.post(f'/os/{os_.pk}/peca/', {
            'descricao': 'Bieleta', 'quantidade': '2', 'preco_unitario': '45,00', 'origem': 'fiado',
            'loja': 'Auto Peças X', 'custo_unitario': '29,50', 'foto_nota': foto()})
        self.assertEqual(r.status_code, 302, r.content.decode()[:2000])
        nota = Nota.objects.get()

        # Segunda peça, mesmo papel da loja
        r = self.client.post(f'/os/{os_.pk}/peca/', {
            'descricao': 'Pastilha', 'quantidade': '1', 'preco_unitario': '80', 'origem': 'fiado',
            'loja': 'auto peças x', 'custo_unitario': '52', 'nota': str(nota.pk)})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(nota.itens.count(), 2)

        self.client.post(f'/os/{os_.pk}/peca/', {'descricao': 'Óleo 5w30', 'quantidade': '4', 'preco_unitario': '35',
                                                 'origem': 'cliente'})
        self.client.post(f'/os/{os_.pk}/servico/', {'descricao': 'Revisão', 'preco_unitario': '260',
                                                    'executor': 'dono'})

        self.assertEqual(os_.total(), Decimal('90') + 80 + 140 + 260)
        self.assertEqual(os_.total_cartao(), Decimal('627.00'))
        self.assertContains(self.client.get(f'/os/{os_.pk}/'), 'wa.me/5511999990000')
        self.assertContains(self.client.get(f'/os/{os_.pk}/imprimir/'), 'TOTAL À VISTA')

        self.client.post(f'/os/{os_.pk}/status/', {'acao': 'pagar', 'forma_pagamento': 'pix'})
        os_.refresh_from_db()
        self.assertEqual(os_.status, 'paga')

        # OS paga não aceita mais peça
        r = self.client.post(f'/os/{os_.pk}/peca/', {'descricao': 'X', 'quantidade': '1', 'preco_unitario': '1',
                                                     'origem': 'estoque'})
        self.assertEqual(ItemOS.objects.filter(descricao='X').count(), 0)

        r = self.client.get('/lojas/')
        self.assertContains(r, 'R$ 111,00')  # 2*29,50 + 52

        loja = nota.loja
        ids = list(ItemOS.objects.filter(loja=loja).values_list('pk', flat=True))
        self.client.post(f'/lojas/{loja.pk}/', {'itens': ids[:1]})
        self.assertContains(self.client.get('/lojas/'), 'R$ 52,00')

        # Histórico registrou quem fez
        self.assertTrue(Registro.objects.filter(usuario=self.atendente, acao='alterou', modelo='ordem de serviço').exists())

    def test_funcionario_nao_cancela_os_paga(self):
        os_ = self.abrir_os()
        self.client.post(f'/os/{os_.pk}/servico/', {'descricao': 'Revisão', 'preco_unitario': '100',
                                                    'executor': 'dono'})
        self.client.post(f'/os/{os_.pk}/status/', {'acao': 'pagar', 'forma_pagamento': 'dinheiro'})
        self.client.post(f'/os/{os_.pk}/status/', {'acao': 'cancelar', 'motivo': 'ops'})
        os_.refresh_from_db()
        self.assertEqual(os_.status, 'paga')

    def test_fiado_exige_loja_e_custo(self):
        os_ = self.abrir_os()
        r = self.client.post(f'/os/{os_.pk}/peca/', {'descricao': 'Bieleta', 'quantidade': '1',
                                                     'preco_unitario': '45', 'origem': 'fiado'})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Escreva o nome da loja')

    def test_placa_conhecida_vai_para_historico(self):
        self.abrir_os()
        r = self.client.get('/placa/', {'placa': 'ABC 1D23'})
        self.assertRedirects(r, f'/carro/{Veiculo.objects.get().pk}/')


class QuemFezMaoDeObra(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_user('atendente', password='x'))
        v = Veiculo.objects.create(placa='ABC1D23', modelo='207', cliente=Cliente.objects.create(nome='Ana'))
        self.os = OrdemServico.objects.create(veiculo=v, cliente=v.cliente)
        # Cada mecânico tem a sua partilha: o João deixa 30% (sozinho) ou 50% (junto) para o dono, o Pedro 20% / 40%.
        self.joao = Mecanico.objects.create(nome='João', percentual_dono_sozinho=30, percentual_dono_junto=50)
        self.pedro = Mecanico.objects.create(nome='Pedro', percentual_dono_sozinho=20, percentual_dono_junto=40)

    def lancar(self, descricao, valor, executor):
        return self.client.post(f'/os/{self.os.pk}/servico/', {'descricao': descricao, 'preco_unitario': valor,
                                                                'executor': executor})

    def test_exige_quem_fez(self):
        r = self.lancar('Revisão', '100', '')
        self.assertContains(r, 'Escolha quem fez o serviço')
        self.assertFalse(ItemOS.objects.exists())

    def test_opcoes_sao_o_dono_e_cada_mecanico_ativo(self):
        r = self.client.get(f'/os/{self.os.pk}/servico/')
        self.assertEqual(
            [nome for _, nome in r.context['form'].fields['executor'].choices],
            ['Dono Teste', 'João', 'Dono Teste + João', 'Pedro', 'Dono Teste + Pedro'])
        self.assertContains(r, 'Dono Teste + Pedro')

    def test_escolha_invalida_ou_de_mecanico_inexistente_e_recusada(self):
        for escolha in ('ambos', 'mecanico:999', 'invalido'):
            self.assertContains(self.lancar('Revisão', '100', escolha), 'Faça uma escolha válida')
        self.assertFalse(ItemOS.objects.exists())

    def test_grava_quem_fez_e_o_percentual_aplicado(self):
        self.lancar('Revisão', '100', f'ambos:{self.joao.pk}')
        self.lancar('Motor', '100', f'mecanico:{self.pedro.pk}')
        self.lancar('Suspensão', '100', 'dono')
        juntos, sozinho, dono = ItemOS.objects.order_by('id')
        self.assertEqual((juntos.executor, juntos.mecanico, juntos.percentual_dono), (ItemOS.AMBOS, self.joao, 50))
        self.assertEqual((sozinho.executor, sozinho.mecanico, sozinho.percentual_dono), (ItemOS.MECANICO, self.pedro, 20))
        self.assertEqual((dono.executor, dono.mecanico, dono.percentual_dono), (ItemOS.DONO, None, 100))

    def test_divisao_por_executor(self):
        self.lancar('Revisão', '100', 'dono')
        self.lancar('Suspensão', '200', f'mecanico:{self.joao.pk}')
        self.lancar('Motor', '300', f'ambos:{self.joao.pk}')
        d = self.os.divisao_mao_de_obra()
        self.assertEqual(d['dono'], Decimal('100') + 60 + 150)
        self.assertEqual(d[self.joao], Decimal('140') + 150)
        self.assertEqual(set(d), {'dono', self.joao})

    def test_cada_mecanico_tem_a_sua_partilha(self):
        self.lancar('Suspensão', '200', f'mecanico:{self.joao.pk}')
        self.lancar('Freios', '200', f'mecanico:{self.pedro.pk}')
        self.lancar('Embreagem', '200', f'ambos:{self.pedro.pk}')
        d = self.os.divisao_mao_de_obra()
        self.assertEqual(d['dono'], Decimal('60') + 40 + 80)
        self.assertEqual(d[self.joao], Decimal('140'))
        self.assertEqual(d[self.pedro], Decimal('160') + 120)

    def test_mudar_o_cadastro_nao_muda_o_que_ja_foi_lancado(self):
        self.lancar('Suspensão', '200', f'mecanico:{self.joao.pk}')
        self.joao.percentual_dono_sozinho = 10
        self.joao.save()
        self.lancar('Freios', '200', f'mecanico:{self.joao.pk}')
        antes, depois = ItemOS.objects.order_by('id')
        self.assertEqual(antes.divisao()[self.joao], Decimal('140.00'))
        self.assertEqual(depois.divisao()[self.joao], Decimal('180.00'))

    def test_centavos_nao_somem(self):
        self.lancar('Ajuste', '0,05', f'ambos:{self.joao.pk}')
        d = self.os.divisao_mao_de_obra()
        self.assertEqual(d['dono'] + d[self.joao], Decimal('0.05'))

    def test_peca_nao_entra_na_divisao(self):
        ItemOS.objects.create(os=self.os, tipo=ItemOS.PECA, descricao='Bieleta', preco_unitario=50, origem='estoque')
        self.lancar('Revisão', '100', f'mecanico:{self.joao.pk}')
        self.assertEqual(self.os.divisao_mao_de_obra(), {'dono': Decimal('30.00'), self.joao: Decimal('70.00')})

    def test_mecanico_inativo_sai_das_opcoes_mas_o_historico_fica(self):
        self.lancar('Suspensão', '200', f'mecanico:{self.pedro.pk}')
        self.pedro.ativo = False
        self.pedro.save()
        r = self.client.get(f'/os/{self.os.pk}/servico/')
        self.assertNotContains(r, 'Pedro')
        self.assertContains(self.lancar('Freios', '100', f'mecanico:{self.pedro.pk}'), 'Faça uma escolha válida')
        self.assertContains(self.client.get(f'/os/{self.os.pk}/'), 'Fica com Pedro')

    def test_os_mostra_divisao_mas_cliente_nao_ve(self):
        self.lancar('Revisão', '100', f'mecanico:{self.joao.pk}')
        self.lancar('Freios', '100', f'ambos:{self.pedro.pk}')
        r = self.client.get(f'/os/{self.os.pk}/')
        # João sozinho 100 -> dono 30 / João 70. Pedro junto com o dono 100 -> dono 40 / Pedro 60.
        for linha in ('Fica com Dono Teste</span><span>R$ 70,00', 'Fica com João</span><span>R$ 70,00',
                      'Fica com Pedro</span><span>R$ 60,00'):
            self.assertContains(r, linha)
        impressao = self.client.get(f'/os/{self.os.pk}/imprimir/')
        for nome in ('João', 'Pedro'):
            self.assertNotContains(impressao, nome)

    def test_so_aparece_na_divisao_quem_trabalhou_na_os(self):
        self.lancar('Revisão', '100', 'dono')
        self.assertNotContains(self.client.get(f'/os/{self.os.pk}/'), 'Fica com João')

    def test_servico_sem_executor_aparece_como_nao_informado(self):
        ItemOS.objects.create(os=self.os, tipo=ItemOS.SERVICO, descricao='Antigo', preco_unitario=10)
        self.assertContains(self.client.get(f'/os/{self.os.pk}/'), 'quem fez não informado')

    def test_cadastro_de_mecanico_no_painel(self):
        self.client.force_login(User.objects.create_superuser('chefe', password='x'))
        self.assertContains(self.client.get('/painel/core/mecanico/'), 'João')
        r = self.client.post('/painel/core/mecanico/add/', {'nome': 'Zé', 'percentual_dono_sozinho': '25',
                                                            'percentual_dono_junto': '45', 'ativo': 'on'})
        self.assertEqual(r.status_code, 302)
        ze = Mecanico.objects.get(nome='Zé')
        self.assertEqual((ze.percentual_dono_sozinho, ze.percentual_dono_junto), (25, 45))
        self.assertTrue(Registro.objects.filter(modelo='mecânico', acao='criou', descricao='Zé').exists())
        r = self.client.post('/painel/core/mecanico/add/', {'nome': 'Fora', 'percentual_dono_sozinho': '150',
                                                            'percentual_dono_junto': '45', 'ativo': 'on'})
        self.assertEqual(r.status_code, 200)  # volta com erro: porcentagem acima de 100
        self.assertFalse(Mecanico.objects.filter(nome='Fora').exists())


class TodasAsOS(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_user('atendente', password='x'))
        ana = Cliente.objects.create(nome='Ana Souza', telefone='31988887777')
        beto = Cliente.objects.create(nome='Beto Lima')
        gol = Veiculo.objects.create(placa='ABC1D23', modelo='Gol', cliente=ana)
        uno = Veiculo.objects.create(placa='XYZ9A99', modelo='Uno', cliente=beto)
        self.paga = OrdemServico.objects.create(veiculo=gol, cliente=ana, status=OrdemServico.PAGA,
                                                forma_pagamento='pix', pago_em=timezone.now())
        ItemOS.objects.create(os=self.paga, tipo=ItemOS.SERVICO, descricao='Revisão', preco_unitario=250)
        self.aberta = OrdemServico.objects.create(veiculo=uno, cliente=beto)
        self.cancelada = OrdemServico.objects.create(veiculo=uno, cliente=beto, status=OrdemServico.CANCELADA,
                                                     motivo_cancelamento='desistiu')
        # OS antiga, de 40 dias atrás
        OrdemServico.objects.filter(pk=self.cancelada.pk).update(criado_em=timezone.now() - timedelta(days=40))

    def numeros(self, **params):
        r = self.client.get('/os/', params)
        self.assertEqual(r.status_code, 200)
        return {o.pk for o in r.context['pagina']}

    def test_inicio_tem_link(self):
        self.assertContains(self.client.get('/'), 'href="/os/"')

    def test_lista_todas_com_valor(self):
        self.assertEqual(self.numeros(), {self.paga.pk, self.aberta.pk, self.cancelada.pk})
        self.assertContains(self.client.get('/os/'), 'R$ 250,00')

    def test_busca_por_numero_placa_e_cliente(self):
        self.assertEqual(self.numeros(q=self.paga.numero), {self.paga.pk})
        self.assertEqual(self.numeros(q='abc-1d'), {self.paga.pk})
        self.assertEqual(self.numeros(q='xyz 9a99'), {self.aberta.pk, self.cancelada.pk})
        self.assertEqual(self.numeros(q='souza'), {self.paga.pk})
        self.assertEqual(self.numeros(q='ninguém'), set())

    def test_filtro_por_situacao_e_periodo(self):
        self.assertEqual(self.numeros(status='paga'), {self.paga.pk})
        self.assertEqual(self.numeros(status='cancelada'), {self.cancelada.pk})
        hoje = timezone.localdate()
        self.assertEqual(self.numeros(de=hoje - timedelta(days=7)), {self.paga.pk, self.aberta.pk})
        self.assertEqual(self.numeros(ate=hoje - timedelta(days=30)), {self.cancelada.pk})
        self.assertEqual(self.numeros(q='uno', status='aberta', de=hoje), {self.aberta.pk})

    def test_ordena_por_data(self):
        r = self.client.get('/os/')
        self.assertEqual([o.pk for o in r.context['pagina']][-1], self.cancelada.pk)
        self.assertContains(r, 'href="?ordem=antigas"')
        r = self.client.get('/os/', {'ordem': 'antigas', 'status': 'paga'})
        self.assertContains(r, 'name="ordem" value="antigas"')  # a busca mantém a ordem
        self.assertContains(r, 'href="?status=paga"')  # botão volta para mais novas primeiro
        r = self.client.get('/os/', {'ordem': 'antigas'})
        self.assertEqual([o.pk for o in r.context['pagina']],
                         [self.cancelada.pk, self.paga.pk, self.aberta.pk])

    def test_filtro_invalido_nao_quebra(self):
        self.assertEqual(len(self.numeros(status='xxx', de='ontem')), 3)

    def test_paginacao_mantem_filtros(self):
        for _ in range(35):
            OrdemServico.objects.create(veiculo=self.aberta.veiculo, cliente=self.aberta.cliente)
        r = self.client.get('/os/', {'status': 'aberta'})
        self.assertEqual(len(r.context['pagina']), 30)
        self.assertContains(r, 'status=aberta&amp;pagina=2')
        self.assertEqual(len(self.client.get('/os/', {'status': 'aberta', 'pagina': 2}).context['pagina']), 6)

    def test_os_paga_ainda_imprime_e_manda_whatsapp(self):
        r = self.client.get(f'/os/{self.paga.pk}/')
        self.assertContains(r, 'wa.me/5531988887777')
        self.assertContains(r, f'/os/{self.paga.pk}/imprimir/')
        self.assertContains(self.client.get(f'/os/{self.paga.pk}/imprimir/'), 'Revisão')

    def test_precisa_login(self):
        self.client.logout()
        self.assertEqual(self.client.get('/os/').status_code, 302)


class ContasDasLojas(TestCase):
    def setUp(self):
        self.atendente = User.objects.create_user('atendente', password='x')
        self.client.force_login(self.atendente)
        v = Veiculo.objects.create(placa='ABC1D23', modelo='Gol', cliente=Cliente.objects.create(nome='Ana'))
        self.x, self.y = Loja.objects.create(nome='Loja X'), Loja.objects.create(nome='Loja Y')
        self.paga = self.nova_os(v, OrdemServico.PAGA)
        self.aberta = self.nova_os(v, OrdemServico.ABERTA)
        self.pronta = self.nova_os(v, OrdemServico.FINALIZADA)
        self.cancelada = self.nova_os(v, OrdemServico.CANCELADA)
        self.p1 = self.peca(self.paga, self.x, 2, '30')       # 60 devido
        self.p2 = self.peca(self.paga, self.x, 1, '15.50')    # 15,50 devido
        self.p3 = self.peca(self.aberta, self.x, 1, '100')    # 100 previsto
        self.p4 = self.peca(self.pronta, self.y, 1, '40')     # 40 previsto
        self.peca(self.cancelada, self.y, 1, '999')           # não entra
        self.peca(self.paga, self.y, 1, '888', origem=ItemOS.PAGO_NA_HORA)  # não é fiado

    def nova_os(self, v, status):
        return OrdemServico.objects.create(veiculo=v, cliente=v.cliente, status=status)

    def peca(self, os_, loja, qtd, custo, origem=ItemOS.FIADO):
        return ItemOS.objects.create(os=os_, tipo=ItemOS.PECA, descricao='Peça', quantidade=qtd,
                                     preco_unitario=Decimal(custo) * 2, custo_unitario=Decimal(custo),
                                     origem=origem, loja=loja)

    def test_separa_devido_de_previsto_por_loja_e_geral(self):
        r = self.client.get('/lojas/')
        self.assertEqual((r.context['devido'], r.context['previsto'], r.context['total']),
                         (Decimal('75.50'), Decimal('140'), Decimal('215.50')))
        lojas = {l.nome: (l.devido, l.previsto, l.pecas) for l in r.context['lojas']}
        self.assertEqual(lojas, {'Loja X': (Decimal('75.50'), Decimal('100'), 3),
                                 'Loja Y': (Decimal('0'), Decimal('40'), 1)})
        self.assertEqual([l.nome for l in r.context['lojas']], ['Loja X', 'Loja Y'])  # quem tem devido vem antes

        r = self.client.get(f'/lojas/{self.x.pk}/')
        self.assertEqual(r.context['devidos'], [self.p1, self.p2])
        self.assertEqual(r.context['previstos'], [self.p3])
        self.assertEqual((r.context['devido'], r.context['previsto']), (Decimal('75.50'), Decimal('100')))
        self.assertContains(r, f'value="{self.p1.pk}" data-valor="60.00" checked')
        self.assertContains(r, f'value="{self.p3.pk}" data-valor="100.00">')  # previsto vem desmarcado

    def test_taxa_de_comodidade(self):
        # preço = 2x custo, então a comodidade é igual ao custo: X tem 60 + 15,50 + 100, Y tem 40
        r = self.client.get('/lojas/')
        self.assertEqual(r.context['comodidade'], Decimal('215.50'))
        self.assertEqual({l.nome: l.comodidade for l in r.context['lojas']},
                         {'Loja X': Decimal('175.50'), 'Loja Y': Decimal('40')})
        r = self.client.get(f'/lojas/{self.x.pk}/')
        self.assertEqual(r.context['comodidade'], Decimal('175.50'))
        self.assertContains(r, 'cobrado R$ 120,00')

    def test_link_no_topo_e_botao_desligado_sem_devido(self):
        self.assertContains(self.client.get('/'), 'href="/lojas/"', count=2)
        r = self.client.get(f'/lojas/{self.y.pk}/')  # Y só tem previsto: nada vem marcado
        self.assertContains(r, 'id="botao-baixa" disabled')
        self.assertContains(r, 'Marque as peças pagas')

    def test_baixa_gera_pagamento_com_as_pecas(self):
        r = self.client.post(f'/lojas/{self.x.pk}/', {'itens': [self.p1.pk, self.p3.pk]})
        self.assertRedirects(r, f'/lojas/{self.x.pk}/')
        p = PagamentoLoja.objects.get()
        self.assertEqual((p.loja, p.data, p.valor, p.criado_por), (self.x, timezone.localdate(), Decimal('160'), self.atendente))
        self.assertEqual(set(p.itens.all()), {self.p1, self.p3})
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.pago_loja_em, timezone.localdate())
        self.assertTrue(Registro.objects.filter(modelo='pagamento à loja', usuario=self.atendente).exists())

        r = self.client.get('/lojas/')
        self.assertEqual((r.context['devido'], r.context['previsto']), (Decimal('15.50'), Decimal('40')))

    def test_baixa_nao_pega_peca_de_outra_loja_nem_ja_paga(self):
        self.client.post(f'/lojas/{self.x.pk}/', {'itens': [self.p1.pk]})
        self.client.post(f'/lojas/{self.x.pk}/', {'itens': [self.p1.pk, self.p4.pk, self.p2.pk]})
        segundo = PagamentoLoja.objects.order_by('id').last()
        self.assertEqual(list(segundo.itens.all()), [self.p2])
        self.assertEqual(segundo.valor, Decimal('15.50'))

    def test_baixa_sem_nada_marcado_nao_registra(self):
        r = self.client.post(f'/lojas/{self.x.pk}/', {}, follow=True)
        self.assertContains(r, 'Marque pelo menos uma peça')
        self.assertFalse(PagamentoLoja.objects.exists())

    def test_historico_por_loja(self):
        self.client.post(f'/lojas/{self.x.pk}/', {'itens': [self.p1.pk]})
        self.client.post(f'/lojas/{self.y.pk}/', {'itens': [self.p4.pk]})
        r = self.client.get(f'/lojas/{self.x.pk}/')
        self.assertEqual([p.valor for p in r.context['pagamentos']], [Decimal('60')])
        self.assertContains(r, f'OS {self.paga.numero}')
        self.assertContains(r, 'atendente')
        r = self.client.get('/lojas/')
        self.assertEqual(len(r.context['pagamentos']), 2)
        self.assertContains(r, 'R$ 40,00')

    def test_loja_sem_nada_em_aberto_mostra_historico(self):
        self.client.post(f'/lojas/{self.y.pk}/', {'itens': [self.p4.pk]})
        r = self.client.get(f'/lojas/{self.y.pk}/')
        self.assertContains(r, 'Nenhuma peça em aberto')
        self.assertContains(r, 'R$ 40,00')

    def test_peca_paga_a_loja_nao_sai_da_os(self):
        self.client.post(f'/lojas/{self.x.pk}/', {'itens': [self.p3.pk]})
        self.client.post(f'/os/{self.aberta.pk}/item/{self.p3.pk}/remover/')
        self.assertTrue(ItemOS.objects.filter(pk=self.p3.pk).exists())


class Faturamento(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_user('atendente', password='x'))
        self.v = Veiculo.objects.create(placa='ABC1D23', modelo='Gol', cliente=Cliente.objects.create(nome='Ana'))
        self.joao = Mecanico.objects.create(nome='João', percentual_dono_sozinho=30, percentual_dono_junto=50)
        self.pedro = Mecanico.objects.create(nome='Pedro', percentual_dono_sozinho=20, percentual_dono_junto=40)
        agora = timezone.now()
        # Hoje: pix com peça (cobrado 100, custo 60), mão de obra do João (200 -> 60 dono / 140 João)
        # e do Pedro (100 -> 20 dono / 80 Pedro)
        a = self.os_paga('pix', agora)
        self.item(a, ItemOS.PECA, '100', custo='60')
        self.item(a, ItemOS.SERVICO, '200', executor=ItemOS.MECANICO, mecanico=self.joao, percentual=30)
        self.item(a, ItemOS.SERVICO, '100', executor=ItemOS.MECANICO, mecanico=self.pedro, percentual=20)
        # Hoje: cartão com mão de obra do dono com o João (90,01 -> 45,00 / 45,01) e uma sem executor (10)
        b = self.os_paga('cartao', agora)
        self.item(b, ItemOS.SERVICO, '90.01', executor=ItemOS.AMBOS, mecanico=self.joao, percentual=50)
        self.item(b, ItemOS.SERVICO, '10')
        # Há 40 dias: dinheiro, só mão de obra do dono
        self.antiga = self.os_paga('dinheiro', agora - timedelta(days=40))
        self.item(self.antiga, ItemOS.SERVICO, '500', executor=ItemOS.DONO)
        # Não entram: aberta, pronta e cancelada
        for status in (OrdemServico.ABERTA, OrdemServico.FINALIZADA, OrdemServico.CANCELADA):
            o = OrdemServico.objects.create(veiculo=self.v, cliente=self.v.cliente, status=status)
            self.item(o, ItemOS.SERVICO, '999', executor=ItemOS.DONO)

    def os_paga(self, forma, quando):
        return OrdemServico.objects.create(veiculo=self.v, cliente=self.v.cliente, status=OrdemServico.PAGA,
                                           forma_pagamento=forma, pago_em=quando)

    def item(self, os_, tipo, preco, custo='0', executor='', mecanico=None, percentual=100):
        ItemOS.objects.create(os=os_, tipo=tipo, descricao='x', quantidade=1, preco_unitario=Decimal(preco),
                              custo_unitario=Decimal(custo), executor=executor, mecanico=mecanico,
                              percentual_dono=percentual)

    def test_hoje(self):
        c = self.client.get('/faturamento/?periodo=hoje').context
        self.assertEqual(len(c['ordens']), 2)
        self.assertEqual(c['recebido'], Decimal('500.01'))
        self.assertEqual({f['chave']: f['total'] for f in c['formas']},
                         {'pix': Decimal('400'), 'cartao': Decimal('100.01')})
        self.assertEqual(c['formas'][1]['maquininha'], Decimal('110.01'))
        self.assertEqual((c['pecas'], c['custo_pecas'], c['comodidade']),
                         (Decimal('100'), Decimal('60'), Decimal('40')))
        self.assertEqual(c['servicos'], Decimal('400.01'))
        self.assertEqual(c['mao_de_obra'], [{'nome': 'Dono Teste', 'valor': Decimal('125.00')},
                                            {'nome': 'João', 'valor': Decimal('185.01')},
                                            {'nome': 'Pedro', 'valor': Decimal('80.00')}])
        self.assertEqual(c['sem_executor'], Decimal('10'))
        self.assertEqual(c['resultado_dono'], Decimal('165.00'))
        self.assertEqual(c['pecas'] + c['servicos'], c['recebido'])

    def test_datas_livres_e_ordem_invertida(self):
        hoje = timezone.localdate()
        de, ate = hoje - timedelta(days=45), hoje - timedelta(days=30)
        r = self.client.get(f'/faturamento/?periodo=livre&de={ate:%Y-%m-%d}&ate={de:%Y-%m-%d}')
        self.assertEqual((r.context['de'], r.context['ate']), (de, ate))
        self.assertEqual(r.context['ordens'], [self.antiga])
        self.assertEqual(r.context['resultado_dono'], Decimal('500'))
        self.assertContains(r, f'value="{de:%Y-%m-%d}"')

    def test_sem_nada_no_periodo(self):
        hoje = timezone.localdate() + timedelta(days=1)
        r = self.client.get(f'/faturamento/?periodo=livre&de={hoje:%Y-%m-%d}')
        self.assertEqual((r.context['recebido'], r.context['resultado_dono'], r.context['formas']),
                         (Decimal('0'), Decimal('0'), []))
        self.assertEqual(r.context['mao_de_obra'], [{'nome': 'Dono Teste', 'valor': Decimal('0')}])
        self.assertContains(r, 'R$ 0,00')

    def test_periodos(self):
        from .forms import FaturamentoForm
        hoje = date(2026, 10, 15)  # quinta-feira

        def intervalo(**get):
            return FaturamentoForm(get or None).intervalo(hoje)
        self.assertEqual(intervalo(), (date(2026, 10, 1), hoje, 'mes'))
        self.assertEqual(intervalo(periodo='hoje'), (hoje, hoje, 'hoje'))
        self.assertEqual(intervalo(periodo='semana'), (date(2026, 10, 12), hoje, 'semana'))
        self.assertEqual(intervalo(periodo='livre', de='2026-09-01'), (date(2026, 9, 1), hoje, 'livre'))
        self.assertEqual(intervalo(periodo='livre', ate='2026-09-01'), (date(2026, 9, 1), date(2026, 9, 1), 'livre'))
        self.assertEqual(intervalo(periodo='xpto'), (date(2026, 10, 1), hoje, 'mes'))

    def test_link_na_inicial_e_precisa_login(self):
        self.assertContains(self.client.get('/'), 'href="/faturamento/"', count=2)
        self.client.logout()
        self.assertEqual(self.client.get('/faturamento/').status_code, 302)


@override_settings(MEDIA_ROOT=MEDIA)
class Fotos(TestCase):
    def test_foto_grande_e_reduzida_e_so_logado_ve(self):
        user = User.objects.create_user('atendente', password='x')
        self.client.force_login(user)
        r = self.client.post('/os/nova/', {'placa': 'XYZ9A99', 'modelo': 'Gol', 'cliente_nome': 'Ana'})
        os_ = OrdemServico.objects.get()
        buf = io.BytesIO()
        Image.new('RGB', (4000, 3000), 'white').save(buf, 'JPEG')
        grande = SimpleUploadedFile('IMG_1234.jpg', buf.getvalue(), content_type='image/jpeg')
        self.client.post(f'/os/{os_.pk}/peca/', {'descricao': 'Bieleta', 'quantidade': '1', 'preco_unitario': '45',
                                                 'origem': 'fiado', 'loja': 'Loja Y', 'custo_unitario': '30',
                                                 'foto_nota': grande})
        nota = Nota.objects.get()
        self.assertEqual(max(Image.open(nota.foto.path).size), 2560)

        self.assertEqual(self.client.get(nota.foto.url).status_code, 200)
        self.client.logout()
        self.assertEqual(self.client.get(nota.foto.url).status_code, 302)


@override_settings(MEDIA_ROOT=MEDIA)
class ReaproveitarNota(TestCase):
    """Um papel da loja vale para peças de várias OS: a mesma foto, nunca uma cópia."""

    def setUp(self):
        self.client.force_login(User.objects.create_user('atendente', password='x'))
        self.loja = Loja.objects.create(nome='Auto Peças X')
        cli = Cliente.objects.create(nome='Ana')
        self.os1 = OrdemServico.objects.create(veiculo=Veiculo.objects.create(placa='AAA1A11', cliente=cli), cliente=cli)
        self.os2 = OrdemServico.objects.create(veiculo=Veiculo.objects.create(placa='BBB2B22', cliente=cli), cliente=cli)
        self.hoje = timezone.localdate()

    def nota(self, dias_atras=0, loja=None):
        return Nota.objects.create(loja=loja or self.loja, data=self.hoje - timedelta(days=dias_atras), foto=foto())

    def peca(self, os_, descricao, nota=None):
        return ItemOS.objects.create(os=os_, tipo=ItemOS.PECA, descricao=descricao, quantidade=2, preco_unitario=45,
                                     custo_unitario=30, origem=ItemOS.FIADO, loja=self.loja, nota=nota)

    def visor(self, os_=None):
        r = self.client.get(f'/os/{(os_ or self.os2).pk}/peca/')
        return r, r.context['notas_visor']

    def test_visor_mostra_o_que_ja_foi_lancado_na_nota(self):
        nota = self.nota()
        self.peca(self.os1, 'Bieleta', nota)
        r, notas = self.visor()
        self.assertEqual(len(notas), 1)
        self.assertEqual(notas[0]['loja'], 'Auto Peças X')
        self.assertEqual(notas[0]['itens'], ['2× Bieleta · AAA1A11'])
        self.assertEqual(notas[0]['foto'], nota.foto.url)
        self.assertTrue(notas[0]['hoje'])
        self.assertTrue(notas[0]['quando'].startswith('hoje às '))
        self.assertContains(r, 'Ver notas já fotografadas (1)')
        self.assertContains(r, 'id="visor"')

    def test_sem_notas_nao_tem_visor_mas_a_peca_continua_funcionando(self):
        r, notas = self.visor()
        self.assertEqual(notas, [])
        self.assertNotContains(r, 'id="visor"')
        self.assertNotContains(r, 'id="abrir-notas"')
        self.assertContains(r, 'name="nota"')  # o campo que leva a nota escolhida

    def test_nota_sem_peca_ainda_vem_com_lista_vazia(self):
        self.nota()
        self.assertEqual(self.visor()[1][0]['itens'], [])

    def test_visor_passa_da_mais_recente_para_a_mais_antiga(self):
        antiga = self.nota(dias_atras=3)
        recente = self.nota()
        meio = self.nota(dias_atras=1)
        self.assertEqual([n['id'] for n in self.visor()[1]], [recente.pk, meio.pk, antiga.pk])

    def test_visor_lista_todas_as_pecas_da_nota(self):
        nota = self.nota()
        for n in range(6):
            self.peca(self.os1, f'Peça {n}', nota)
        self.assertEqual(len(self.visor()[1][0]['itens']), 6)

    def test_descricao_com_html_nao_escapa_do_json_da_pagina(self):
        self.peca(self.os1, '</script><b>x', self.nota())
        r, notas = self.visor()
        self.assertEqual(notas[0]['itens'], ['2× </script><b>x · AAA1A11'])
        self.assertNotContains(r, '</script><b>x')

    def test_janela_de_sete_dias(self):
        dentro = self.nota(dias_atras=7)
        antiga = self.nota(dias_atras=8, loja=Loja.objects.create(nome='Loja Velha'))
        self.assertEqual([n['id'] for n in self.visor(self.os1)[1]], [dentro.pk])
        # Nota fora da janela não pode ser enviada na mão.
        r = self.client.post(f'/os/{self.os1.pk}/peca/', {
            'descricao': 'Pastilha', 'quantidade': '1', 'preco_unitario': '80', 'origem': 'fiado',
            'loja': 'Loja Velha', 'custo_unitario': '50', 'nota': str(antiga.pk)})
        self.assertContains(r, 'Essa nota não foi encontrada')

    def test_nota_escolhida_volta_marcada_quando_o_formulario_da_erro(self):
        nota = self.nota()
        r = self.client.post(f'/os/{self.os1.pk}/peca/', {
            'descricao': 'Bieleta', 'quantidade': '1', 'preco_unitario': '45', 'origem': 'fiado',
            'loja': 'Auto Peças X', 'nota': str(nota.pk)})  # falta o custo
        self.assertContains(r, 'Quanto a loja cobrou')
        self.assertContains(r, f'name="nota" id="id_nota" value="{nota.pk}"')

    def test_mesma_nota_em_duas_os_sem_nova_foto(self):
        nota = self.nota()
        for os_ in (self.os1, self.os2):
            r = self.client.post(f'/os/{os_.pk}/peca/', {
                'descricao': 'Bieleta', 'quantidade': '1', 'preco_unitario': '45', 'origem': 'fiado',
                'loja': 'auto peças x', 'custo_unitario': '30', 'nota': str(nota.pk)})
            self.assertEqual(r.status_code, 302)
        self.assertEqual(Nota.objects.count(), 1)
        self.assertEqual(nota.itens.count(), 2)

    def test_nota_de_outra_loja_continua_barrada(self):
        nota = self.nota()
        r = self.client.post(f'/os/{self.os1.pk}/peca/', {
            'descricao': 'Bieleta', 'quantidade': '1', 'preco_unitario': '45', 'origem': 'fiado',
            'loja': 'Outra Loja', 'custo_unitario': '30', 'nota': str(nota.pk)})
        self.assertContains(r, 'A nota escolhida é da loja')
        self.assertEqual(ItemOS.objects.count(), 0)

    def test_peca_do_cliente_ignora_nota_marcada_antes(self):
        # O bloco da nota some quando a peça é do cliente, mas o rádio marcado ainda seria enviado.
        nota = self.nota()
        r = self.client.post(f'/os/{self.os1.pk}/peca/', {
            'descricao': 'Óleo', 'quantidade': '1', 'preco_unitario': '35', 'origem': 'cliente',
            'nota': str(nota.pk), 'foto_nota': foto()})
        self.assertEqual(r.status_code, 302)
        item = ItemOS.objects.get()
        self.assertIsNone(item.nota)
        self.assertEqual(Nota.objects.count(), 1)

    def test_consultas_nao_crescem_com_o_numero_de_notas(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        def consultas():
            with CaptureQueriesContext(connection) as c:
                self.client.get(f'/os/{self.os2.pk}/peca/')
            return len(c)

        self.peca(self.os1, 'Bieleta', self.nota())
        antes = consultas()
        for n in range(4):
            self.peca(self.os1, f'Peça {n}', self.nota())
        self.assertEqual(consultas(), antes)


@override_settings(CONFIAR_IP_CLOUDFLARE=True)
class BloqueioLogin(TestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        User.objects.create_user('atendente', password='senha-certa')
        User.objects.create_user('dono', password='senha-do-dono', is_staff=True)

    def entrar(self, usuario, senha, url='/entrar/', ip='200.1.1.1'):
        return self.client.post(url, {'username': usuario, 'password': senha}, HTTP_CF_CONNECTING_IP=ip)

    def test_bloqueia_usuario_depois_de_5_erros_mesmo_com_senha_certa(self):
        for _ in range(5):
            self.assertContains(self.entrar('atendente', 'errada'), 'Usuário ou senha errados.')
        r = self.entrar('atendente', 'senha-certa')
        self.assertContains(r, 'Muitas tentativas erradas')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_erro_de_funcionario_nao_tranca_o_dono_no_mesmo_ip(self):
        for _ in range(5):
            self.entrar('atendente', 'errada')
        self.assertEqual(self.entrar('dono', 'senha-do-dono').status_code, 302)

    def test_acerto_zera_o_contador(self):
        for _ in range(4):
            self.entrar('atendente', 'errada')
        self.assertEqual(self.entrar('atendente', 'senha-certa').status_code, 302)
        self.client.logout()
        for _ in range(4):
            self.entrar('atendente', 'errada')
        self.assertEqual(self.entrar('atendente', 'senha-certa').status_code, 302)

    def test_ip_bloqueado_depois_de_20_erros_em_usuarios_variados(self):
        for i in range(20):
            self.entrar(f'robo{i}', 'x')
        self.assertContains(self.entrar('dono', 'senha-do-dono'), 'Muitas tentativas erradas')
        self.assertEqual(self.entrar('dono', 'senha-do-dono', ip='200.2.2.2').status_code, 302)

    def test_painel_tambem_bloqueia(self):
        for _ in range(5):
            self.entrar('dono', 'errada', url='/painel/login/')
        r = self.entrar('dono', 'senha-do-dono', url='/painel/login/')
        self.assertContains(r, 'Muitas tentativas erradas')


    @override_settings(CONFIAR_IP_CLOUDFLARE=False)
    def test_cabecalho_do_cloudflare_e_ignorado_se_nao_configurado(self):
        # Sem OFICINA_CLOUDFLARE=1 o cabeçalho pode ser forjado: trocar de IP não pode zerar o bloqueio.
        for i in range(20):
            self.entrar(f'robo{i}', 'x', ip=f'200.9.9.{i}')
        self.assertContains(self.entrar('dono', 'senha-do-dono', ip='200.2.2.2'), 'Muitas tentativas erradas')


class Configuracao(TestCase):
    def test_nome_do_dono_vem_da_configuracao(self):
        from .models import executores
        self.assertEqual(executores(), [('dono', 'Dono Teste'), ('mecanico', 'Mecânico'),
                                        ('ambos', 'Dono Teste + mecânico')])
        with override_settings(NOME_DONO='Marcos'):
            self.assertEqual(executores()[0], ('dono', 'Marcos'))

    def test_semear_demo_cria_e_apaga_so_o_que_e_dele(self):
        Cliente.objects.create(nome='Cliente Real')
        Mecanico.objects.create(nome='Mecânico Real')
        call_command('semear_demo', verbosity=0)
        self.assertEqual(OrdemServico.objects.count(), 8)
        servicos = ItemOS.objects.filter(tipo=ItemOS.SERVICO)
        self.assertEqual(servicos.count(), 9)
        self.assertFalse(servicos.filter(executor=ItemOS.DONO, mecanico__isnull=False).exists())
        self.assertFalse(servicos.exclude(executor=ItemOS.DONO).filter(mecanico__isnull=True).exists())
        self.assertEqual(Mecanico.objects.filter(nome__endswith='(demo)').count(), 2)
        call_command('semear_demo', verbosity=0)  # idempotente
        self.assertEqual(OrdemServico.objects.count(), 8)
        call_command('semear_demo', apagar=True, verbosity=0)
        self.assertEqual(OrdemServico.objects.count(), 0)
        self.assertEqual(list(Cliente.objects.values_list('nome', flat=True)), ['Cliente Real'])
        self.assertEqual(list(Mecanico.objects.values_list('nome', flat=True)), ['Mecânico Real'])

    def test_banco_novo_comeca_vazio(self):
        self.assertFalse(Veiculo.objects.exists())
