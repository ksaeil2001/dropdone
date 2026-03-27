from plyer import notification


def show(title: str, message: str):
    notification.notify(
        title=title,
        message=message,
        app_name='DropDone',
        timeout=5,
    )
