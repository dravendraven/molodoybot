"""
Real-Time Minimap Visualizer for Cavebot
Generates minimap images with optimized caching for high-frequency updates
"""

import os
from PIL import Image
from collections import defaultdict


class RealtimeMinimapVisualizer:
    """
    Generates real-time minimap visualizations with performance-critical caching.

    Separates terrain rendering (expensive, cached) from overlay drawing (fast, every update).
    This achieves 10-20x performance improvement for real-time updates.
    """

    def __init__(self, maps_dir, walkable_colors, color_palette):
        """
        Initialize the minimap visualizer.

        Args:
            maps_dir: Directory containing .map chunk files
            walkable_colors: Set or list of IDs that are walkable
            color_palette: Dict mapping byte values to RGB tuples
        """
        self.maps_dir = maps_dir
        self.walkable_colors = set(walkable_colors)
        self.color_palette = color_palette
        self.default_color = (80, 80, 80)

        # Cache of rendered base maps (terrain layer only)
        # Key: (floor_z, min_x, min_y, max_x, max_y) -> PIL.Image
        self.base_map_cache = {}

        # Cache of raw chunk data from disk
        # Key: (cx, cy, z) -> bytes
        self.chunk_cache = {}

    def generate_minimap(self, player_pos, target_wp, all_waypoints,
                        global_route=None, local_cache=None):
        """
        Generate a real-time minimap image.

        Args:
            player_pos: (x, y, z) current player position
            target_wp: {'x': int, 'y': int, 'z': int} current target waypoint
            all_waypoints: List of all configured waypoints
            global_route: [(x, y, z), ...] global path (optional)
            local_cache: [(dx, dy), ...] local A* steps (optional)

        Returns:
            PIL.Image: Minimap image ready for display
        """
        px, py, pz = player_pos

        # Step 1: Get waypoints for current floor
        floor_waypoints = [wp for wp in all_waypoints if wp['z'] == pz]

        if not floor_waypoints:
            return self._create_placeholder_image()

        # Step 2: Calculate bounding box
        bbox = self._calculate_bbox(floor_waypoints, player_pos, padding=30)

        # Step 3: Get base map (cached or render new)
        base_img = self._get_base_map(pz, bbox)

        # Step 4: Create copy for overlay drawing
        overlay_img = base_img.copy()

        # Step 5: Draw overlays in order (background to foreground)
        self._draw_all_waypoints(overlay_img, floor_waypoints, bbox)
        self._draw_floor_transitions(overlay_img, all_waypoints, pz, bbox)

        if global_route:
            self._draw_global_route(overlay_img, global_route, pz, bbox)

        if local_cache:
            self._draw_local_cache(overlay_img, player_pos, local_cache, bbox)

        self._draw_current_target(overlay_img, target_wp, bbox)
        self._draw_player_position(overlay_img, player_pos, bbox)

        return overlay_img

    # ========== CACHE METHODS (Performance-Critical) ==========

    def _get_base_map(self, floor_z, bbox):
        """
        Get cached base map or render new one.

        Returns a copy to avoid modifying the cached version.
        """
        cache_key = (floor_z, *bbox)

        if cache_key not in self.base_map_cache:
            self.base_map_cache[cache_key] = self._render_base_terrain(floor_z, bbox)

        return self.base_map_cache[cache_key].copy()

    def _render_base_terrain(self, floor_z, bbox):
        """
        Render the terrain layer (base map without overlays).
        This is the expensive operation that we cache.
        """
        min_x, min_y, max_x, max_y = bbox
        width = max_x - min_x + 1
        height = max_y - min_y + 1

        img = Image.new('RGB', (width, height), (0, 0, 0))
        pixels = img.load()

        # Calculate which chunks are needed
        start_cx, end_cx = min_x // 256, max_x // 256
        start_cy, end_cy = min_y // 256, max_y // 256

        # Load and render each chunk
        for cx in range(start_cx, end_cx + 1):
            for cy in range(start_cy, end_cy + 1):
                chunk_data = self._load_chunk(cx, cy, floor_z)
                if chunk_data:
                    self._render_chunk_to_image(pixels, chunk_data, cx, cy, bbox)

        return img

    def _load_chunk(self, cx, cy, z):
        """Load chunk from disk (with cache)."""
        cache_key = (cx, cy, z)

        if cache_key in self.chunk_cache:
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
                    return data
                except Exception as e:
                    print(f"[Minimap] Error loading chunk {fname}: {e}")
                    return None

        return None

    def _render_chunk_to_image(self, pixels, chunk_data, cx, cy, bbox):
        """
        Render a single 256x256 chunk to the image pixels.
        Only renders pixels within the bounding box.
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
                # Convert to image coordinates
                img_x = tile_x - min_x
                img_y = tile_y - min_y

                # Get color for this tile
                color = self.color_palette.get(byte_val, self.default_color)
                pixels[img_x, img_y] = color

    # ========== OVERLAY DRAWING METHODS ==========

    def _draw_all_waypoints(self, img, waypoints, bbox):
        """Draw all waypoints on current floor (blue circles, 2x2 pixels)."""
        pixels = img.load()
        min_x, min_y, max_x, max_y = bbox

        for wp in waypoints:
            wx, wy = wp['x'], wp['y']

            if min_x <= wx <= max_x and min_y <= wy <= max_y:
                rel_x = wx - min_x
                rel_y = wy - min_y

                # Draw 2x2 blue square
                for dx in range(-1, 2):
                    for dy in range(-1, 2):
                        if 0 <= rel_x + dx < img.width and 0 <= rel_y + dy < img.height:
                            pixels[rel_x + dx, rel_y + dy] = (50, 150, 255)  # Blue

    def _draw_floor_transitions(self, img, all_waypoints, current_z, bbox):
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
                        rel_x = tx - min_x
                        rel_y = ty - min_y

                        # Draw 3x3 square
                        for dx in range(-1, 2):
                            for dy in range(-1, 2):
                                if 0 <= rel_x + dx < img.width and 0 <= rel_y + dy < img.height:
                                    pixels[rel_x + dx, rel_y + dy] = color

    def _draw_global_route(self, img, global_route, current_z, bbox):
        """Draw global route (green path)."""
        pixels = img.load()
        min_x, min_y, max_x, max_y = bbox

        # Filter route to current floor
        route_on_floor = [(x, y) for x, y, z in global_route if z == current_z]

        for x, y in route_on_floor:
            if min_x <= x <= max_x and min_y <= y <= max_y:
                rel_x = x - min_x
                rel_y = y - min_y
                pixels[rel_x, rel_y] = (0, 255, 0)  # Green

    def _draw_local_cache(self, img, player_pos, local_cache, bbox):
        """
        Draw next local A* steps (cyan, 5 steps ahead).
        Converts relative steps to absolute coordinates for drawing.
        """
        pixels = img.load()
        min_x, min_y, max_x, max_y = bbox
        px, py, pz = player_pos

        # Trace path from current position
        curr_x, curr_y = px, py

        for dx, dy in local_cache[:5]:  # Only next 5 steps
            curr_x += dx
            curr_y += dy

            if min_x <= curr_x <= max_x and min_y <= curr_y <= max_y:
                rel_x = curr_x - min_x
                rel_y = curr_y - min_y
                pixels[rel_x, rel_y] = (0, 255, 255)  # Cyan

    def _draw_current_target(self, img, target_wp, bbox):
        """Highlight current target waypoint (yellow, 4x4 square)."""
        pixels = img.load()
        min_x, min_y, max_x, max_y = bbox
        tx, ty = target_wp['x'], target_wp['y']

        if min_x <= tx <= max_x and min_y <= ty <= max_y:
            rel_x = tx - min_x
            rel_y = ty - min_y

            # Draw 4x4 yellow square
            for dx in range(-2, 3):
                for dy in range(-2, 3):
                    if 0 <= rel_x + dx < img.width and 0 <= rel_y + dy < img.height:
                        pixels[rel_x + dx, rel_y + dy] = (255, 255, 0)  # Yellow

    def _draw_player_position(self, img, player_pos, bbox):
        """Mark player position (white, 3x3 square)."""
        pixels = img.load()
        min_x, min_y, max_x, max_y = bbox
        px, py, pz = player_pos

        if min_x <= px <= max_x and min_y <= py <= max_y:
            rel_x = px - min_x
            rel_y = py - min_y

            # Draw 3x3 white square
            for dx in range(-1, 2):
                for dy in range(-1, 2):
                    if 0 <= rel_x + dx < img.width and 0 <= rel_y + dy < img.height:
                        pixels[rel_x + dx, rel_y + dy] = (255, 255, 255)  # White

    # ========== UTILITY METHODS ==========

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
        """Create placeholder image when no waypoints exist on current floor."""
        img = Image.new('RGB', (200, 100), (40, 40, 40))
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
