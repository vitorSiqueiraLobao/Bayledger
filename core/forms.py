from datetime import timedelta

from django import forms

from .models import ItemOS, Loja, Nota, OrdemServico, executores


def campo_dinheiro(label, required=True, initial=None):
    # Texto com teclado numérico: aceita "26,50" (input type=number rejeitaria a vírgula).
    return forms.DecimalField(
        label=label, required=required, initial=initial, min_value=0,
        max_digits=10, decimal_places=2, localize=True,
        widget=forms.TextInput(attrs={'inputmode': 'decimal', 'autocomplete': 'off'}),
    )


def campo_quantidade():
    return forms.DecimalField(
        label='Quantidade', initial=1, min_value=0.01, max_digits=8, decimal_places=2, localize=True,
        widget=forms.TextInput(attrs={'inputmode': 'decimal', 'autocomplete': 'off'}),
    )


class PlacaForm(forms.Form):
    placa = forms.CharField(
        label='Placa do carro', max_length=10,
        widget=forms.TextInput(attrs={'autocapitalize': 'characters', 'autocomplete': 'off',
                                      'placeholder': 'ABC1D23', 'autofocus': True}),
    )


class NovaOSCarroNovoForm(forms.Form):
    placa = forms.CharField(label='Placa', max_length=10,
                            widget=forms.TextInput(attrs={'autocapitalize': 'characters'}))
    marca = forms.CharField(label='Marca', max_length=60, required=False,
                            widget=forms.TextInput(attrs={'placeholder': 'Peugeot'}))
    modelo = forms.CharField(label='Modelo', max_length=60,
                             widget=forms.TextInput(attrs={'placeholder': '207'}))
    ano = forms.CharField(label='Ano', max_length=10, required=False,
                          widget=forms.TextInput(attrs={'inputmode': 'numeric'}))
    cliente_nome = forms.CharField(label='Nome do cliente', max_length=120)
    cliente_telefone = forms.CharField(label='WhatsApp do cliente', max_length=30, required=False,
                                       widget=forms.TextInput(attrs={'inputmode': 'tel',
                                                                     'placeholder': '(11) 99999-9999'}))
    km = forms.IntegerField(label='Km do carro', required=False, min_value=0,
                            widget=forms.TextInput(attrs={'inputmode': 'numeric'}))
    pedido = forms.CharField(label='O que o cliente pediu', required=False,
                             widget=forms.Textarea(attrs={'rows': 3}))


class NovaOSCarroConhecidoForm(forms.Form):
    km = forms.IntegerField(label='Km do carro', required=False, min_value=0,
                            widget=forms.TextInput(attrs={'inputmode': 'numeric', 'autofocus': True}))
    pedido = forms.CharField(label='O que o cliente pediu', required=False,
                             widget=forms.Textarea(attrs={'rows': 3}))


class ServicoForm(forms.Form):
    descricao = forms.CharField(label='Serviço feito', max_length=200,
                                widget=forms.TextInput(attrs={'list': 'sugestoes', 'autocomplete': 'off',
                                                              'placeholder': 'Troca de óleo e filtros'}))
    preco_unitario = campo_dinheiro('Valor da mão de obra (R$)')
    executor = forms.ChoiceField(label='Quem fez?', choices=executores, widget=forms.RadioSelect,
                                 error_messages={'required': 'Escolha quem fez o serviço.'})


