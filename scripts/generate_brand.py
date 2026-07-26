from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).parents[1]
TARGET = ROOT / "custom_components" / "justsmart_peak_manager" / "brand"
SIZE = 1024
image = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
pixels = image.load()
for y in range(SIZE):
    for x in range(SIZE):
        t = (x + y) / (2 * SIZE)
        pixels[x, y] = (round(16 - 9 * t), round(26 - 10 * t), round(36 - 11 * t), 255)

draw = ImageDraw.Draw(image)
draw.rounded_rectangle((40, 40, 984, 984), radius=240, outline=(38, 59, 67, 255), width=16)
box = (216, 190, 808, 782)
draw.arc(box, 200, 340, fill=(36, 52, 62, 255), width=68)
# Segmented premium gauge: teal -> gold -> coral.
draw.arc(box, 200, 270, fill=(84, 215, 207, 255), width=48)
draw.arc(box, 270, 315, fill=(255, 209, 102, 255), width=48)
draw.arc(box, 315, 340, fill=(255, 107, 114, 255), width=48)
draw.ellipse((778, 588, 846, 656), fill=(255, 107, 114, 255))
bolt = [(568, 210), (360, 540), (502, 540), (454, 794), (670, 438), (526, 438)]
draw.polygon(bolt, fill=(84, 215, 207, 255))
draw.line(bolt + [bolt[0]], fill=(185, 255, 249, 255), width=12, joint="curve")

TARGET.mkdir(parents=True, exist_ok=True)
resampling = Image.Resampling.LANCZOS
image.resize((512, 512), resampling).save(TARGET / "icon@2x.png", optimize=True)
image.resize((256, 256), resampling).save(TARGET / "icon.png", optimize=True)
print(TARGET / "icon.png")
print(TARGET / "icon@2x.png")
