"""
Render Claude Monitor display sprites as JPG images.

Recreates the ESP32 display output (240x320, ILI9341) for each screen state.
Uses the same coordinate system and color palette as the firmware.
"""

from PIL import Image, ImageDraw, ImageFont
import math
import os

# --- Screen dimensions ---
SCREEN_W = 240
SCREEN_H = 320
ANIM_H = 240
HEADER_H = 0
FOOTER_H = 80

# --- RGB565 to RGB888 conversion ---
def rgb565_to_rgb(c):
    r = ((c >> 11) & 0x1F) * 255 // 31
    g = ((c >> 5) & 0x3F) * 255 // 63
    b = (c & 0x1F) * 255 // 31
    return (r, g, b)

# --- Color palette ---
BG_DARK      = rgb565_to_rgb(0x1082)
BG_PANEL     = rgb565_to_rgb(0x2104)
TEXT_PRIMARY  = rgb565_to_rgb(0xFFFF)
TEXT_DIM      = rgb565_to_rgb(0x8410)
CLAUDE_ORANGE = rgb565_to_rgb(0xFBE0)
BLUE_IDLE     = rgb565_to_rgb(0x2D7F)
GREEN_OK      = rgb565_to_rgb(0x07E0)
RED_ALERT     = rgb565_to_rgb(0xF800)
YELLOW_WARN   = rgb565_to_rgb(0xFFE0)
PURPLE_TOOL   = rgb565_to_rgb(0x780F)
CYAN_INFO     = rgb565_to_rgb(0x07FF)

# --- Sin LUT (256 entries, -127 to 127) ---
def isin(angle):
    return int(127 * math.sin(angle * 2 * math.pi / 256))

def icos(angle):
    return isin((angle + 64) % 256)

# Character constants
S = 11  # logical pixel size


def color565(r, g, b):
    return (r, g, b)


def draw_clawd(draw, cx, cy, body_color, eye_mode, leg_phase, shake_x=0, shake_y=0):
    """Draw the Clawd character."""
    cx += shake_x
    cy += shake_y
    dark = (15, 1, 0)

    bx = cx - 5 * S
    by = cy - 4 * S

    # Body: 10S x 8S
    draw.rectangle([bx, by, bx + 10*S - 1, by + 8*S - 1], fill=body_color)

    # Left arm
    draw.rectangle([bx - 2*S, by + 4*S, bx - 1, by + 6*S - 1], fill=body_color)

    # Right arm
    draw.rectangle([bx + 10*S, by + 4*S, bx + 12*S - 1, by + 6*S - 1], fill=body_color)

    # Eyes
    lEyeX = bx + 1 * S
    rEyeX = bx + 6 * S
    eyeY = by + 2 * S

    if eye_mode == 0:  # OPEN
        draw.rectangle([lEyeX, eyeY, lEyeX + 2*S - 1, eyeY + 2*S - 1], fill=dark)
        draw.rectangle([rEyeX, eyeY, rEyeX + 2*S - 1, eyeY + 2*S - 1], fill=dark)
    elif eye_mode == 1:  # CLOSED
        draw.rectangle([lEyeX, eyeY + S - 1, lEyeX + 2*S - 1, eyeY + S], fill=dark)
        draw.rectangle([rEyeX, eyeY + S - 1, rEyeX + 2*S - 1, eyeY + S], fill=dark)
    elif eye_mode == 2:  # WIDE
        draw.rectangle([lEyeX, eyeY, lEyeX + 2*S - 1, eyeY + 3*S - 1], fill=dark)
        draw.rectangle([rEyeX, eyeY, rEyeX + 2*S - 1, eyeY + 3*S - 1], fill=dark)
    elif eye_mode == 3:  # X
        draw.rectangle([lEyeX, eyeY, lEyeX + 2*S - 1, eyeY + 2*S - 1], fill=dark)
        draw.rectangle([rEyeX, eyeY, rEyeX + 2*S - 1, eyeY + 2*S - 1], fill=dark)
        red = (255, 0, 0)
        for t in range(-1, 2):
            draw.line([lEyeX + t, eyeY, lEyeX + 2*S - 1 + t, eyeY + 2*S - 1], fill=red, width=1)
            draw.line([lEyeX + 2*S - 1 + t, eyeY, lEyeX + t, eyeY + 2*S - 1], fill=red, width=1)
            draw.line([rEyeX + t, eyeY, rEyeX + 2*S - 1 + t, eyeY + 2*S - 1], fill=red, width=1)
            draw.line([rEyeX + 2*S - 1 + t, eyeY, rEyeX + t, eyeY + 2*S - 1], fill=red, width=1)

    # Legs
    lLegX = bx + 1 * S
    rLegX = bx + 6 * S
    legBaseY = by + 8 * S

    lp = abs(leg_phase)
    draw.rectangle([lLegX, legBaseY + lp, lLegX + 2*S - 1, legBaseY + lp + 3*S - 1], fill=body_color)
    draw.rectangle([rLegX, legBaseY + (S - lp), rLegX + 2*S - 1, legBaseY + (S - lp) + 3*S - 1], fill=body_color)