class PecaForm(forms.Form):
    descricao = forms.CharField(label='Peça', max_length=200,
                                widget=forms.TextInput(attrs={'list': 'sugestoes', 'autocomplete': 'off',
                                                              'placeholder': 'Bieleta'}))
    quantidade = campo_quantidade()
    preco_unitario = campo_dinheiro('Preço cliente (R$)')
    origem = forms.ChoiceField(label='De onde veio a peça?', choices=ItemOS.ORIGENS,
                               initial=ItemOS.FIADO, widget=forms.RadioSelect)
    loja = forms.CharField(label='Qual loja?', max_length=120, required=False,
                           widget=forms.TextInput(attrs={'list': 'lojas', 'autocomplete': 'off'}))
    custo_unitario = campo_dinheiro('Quanto a loja cobrou, cada (R$)', required=False)
    nota = forms.CharField(required=False, widget=forms.HiddenInput)
    foto_nota = forms.ImageField(
        label='Foto da nota', required=False,
        widget=forms.ClearableFileInput(attrs={'accept': 'image/*', 'capture': 'environment'}),
    )

    PRECISA_LOJA = {ItemOS.FIADO, ItemOS.PAGO_NA_HORA, ItemOS.INTERNET}

    def __init__(self, *args, notas_recentes=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.notas_recentes = list(notas_recentes)

    def clean(self):
        dados = super().clean()
        origem = dados.get('origem')
        nome_loja = (dados.get('loja') or '').strip()

        if origem in self.PRECISA_LOJA and not nome_loja:
            self.add_error('loja', 'Escreva o nome da loja.')
        if origem == ItemOS.CLIENTE:
            dados['custo_unitario'] = 0
            nome_loja = ''
            # O bloco da nota fica escondido nesse caso, mas o que foi marcado antes ainda seria enviado.
            dados['nota'] = ''
            dados['foto_nota'] = None
        elif origem in self.PRECISA_LOJA and dados.get('custo_unitario') in (None, ''):
            self.add_error('custo_unitario', 'Quanto a loja cobrou? (Se não souber agora, coloque 0.)')
        if dados.get('custo_unitario') is None:
            dados['custo_unitario'] = 0
        dados['loja_nome'] = nome_loja

        # Foto nova tem prioridade; senão, pode reaproveitar uma nota já fotografada (várias peças, um papel só).
        nota_id = dados.get('nota')
        dados['nota_obj'] = None
        if dados.get('foto_nota'):
            if not nome_loja:
                self.add_error('loja', 'Para guardar a foto da nota, diga de qual loja ela é.')
        elif nota_id:
            nota = next((n for n in self.notas_recentes if str(n.pk) == nota_id), None)
            if nota is None:
                self.add_error(None, 'Essa nota não foi encontrada. Tire a foto de novo.')
            elif nota.loja.nome.lower() != nome_loja.lower():
                self.add_error(None, f'A nota escolhida é da loja "{nota.loja}", mas a peça é da "{nome_loja or "?"}".')
            else:
                dados['nota_obj'] = nota
        return dados


class PagarForm(forms.Form):
    forma_pagamento = forms.ChoiceField(label='Como o cliente pagou?', choices=OrdemServico.FORMAS_PAGAMENTO,
                                        widget=forms.RadioSelect)


class BuscaOSForm(forms.Form):
    q = forms.CharField(label='Buscar', required=False, max_length=120,
                        widget=forms.TextInput(attrs={'type': 'search', 'autocomplete': 'off',
                                                      'placeholder': 'Nº, placa, cliente ou carro'}))
    status = forms.ChoiceField(label='Situação', required=False,
                               choices=[('', 'Todas')] + OrdemServico.STATUS)
    de = forms.DateField(label='De', required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    ate = forms.DateField(label='Até', required=False, widget=forms.DateInput(attrs={'type': 'date'}))

    def clean(self):
        dados = super().clean()
        if dados.get('de') and dados.get('ate') and dados['de'] > dados['ate']:
            dados['de'], dados['ate'] = dados['ate'], dados['de']
        return dados


class FaturamentoForm(forms.Form):
    PERIODOS = [('hoje', 'Hoje'), ('semana', 'Semana'), ('mes', 'Mês'), ('livre', 'Escolher datas')]
    periodo = forms.ChoiceField(label='Período', choices=PERIODOS, required=False, widget=forms.RadioSelect)
    de = forms.DateField(label='De', required=False,
                         widget=forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'))
    ate = forms.DateField(label='Até', required=False,
                          widget=forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'))

    def intervalo(self, hoje):
        """(de, até, período escolhido). Semana começa na segunda; mês no dia 1. Data livre sem fim vai até hoje."""
        d = self.cleaned_data if self.is_valid() else {}
        periodo = d.get('periodo') or ('livre' if d.get('de') or d.get('ate') else 'mes')
        if periodo == 'hoje':
            return hoje, hoje, periodo
        if periodo == 'semana':
            return hoje - timedelta(days=hoje.weekday()), hoje, periodo
        if periodo == 'livre' and (d.get('de') or d.get('ate')):
            de = d.get('de') or d['ate']
            ate = d.get('ate') or max(de, hoje)
            return min(de, ate), max(de, ate), periodo
        return hoje.replace(day=1), hoje, 'mes'


class CancelarForm(forms.Form):
    motivo = forms.CharField(label='Por que cancelar?', widget=forms.Textarea(attrs={'rows': 2}))


class LojaForm(forms.ModelForm):
    class Meta:
        model = Loja
        fields = ['nome', 'telefone']
