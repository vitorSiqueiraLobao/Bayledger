import csv
import re
from datetime import timedelta
from decimal import Decimal
from urllib.parse import quote

from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.core.paginator import Paginator
from django.db.models import Count, F, Max, Prefetch, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.static import serve

from .forms import (BuscaOSForm, CancelarForm, FaturamentoForm, NovaOSCarroConhecidoForm, NovaOSCarroNovoForm,
                    PagarForm, PecaForm, PlacaForm, ServicoForm)
from .imagens import reduzir_foto
from .models import Cliente, ItemOS, Loja, Nota, OrdemServico, PagamentoLoja, Veiculo
from .templatetags.formatos import brl, qtd

NOTAS_DIAS = 7  # até quantos dias atrás uma nota já fotografada pode ser reaproveitada em outra peça


@login_required
def foto_protegida(request, path):
    """Fotos das notas só para quem está logado: /media/ nunca fica aberto no túnel.

    Para o volume de uma oficina, servir pelo Django é suficiente.
    """
    resp = serve(request, path, document_root=settings.MEDIA_ROOT)
    resp['Cache-Control'] = 'private, max-age=86400'
    return resp


@login_required
def inicio(request):
    abertas = (OrdemServico.objects.filter(status__in=[OrdemServico.ABERTA, OrdemServico.FINALIZADA])
               .select_related('veiculo', 'cliente'))
    return render(request, 'core/inicio.html', {'abertas': abertas, 'form': PlacaForm()})


@login_required
def todas_os(request):
    """Histórico de todas as OS, para achar uma antiga e reimprimir ou mandar de novo."""
    form = BuscaOSForm(request.GET or None)
    antigas_primeiro = request.GET.get('ordem') == 'antigas'
    ordens = (OrdemServico.objects.select_related('veiculo', 'cliente')
              .annotate(valor=Sum(F('itens__quantidade') * F('itens__preco_unitario')))
              .order_by(*(['criado_em', 'id'] if antigas_primeiro else ['-criado_em', '-id'])))
    if form.is_valid():
        d = form.cleaned_data
        q = d['q'].strip()
        if q:
            filtro = Q(cliente__nome__icontains=q) | Q(veiculo__modelo__icontains=q)
            placa = Veiculo.normalizar_placa(q)
            if placa:
                filtro |= Q(veiculo__placa__contains=placa)
            if q.lstrip('#').isdigit():
                filtro |= Q(pk=int(q.lstrip('#')))
            ordens = ordens.filter(filtro)
        if d['status']:
            ordens = ordens.filter(status=d['status'])
        if d['de']:
            ordens = ordens.filter(criado_em__date__gte=d['de'])
        if d['ate']:
            ordens = ordens.filter(criado_em__date__lte=d['ate'])

    pagina = Paginator(ordens, 30).get_page(request.GET.get('pagina'))
    filtros = request.GET.copy()
    filtros.pop('pagina', None)
    inverter = filtros.copy()
    inverter.pop('ordem', None)
    if not antigas_primeiro:
        inverter['ordem'] = 'antigas'
    tem_filtro = any(request.GET.get(k) for k in BuscaOSForm.base_fields)
    return render(request, 'core/todas_os.html', {'form': form, 'pagina': pagina, 'tem_filtro': tem_filtro,
                                                  'filtros': filtros.urlencode(), 'inverter': inverter.urlencode(),
                                                  'antigas_primeiro': antigas_primeiro})


@login_required
def buscar_placa(request):
    form = PlacaForm(request.GET or None)
    if not form.is_valid():
        return render(request, 'core/placa.html', {'form': form})
    placa = Veiculo.normalizar_placa(form.cleaned_data['placa'])
    veiculo = Veiculo.objects.filter(placa=placa).first()
    if veiculo:
        return redirect('veiculo', veiculo.pk)
    return redirect(f"{reverse('nova_os')}?placa={placa}")


@login_required
def veiculo(request, pk):
    v = get_object_or_404(Veiculo.objects.select_related('cliente'), pk=pk)
    ordens = v.ordens.prefetch_related('itens').order_by('-criado_em')
    return render(request, 'core/veiculo.html', {'veiculo': v, 'ordens': ordens})


