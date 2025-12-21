"""
Shared color palette for Tibia terrain visualization.
Used by waypoint_editor.py and visualize_path.py
"""

# Tibia terrain color ID to RGB mapping
COLOR_PALETTE = {
    0x00: (0, 0, 0),        # Black (void/unwalkable)
    0x0C: (0, 60, 0),       # Dark Green (grass variant)
    0x18: (0, 200, 0),      # Light Green (grass)
    0x28: (51, 0, 204),   # Blue (water)
    0x33: (50, 100, 200),   # Blue (water variant)
    0x72: (100, 50, 20),    # Dark Brown
    0x79: (120, 80, 40),    # Brown
    0x81: (150, 150, 150),  # Gray (floor)
    0xBA: (200, 50, 50),    # Red (roofs)
    0xD2: (255, 255, 0),    # Yellow (stairs)
    0x1E: (30, 30, 30),     # Dark (cave)
    0xC0: (255, 100, 0),    # Orange (lava)
}

# Default color for unknown IDs
DEFAULT_COLOR = (80, 80, 80)  # Dark gray


def get_color(color_id):
    """Get RGB color for a Tibia color ID."""
    return COLOR_PALETTE.get(color_id, DEFAULT_COLOR)


def get_color_by_byte(byte_val):
    """Get RGB color for a byte value (same as get_color)."""
    return get_color(byte_val)
