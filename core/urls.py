from django.urls import path

from . import views

urlpatterns = [
    path('', views.inicio, name='inicio'),
    path('placa/', views.buscar_placa, name='buscar_placa'),
    path('carro/<int:pk>/', views.veiculo, name='veiculo'),
    path('os/', views.todas_os, name='todas_os'),
    path('os/nova/', views.nova_os, name='nova_os'),
    path('carro/<int:veiculo_pk>/nova-os/', views.nova_os, name='nova_os_veiculo'),
    path('os/<int:pk>/', views.os_detalhe, name='os'),
    path('os/<int:pk>/peca/', views.adicionar_peca, name='adicionar_peca'),
    path('os/<int:pk>/servico/', views.adicionar_servico, name='adicionar_servico'),
    path('os/<int:pk>/item/<int:item_pk>/remover/', views.remover_item, name='remover_item'),
    path('os/<int:pk>/status/', views.mudar_status, name='mudar_status'),
    path('os/<int:pk>/imprimir/', views.imprimir_os, name='imprimir_os'),
    path('lojas/', views.contas_lojas, name='contas'),
    path('lojas/<int:pk>/', views.conta_loja, name='conta_loja'),
    path('faturamento/', views.faturamento, name='faturamento'),
    path('exportar/itens.csv', views.exportar_itens, name='exportar_itens'),
]
