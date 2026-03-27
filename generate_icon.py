"""
DropDone 아이콘 & 인스톨러 이미지 생성기
  assets/icon.ico            — 다중 해상도 ICO (16, 32, 48, 256)
  assets/installer_banner.bmp — Inno Setup WizardImageFile (163×314)
  assets/installer_icon.bmp  — Inno Setup WizardSmallImageFile (55×58)
"""

from PIL import Image, ImageDraw, ImageFont
import os

ASSETS = os.path.join(os.path.dirname(__file__), 'assets')
os.makedirs(ASSETS, exist_ok=True)

BG_BLUE   = (47, 129, 247, 255)   # #2F81F7
WHITE     = (255, 255, 255, 255)
DARK_BLUE = (22,  80, 174, 255)   # 배너 배경 짙은 파랑


# ─────────────────────────────────────────────────────
# 1. 아이콘 기본 이미지 그리기 (RGBA, size×size)
# ─────────────────────────────────────────────────────
def draw_icon(size: int) -> Image.Image:
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    pad  = size * 0.04
    r    = (size / 2) - pad
    cx   = size / 2
    cy   = size / 2

    # 파란 원 배경
    draw.ellipse(
        [cx - r, cy - r, cx + r, cy + r],
        fill=BG_BLUE,
    )

    # 흰색 아래 화살표 (↓)
    aw  = size * 0.38    # 화살표 전체 너비
    ah  = size * 0.44    # 화살표 전체 높이
    sw  = size * 0.14    # 줄기 너비
    top = cy - ah * 0.5
    bot = cy + ah * 0.5

    stem_top    = top
    stem_bottom = bot - ah * 0.38
    head_top    = stem_bottom
    head_bottom = bot

    # 줄기
    draw.rectangle(
        [cx - sw / 2, stem_top, cx + sw / 2, stem_bottom],
        fill=WHITE,
    )
    # 삼각 머리
    draw.polygon(
        [
            (cx - aw / 2, head_top),
            (cx + aw / 2, head_top),
            (cx,          head_bottom),
        ],
        fill=WHITE,
    )
    # 하단 밑줄 (받침대)
    bh = max(2, size * 0.07)
    bw = size * 0.55
    draw.rectangle(
        [cx - bw / 2, bot + size * 0.04,
         cx + bw / 2, bot + size * 0.04 + bh],
        fill=WHITE,
    )

    return img


# ─────────────────────────────────────────────────────
# 2. icon.ico — 4 해상도 멀티사이즈
#    PIL ICO: 256px 기준 이미지 하나로 sizes 자동 리사이즈
# ─────────────────────────────────────────────────────
ico_path = os.path.join(ASSETS, 'icon.ico')
img256 = draw_icon(256)
img256.save(
    ico_path,
    format='ICO',
    sizes=[(256, 256), (48, 48), (32, 32), (16, 16)],
)
print(f'[OK] {ico_path}  ({os.path.getsize(ico_path):,} bytes)')


# ─────────────────────────────────────────────────────
# 3. installer_banner.bmp  (163 × 314, WizardImageFile)
# ─────────────────────────────────────────────────────
BW, BH = 163, 314
banner = Image.new('RGB', (BW, BH), DARK_BLUE[:3])
draw   = ImageDraw.Draw(banner)

# 그라디언트 느낌: 위쪽 밝게
for y in range(BH):
    t = y / BH
    r = int(DARK_BLUE[0] + (BG_BLUE[0] - DARK_BLUE[0]) * (1 - t))
    g = int(DARK_BLUE[1] + (BG_BLUE[1] - DARK_BLUE[1]) * (1 - t))
    b = int(DARK_BLUE[2] + (BG_BLUE[2] - DARK_BLUE[2]) * (1 - t))
    draw.line([(0, y), (BW, y)], fill=(r, g, b))

# 아이콘 중앙 상단에 배치
icon_size = 80
icon_img  = draw_icon(icon_size).convert('RGB')
ix = (BW - icon_size) // 2
iy = 40
banner.paste(icon_img, (ix, iy))

# 앱 이름 텍스트
try:
    font_large = ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf', 22)
    font_small = ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf', 11)
except Exception:
    font_large = ImageFont.load_default()
    font_small = font_large

text_y = iy + icon_size + 16
draw.text((BW // 2, text_y), 'DropDone', font=font_large, fill='white', anchor='mt')
draw.text((BW // 2, text_y + 30), '다운로드 자동 정리', font=font_small, fill=(180, 210, 255), anchor='mt')
draw.text((BW // 2, text_y + 48), 'v1.0.0', font=font_small, fill=(140, 180, 230), anchor='mt')

banner_path = os.path.join(ASSETS, 'installer_banner.bmp')
banner.save(banner_path, format='BMP')
print(f'[OK] {banner_path}')


# ─────────────────────────────────────────────────────
# 4. installer_icon.bmp  (55 × 58, WizardSmallImageFile)
# ─────────────────────────────────────────────────────
SW, SH = 55, 58
small_banner = Image.new('RGB', (SW, SH), BG_BLUE[:3])
icon_small   = draw_icon(46).convert('RGB')
sx = (SW - 46) // 2
sy = (SH - 46) // 2
small_banner.paste(icon_small, (sx, sy))

small_path = os.path.join(ASSETS, 'installer_icon.bmp')
small_banner.save(small_path, format='BMP')
print(f'[OK] {small_path}')

print()
print('assets/ 생성 완료:')
for f in os.listdir(ASSETS):
    fp = os.path.join(ASSETS, f)
    print(f'  {f}  ({os.path.getsize(fp):,} bytes)')
