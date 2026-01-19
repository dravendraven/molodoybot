"""
Waypoint Editor - Visual GUI for creating and editing cavebot waypoint routes.

This module provides an independent window (toplevel) for creating and editing
waypoint routes by visually clicking on a rendered map, without needing to
physically walk to each location in the game.

Features:
- Interactive canvas with rendered Tibia map
- Click to add waypoints, right-click to remove
- Arrow keys to pan map
- Load/save waypoint files
- Floor (Z-level) selection
- Fixed optimal zoom for accuracy and visibility
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import json
import os
from pathlib import Path
from PIL import Image, ImageDraw
import sys
import threading
import time

# Import config and game map
try:
    from config import MAPS_DIRECTORY, WALKABLE_COLORS
    from core.global_map import GlobalMap
    from utils.color_palette import get_color
except ImportError:
    # Fallback for relative imports
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from config import MAPS_DIRECTORY, WALKABLE_COLORS
    from core.global_map import GlobalMap
    from utils.color_palette import get_color


class WaypointEditorWindow:
    """
    Independent window for visual waypoint editing.

    Layout:
    - Left: Canvas with rendered map (500x500px)
    - Right: Control panel with waypoint list, buttons, and settings
    """

    def __init__(self, parent_window=None, maps_directory=MAPS_DIRECTORY,
                 current_waypoints=None, on_save_callback=None, current_pos=None):
        """
        Initialize the waypoint editor window.

        Args:
            parent_window: Parent Tkinter window (for positioning)
            maps_directory: Path to Tibia map files (.map)
            current_waypoints: List of existing waypoints to load
            on_save_callback: Function to call when user saves
            current_pos: Current player position (x, y, z) for default center
        """
        self.parent_window = parent_window
        self.maps_directory = maps_directory
        self.on_save_callback = on_save_callback
        self.current_pos = current_pos or (32082, 32153, 7)

        # Initialize map system
        self.global_map = GlobalMap(maps_directory, WALKABLE_COLORS)

        # Waypoint data
        self.waypoints = []
        if current_waypoints:
            self.waypoints = [wp.copy() for wp in current_waypoints]

        # Viewport and rendering
        self.viewport_center_x, self.viewport_center_y = self.current_pos[0], self.current_pos[1]
        self.current_floor = self.current_pos[2]
        self.viewport_radius = 90  # Tiles in each direction (fixed for performance and accuracy)
        self.pixels_per_tile = 4  # Fixed zoom: 4 pixels per tile for good visibility

        # Canvas dimensions
        self.canvas_width = 500
        self.canvas_height = 500

        # UI state
        self.selected_waypoint_idx = None
        self.map_image = None
        self.canvas_image_ref = None  # Keep reference to avoid GC
        self._should_scroll_to_selection = False  # Flag to control listbox auto-scroll
        self._last_waypoint_count = 0  # Track waypoint list changes to avoid unnecessary rebuilds

        # Threading for map rendering
        self._render_thread = None
        self._stop_render_thread = False
        self._map_data_lock = threading.Lock()
        self._pending_render = False

        # For accurate coordinate conversion
        self.viewport_min_x = 0
        self.viewport_min_y = 0
        self.image_crop_offset_x = 0  # How much we cropped from left
        self.image_crop_offset_y = 0  # How much we cropped from top

        # Panning state (Shift+Drag)
        self._pan_start_x = None
        self._pan_start_y = None
        self._is_panning = False
        self._pan_viewport_start_x = None
        self._pan_viewport_start_y = None

        # Waypoint drag state
        self._dragging_waypoint_idx = None

        # Zoom levels
        self.zoom_levels = [2, 3, 4, 6, 8]  # pixels per tile
        self.current_zoom_idx = 2  # Começa em 4 (índice 2)

        # Insert mode (inserir waypoint após selecionado)
        self._insert_after_idx = None

        # Undo/Redo stacks
        self._undo_stack = []  # Lista de (waypoints_snapshot, description)
        self._redo_stack = []
        self._max_history = 30

        # Create window
        self._create_window()
        self._render_map_async()
        self._update_display()

        # Start periodic update checker for async rendering
        self._schedule_display_update()

    def _create_window(self):
        """Create the main window and UI layout."""
        self.window = tk.Toplevel(self.parent_window) if self.parent_window else tk.Tk()
        self.window.title("🗺️ Waypoint Editor")
        self.window.geometry("900x600")
        self.window.resizable(True, True)

        # Main container
        main_frame = ttk.Frame(self.window)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # LEFT: Canvas
        left_frame = ttk.Frame(main_frame)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        canvas_label = ttk.Label(left_frame, text="Click=Add | Arrastar=Mover | Dir.=Remover | Scroll=Zoom | Ctrl+Z/Y=Undo/Redo")
        canvas_label.pack(side=tk.TOP, padx=5, pady=2)

        self.canvas = tk.Canvas(
            left_frame,
            width=self.canvas_width,
            height=self.canvas_height,
            bg='black',
            cursor='crosshair'
        )
        self.canvas.pack(side=tk.TOP, padx=5, pady=5)

        # Canvas event bindings
        self.canvas.bind('<Button-1>', self._on_canvas_click)
        self.canvas.bind('<B1-Motion>', self._on_canvas_drag)
        self.canvas.bind('<ButtonRelease-1>', self._on_canvas_release)
        self.canvas.bind('<Button-3>', self._on_canvas_right_click)
        self.canvas.bind('<Motion>', self._on_canvas_motion)

        # Shift+Drag for panning
        self.canvas.bind('<Shift-Button-1>', self._on_pan_start)
        self.canvas.bind('<Shift-B1-Motion>', self._on_pan_drag)
        self.canvas.bind('<Shift-ButtonRelease-1>', self._on_pan_end)

        # Arrow key bindings for panning (window level for global capture)
        self.window.bind('<Up>', self._on_pan_up)
        self.window.bind('<Down>', self._on_pan_down)
        self.window.bind('<Left>', self._on_pan_left)
        self.window.bind('<Right>', self._on_pan_right)

        # WASD keys for panning
        self.window.bind('<w>', self._on_pan_up)
        self.window.bind('<W>', self._on_pan_up)
        self.window.bind('<s>', self._on_pan_down)
        self.window.bind('<S>', self._on_pan_down)
        self.window.bind('<a>', self._on_pan_left)
        self.window.bind('<A>', self._on_pan_left)
        self.window.bind('<d>', self._on_pan_right)
        self.window.bind('<D>', self._on_pan_right)

        # Mouse wheel zoom
        self.canvas.bind('<MouseWheel>', self._on_mouse_wheel)  # Windows
        self.canvas.bind('<Control-MouseWheel>', self._on_ctrl_mouse_wheel)  # Ctrl+Scroll = floor

        # Undo/Redo shortcuts
        self.window.bind('<Control-z>', self._undo)
        self.window.bind('<Control-Z>', self._undo)
        self.window.bind('<Control-y>', self._redo)
        self.window.bind('<Control-Y>', self._redo)

        # Escape to cancel insert mode
        self.window.bind('<Escape>', lambda e: self._cancel_insert_mode())

        # Window close handler for cleanup
        self.window.protocol('WM_DELETE_WINDOW', self._on_window_close)

        # Set initial focus to canvas to enable arrow key panning
        self.canvas.focus_set()

        # RIGHT: Control Panel
        right_frame = ttk.Frame(main_frame, width=300)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, padx=5, pady=5)
        right_frame.pack_propagate(False)

        # Waypoint list
        list_label = ttk.Label(right_frame, text="Lista de Waypoints:")
        list_label.pack(anchor=tk.W, pady=(5, 2))

        list_frame = ttk.Frame(right_frame)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=2)

        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.waypoint_listbox = tk.Listbox(
            list_frame,
            yscrollcommand=scrollbar.set,
            height=10
        )
        self.waypoint_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.waypoint_listbox.bind('<<ListboxSelect>>', self._on_waypoint_select)
        scrollbar.config(command=self.waypoint_listbox.yview)

        # Waypoint controls
        controls_frame = ttk.Frame(right_frame)
        controls_frame.pack(fill=tk.X, pady=5)

        ttk.Button(controls_frame, text="↑ Subir", command=self._move_waypoint_up).pack(fill=tk.X, pady=2)
        ttk.Button(controls_frame, text="↓ Descer", command=self._move_waypoint_down).pack(fill=tk.X, pady=2)
        ttk.Button(controls_frame, text="➕ Inserir Após", command=self._start_insert_after_mode).pack(fill=tk.X, pady=2)
        ttk.Button(controls_frame, text="❌ Remover", command=self._remove_selected_waypoint).pack(fill=tk.X, pady=2)

        # Floor selector with buttons
        floor_frame = ttk.LabelFrame(right_frame, text="Andar (Nível Z)")
        floor_frame.pack(fill=tk.X, pady=5)

        # Container for floor controls
        floor_controls = ttk.Frame(floor_frame)
        floor_controls.pack(padx=5, pady=5)

        # Up button
        ttk.Button(floor_controls, text="▲", width=3, command=self._floor_up).pack(side=tk.LEFT, padx=2)

        # Floor display label
        self.floor_label = ttk.Label(floor_controls, text=f"Andar: {self.current_floor}", width=10, anchor=tk.CENTER)
        self.floor_label.pack(side=tk.LEFT, padx=5)

        # Down button
        ttk.Button(floor_controls, text="▼", width=3, command=self._floor_down).pack(side=tk.LEFT, padx=2)

        # File operations
        file_frame = ttk.LabelFrame(right_frame, text="Operações de Arquivo")
        file_frame.pack(fill=tk.X, pady=5)

        ttk.Button(file_frame, text="📂 Carregar JSON", command=self._load_waypoints).pack(fill=tk.X, padx=5, pady=2)
        ttk.Button(file_frame, text="💾 Salvar JSON", command=self._save_waypoints).pack(fill=tk.X, padx=5, pady=2)
        ttk.Button(file_frame, text="🔄 Sincronizar com Bot", command=self._sync_to_bot).pack(fill=tk.X, padx=5, pady=2)

        # Status bar
        status_frame = ttk.Frame(right_frame)
        status_frame.pack(fill=tk.X, pady=5)

        self.status_label = ttk.Label(
            status_frame,
            text=f"Waypoints: 0 | Andar: {self.current_floor} | Coords: ({self.viewport_center_x}, {self.viewport_center_y})",
            relief=tk.SUNKEN
        )
        self.status_label.pack(fill=tk.X)

        # Close button
        ttk.Button(right_frame, text="❌ Fechar", command=self.window.destroy).pack(fill=tk.X, pady=5)

    def _render_map_async(self):
        """Queue async map rendering in background thread."""
        self._pending_render = True
        if self._render_thread is None or not self._render_thread.is_alive():
            self._render_thread = threading.Thread(target=self._render_map_thread, daemon=True)
            self._render_thread.start()

    def _render_map_thread(self):
        """Background thread for map rendering (non-blocking)."""
        while not self._stop_render_thread:
            if self._pending_render:
                self._pending_render = False
                try:
                    self._render_map_sync()
                    # Notify main thread to update display after render completes
                    if self.window.winfo_exists():
                        self.window.after(0, self._update_display)
                except Exception as e:
                    print(f"Error in render thread: {e}")
            time.sleep(0.016)  # ~60 FPS polling

    def _render_map_sync(self):
        """Synchronously render the map (called from background thread)."""
        try:
            min_x = int(self.viewport_center_x - self.viewport_radius)
            max_x = int(self.viewport_center_x + self.viewport_radius)
            min_y = int(self.viewport_center_y - self.viewport_radius)
            max_y = int(self.viewport_center_y + self.viewport_radius)

            # Cache viewport bounds for coordinate conversion
            self.viewport_min_x = min_x
            self.viewport_min_y = min_y

            # Create image with pixels_per_tile scaling
            img_width = (max_x - min_x + 1) * self.pixels_per_tile
            img_height = (max_y - min_y + 1) * self.pixels_per_tile

            map_image = Image.new('RGB', (img_width, img_height), color=(10, 10, 10))
            pixels = map_image.load()

            # Fill with map data, each tile = pixels_per_tile x pixels_per_tile
            # Read in chunks to improve cache locality
            chunk_size = 16  # Read 16x16 tiles at a time
            for chunk_x in range(min_x, max_x + 1, chunk_size):
                for chunk_y in range(min_y, max_y + 1, chunk_size):
                    chunk_end_x = min(chunk_x + chunk_size, max_x + 1)
                    chunk_end_y = min(chunk_y + chunk_size, max_y + 1)

                    for abs_x in range(chunk_x, chunk_end_x):
                        for abs_y in range(chunk_y, chunk_end_y):
                            color_id = self.global_map.get_color_id(abs_x, abs_y, self.current_floor)
                            rgb = self._color_id_to_rgb(color_id)

                            # Draw pixels_per_tile x pixels_per_tile square for this tile
                            start_px = (abs_x - min_x) * self.pixels_per_tile
                            start_py = (abs_y - min_y) * self.pixels_per_tile

                            for px in range(self.pixels_per_tile):
                                for py in range(self.pixels_per_tile):
                                    if start_px + px < img_width and start_py + py < img_height:
                                        pixels[start_px + px, start_py + py] = rgb

            # Thread-safe update of map image
            with self._map_data_lock:
                self.map_image = map_image

        except Exception as e:
            print(f"Error rendering map: {e}")
            with self._map_data_lock:
                self.map_image = Image.new('RGB', (self.canvas_width, self.canvas_height), color=(50, 50, 50))

    def _return_focus_to_canvas(self):
        """Return keyboard focus to canvas for arrow key panning."""
        self.canvas.focus_set()
        return 'break'  # Stop event propagation

    def _on_window_close(self):
        """Handle window close - cleanup threads."""
        self._stop_render_thread = True
        if self._render_thread and self._render_thread.is_alive():
            self._render_thread.join(timeout=1.0)
        self.window.destroy()

    def _schedule_display_update(self):
        """Schedule periodic check for completed async renders."""
        try:
            # Refresh display if map image updated
            self._update_display()

            # Schedule next check (50ms for smoother updates)
            self.window.after(50, self._schedule_display_update)
        except Exception:
            pass  # Window might be closing

    def _color_id_to_rgb(self, color_id):
        """Convert Tibia color ID to RGB tuple."""
        return get_color(color_id)

    def _game_to_canvas_coords(self, abs_x, abs_y):
        """Convert game coordinates to canvas pixel coordinates."""
        # Convert to image coordinates
        img_x = (abs_x - self.viewport_min_x) * self.pixels_per_tile
        img_y = (abs_y - self.viewport_min_y) * self.pixels_per_tile

        # Convert to canvas coordinates (account for crop offset)
        canvas_x = img_x - self.image_crop_offset_x
        canvas_y = img_y - self.image_crop_offset_y

        return canvas_x, canvas_y

    def _canvas_to_game_coords(self, canvas_x, canvas_y):
        """Convert canvas pixel coordinates to game coordinates."""
        # Convert from canvas to image coordinates
        img_x = canvas_x + self.image_crop_offset_x
        img_y = canvas_y + self.image_crop_offset_y

        # Convert from image pixels to game tiles
        rel_x = img_x / self.pixels_per_tile
        rel_y = img_y / self.pixels_per_tile

        abs_x = int(rel_x + self.viewport_min_x)
        abs_y = int(rel_y + self.viewport_min_y)

        return abs_x, abs_y

    def _find_waypoint_at_canvas_pos(self, canvas_x, canvas_y, tolerance_pixels=12):
        """
        Detect if click is on an existing waypoint.

        Args:
            canvas_x, canvas_y: Canvas pixel coordinates
            tolerance_pixels: Click tolerance in pixels

        Returns:
            Index of waypoint if found, None otherwise
        """
        abs_x, abs_y = self._canvas_to_game_coords(canvas_x, canvas_y)
        tolerance_tiles = tolerance_pixels / self.pixels_per_tile

        closest_idx = None
        min_dist = tolerance_tiles

        for i, wp in enumerate(self.waypoints):
            if wp['z'] != self.current_floor:
                continue
            dist = max(abs(wp['x'] - abs_x), abs(wp['y'] - abs_y))
            if dist < min_dist:
                min_dist = dist
                closest_idx = i

        return closest_idx

    def _on_canvas_click(self, event):
        """Handle left-click - insert mode, start drag, or add waypoint."""
        # Verificar se está em modo de inserção
        if self._insert_after_idx is not None:
            abs_x, abs_y = self._canvas_to_game_coords(event.x, event.y)
            new_wp = {"action": "walk", "x": abs_x, "y": abs_y, "z": self.current_floor}

            # Salvar estado para undo
            self._save_undo_state(f"Inserir WP #{self._insert_after_idx + 2}")

            # Inserir após o índice selecionado
            insert_pos = self._insert_after_idx + 1
            self.waypoints.insert(insert_pos, new_wp)

            # Sair do modo de inserção
            self._insert_after_idx = None
            self.canvas.config(cursor='crosshair')

            self._update_display()
            self._show_status(f"✅ WP #{insert_pos + 1} inserido em ({abs_x}, {abs_y})")
            return

        # Check if clicking on existing waypoint
        wp_idx = self._find_waypoint_at_canvas_pos(event.x, event.y)

        if wp_idx is not None:
            # Start dragging existing waypoint
            self._dragging_waypoint_idx = wp_idx
            self.selected_waypoint_idx = wp_idx
            self.canvas.config(cursor='hand2')
            # Salvar estado para undo ANTES de começar a arrastar
            self._save_undo_state(f"Mover WP #{wp_idx + 1}")
            self._show_status(f"🖐️ Arrastando waypoint #{wp_idx + 1}...")
        else:
            # Add new waypoint
            abs_x, abs_y = self._canvas_to_game_coords(event.x, event.y)
            abs_z = self.current_floor

            # Salvar estado para undo
            self._save_undo_state(f"Adicionar WP #{len(self.waypoints) + 1}")

            new_wp = {"action": "walk", "x": abs_x, "y": abs_y, "z": abs_z}
            self.waypoints.append(new_wp)

            self._update_display()
            self._show_status(f"✅ Waypoint #{len(self.waypoints)} adicionado: ({abs_x}, {abs_y}, {abs_z})")

    def _on_canvas_drag(self, event):
        """Handle mouse drag - move waypoint in real-time."""
        if self._dragging_waypoint_idx is None:
            return

        # Update waypoint position in real-time
        abs_x, abs_y = self._canvas_to_game_coords(event.x, event.y)
        self.waypoints[self._dragging_waypoint_idx]['x'] = abs_x
        self.waypoints[self._dragging_waypoint_idx]['y'] = abs_y

        # Redraw overlay only (faster than full render)
        self._draw_waypoints_overlay()
        self._show_status(f"📍 Movendo WP #{self._dragging_waypoint_idx + 1} para ({abs_x}, {abs_y})")

    def _on_canvas_release(self, event):
        """Handle mouse release - finish waypoint drag."""
        del event
        if self._dragging_waypoint_idx is not None:
            wp = self.waypoints[self._dragging_waypoint_idx]
            self._show_status(f"✅ WP #{self._dragging_waypoint_idx + 1} movido para ({wp['x']}, {wp['y']})")
            self._dragging_waypoint_idx = None
            self.canvas.config(cursor='crosshair')
            self._update_display()

    def _on_canvas_right_click(self, event):
        """Handle right-click to remove waypoint or cancel insert mode."""
        # Cancelar modo de inserção se ativo
        if self._insert_after_idx is not None:
            self._cancel_insert_mode()
            return

        abs_x, abs_y = self._canvas_to_game_coords(event.x, event.y)

        # Find closest waypoint on current floor
        closest_idx = None
        min_dist = 5  # Tolerance in tiles (Chebyshev distance)

        for i, wp in enumerate(self.waypoints):
            if wp['z'] != self.current_floor:
                continue

            dist = max(abs(wp['x'] - abs_x), abs(wp['y'] - abs_y))
            if dist < min_dist:
                min_dist = dist
                closest_idx = i

        if closest_idx is not None:
            # Salvar estado para undo
            self._save_undo_state(f"Remover WP #{closest_idx + 1}")
            self.waypoints.pop(closest_idx)
            self._update_display()
            self._show_status(f"🗑️ Waypoint #{closest_idx+1} removido")
        else:
            self._show_status("⚠️ Nenhum waypoint próximo (dentro de 5 tiles)")

    # ==================== PANNING METHODS ====================

    def _on_pan_start(self, event):
        """Start pan operation (Shift+Click)."""
        self._is_panning = True
        self._pan_start_x = event.x
        self._pan_start_y = event.y
        self._pan_viewport_start_x = self.viewport_center_x
        self._pan_viewport_start_y = self.viewport_center_y
        self.canvas.config(cursor='fleur')

    def _on_pan_drag(self, event):
        """Handle pan dragging - update viewport in real-time."""
        if not self._is_panning:
            return

        # Calculate pixel delta and convert to tiles (inverse for intuitive pan)
        dx_tiles = -(event.x - self._pan_start_x) / self.pixels_per_tile
        dy_tiles = -(event.y - self._pan_start_y) / self.pixels_per_tile

        # Update viewport center
        self.viewport_center_x = int(self._pan_viewport_start_x + dx_tiles)
        self.viewport_center_y = int(self._pan_viewport_start_y + dy_tiles)

        # Queue async render
        self._render_map_async()

        # Update waypoints overlay immediately for visual feedback during drag
        self._draw_waypoints_overlay()

    def _on_pan_end(self, event):
        """End pan operation."""
        del event
        self._is_panning = False
        self.canvas.config(cursor='crosshair')

    def _on_pan_up(self, event):
        """Handle up arrow/W to pan map up."""
        del event  # Unused, but required by binding
        self.viewport_center_y -= 5
        self._render_map_async()
        # _update_display será chamado automaticamente após render completar

    def _on_pan_down(self, event):
        """Handle down arrow/S to pan map down."""
        del event
        self.viewport_center_y += 5
        self._render_map_async()

    def _on_pan_left(self, event):
        """Handle left arrow/A to pan map left."""
        del event
        self.viewport_center_x -= 5
        self._render_map_async()

    def _on_pan_right(self, event):
        """Handle right arrow/D to pan map right."""
        del event
        self.viewport_center_x += 5
        self._render_map_async()

    def _on_canvas_motion(self, event):
        """Handle mouse motion to show coordinates."""
        abs_x, abs_y = self._canvas_to_game_coords(event.x, event.y)
        self._show_status(f"Waypoints: {len(self.waypoints)} | Andar: {self.current_floor} | Coords: ({abs_x}, {abs_y})")

    # ==================== ZOOM METHODS ====================

    def _on_mouse_wheel(self, event):
        """Zoom in/out com scroll do mouse."""
        if event.delta > 0:
            self._zoom_in()
        else:
            self._zoom_out()

    def _on_ctrl_mouse_wheel(self, event):
        """Mudar andar com Ctrl+Scroll."""
        if event.delta > 0:
            self._floor_up()
        else:
            self._floor_down()

    def _zoom_in(self):
        """Aumentar zoom (mais pixels/tile)."""
        if self.current_zoom_idx < len(self.zoom_levels) - 1:
            self.current_zoom_idx += 1
            self.pixels_per_tile = self.zoom_levels[self.current_zoom_idx]
            # Ajustar viewport_radius inversamente
            self.viewport_radius = int(90 * 4 / self.pixels_per_tile)
            self._render_map_async()
            self._show_status(f"🔍 Zoom: {self.pixels_per_tile}x")

    def _zoom_out(self):
        """Diminuir zoom (menos pixels/tile)."""
        if self.current_zoom_idx > 0:
            self.current_zoom_idx -= 1
            self.pixels_per_tile = self.zoom_levels[self.current_zoom_idx]
            self.viewport_radius = int(90 * 4 / self.pixels_per_tile)
            self._render_map_async()
            self._show_status(f"🔍 Zoom: {self.pixels_per_tile}x")

    # ==================== INSERT MODE METHODS ====================

    def _start_insert_after_mode(self):
        """Ativa modo de inserção após waypoint selecionado."""
        if self.selected_waypoint_idx is None:
            self._show_status("⚠️ Selecione um waypoint primeiro")
            return

        self._insert_after_idx = self.selected_waypoint_idx
        self.canvas.config(cursor='plus')
        self._show_status(f"🎯 Clique no mapa para inserir após WP #{self._insert_after_idx + 1}")

    def _cancel_insert_mode(self):
        """Cancela modo de inserção."""
        if self._insert_after_idx is not None:
            self._insert_after_idx = None
            self.canvas.config(cursor='crosshair')
            self._show_status("❌ Inserção cancelada")

    # ==================== UNDO/REDO METHODS ====================

    def _save_undo_state(self, description=""):
        """Salva estado atual na pilha de undo."""
        snapshot = [wp.copy() for wp in self.waypoints]
        self._undo_stack.append((snapshot, description))

        # Limitar tamanho da pilha
        if len(self._undo_stack) > self._max_history:
            self._undo_stack.pop(0)

        # Limpar redo stack (nova ação invalida redo)
        self._redo_stack.clear()

    def _undo(self, event=None):
        """Desfaz última ação."""
        del event
        if not self._undo_stack:
            self._show_status("⚠️ Nada para desfazer")
            return

        # Salvar estado atual no redo
        current = [wp.copy() for wp in self.waypoints]
        self._redo_stack.append((current, "redo"))

        # Restaurar estado anterior
        snapshot, desc = self._undo_stack.pop()
        self.waypoints = snapshot
        self.selected_waypoint_idx = None
        self._last_waypoint_count = -1  # Forçar rebuild da lista

        self._update_display()
        self._show_status(f"↩️ Desfeito: {desc}" if desc else "↩️ Desfeito")

    def _redo(self, event=None):
        """Refaz última ação desfeita."""
        del event
        if not self._redo_stack:
            self._show_status("⚠️ Nada para refazer")
            return

        # Salvar estado atual no undo
        current = [wp.copy() for wp in self.waypoints]
        self._undo_stack.append((current, "undo"))

        # Restaurar estado redo
        snapshot, _ = self._redo_stack.pop()
        self.waypoints = snapshot
        self.selected_waypoint_idx = None
        self._last_waypoint_count = -1

        self._update_display()
        self._show_status("↪️ Refeito")

    def _floor_up(self):
        """Increase floor level."""
        if self.current_floor < 15:
            self.current_floor += 1
            self.floor_label.config(text=f"Andar: {self.current_floor}")
            self._show_status(f"⏳ Carregando andar {self.current_floor}...")
            self._render_map_async()
            self._update_display()

    def _floor_down(self):
        """Decrease floor level."""
        if self.current_floor > 0:
            self.current_floor -= 1
            self.floor_label.config(text=f"Andar: {self.current_floor}")
            self._show_status(f"⏳ Carregando andar {self.current_floor}...")
            self._render_map_async()
            self._update_display()

    def _on_waypoint_select(self, event):
        """Handle waypoint selection in listbox."""
        del event  # Unused but required by binding
        selection = self.waypoint_listbox.curselection()
        if selection:
            self.selected_waypoint_idx = selection[0]
            wp = self.waypoints[self.selected_waypoint_idx]

            # Center viewport on selected waypoint if on same floor
            if wp['z'] == self.current_floor:
                self.viewport_center_x = wp['x']
                self.viewport_center_y = wp['y']
                self._render_map_async()
            else:
                # Switch floor if waypoint is on different floor
                self.current_floor = wp['z']
                self.floor_label.config(text=f"Andar: {self.current_floor}")
                self.viewport_center_x = wp['x']
                self.viewport_center_y = wp['y']
                self._show_status(f"⏳ Carregando andar {self.current_floor}...")
                self._render_map_async()

        self._update_display()

    def _move_waypoint_up(self):
        """Move selected waypoint up in the list."""
        if self.selected_waypoint_idx is not None and self.selected_waypoint_idx > 0:
            idx = self.selected_waypoint_idx
            # Salvar estado para undo
            self._save_undo_state(f"Subir WP #{idx + 1}")
            self.waypoints[idx], self.waypoints[idx-1] = self.waypoints[idx-1], self.waypoints[idx]
            self.selected_waypoint_idx = idx - 1
            self._should_scroll_to_selection = True  # Enable auto-scroll after move
            self._update_display()
            self.waypoint_listbox.selection_clear(0, tk.END)
            self.waypoint_listbox.selection_set(self.selected_waypoint_idx)

    def _move_waypoint_down(self):
        """Move selected waypoint down in the list."""
        if self.selected_waypoint_idx is not None and self.selected_waypoint_idx < len(self.waypoints) - 1:
            idx = self.selected_waypoint_idx
            # Salvar estado para undo
            self._save_undo_state(f"Descer WP #{idx + 1}")
            self.waypoints[idx], self.waypoints[idx+1] = self.waypoints[idx+1], self.waypoints[idx]
            self.selected_waypoint_idx = idx + 1
            self._should_scroll_to_selection = True  # Enable auto-scroll after move
            self._update_display()
            self.waypoint_listbox.selection_clear(0, tk.END)
            self.waypoint_listbox.selection_set(self.selected_waypoint_idx)

    def _remove_selected_waypoint(self):
        """Remove the selected waypoint."""
        if self.selected_waypoint_idx is not None:
            idx = self.selected_waypoint_idx
            # Salvar estado para undo
            self._save_undo_state(f"Remover WP #{idx + 1}")
            self.waypoints.pop(idx)
            self.selected_waypoint_idx = None
            self._update_display()

    def _update_display(self):
        """Update canvas and waypoint list display."""
        # Render map to canvas
        if self.map_image:
            # Crop to canvas size if image is larger
            img_to_display = self.map_image
            self.image_crop_offset_x = 0
            self.image_crop_offset_y = 0

            if self.map_image.width > self.canvas_width or self.map_image.height > self.canvas_height:
                # Center crop to canvas size
                left = max(0, (self.map_image.width - self.canvas_width) // 2)
                top = max(0, (self.map_image.height - self.canvas_height) // 2)
                right = min(self.map_image.width, left + self.canvas_width)
                bottom = min(self.map_image.height, top + self.canvas_height)

                # Track how much we cropped (in pixels)
                self.image_crop_offset_x = left
                self.image_crop_offset_y = top

                img_to_display = self.map_image.crop((left, top, right, bottom))

            # Use ImageTk for display
            from PIL import ImageTk
            self.canvas_photo = ImageTk.PhotoImage(img_to_display)
            self.canvas.delete('all')
            self.canvas.create_image(self.canvas_width // 2, self.canvas_height // 2, image=self.canvas_photo)

        # Draw waypoints and route
        self._draw_waypoints_overlay()

        # Only rebuild waypoint list if the count changed (avoid resetting scroll position)
        if len(self.waypoints) != self._last_waypoint_count:
            self._last_waypoint_count = len(self.waypoints)

            self.waypoint_listbox.delete(0, tk.END)
            for i, wp in enumerate(self.waypoints):
                floor_indicator = "" if wp['z'] == self.current_floor else f" [Z:{wp['z']}]"
                self.waypoint_listbox.insert(tk.END, f"#{i+1}: ({wp['x']}, {wp['y']}, {wp['z']}){floor_indicator}")

        # Highlight selected
        if self.selected_waypoint_idx is not None and 0 <= self.selected_waypoint_idx < len(self.waypoints):
            self.waypoint_listbox.selection_set(self.selected_waypoint_idx)
            # Only auto-scroll when explicitly requested (not on every update)
            if self._should_scroll_to_selection:
                self.waypoint_listbox.see(self.selected_waypoint_idx)
                self._should_scroll_to_selection = False

        # Update status
        self._show_status(f"Waypoints: {len(self.waypoints)} | Andar: {self.current_floor}")

    def _draw_waypoints_overlay(self):
        """Draw waypoint markers and route on canvas."""
        self.canvas.delete('waypoint')

        # Filter waypoints on current floor
        visible_wps = [(i, wp) for i, wp in enumerate(self.waypoints) if wp['z'] == self.current_floor]

        if not visible_wps:
            return

        # Draw connecting line
        if len(visible_wps) >= 2:
            points = []
            for i, wp in visible_wps:
                cx, cy = self._game_to_canvas_coords(wp['x'], wp['y'])
                points.extend([cx, cy])

            if len(points) >= 4:
                self.canvas.create_line(
                    points,
                    fill='cyan',
                    width=2,
                    tags='waypoint',
                    dash=(5, 5)
                )

        # Draw waypoint circles with selection/drag highlighting
        for i, wp in visible_wps:
            cx, cy = self._game_to_canvas_coords(wp['x'], wp['y'])

            is_selected = i == self.selected_waypoint_idx
            is_dragging = i == self._dragging_waypoint_idx

            # Visual properties based on state
            if is_dragging:
                radius = 10
                color = '#00FF00'  # Green while dragging
                outline_color = 'white'
                outline_width = 3
            elif is_selected:
                radius = 8
                color = '#FF1493'  # Pink for selected
                outline_color = 'white'
                outline_width = 3
            else:
                radius = 6
                color = 'orange'
                outline_color = 'gray'
                outline_width = 2

            self.canvas.create_oval(
                cx - radius, cy - radius,
                cx + radius, cy + radius,
                fill=color,
                outline=outline_color,
                width=outline_width,
                tags='waypoint'
            )

            # Draw number
            text_color = 'white' if (is_dragging or is_selected) else 'black'
            self.canvas.create_text(
                cx, cy,
                text=str(i + 1),
                fill=text_color,
                font=('Arial', 9, 'bold'),
                tags='waypoint'
            )

    def _load_waypoints(self):
        """Load waypoints from JSON file."""
        file_path = filedialog.askopenfilename(
            title='Carregar Waypoints',
            filetypes=[('Arquivos JSON', '*.json'), ('Todos os arquivos', '*.*')],
            initialdir='cavebot_scripts'
        )

        if not file_path:
            return

        try:
            # Salvar estado atual para undo (antes de carregar)
            if self.waypoints:
                self._save_undo_state("Carregar arquivo")

            with open(file_path, 'r') as f:
                self.waypoints = json.load(f)

            if self.waypoints:
                # Center on first waypoint
                first_wp = self.waypoints[0]
                self.viewport_center_x = first_wp['x']
                self.viewport_center_y = first_wp['y']
                self.current_floor = first_wp['z']
                self.floor_label.config(text=f"Andar: {self.current_floor}")
                self._show_status(f"⏳ Carregando waypoints...")
                self._render_map_async()

            self._update_display()
            self._show_status(f"✅ {len(self.waypoints)} waypoints carregados de {Path(file_path).name}")
        except Exception as e:
            messagebox.showerror('Erro', f'Falha ao carregar waypoints: {e}')
            self._show_status('❌ Falha ao carregar')

    def _save_waypoints(self):
        """Save waypoints to JSON file."""
        if not self.waypoints:
            messagebox.showwarning('Aviso', 'Nenhum waypoint para salvar')
            return

        file_path = filedialog.asksaveasfilename(
            title='Salvar Waypoints',
            filetypes=[('Arquivos JSON', '*.json'), ('Todos os arquivos', '*.*')],
            initialdir='cavebot_scripts',
            defaultextension='.json'
        )

        if not file_path:
            return

        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(file_path) or '.', exist_ok=True)

            with open(file_path, 'w') as f:
                json.dump(self.waypoints, f, indent=2)

            self._show_status(f"✅ {len(self.waypoints)} waypoints salvos em {Path(file_path).name}")
        except Exception as e:
            messagebox.showerror('Erro', f'Falha ao salvar waypoints: {e}')
            self._show_status('❌ Falha ao salvar')

    def _sync_to_bot(self):
        """Send waypoints to bot via callback."""
        if not self.waypoints:
            messagebox.showwarning('Aviso', 'Nenhum waypoint para sincronizar')
            return

        if self.on_save_callback:
            try:
                self.on_save_callback(self.waypoints)
                self._show_status(f"✅ {len(self.waypoints)} waypoints sincronizados com o bot")
            except Exception as e:
                messagebox.showerror('Erro', f'Falha ao sincronizar: {e}')
                self._show_status('❌ Falha na sincronização')
        else:
            messagebox.showinfo('Info', f'{len(self.waypoints)} waypoints prontos para uso')
            self._show_status('✅ Waypoints prontos')

    def _show_status(self, message):
        """Update status bar message."""
        self.status_label.config(text=message)


if __name__ == '__main__':
    # Test the editor
    root = tk.Tk()
    root.withdraw()  # Hide main window

    editor = WaypointEditorWindow(
        parent_window=root,
        maps_directory=MAPS_DIRECTORY,
        current_waypoints=[
            {"action": "walk", "x": 32082, "y": 32153, "z": 7},
            {"action": "walk", "x": 32091, "y": 32147, "z": 7},
            {"action": "walk", "x": 32095, "y": 32140, "z": 7},
        ],
        current_pos=(32082, 32153, 7)
    )

    root.mainloop()
