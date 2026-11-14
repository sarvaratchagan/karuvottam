"""Generate the installable app icons from a simple code-native weather mark.

Run with Pillow available: python scripts/build_pwa_icons.py
"""

from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1] / 'static/icons'
ROOT.mkdir(parents=True, exist_ok=True)
SIZE = 1024
image = Image.new('RGB', (SIZE, SIZE), '#245f3d')
draw = ImageDraw.Draw(image)

# Keep the mark inside the center safe area used by masked mobile icons.
draw.ellipse((285, 250, 525, 490), fill='#f5c64d')
draw.ellipse((415, 395, 650, 620), fill='#f5f7f5')
draw.ellipse((555, 435, 745, 625), fill='#f5f7f5')
draw.rounded_rectangle((320, 510, 755, 645), radius=65, fill='#f5f7f5')
for x, y in ((405, 695), (535, 720), (665, 695)):
    draw.line((x, y, x - 35, y + 92), fill='#91d9da', width=35)

for pixels, filename in ((192, 'icon-192.png'),
                         (512, 'icon-512.png'),
                         (180, 'apple-touch-icon.png')):
    image.resize((pixels, pixels), Image.Resampling.LANCZOS).save(ROOT / filename,
                                                                  optimize=True)
