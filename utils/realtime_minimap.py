"""
Real-Time Minimap Visualizer for Cavebot
Generates minimap images with optimized caching for high-frequency updates
"""

import os
from PIL import Image
from collections import defaultdict, OrderedDict


class RealtimeMinimapVisualizer:
    """
    Generates real-time minimap visualizations with performance-critical caching.

    Separates terrain rendering (expensive, cached) from overlay drawing (fast, every update).
    This achieves 10-20x performance improvement for real-time updates.
    """

    def __init__(self, maps_dir, walkable_colors, color_palette, fixed_size=150):
        """
        Initialize the minimap visualizer.

        Args:
            maps_dir: Directory containing .map chunk files
            walkable_colors: Set or list of IDs that are walkable
            color_palette: Dict mapping byte values to RGB tuples
            fixed_size: Fixed size in pixels for the minimap (always 150x150)
        """
        self.maps_dir = maps_dir
        self.walkable_colors = set(walkable_colors)
        self.color_palette = color_palette
        self.default_color = (80, 80, 80)
        self.fixed_size = fixed_size  # Fixed image size (always 150x150)

        # === MEMORY OPTIMIZATION: LRU caches com limite ===
        # Cache of rendered base maps (terrain layer only)
        # Key: (floor_z, min_x, min_y, max_x, max_y) -> PIL.Image
        self.base_map_cache = OrderedDict()
        self._base_map_cache_max = 20  # ~3 MB max (150x150 RGB = ~68 KB each)

        # Cache of raw chunk data from disk
        # Key: (cx, cy, z) -> bytes
        self.chunk_cache = OrderedDict()
        self._chunk_cache_max = 50  # ~3.2 MB max (64 KB each)

    def generate_minimap(self, player_pos, target_wp, all_waypoints,
                        global_route=None, local_cache=None, current_wp_index=None,
                        enable_dynamic_zoom=True):
        """
        Generate a real-time minimap image.

        Args:
            player_pos: (x, y, z) current player position
            target_wp: {'x': int, 'y': int, 'z': int} current target waypoint
            all_waypoints: List of all configured waypoints
            global_route: [(x, y, z), ...] global path (optional)
            local_cache: [(dx, dy), ...] local A* steps (optional)
            current_wp_index: Index of current target waypoint (optional)
            enable_dynamic_zoom: If True, shows only nearby waypoints (WP n-2 to n+1).
                                If False, shows all waypoints on floor (full view).
                                Default: True

        Returns:
            PIL.Image: Minimap image ready for display
        """
        px, py, pz = player_pos

        # Step 1: Get waypoints for current floor
        floor_waypoints = [wp for wp in all_waypoints if wp['z'] == pz]

        if not floor_waypoints:
            return self._create_placeholder_image()

        # Step 2: Calculate bounding box (ZOOM mode if enabled and index provided)
        if enable_dynamic_zoom and current_wp_index is not None:
            bbox = self._calculate_zoom_bbox(all_waypoints, player_pos, current_wp_index, margin=12)
        else:
            bbox = self._calculate_bbox(floor_waypoints, player_pos, padding=30)

        # Step 3: Get base map (cached or render new) with dynamic zoom
        base_img, pixels_per_tile = self._get_base_map(pz, bbox)

        # Step 4: Create copy for overlay drawing
        overlay_img = base_img.copy()

        # Step 5: Draw overlays in order (background to foreground)
        self._draw_all_waypoints(overlay_img, floor_waypoints, bbox, pixels_per_tile)
        self._draw_floor_transitions(overlay_img, all_waypoints, pz, bbox, pixels_per_tile)

        if global_route:
            self._draw_global_route(overlay_img, global_route, pz, bbox, pixels_per_tile)

        if local_cache:
            self._draw_local_cache(overlay_img, player_pos, local_cache, bbox, pixels_per_tile)

        self._draw_current_target(overlay_img, target_wp, bbox, pixels_per_tile)
        self._draw_player_position(overlay_img, player_pos, bbox, pixels_per_tile)

        return overlay_img

    # ========== CACHE METHODS (Performance-Critical) ==========

    def _get_base_map(self, floor_z, bbox):
        """
        Get cached base map or render new one.
        Uses LRU eviction to limit memory usage.

        Returns tuple: (image_copy, pixels_per_tile)
        """
        cache_key = (floor_z, *bbox)

        if cache_key in self.base_map_cache:
            # Move to end (most recently used)
            self.base_map_cache.move_to_end(cache_key)
            img, ppt = self.base_map_cache[cache_key]
        else:
            img, ppt = self._render_base_terrain(floor_z, bbox)
            self.base_map_cache[cache_key] = (img, ppt)

            # LRU eviction: remove oldest entries if over limit
            while len(self.base_map_cache) > self._base_map_cache_max:
                self.base_map_cache.popitem(last=False)

        return img.copy(), ppt

    def _calculate_pixels_per_tile(self, tile_width, tile_height):
        """
        Calculate pixels_per_tile to fit bbox into fixed_size.
        Uses the larger dimension to ensure everything fits in the square.
        """
        max_tiles = max(tile_width, tile_height)
        return self.fixed_size / max_tiles

    def _render_base_terrain(self, floor_z, bbox):
        """
        Render the terrain layer (base map without overlays).
        This is the expensive operation that we cache.

        Returns tuple: (image, pixels_per_tile)
        """
        min_x, min_y, max_x, max_y = bbox
        tile_width = max_x - min_x + 1
        tile_height = max_y - min_y + 1

        # Calculate pixels_per_tile to fit in fixed_size
        pixels_per_tile = self._calculate_pixels_per_tile(tile_width, tile_height)

        # FIXED SIZE: always fixed_size x fixed_size (150x150)
        img = Image.new('RGB', (self.fixed_size, self.fixed_size), (0, 0, 0))
        pixels = img.load()

        # Calculate which chunks are needed
        start_cx, end_cx = min_x // 256, max_x // 256
        start_cy, end_cy = min_y // 256, max_y // 256

        # Load and render each chunk
        for cx in range(start_cx, end_cx + 1):
            for cy in range(start_cy, end_cy + 1):
                chunk_data = self._load_chunk(cx, cy, floor_z)
                if chunk_data:
                    self._render_chunk_to_image(pixels, chunk_data, cx, cy, bbox, pixels_per_tile)

        return img, pixels_per_tile

    def _load_chunk(self, cx, cy, z):
        """Load chunk from disk (with LRU cache)."""
        cache_key = (cx, cy, z)

        if cache_key in self.chunk_cache:
            # Move to end (most recently used)
            self.chunk_cache.move_to_end(cache_key)
            return self.chunk_cache[cache_key]

        # Try both filename formats
        filenames = [f"{cx:03}{cy:03}{z:02}.map", f"{cx}{cy}{z:02}.map"]

        for fname in filenames:
            path = os.path.join(self.maps_dir, fname)
            if os.path.exists(path):
                try:
                    with open(path, "rb") as f:
                        data = f.read()
                    self.chunk_cache[cache_key] = data

                    # LRU eviction: remove oldest entries if over limit
                    while len(self.chunk_cache) > self._chunk_cache_max:
                        self.chunk_cache.popitem(last=False)

                    return data
                except Exception as e:
                    print(f"[Minimap] Error loading chunk {fname}: {e}")
                    return None

        return None

    def _render_chunk_to_image(self, pixels, chunk_data, cx, cy, bbox, pixels_per_tile):
        """
        Render a single 256x256 chunk to the image pixels.
        Only renders pixels within the bounding box.
        Supports fractional pixels_per_tile for dynamic zoom.
        """
        min_x, min_y, max_x, max_y = bbox
        base_x = cx * 256
        base_y = cy * 256

        for i, byte_val in enumerate(chunk_data):
            if byte_val == 0:  # Skip empty pixels
                continue

            # Calculate absolute coordinates
            tile_x = base_x + (i // 256)
            tile_y = base_y + (i % 256)

            # Only render if within bounding box
            if min_x <= tile_x <= max_x and min_y <= tile_y <= max_y:
                # Convert to image coordinates (in tiles)
                rel_tile_x = tile_x - min_x
                rel_tile_y = tile_y - min_y

                # Get color for this tile
                base_color = self.color_palette.get(byte_val, self.default_color)

                # Reduce saturation/brightness to make overlays stand out
                # Apply 60% brightness to terrain tiles
                color = tuple(int(c * 0.6) for c in base_color)

                # Calculate pixel range for this tile (handles fractional pixels_per_tile)
                start_px = int(rel_tile_x * pixels_per_tile)
                start_py = int(rel_tile_y * pixels_per_tile)
                end_px = int((rel_tile_x + 1) * pixels_per_tile)
                end_py = int((rel_tile_y + 1) * pixels_per_tile)

                # Draw pixel block for this tile (at least 1 pixel)
                for px in range(start_px, max(end_px, start_px + 1)):
                    for py in range(start_py, max(end_py, start_py + 1)):
                        if 0 <= px < self.fixed_size and 0 <= py < self.fixed_size:
                            pixels[px, py] = color

    # ========== OVERLAY DRAWING METHODS ==========

    def _draw_all_waypoints(self, img, waypoints, bbox, pixels_per_tile):
        """Draw all waypoints on current floor (blue circles, centered on tile)."""
        pixels = img.load()
        min_x, min_y, max_x, max_y = bbox

        for wp in waypoints:
            wx, wy = wp['x'], wp['y']

            if min_x <= wx <= max_x and min_y <= wy <= max_y:
                rel_tile_x = wx - min_x
                rel_tile_y = wy - min_y

                # Center of the tile block (handles fractional pixels_per_tile)
                center_px = int(rel_tile_x * pixels_per_tile + pixels_per_tile / 2)
                center_py = int(rel_tile_y * pixels_per_tile + pixels_per_tile / 2)

                # Draw marker (size adapts to pixels_per_tile, minimum 1 pixel)
                marker_size = max(1, int(pixels_per_tile / 2))
                for dx in range(-marker_size, marker_size + 1):
                    for dy in range(-marker_size, marker_size + 1):
                        px = center_px + dx
                        py = center_py + dy
                        if 0 <= px < img.width and 0 <= py < img.height:
                            color = (128, 0, 255) if wp.get('in_cooldown') else (50, 150, 255)
                            pixels[px, py] = color

    def _draw_floor_transitions(self, img, all_waypoints, current_z, bbox, pixels_per_tile):
        """
        Mark floor transitions (stairs/ladders).
        Magenta (255, 0, 255) for going up, Cyan (0, 255, 255) for going down.
        """
        pixels = img.load()
        min_x, min_y, max_x, max_y = bbox

        # Find transitions from consecutive waypoints
        for i in range(len(all_waypoints) - 1):
            curr_wp = all_waypoints[i]
            next_wp = all_waypoints[i + 1]

            if curr_wp['z'] != next_wp['z']:
                # Transition detected
                if curr_wp['z'] == current_z:
                    tx, ty = curr_wp['x'], curr_wp['y']

                    # Determine color based on direction
                    is_up = next_wp['z'] < current_z
                    color = (255, 0, 255) if is_up else (0, 255, 255)

                    if min_x <= tx <= max_x and min_y <= ty <= max_y:
                        rel_tile_x = tx - min_x
                        rel_tile_y = ty - min_y

                        # Fill tile with color (handles fractional pixels_per_tile)
                        start_px = int(rel_tile_x * pixels_per_tile)
                        start_py = int(rel_tile_y * pixels_per_tile)
                        end_px = int((rel_tile_x + 1) * pixels_per_tile)
                        end_py = int((rel_tile_y + 1) * pixels_per_tile)

                        for px in range(start_px, max(end_px, start_px + 1)):
                            for py in range(start_py, max(end_py, start_py + 1)):
                                if 0 <= px < img.width and 0 <= py < img.height:
                                    pixels[px, py] = color

    def _draw_global_route(self, img, global_route, current_z, bbox, pixels_per_tile):
        """Draw global route (pink path - fills entire tiles)."""
        pixels = img.load()
        min_x, min_y, max_x, max_y = bbox

        # Filter route to current floor
        route_on_floor = [(x, y) for x, y, z in global_route if z == current_z]

        for x, y in route_on_floor:
            if min_x <= x <= max_x and min_y <= y <= max_y:
                rel_tile_x = x - min_x
                rel_tile_y = y - min_y

                # Fill tile with pink (handles fractional pixels_per_tile)
                start_px = int(rel_tile_x * pixels_per_tile)
                start_py = int(rel_tile_y * pixels_per_tile)
                end_px = int((rel_tile_x + 1) * pixels_per_tile)
                end_py = int((rel_tile_y + 1) * pixels_per_tile)

                for px in range(start_px, max(end_px, start_px + 1)):
                    for py in range(start_py, max(end_py, start_py + 1)):
                        if 0 <= px < img.width and 0 <= py < img.height:
                            pixels[px, py] = (255, 20, 147)  # Deep Pink

    def _draw_local_cache(self, img, player_pos, local_cache, bbox, pixels_per_tile):
        """
        Draw next local A* steps (cyan, 5 steps ahead - fills entire tiles).
        Converts relative steps to absolute coordinates for drawing.
        """
        pixels = img.load()
        min_x, min_y, max_x, max_y = bbox
        player_x, player_y, pz = player_pos

        # Trace path from current position
        curr_x, curr_y = player_x, player_y

        for dx, dy in local_cache[:5]:  # Only next 5 steps
            curr_x += dx
            curr_y += dy

            if min_x <= curr_x <= max_x and min_y <= curr_y <= max_y:
                rel_tile_x = curr_x - min_x
                rel_tile_y = curr_y - min_y

                # Fill tile with cyan (handles fractional pixels_per_tile)
                start_px = int(rel_tile_x * pixels_per_tile)
                start_py = int(rel_tile_y * pixels_per_tile)
                end_px = int((rel_tile_x + 1) * pixels_per_tile)
                end_py = int((rel_tile_y + 1) * pixels_per_tile)

                for px in range(start_px, max(end_px, start_px + 1)):
                    for py in range(start_py, max(end_py, start_py + 1)):
                        if 0 <= px < img.width and 0 <= py < img.height:
                            pixels[px, py] = (0, 255, 255)  # Cyan

    def _draw_current_target(self, img, target_wp, bbox, pixels_per_tile):
        """Highlight current target waypoint (yellow, fills entire tile)."""
        pixels = img.load()
        min_x, min_y, max_x, max_y = bbox
        tx, ty = target_wp['x'], target_wp['y']

        if min_x <= tx <= max_x and min_y <= ty <= max_y:
            rel_tile_x = tx - min_x
            rel_tile_y = ty - min_y

            # Fill tile with yellow (handles fractional pixels_per_tile)
            start_px = int(rel_tile_x * pixels_per_tile)
            start_py = int(rel_tile_y * pixels_per_tile)
            end_px = int((rel_tile_x + 1) * pixels_per_tile)
            end_py = int((rel_tile_y + 1) * pixels_per_tile)

            for px in range(start_px, max(end_px, start_px + 1)):
                for py in range(start_py, max(end_py, start_py + 1)):
                    if 0 <= px < img.width and 0 <= py < img.height:
                        pixels[px, py] = (255, 255, 0)  # Yellow

    def _draw_player_position(self, img, player_pos, bbox, pixels_per_tile):
        """Mark player position (white, fills entire tile)."""
        pixels = img.load()
        min_x, min_y, max_x, max_y = bbox
        player_x, player_y, _ = player_pos

        if min_x <= player_x <= max_x and min_y <= player_y <= max_y:
            rel_tile_x = player_x - min_x
            rel_tile_y = player_y - min_y

            # Fill tile with white (handles fractional pixels_per_tile)
            start_px = int(rel_tile_x * pixels_per_tile)
            start_py = int(rel_tile_y * pixels_per_tile)
            end_px = int((rel_tile_x + 1) * pixels_per_tile)
            end_py = int((rel_tile_y + 1) * pixels_per_tile)

            for px in range(start_px, max(end_px, start_px + 1)):
                for py in range(start_py, max(end_py, start_py + 1)):
                    if 0 <= px < img.width and 0 <= py < img.height:
                        pixels[px, py] = (255, 255, 255)  # White

    # ========== UTILITY METHODS ==========

    def _calculate_zoom_bbox(self, all_waypoints, player_pos, current_wp_index, margin=12):
        """
        Calculate zoomed bounding box showing only nearby waypoints.

        Shows waypoints from index-2 to index+1 relative to current target.
        This creates a "zoomed in" view of the relevant route section.

        Args:
            all_waypoints: Full waypoint list
            player_pos: (x, y, z)
            current_wp_index: Index of current target waypoint
            margin: Tiles to add around visible waypoints

        Returns:
            (min_x, min_y, max_x, max_y) bounding box
        """
        if current_wp_index is None or len(all_waypoints) == 0:
            # Fallback to old behavior if no index provided
            return self._calculate_bbox(all_waypoints, player_pos, padding=margin)

        # Get current floor
        pz = player_pos[2]

        # Define range of waypoints to show (n-2 to n+1)
        start_idx = max(0, current_wp_index - 2)
        end_idx = min(len(all_waypoints), current_wp_index + 2)  # +2 because range is exclusive

        # Get visible waypoints on current floor
        visible_wps = [
            wp for wp in all_waypoints[start_idx:end_idx]
            if wp['z'] == pz
        ]

        # If no waypoints on current floor, include nearby floor waypoints for context
        if not visible_wps:
            visible_wps = all_waypoints[start_idx:end_idx]

        # Include player position
        all_xs = [wp['x'] for wp in visible_wps] + [player_pos[0]]
        all_ys = [wp['y'] for wp in visible_wps] + [player_pos[1]]

        # Ensure minimum bbox size (at least 30x30 tiles)
        min_size = 30

        min_x = min(all_xs) - margin
        max_x = max(all_xs) + margin
        min_y = min(all_ys) - margin
        max_y = max(all_ys) + margin

        # Enforce minimum size
        width = max_x - min_x
        height = max_y - min_y

        if width < min_size:
            center_x = (min_x + max_x) / 2
            min_x = int(center_x - min_size / 2)
            max_x = int(center_x + min_size / 2)

        if height < min_size:
            center_y = (min_y + max_y) / 2
            min_y = int(center_y - min_size / 2)
            max_y = int(center_y + min_size / 2)

        return (min_x, min_y, max_x, max_y)

    def _calculate_bbox(self, waypoints, player_pos, padding=30):
        """Calculate bounding box that encompasses all waypoints and player."""
        all_xs = [wp['x'] for wp in waypoints] + [player_pos[0]]
        all_ys = [wp['y'] for wp in waypoints] + [player_pos[1]]

        min_x = min(all_xs) - padding
        max_x = max(all_xs) + padding
        min_y = min(all_ys) - padding
        max_y = max(all_ys) + padding

        return (min_x, min_y, max_x, max_y)

    def _create_placeholder_image(self):
        """Create placeholder image with fixed size."""
        img = Image.new('RGB', (self.fixed_size, self.fixed_size), (40, 40, 40))
        return img

    def clear_cache(self):
        """
        Clear all cached base maps.
        Call this when waypoints change significantly or to free memory.
        """
        self.base_map_cache.clear()

    def clear_chunk_cache(self):
        """Clear chunk cache to free memory."""
        self.chunk_cache.clear()
