import customtkinter as ctk
from PIL import Image
import os

# === MEMORY OPTIMIZATION: Limite máximo de tamanho de imagem ===
MAX_IMAGE_WIDTH = 800
MAX_IMAGE_HEIGHT = 600


class PathPreviewWindow(ctk.CTkToplevel):
    def __init__(self, parent, image_paths, title="Visualização de Rota"):
        super().__init__(parent)

        self.title(title)
        self.geometry("900x700")  # Tamanho inicial da janela

        # Traz a janela para frente
        self.attributes("-topmost", True)
        self.after(100, lambda: self.attributes("-topmost", False))  # Libera depois para não travar

        # Título / Cabeçalho
        self.lbl_title = ctk.CTkLabel(
            self,
            text=f"Visualização gerada: {len(image_paths)} andares",
            font=("Roboto", 16, "bold")
        )
        self.lbl_title.pack(pady=10)

        # Área de Rolagem (Caso a imagem seja gigante)
        self.scroll_frame = ctk.CTkScrollableFrame(self, label_text="Mapa Renderizado")
        self.scroll_frame.pack(fill="both", expand=True, padx=10, pady=10)

        self.images_ref = []  # Referência para o Garbage Collector não apagar as imagens

        # Renderiza cada imagem enviada
        for img_path in image_paths:
            if os.path.exists(img_path):
                try:
                    # 1. Abre a imagem com Pillow
                    pil_img = Image.open(img_path)
                    w, h = pil_img.size

                    # === MEMORY OPTIMIZATION: Redimensiona imagens grandes ===
                    # Limita tamanho máximo para economizar memória (~80% economia em imagens grandes)
                    if w > MAX_IMAGE_WIDTH or h > MAX_IMAGE_HEIGHT:
                        ratio = min(MAX_IMAGE_WIDTH / w, MAX_IMAGE_HEIGHT / h)
                        new_w, new_h = int(w * ratio), int(h * ratio)
                        pil_img = pil_img.resize((new_w, new_h), Image.LANCZOS)
                        w, h = new_w, new_h

                    # 2. Cria o objeto CTkImage
                    ctk_img = ctk.CTkImage(
                        light_image=pil_img,
                        dark_image=pil_img,
                        size=(w, h)
                    )

                    # === MEMORY OPTIMIZATION: Fecha PIL Image após criar CTkImage ===
                    pil_img.close()

                    # 3. Adiciona na interface
                    # Label descritiva do arquivo
                    lbl_filename = ctk.CTkLabel(self.scroll_frame, text=f"Arquivo: {os.path.basename(img_path)}", text_color="gray")
                    lbl_filename.pack(pady=(20, 5))

                    # Label com a imagem
                    img_label = ctk.CTkLabel(self.scroll_frame, image=ctk_img, text="")
                    img_label.pack(pady=5)

                    self.images_ref.append(ctk_img)  # Mantém referência

                except Exception as e:
                    print(f"[UI] Erro ao carregar imagem {img_path}: {e}")
                    err_lbl = ctk.CTkLabel(self.scroll_frame, text=f"Erro ao carregar: {img_path}", text_color="red")
                    err_lbl.pack()
            else:
                print(f"[UI] Arquivo não encontrado: {img_path}")

        # Botão Fechar
        self.btn_close = ctk.CTkButton(self, text="Fechar", command=self._on_close, fg_color="#C0392B", hover_color="#E74C3C")
        self.btn_close.pack(pady=10)

        # === MEMORY OPTIMIZATION: Cleanup ao fechar janela ===
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self):
        """Limpa recursos antes de fechar a janela."""
        # Limpa referências de imagens
        self.images_ref.clear()
        self.destroy()