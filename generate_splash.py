"""
Gera splash.png automaticamente com a versao do version.txt.
Requer: splash_base.png (imagem sem a versao)
"""
from PIL import Image, ImageDraw, ImageFont
import os
import sys

def generate_splash():
    # Le versao
    with open('version.txt', 'r') as f:
        version = f.read().strip()

    # Carrega imagem base
    if not os.path.exists('splash_base.png'):
        print("ERRO: splash_base.png nao encontrado!")
        print("Crie uma copia do splash.png SEM o texto da versao.")
        sys.exit(1)

    img = Image.open('splash_base.png')
    draw = ImageDraw.Draw(img)

    # Configuracoes do texto
    version_text = f"v{version}"

    # Tenta carregar fonte Verdana
    font = None
    font_paths = [
        "verdana.ttf",
        "C:/Windows/Fonts/verdana.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]

    for path in font_paths:
        try:
            font = ImageFont.truetype(path, 12)
            break
        except:
            continue

    if font is None:
        font = ImageFont.load_default()

    # Calcula posicao do texto
    # Imagem tem ~300x80px, texto deve ficar abaixo de "MolodoyBot"
    text_bbox = draw.textbbox((0, 0), version_text, font=font)
    text_width = text_bbox[2] - text_bbox[0]

    # Posicao: centralizado na area do texto (lado direito), abaixo do titulo
    # "MolodoyBot" comeca em ~115px do lado esquerdo
    x = 195 - (text_width // 2)  # Centraliza no lado direito
    y = 52  # Abaixo de "MolodoyBot"

    # Cor cinza (#969696)
    text_color = (150, 150, 150)

    draw.text((x, y), version_text, font=font, fill=text_color)

    # Salva
    img.save('splash.png')
    print(f"splash.png gerado com versao v{version}")
    return True

if __name__ == '__main__':
    generate_splash()