@login_required
def nova_os(request, veiculo_pk=None):
    v = get_object_or_404(Veiculo.objects.select_related('cliente'), pk=veiculo_pk) if veiculo_pk else None
    FormCls = NovaOSCarroConhecidoForm if v else NovaOSCarroNovoForm
    initial = {} if v else {'placa': request.GET.get('placa', '')}
    form = FormCls(request.POST or None, initial=initial)

    if request.method == 'POST' and form.is_valid():
        d = form.cleaned_data
        with transaction.atomic():
            if v is None:
                placa = Veiculo.normalizar_placa(d['placa'])
                v = Veiculo.objects.filter(placa=placa).first()
                if v is None:
                    tel = d['cliente_telefone'].strip()
                    cliente = Cliente.objects.filter(telefone=tel).first() if tel else None
                    cliente = cliente or Cliente.objects.create(nome=d['cliente_nome'].strip(), telefone=tel)
                    v = Veiculo.objects.create(placa=placa, marca=d['marca'].strip(), modelo=d['modelo'].strip(),
                                               ano=d['ano'].strip(), cliente=cliente)
            os_ = OrdemServico.objects.create(veiculo=v, cliente=v.cliente, km=d['km'], pedido=d['pedido'],
                                              criado_por=request.user)
        return redirect('os', os_.pk)

    return render(request, 'core/nova_os.html', {'form': form, 'veiculo': v})


@login_required
def os_detalhe(request, pk):
    os_ = get_object_or_404(OrdemServico.objects.select_related('veiculo', 'cliente'), pk=pk)
    itens = os_.itens.select_related('loja', 'nota', 'mecanico')
    servicos = [i for i in itens if i.tipo == ItemOS.SERVICO]
    return render(request, 'core/os.html', {
        'os': os_,
        'pecas': [i for i in itens if i.tipo == ItemOS.PECA],
        'servicos': servicos,
        'divisao': _linhas_divisao(os_.divisao_mao_de_obra()) if servicos else None,
        'whatsapp': _link_whatsapp(os_),
        'pagar_form': PagarForm(),
        'cancelar_form': CancelarForm(),
    })


def _linhas_divisao(partes):
    """{'dono': x, <Mecanico>: y} -> [{'nome', 'valor'}], o dono primeiro e os mecânicos em ordem alfabética."""
    linhas = [{'nome': settings.NOME_DONO, 'valor': partes.get('dono', Decimal('0'))}]
    for quem in sorted((k for k in partes if k != 'dono'), key=lambda m: m.nome.lower()):
        linhas.append({'nome': quem.nome, 'valor': partes[quem]})
    return linhas


def _link_whatsapp(os_):
    linhas = [f'*{settings.NOME_OFICINA}* – OS {os_.numero}',
              f'{os_.veiculo.modelo} {os_.veiculo.placa}'.strip(), '']
    for i in os_.itens.all():
        linhas.append(f'{qtd(i.quantidade)}x {i.descricao} – {brl(i.total())}')
    linhas += ['', f'*Total à vista: {brl(os_.total())}*', f'No cartão: {brl(os_.total_cartao())}']
    texto = quote('\n'.join(linhas))
    fone = re.sub(r'\D', '', os_.cliente.telefone)
    if fone and not fone.startswith(settings.CODIGO_PAIS_TELEFONE):
        fone = settings.CODIGO_PAIS_TELEFONE + fone
    return f'https://wa.me/{fone}?text={texto}' if fone else f'https://wa.me/?text={texto}'


def _os_editavel_ou_volta(request, os_):
    if not os_.editavel:
        messages.error(request, 'Essa OS já foi fechada e não pode mais ser alterada.')
        return redirect('os', os_.pk)
    return None


def _sugestoes(tipo):
    """Últimos valores usados para cada descrição, para o formulário preencher sozinho."""
    ultimos = (ItemOS.objects.filter(tipo=tipo).values('descricao')
               .annotate(ultimo=Max('id'), vezes=Count('id')).order_by('-vezes')[:300])
    itens = ItemOS.objects.select_related('loja').in_bulk([u['ultimo'] for u in ultimos])
    return {
        i.descricao: {'preco': f'{i.preco_unitario:.2f}'.replace('.', ','),
                      'custo': f'{i.custo_unitario:.2f}'.replace('.', ','),
                      'loja': i.loja.nome if i.loja else '', 'origem': i.origem}
        for i in itens.values()
    }


@login_required
def adicionar_servico(request, pk):
    os_ = get_object_or_404(OrdemServico, pk=pk)
    if (r := _os_editavel_ou_volta(request, os_)):
        return r
    form = ServicoForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        ItemOS.objects.create(os=os_, tipo=ItemOS.SERVICO, quantidade=1, **form.cleaned_data)
        return redirect('os', os_.pk)
    sugestoes = _sugestoes(ItemOS.SERVICO)
    return render(request, 'core/servico_form.html', {'os': os_, 'form': form, 'sugestoes': sugestoes})


