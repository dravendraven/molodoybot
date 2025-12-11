import struct

class MinimapMemorySimulator:
    def __init__(self):
        # Constantes do Tibia 7.4
        self.MAP_WIDTH = 106
        self.MAP_HEIGHT = 106
        self.BYTES_PER_PIXEL = 4
        
        # O centro do minimapa (onde o char está)
        # Em 106 pixels, o centro é o índice 53 (0-105)
        self.CENTER_X = 53
        self.CENTER_Y = 53
        
        # Definição de Cores (Formato 0xRRGGBB)
        self.COLOR_GRASS = 0x00CC00  # Verde
        self.COLOR_WATER = 0x0000FF  # Azul
        self.COLOR_CROSS = 0xFFFFFF  # Branco (Jogador)
        
        # Simulando a memória RAM do cliente (Buffer vazio)
        # Tamanho = Largura * Altura * 4 bytes
        self.memory_buffer = bytearray(self.MAP_WIDTH * self.MAP_HEIGHT * self.BYTES_PER_PIXEL)
        
        # Populamos a memória com um mapa falso para teste
        self._generate_mock_map()

    def _set_pixel_in_memory(self, x, y, color_hex):
        """Escreve uma cor num pixel específico da memória simulada"""
        if 0 <= x < self.MAP_WIDTH and 0 <= y < self.MAP_HEIGHT:
            # Calcula o índice linear (offset)
            index = (y * self.MAP_WIDTH + x) * self.BYTES_PER_PIXEL
            
            # Empacota o hex em 4 bytes (Little Endian: B G R A)
            # Isso simula como o Windows/Intel guarda o valor na RAM
            # B G R A (Alpha assumido como 00 ou FF)
            b = color_hex & 0xFF
            g = (color_hex >> 8) & 0xFF
            r = (color_hex >> 16) & 0xFF
            a = 0xFF 
            
            struct.pack_into('<BBBB', self.memory_buffer, index, b, g, r, a)

    def _draw_tile(self, tile_x, tile_y, color):
        """Desenha um tile (bloco de 2x2 pixels) na memória"""
        # tile_x, tile_y são coordenadas absolutas em PIXELS
        self._set_pixel_in_memory(tile_x, tile_y, color)         # Pixel 0,0
        self._set_pixel_in_memory(tile_x + 1, tile_y, color)     # Pixel 1,0
        self._set_pixel_in_memory(tile_x, tile_y + 1, color)     # Pixel 0,1
        self._set_pixel_in_memory(tile_x + 1, tile_y + 1, color) # Pixel 1,1

    def _generate_mock_map(self):
        """Cria um cenário fictício na memória"""
        print("--- Gerando Mapa na Memória ---")
        
        # 1. Preenche tudo com GRAMA (Verde)
        for y in range(0, self.MAP_HEIGHT, 2):
            for x in range(0, self.MAP_WIDTH, 2):
                self._draw_tile(x, y, self.COLOR_GRASS)
        
        # 2. Desenha um rio de ÁGUA (Azul) ao NORTE do jogador
        # Vamos fazer um rio horizontal 3 tiles acima do jogador
        river_y_pixel = self.CENTER_Y - (3 * 2) # 3 tiles * 2 pixels
        for x in range(0, self.MAP_WIDTH, 2):
             self._draw_tile(x, river_y_pixel, self.COLOR_WATER)

        # 3. Desenha a CRUZ BRANCA do Jogador (Player)
        # Ocupa o centro e os 4 tiles adjacentes
        cx, cy = self.CENTER_X, self.CENTER_Y
        self._draw_tile(cx, cy, self.COLOR_CROSS)         # Centro
        self._draw_tile(cx, cy - 2, self.COLOR_CROSS)     # Norte
        self._draw_tile(cx, cy + 2, self.COLOR_CROSS)     # Sul
        self._draw_tile(cx - 2, cy, self.COLOR_CROSS)     # Oeste
        self._draw_tile(cx + 2, cy, self.COLOR_CROSS)     # Leste
        print("Mapa gerado. Jogador em (0,0) cercado por grama, com água ao norte.\n")

    # --- A FUNÇÃO QUE VOCÊ PRECISA ---
    def get_tile_color(self, dx, dy):
        """
        Lê a memória e retorna a cor do tile na posição relativa (dx, dy).
        """
        # 1. Converter dist. de Tile para Pixel
        pixel_dx = dx * 2
        pixel_dy = dy * 2 # No Tibia/Computação, Y cresce para baixo
        
        # 2. Calcular posição absoluta na matriz de pixels
        abs_x = self.CENTER_X + pixel_dx
        abs_y = self.CENTER_Y + pixel_dy
        
        # Verifica limites
        if not (0 <= abs_x < self.MAP_WIDTH and 0 <= abs_y < self.MAP_HEIGHT):
            return "OUT_OF_BOUNDS"

        # 3. Calcular endereço (Offset)
        # Offset = (Y * Largura + X) * 4 bytes
        offset = (abs_y * self.MAP_WIDTH + abs_x) * self.BYTES_PER_PIXEL
        
        # 4. Ler os 4 bytes da memória simulada
        # Lendo como unsigned int (I) Little Endian (<)
        color_data = struct.unpack_from('<I', self.memory_buffer, offset)[0]
        
        # Remover o canal Alpha (se houver) para ficar limpo (0xRRGGBB)
        # Como lemos Little Endian, o struct já inverteu para nós.
        # Mas precisamos garantir a ordem correta de exibição. 
        # Na memória está BB GG RR AA. O int lido é 0xAARRGGBB.
        
        r = (color_data >> 16) & 0xFF
        g = (color_data >> 8) & 0xFF
        b = color_data & 0xFF
        
        hex_color = (r << 16) | (g << 8) | b
        return hex_color

# --- Execução do Teste ---

bot = MinimapMemorySimulator()

# Vamos escanear os tiles ao redor do jogador
# dx: -2 a 2, dy: -4 a 2
print(f"{'DX':^4} | {'DY':^4} | {'HEX LIDO':^10} | {'IDENTIFICAÇÃO'}")
print("-" * 40)

for dy in range(-4, 3):
    for dx in range(-2, 3):
        color = bot.get_tile_color(dx, dy)
        
        tile_name = "Desconhecido"
        if color == 0xFFFFFF: tile_name = "CROSS (Player)"
        elif color == 0x00CC00: tile_name = "Grama"
        elif color == 0x0000FF: tile_name = "Água"
        
        # Formatação bonita para o log
        hex_str = f"0x{color:06X}"
        print(f"{dx:^4} | {dy:^4} | {hex_str:^10} | {tile_name}")
    
    # Separador de linha para visualizar o grid
    if dx == 2: print("-" * 40)