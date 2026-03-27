import webbrowser
import pystray
from PIL import Image, ImageDraw
from app.config import DASHBOARD_HOST, DASHBOARD_PORT
from app.engine.db import get_setting


def _create_icon_image():
    img = Image.new('RGB', (64, 64), color=(26, 115, 232))
    d = ImageDraw.Draw(img)
    d.rectangle([20, 28, 44, 44], fill='white')
    d.polygon([(32, 48), (18, 30), (46, 30)], fill='white')
    return img


def build_tray(on_quit):
    def open_dashboard(icon, item):
        token = get_setting('api_token', '')
        base  = f'http://{DASHBOARD_HOST}:{DASHBOARD_PORT}'
        if get_setting('onboarding_complete', 'false') == 'true':
            webbrowser.open(f'{base}/?token={token}')
        else:
            webbrowser.open(f'{base}/onboarding?token={token}')

    def quit_app(icon, item):
        icon.stop()
        on_quit()

    menu = pystray.Menu(
        pystray.MenuItem('대시보드 열기', open_dashboard, default=True),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem('종료', quit_app),
    )

    icon = pystray.Icon(
        name='DropDone',
        icon=_create_icon_image(),
        title='DropDone',
        menu=menu,
    )

    # pystray 0.19.x: setup 콜백에서 visible=True 명시 필요
    def setup(icon):
        icon.visible = True

    icon._setup = setup
    return icon