def _nota_para_visor(nota, hoje):
    """Dados que o visor de notas (JavaScript, na tela da peça) mostra para cada nota."""
    dia = 'hoje' if nota.data == hoje else f'{nota.data:%d/%m}'
    return {
        'id': nota.pk,
        'loja': nota.loja.nome,
        'foto': nota.foto.url,
        'hoje': nota.data == hoje,
        'quando': f'{dia} às {timezone.localtime(nota.criado_em):%H:%M}',
        'itens': [f'{qtd(i.quantidade)}× {i.descricao} · {i.os.veiculo.placa}' for i in nota.itens.all()],
    }


@login_required
def adicionar_peca(request, pk):
    os_ = get_object_or_404(OrdemServico, pk=pk)
    if (r := _os_editavel_ou_volta(request, os_)):
        return r
    hoje = timezone.localdate()
    # Da mais recente para a mais antiga (ordem do model), cada uma com as peças já lançadas nela:
    # é o que a pessoa lembra para reconhecer o papel.
    notas_recentes = list(
        Nota.objects.filter(data__gte=hoje - timedelta(days=NOTAS_DIAS)).select_related('loja')
        .prefetch_related(Prefetch('itens', queryset=ItemOS.objects.select_related('os__veiculo')))
    )
    form = PecaForm(request.POST or None, request.FILES or None, notas_recentes=notas_recentes)

    if request.method == 'POST' and form.is_valid():
        d = form.cleaned_data
        with transaction.atomic():
            loja = None
            if d['loja_nome']:
                loja = Loja.objects.filter(nome__iexact=d['loja_nome']).first() or \
                    Loja.objects.create(nome=d['loja_nome'])
            nota = d['nota_obj']
            if d.get('foto_nota'):
                nota = Nota.objects.create(loja=loja, data=hoje, foto=reduzir_foto(d['foto_nota']),
                                           criado_por=request.user)
            ItemOS.objects.create(
                os=os_, tipo=ItemOS.PECA, descricao=d['descricao'].strip(), quantidade=d['quantidade'],
                preco_unitario=d['preco_unitario'], custo_unitario=d['custo_unitario'],
                origem=d['origem'], loja=loja, nota=nota,
            )
        messages.success(request, f'{d["descricao"]} lançada.')
        return redirect('os', os_.pk)

    sugestoes = _sugestoes(ItemOS.PECA)
    return render(request, 'core/peca_form.html', {
        'os': os_, 'form': form, 'notas_visor': [_nota_para_visor(n, hoje) for n in notas_recentes],
        'lojas': Loja.objects.filter(ativa=True), 'sugestoes': sugestoes,
        'nota_escolhida': request.POST.get('nota', ''),
    })


@login_required
@require_POST
def remover_item(request, pk, item_pk):
    os_ = get_object_or_404(OrdemServico, pk=pk)
    if (r := _os_editavel_ou_volta(request, os_)):
        return r
    item = get_object_or_404(ItemOS, pk=item_pk, os=os_)
    if item.pagamento_id:
        messages.error(request, f'{item.descricao} já foi paga à loja e não pode sair da OS.')
        return redirect('os', os_.pk)
    item.delete()
    messages.success(request, f'{item.descricao} removido.')
    return redirect('os', os_.pk)


