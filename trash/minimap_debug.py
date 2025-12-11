import pymem
import struct
from PIL import Image
import math

# ================= CONFIGURAÇÕES =================
PROCESS_NAME = "Tibia.exe"  # Nome do executável do seu jogo
START_ADDR = 0x001967F8
END_ADDR   = 0x00198E08
BYTES_PER_PIXEL = 4  # Você sugeriu 4 bytes (Hex Color)
# =================================================

def main():
    try:
        pm = pymem.Pymem(PROCESS_NAME)
        print(f"Conectado ao {PROCESS_NAME}")
    except Exception as e:
        print(f"Erro ao conectar: {e}")
        return

    # 1. Calcular tamanho total
    total_size = END_ADDR - START_ADDR
    total_pixels = total_size // BYTES_PER_PIXEL
    
    print(f"Lendo intervalo: {hex(START_ADDR)} - {hex(END_ADDR)}")
    print(f"Tamanho em Bytes: {total_size}")
    print(f"Pixels estimados (se 4 bytes/pix): {total_pixels}")

    # Tenta adivinhar a largura (assumindo que seja quadrado ou quase)
    width = int(math.sqrt(total_pixels))
    height = int(total_pixels / width)
    
    # Ajuste fino: Se sobrar pixels, aumentamos a largura para tentar encaixar
    if (width * height) < total_pixels:
        width += 1
        height = int(total_pixels / width) + 1

    print(f"Tentando gerar imagem com dimensões: {width}x{height}")

    # 2. Ler a memória
    try:
        raw_data = pm.read_bytes(START_ADDR, total_size)
    except Exception as e:
        print(f"Erro ao ler memória: {e}")
        return

    # 3. Processar Cores
    # Vamos assumir formato BGRX ou ARGB (comum em memória)
    # Estrutura do pixel (R, G, B)
    pixels = []
    
    # Procura pela cruz branca (User) para debug
    white_cross_found = 0

    for i in range(0, len(raw_data), BYTES_PER_PIXEL):
        chunk = raw_data[i : i + BYTES_PER_PIXEL]
        if len(chunk) < 3: break
        
        # Tenta interpretar como BGR (padrão Windows) ou RGB
        # Ajuste aqui se as cores ficarem invertidas (azul virar vermelho)
        b = chunk[0]
        g = chunk[1]
        r = chunk[2]
        
        # Verifica cruz branca (255, 255, 255)
        if r == 255 and g == 255 and b == 255:
            white_cross_found += 1
            # Vamos pintar de Rosa Choque na imagem debug para destacar o player
            pixels.append((255, 0, 255)) 
        else:
            pixels.append((r, g, b))

    print(f"Pixels 'Brancos' (possível player) encontrados: {white_cross_found}")

    # 4. Gerar Imagem
    img = Image.new('RGB', (width, height))
    
    # Preencher imagem
    try:
        # Coloca os dados na imagem. Se o array for maior que a imagem, corta.
        # Se for menor, preenche o que der.
        img.putdata(pixels[:width*height])
        
        filename = "minimap_dump.png"
        img.save(filename)
        img.show()
        print(f"Imagem salva como '{filename}'. Verifique se parece com o mapa!")
        
        # DICA EXTRA:
        # Se a imagem parecer um ruído ("chuvisco"), o endereço ou o tamanho do byte está errado.
        # Se a imagem parecer o mapa mas "inclinada/distorcida", a largura (width) está errada.
        
    except Exception as e:
        print(f"Erro ao salvar imagem: {e}")

if __name__ == "__main__":
    main()