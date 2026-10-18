"""Roda NO SERVIDOR (o deploy.sh manda este arquivo por ssh): põe as configurações da oficina no oficina.env.

Recebe, em base64 no primeiro argumento, o conteúdo do deploy/servidor.env do seu computador e, para cada
CHAVE=valor dele, troca a linha no ~/oficina-dados/oficina.env (ou acrescenta, se não existir).

Só mexe nas chaves OFICINA_* (menos OFICINA_DATA_DIR) e DJANGO_TIME_ZONE. Segredo, domínio e pasta de dados
ficam como estão, e valor vazio nunca apaga nada. Quando algo muda, guarda a versão anterior em oficina.env.anterior.
"""
import base64
import os
import shutil
import sys
from pathlib import Path

NUNCA = {'OFICINA_DATA_DIR'}


def permitida(chave):
    return (chave.startswith('OFICINA_') and chave not in NUNCA) or chave == 'DJANGO_TIME_ZONE'


def ler_novos(texto):
    novos = {}
    for linha in texto.splitlines():
        linha = linha.strip()
        if not linha or linha.startswith('#') or '=' not in linha:
            continue
        chave, _, valor = linha.partition('=')
        chave = chave.strip()
        if not permitida(chave):
            print(f'  ignorado (não sincronizo esta chave): {chave}')
        elif valor.strip().strip('"\''):
            novos[chave] = valor.strip()
    return novos


def aplicar(atual, novos):
    """Devolve (linhas novas, chaves que mudaram)."""
    resultado, mudou, vistos = [], [], set()
    for linha in atual:
        chave = linha.partition('=')[0].strip()
        if chave in novos and not linha.lstrip().startswith('#'):
            nova = f'{chave}={novos[chave]}'
            if nova != linha:
                mudou.append(chave)
            if chave not in vistos:
                resultado.append(nova)
            vistos.add(chave)
        else:
            resultado.append(linha)
    for chave, valor in novos.items():
        if chave not in vistos:
            resultado.append(f'{chave}={valor}')
            mudou.append(chave)
    return resultado, mudou


def main():
    novos = ler_novos(base64.b64decode(sys.argv[1]).decode('utf-8'))
    arquivo = Path.home() / 'oficina-dados' / 'oficina.env'
    resultado, mudou = aplicar(arquivo.read_text(encoding='utf-8').splitlines(), novos)
    if not mudou:
        print('oficina.env já estava em dia')
        return
    shutil.copy2(arquivo, arquivo.with_name('oficina.env.anterior'))
    tmp = arquivo.with_name('oficina.env.tmp')
    tmp.write_text('\n'.join(resultado) + '\n', encoding='utf-8')
    os.chmod(tmp, 0o600)
    tmp.replace(arquivo)
    print('oficina.env atualizado: ' + ', '.join(mudou))


if __name__ == '__main__':
    main()