@login_required
@require_POST
def mudar_status(request, pk):
    os_ = get_object_or_404(OrdemServico, pk=pk)
    acao = request.POST.get('acao')

    if acao == 'finalizar' and os_.status == OrdemServico.ABERTA:
        if not os_.itens.exists():
            messages.error(request, 'Lance pelo menos uma peça ou serviço antes de finalizar.')
        else:
            os_.status = OrdemServico.FINALIZADA
            os_.save()
    elif acao == 'pagar' and os_.status in (OrdemServico.ABERTA, OrdemServico.FINALIZADA):
        form = PagarForm(request.POST)
        if form.is_valid():
            os_.status = OrdemServico.PAGA
            os_.forma_pagamento = form.cleaned_data['forma_pagamento']
            os_.pago_em = timezone.now()
            os_.save()
            messages.success(request, f'OS {os_.numero} paga.')
        else:
            messages.error(request, 'Escolha como o cliente pagou.')
    elif acao == 'reabrir' and os_.status == OrdemServico.FINALIZADA:
        os_.status = OrdemServico.ABERTA
        os_.save()
    elif acao == 'reabrir' and os_.status in (OrdemServico.PAGA, OrdemServico.CANCELADA):
        if not request.user.is_staff:
            messages.error(request, 'Só o dono pode reabrir uma OS paga ou cancelada.')
        else:
            os_.status, os_.forma_pagamento, os_.pago_em = OrdemServico.ABERTA, '', None
            os_.save()
    elif acao == 'cancelar' and os_.status != OrdemServico.CANCELADA:
        form = CancelarForm(request.POST)
        if os_.status == OrdemServico.PAGA and not request.user.is_staff:
            messages.error(request, 'Só o dono pode cancelar uma OS que já foi paga.')
        elif form.is_valid():
            os_.status = OrdemServico.CANCELADA
            os_.motivo_cancelamento = form.cleaned_data['motivo']
            os_.save()
        else:
            messages.error(request, 'Escreva o motivo do cancelamento.')
    return redirect('os', os_.pk)


@login_required
def imprimir_os(request, pk):
    os_ = get_object_or_404(OrdemServico.objects.select_related('veiculo', 'cliente'), pk=pk)
    return render(request, 'core/os_impressao.html', {'os': os_, 'itens': os_.itens.all(),
                                                      'oficina': settings.NOME_OFICINA})


def _fiado_em_aberto():
    return ItemOS.objects.filter(origem=ItemOS.FIADO, pago_loja_em__isnull=True) \
        .exclude(os__status=OrdemServico.CANCELADA)


@login_required
def contas_lojas(request):
    """Devido agora: peças de OS que o cliente já pagou. Previsto: de OS ainda aberta ou pronta."""
    custo = F('itens__quantidade') * F('itens__custo_unitario')
    cobrado = F('itens__quantidade') * F('itens__preco_unitario')
    em_aberto = Q(itens__in=_fiado_em_aberto())
    lojas = (Loja.objects
             .annotate(devido=Sum(custo, filter=em_aberto & Q(itens__os__status=OrdemServico.PAGA), default=0),
                       previsto=Sum(custo, filter=em_aberto & ~Q(itens__os__status=OrdemServico.PAGA), default=0),
                       comodidade=Sum(cobrado - custo, filter=em_aberto, default=0),
                       pecas=Count('itens', filter=em_aberto))
             .filter(pecas__gt=0)
             .order_by('-devido', '-previsto', 'nome'))
    pagamentos = PagamentoLoja.objects.select_related('loja', 'criado_por').annotate(pecas=Count('itens'))[:10]
    devido = sum((l.devido for l in lojas), Decimal('0'))
    previsto = sum((l.previsto for l in lojas), Decimal('0'))
    comodidade = sum((l.comodidade for l in lojas), Decimal('0'))
    return render(request, 'core/contas.html', {'lojas': lojas, 'devido': devido, 'previsto': previsto,
                                                'total': devido + previsto, 'comodidade': comodidade,
                                                'pagamentos': pagamentos})


@login_required
def conta_loja(request, pk):
    loja = get_object_or_404(Loja, pk=pk)
    itens = (_fiado_em_aberto().filter(loja=loja)
             .select_related('os__veiculo', 'nota').order_by('criado_em'))

    if request.method == 'POST':
        escolhidos = list(itens.filter(pk__in=request.POST.getlist('itens')))
        if not escolhidos:
            messages.error(request, 'Marque pelo menos uma peça.')
            return redirect('conta_loja', loja.pk)
        hoje = timezone.localdate()
        with transaction.atomic():
            pagamento = PagamentoLoja.objects.create(
                loja=loja, data=hoje, valor=sum((i.custo_total() for i in escolhidos), Decimal('0')),
                criado_por=request.user)
            for item in escolhidos:  # um a um para cada peça entrar no histórico de alterações
                item.pago_loja_em, item.pagamento = hoje, pagamento
                item.save()
        messages.success(request, f'Pagamento de {brl(pagamento.valor)} para {loja} registrado '
                                  f'({len(escolhidos)} peça(s)).')
        return redirect('conta_loja', loja.pk)

    devidos = [i for i in itens if i.os.status == OrdemServico.PAGA]
    previstos = [i for i in itens if i.os.status != OrdemServico.PAGA]
    pagamentos = (loja.pagamentos.select_related('criado_por')
                  .prefetch_related(Prefetch('itens', ItemOS.objects.select_related('os__veiculo'))))
    return render(request, 'core/conta_loja.html', {
        'loja': loja, 'devidos': devidos, 'previstos': previstos,
        'devido': sum((i.custo_total() for i in devidos), Decimal('0')),
        'previsto': sum((i.custo_total() for i in previstos), Decimal('0')),
        'comodidade': sum((i.comodidade() for i in itens), Decimal('0')),
        'sem_nota': sum(1 for i in itens if not i.nota_id),
        'pagamentos': pagamentos,
    })


