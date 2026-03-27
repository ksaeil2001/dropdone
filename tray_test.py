import sys, os, time, threading
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pystray
from PIL import Image, ImageDraw

# 64x64 빨간 원 (최대한 눈에 띄게)
img = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
ImageDraw.Draw(img).ellipse([0, 0, 63, 63], fill=(255, 0, 0, 255))

icon = pystray.Icon('dropdone_test', img, 'DropDone TEST - 빨간 원')

def setup(icon):
    icon.visible = True
    print('>> 아이콘 표시 완료! 작업표시줄 오른쪽 ^ 눌러서 빨간 원 확인하세요', flush=True)

def auto_stop():
    time.sleep(20)
    print('>> 20초 경과, 종료합니다', flush=True)
    icon.stop()

threading.Thread(target=auto_stop, daemon=True).start()
print('>> tray 시작...', flush=True)
icon.run(setup=setup)
print('>> 종료됨', flush=True)