def draw_footer(draw, state_name, state_color, session_id="A1B2C3", needs_attention=False,
                session_count=1, display_rank=0):
    """Draw the footer panel."""
    footerY = HEADER_H + ANIM_H

    # Background
    draw.rectangle([0, footerY, SCREEN_W - 1, SCREEN_H - 1], fill=BG_PANEL)

    # Orange divider
    draw.line([0, footerY, SCREEN_W - 1, footerY], fill=CLAUDE_ORANGE)

    # State name - larger text
    try:
        font_large = ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", 20)
        font_small = ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", 12)
    except (OSError, IOError):
        font_large = ImageFont.load_default()
        font_small = ImageFont.load_default()

    # State name centered
    bbox = draw.textbbox((0, 0), state_name, font=font_large)
    tw = bbox[2] - bbox[0]
    draw.text(((SCREEN_W - tw) // 2, footerY + 12), state_name, fill=state_color, font=font_large)

    # Subtitle
    if needs_attention:
        subtitle = "TAP SCREEN TO FOCUS"
        sub_color = YELLOW_WARN
    else:
        subtitle = f"session: {session_id}"
        sub_color = TEXT_DIM

    bbox = draw.textbbox((0, 0), subtitle, font=font_small)
    tw = bbox[2] - bbox[0]
    draw.text(((SCREEN_W - tw) // 2, footerY + 42), subtitle, fill=sub_color, font=font_small)

    # Multi-session dots
    if session_count > 1:
        DOT_R = 3
        DOT_GAP = 10
        totalW = (session_count - 1) * DOT_GAP
        startX = (SCREEN_W - totalW) // 2
        dotY = footerY + FOOTER_H - DOT_R - 4
        for i in range(session_count):
            dx = startX + i * DOT_GAP
            if i == display_rank:
                draw.ellipse([dx - DOT_R, dotY - DOT_R, dx + DOT_R, dotY + DOT_R], fill=state_color)
            else:
                draw.ellipse([dx - DOT_R, dotY - DOT_R, dx + DOT_R, dotY + DOT_R], outline=TEXT_DIM)


def draw_glow_idle(draw, cx, cy):
    """Draw subtle glow under feet for IDLE state."""
    feetY = cy + 4*S + 3*S
    glow_bright = 40
    for r in range(5*S, 3*S - 1, -S):
        fade = glow_bright * (r - 2*S) // (3*S)
        gc = (fade // 4, fade // 3, fade)
        draw.ellipse([cx - r, feetY - S//4, cx + r, feetY + S//4], outline=gc)


def draw_thinking_dots(draw, cx, cy, phase=200):
    """Draw animated thinking dots above head."""
    dotsY = cy - 4*S - 18
    for i in range(3):
        dot_angle = int((phase * 256) / 600) + i * 85
        dy = (isin(dot_angle % 256) * 5) // 127
        lit = ((phase // 400 + i) % 3) == 0
        dc = CLAUDE_ORANGE if lit else TEXT_DIM
        cx_dot = cx - 12 + i * 12
        draw.ellipse([cx_dot - 4, dotsY + dy - 4, cx_dot + 4, dotsY + dy + 4], fill=dc)


def draw_tool_icon(draw, cx, cy, phase=0):
    """Draw spinning tool icon."""
    gx = cx + 5*S + 16
    gy = cy - 4*S + 16
    spin_angle = int((phase * 256) / 1000) % 256
    spoke_len = 12

    for s in range(4):
        a = (spin_angle + s * 64) % 256
        ex = gx + (icos(a) * spoke_len) // 127
        ey = gy + (isin(a) * spoke_len) // 127
        draw.line([gx, gy, ex, ey], fill=PURPLE_TOOL, width=3)

    # Hub
    draw.ellipse([gx - 4, gy - 4, gx + 4, gy + 4], fill=CYAN_INFO)

    # Outer ring
    r = spoke_len + 3
    draw.ellipse([gx - r, gy - r, gx + r, gy + r], outline=PURPLE_TOOL)


def draw_permission_border(draw, cx, cy):
    """Draw pulsing red border around character."""
    bx = cx - 5*S
    by = cy - 4*S
    bw = 10*S
    bh = 8*S + 3*S

    boxX = bx - 2*S - 4
    boxY = by - 4
    boxW = bw + 4*S + 8
    boxH = bh + 8

    border_color = (200, 0, 0)
    for i in range(3):
        draw.rectangle([boxX - i, boxY - i, boxX + boxW + i, boxY + boxH + i], outline=border_color)


def draw_attention_arrows(draw, color):
    """Draw blinking attention arrows near bottom of animation zone."""
    ay = ANIM_H - 12
    # Left arrow (pointing right)
    draw.polygon([(5, ay), (15, ay - 5), (15, ay + 5)], fill=color)
    # Right arrow (pointing left)
    draw.polygon([(234, ay), (224, ay - 5), (224, ay + 5)], fill=color)


def draw_error_glow(draw, cx, cy):
    """Draw red glow under character for ERROR state."""
    feetY = cy + 4*S + 3*S
    glow_r = 4*S
    draw.ellipse([cx - glow_r, feetY - glow_r//3, cx + glow_r, feetY + glow_r//3],
                 fill=(60, 0, 0))


def draw_cursor(draw, cx, cy):
    """Draw blinking cursor for INPUT_NEEDED state."""
    curX = cx + 5*S + 8
    curY = cy
    draw.rectangle([curX, curY, curX + 10, curY + 3], fill=CLAUDE_ORANGE)


def create_base_image():
    """Create a base image with dark background."""
    img = Image.new('RGB', (SCREEN_W, SCREEN_H), BG_DARK)
    return img


def render_idle():
    """Render IDLE state."""
    img = create_base_image()
    draw = ImageDraw.Draw(img)
    cx, cy = 120, 100
    body_color = (206, 142, 107)

    draw_glow_idle(draw, cx, cy)
    draw_clawd(draw, cx, cy, body_color, eye_mode=0, leg_phase=0, shake_y=0)
    draw_footer(draw, "IDLE", BLUE_IDLE)
    return img


def render_thinking():
    """Render THINKING state."""
    img = create_base_image()
    draw = ImageDraw.Draw(img)
    cx, cy = 120, 100
    body_color = (206, 142, 107)

    draw_clawd(draw, cx, cy, body_color, eye_mode=0, leg_phase=6)
    draw_thinking_dots(draw, cx, cy, phase=200)
    draw_footer(draw, "THINKING", CLAUDE_ORANGE)
    return img


def render_tool_use():
    """Render TOOL_USE state."""
    img = create_base_image()
    draw = ImageDraw.Draw(img)
    cx, cy = 120, 100
    body_color = (190, 120, 160)  # purple tint

    draw_clawd(draw, cx, cy, body_color, eye_mode=0, leg_phase=8)
    draw_tool_icon(draw, cx, cy, phase=250)
    draw_footer(draw, "TOOL_USE", PURPLE_TOOL)
    return img


def render_permission():
    """Render PERMISSION state."""
    img = create_base_image()
    draw = ImageDraw.Draw(img)
    cx, cy = 120, 100
    body_color = (206, 142, 107)

    draw_permission_border(draw, cx, cy)
    draw_clawd(draw, cx, cy, body_color, eye_mode=2, leg_phase=0, shake_x=5)
    draw_attention_arrows(draw, YELLOW_WARN)
    draw_footer(draw, "PERMISSION", RED_ALERT, needs_attention=True)
    return img


def render_input_needed():
    """Render INPUT_NEEDED state."""
    img = create_base_image()
    draw = ImageDraw.Draw(img)
    cx, cy = 120, 100
    body_color = (206, 142, 107)

    draw_clawd(draw, cx, cy, body_color, eye_mode=0, leg_phase=0)
    draw_cursor(draw, cx, cy)
    draw_attention_arrows(draw, CYAN_INFO)
    draw_footer(draw, "INPUT", CYAN_INFO, needs_attention=True)
    return img


def render_error():
    """Render ERROR state."""
    img = create_base_image()
    draw = ImageDraw.Draw(img)
    cx, cy = 120, 100
    body_color = (200, 80, 70)  # red tint

    draw_error_glow(draw, cx, cy)
    draw_clawd(draw, cx, cy, body_color, eye_mode=3, leg_phase=0, shake_x=3)
    draw_footer(draw, "ERROR", RED_ALERT, needs_attention=False, session_count=3, display_rank=1)
    return img


def render_waiting_ble():
    """Render Waiting for BLE screen."""
    img = create_base_image()
    draw = ImageDraw.Draw(img)

    try:
        font_large = ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", 20)
        font_small = ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", 12)
    except (OSError, IOError):
        font_large = ImageFont.load_default()
        font_small = ImageFont.load_default()

    # Title
    title = "Claude Monitor"
    bbox = draw.textbbox((0, 0), title, font=font_large)
    tw = bbox[2] - bbox[0]
    draw.text(((SCREEN_W - tw) // 2, SCREEN_H // 2 - 70), title, fill=CLAUDE_ORANGE, font=font_large)

    # BLE icon
    bx, by = SCREEN_W // 2, SCREEN_H // 2
    s = 3
    ble_color = (0, 130, 200)

    draw.line([bx, by - 8*s, bx, by + 8*s], fill=ble_color, width=2)
    draw.line([bx, by - 8*s, bx + 5*s, by - 3*s], fill=ble_color, width=2)
    draw.line([bx + 5*s, by - 3*s, bx - 4*s, by + 4*s], fill=ble_color, width=2)
    draw.line([bx, by + 8*s, bx + 5*s, by + 3*s], fill=ble_color, width=2)
    draw.line([bx + 5*s, by + 3*s, bx - 4*s, by - 4*s], fill=ble_color, width=2)

    # Broadcast arcs
    for r in range(20, 36, 8):
        arc_bright = 200 * (40 - r) // 40
        arc_color = (0, arc_bright * 2 // 3, arc_bright)
        draw.ellipse([bx - r, by - r, bx + r, by + r], outline=arc_color)

    # Subtitle text
    for i, line in enumerate(["Bluetooth advertising...",
                               "Run claude-monitor on",
                               "your computer to connect"]):
        bbox = draw.textbbox((0, 0), line, font=font_small)
        tw = bbox[2] - bbox[0]
        draw.text(((SCREEN_W - tw) // 2, SCREEN_H // 2 + 50 + i * 18), line,
                  fill=TEXT_DIM, font=font_small)

    return img


def render_no_sessions():
    """Render No Sessions screen."""
    img = create_base_image()
    draw = ImageDraw.Draw(img)

    try:
        font_large = ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", 20)
        font_small = ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", 12)
    except (OSError, IOError):
        font_large = ImageFont.load_default()
        font_small = ImageFont.load_default()

    # Title
    title = "Claude Monitor"
    bbox = draw.textbbox((0, 0), title, font=font_large)
    tw = bbox[2] - bbox[0]
    draw.text(((SCREEN_W - tw) // 2, SCREEN_H // 2 - 40), title, fill=TEXT_DIM, font=font_large)

    # Subtitle lines
    for i, (line, color) in enumerate([
        ("No active sessions", TEXT_DIM),
        ("Waiting for Claude Code...", TEXT_DIM),
    ]):
        bbox = draw.textbbox((0, 0), line, font=font_small)
        tw = bbox[2] - bbox[0]
        draw.text(((SCREEN_W - tw) // 2, SCREEN_H // 2 + 2 + i * 20), line, fill=color, font=font_small)

    # BLE connected label
    ble_label = "BLE connected"
    ble_color = (0, 60, 80)
    bbox = draw.textbbox((0, 0), ble_label, font=font_small)
    tw = bbox[2] - bbox[0]
    draw.text(((SCREEN_W - tw) // 2, SCREEN_H // 2 + 48), ble_label, fill=ble_color, font=font_small)

    # Breathing dot
    dotX, dotY = SCREEN_W // 2, SCREEN_H // 2 + 75
    bright = 80
    draw.ellipse([dotX - 5, dotY - 5, dotX + 5, dotY + 5], fill=(bright, bright // 2, 0))

    return img


def main():
    output_dir = os.path.dirname(os.path.abspath(__file__))

    screens = [
        ("01_waiting_ble", render_waiting_ble),
        ("02_no_sessions", render_no_sessions),
        ("03_idle", render_idle),
        ("04_thinking", render_thinking),
        ("05_tool_use", render_tool_use),
        ("06_permission", render_permission),
        ("07_input_needed", render_input_needed),
        ("08_error", render_error),
    ]

    for name, render_fn in screens:
        img = render_fn()
        path = os.path.join(output_dir, f"{name}.jpg")
        img.save(path, "JPEG", quality=95)
        print(f"Saved {path}")


if __name__ == "__main__":
    main()