@login_required
def faturamento(request):
    """O que entrou no período: só OS pagas, pela data em que o cliente pagou (valores à vista)."""
    form = FaturamentoForm(request.GET or None)
    de, ate, periodo = form.intervalo(timezone.localdate())
    ordens = list(OrdemServico.objects.filter(status=OrdemServico.PAGA, pago_em__date__gte=de,
                                              pago_em__date__lte=ate)
                  .select_related('veiculo', 'cliente')
                  .annotate(valor=Sum(F('itens__quantidade') * F('itens__preco_unitario'), default=0))
                  .order_by('-pago_em'))
    itens = ItemOS.objects.filter(os__in=[o.pk for o in ordens])
    zero = Decimal('0')

    formas = []
    for chave, nome in OrdemServico.FORMAS_PAGAMENTO:
        do_tipo = [o for o in ordens if o.forma_pagamento == chave]
        if do_tipo:
            total = sum((o.valor for o in do_tipo), zero)
            formas.append({'nome': nome, 'chave': chave, 'os': len(do_tipo), 'total': total,
                           'maquininha': (total * Decimal(settings.ACRESCIMO_CARTAO)).quantize(Decimal('0.01'))
                           if chave == 'cartao' else None})

    pecas = itens.filter(tipo=ItemOS.PECA).aggregate(
        preco=Sum(F('quantidade') * F('preco_unitario'), default=zero),
        custo=Sum(F('quantidade') * F('custo_unitario'), default=zero))
    partes, sem_executor = {'dono': zero}, zero
    for item in itens.filter(tipo=ItemOS.SERVICO).select_related('mecanico'):  # item a item, para bater centavo com a OS
        divisao = item.divisao()
        if divisao:
            for quem, valor in divisao.items():
                partes[quem] = partes.get(quem, zero) + valor
        else:
            sem_executor += item.total()
    servicos = sum(partes.values(), zero) + sem_executor
    comodidade = pecas['preco'] - pecas['custo']
    return render(request, 'core/faturamento.html', {
        'form': form, 'periodo': periodo, 'de': de, 'ate': ate, 'ordens': ordens, 'formas': formas,
        'recebido': sum((o.valor for o in ordens), zero),
        'pecas': pecas['preco'], 'custo_pecas': pecas['custo'], 'comodidade': comodidade,
        'servicos': servicos, 'mao_de_obra': _linhas_divisao(partes), 'sem_executor': sem_executor,
        'resultado_dono': partes['dono'] + comodidade, 'nome_dono': settings.NOME_DONO,
    })


@staff_member_required
def exportar_itens(request):
    """Planilha crua de todos os itens, para análise fora do sistema."""
    resp = HttpResponse(content_type='text/csv; charset=utf-8')
    resp['Content-Disposition'] = f'attachment; filename="itens_{timezone.localdate():%Y%m%d}.csv"'
    resp.write('﻿')  # BOM para o Excel abrir com acentos certos
    w = csv.writer(resp, delimiter=';')
    w.writerow(['os', 'data', 'status', 'placa', 'modelo', 'km', 'cliente', 'tipo', 'descricao', 'quantidade',
                'preco_unitario', 'custo_unitario', 'origem', 'loja', 'tem_nota', 'pago_loja_em',
                'forma_pagamento'])
    qs = ItemOS.objects.select_related('os__veiculo', 'os__cliente', 'loja').order_by('os_id', 'id')
    for i in qs.iterator():
        o = i.os
        w.writerow([o.numero, f'{o.criado_em:%Y-%m-%d}', o.status, o.veiculo.placa, o.veiculo.modelo, o.km or '',
                    o.cliente.nome, i.tipo, i.descricao, i.quantidade, i.preco_unitario, i.custo_unitario,
                    i.origem, i.loja.nome if i.loja else '', 'sim' if i.nota_id else 'nao',
                    i.pago_loja_em or '', o.forma_pagamento])
    return resp
