from django.db import migrations, models

import core.models

# O que fica gravado em ItemOS.executor deixa de ser o nome de uma pessoa e passa a ser o papel.
# Os nomes mostrados na tela vêm da configuração (OFICINA_NOME_DONO / OFICINA_NOME_MECANICO).
TROCAS = {'lobao': 'dono', 'rafael': 'mecanico'}


def trocar(de_para):
    def aplicar(apps, schema_editor):
        ItemOS = apps.get_model('core', 'ItemOS')
        for antigo, novo in de_para.items():
            ItemOS.objects.filter(executor=antigo).update(executor=novo)
    return aplicar


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0004_pagamento_loja'),
    ]

    operations = [
        migrations.AlterField(
            model_name='itemos',
            name='executor',
            field=models.CharField(blank=True, choices=core.models.executores, max_length=10,
                                   verbose_name='quem fez'),
        ),
        migrations.RunPython(trocar(TROCAS), trocar({novo: antigo for antigo, novo in TROCAS.items()})),
    ]
