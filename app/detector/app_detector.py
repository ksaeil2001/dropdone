"""
앱 감지 모듈 — psutil 기반 실행 중 앱 동적 감지 + Hitomi 핸들 검사

- get_running_download_apps(): 실행 중인 프로세스 목록 반환 (사용자 선택용)
- has_open_handles(pid, directory): 특정 프로세스가 디렉토리에 열린 핸들이 있는지
- is_hitomi_busy(download_dir): Hitomi Downloader가 해당 폴더에 활성 핸들 보유 중인지
- has_hitomi_temp_files(download_dir): Hitomi 임시 파일(tmp*.tmp 등)이 남아 있는지
"""

import os
import glob
import psutil


def get_running_download_apps() -> list[dict]:
    """
    실행 중인 프로세스 목록 반환.
    특정 앱 이름을 하드코딩하지 않고 사용자가 선택하도록 동적 제공.
    """
    apps = []
    for proc in psutil.process_iter(['pid', 'name', 'exe']):
        try:
            exe = proc.info['exe']
            if exe and os.path.exists(exe):
                apps.append({
                    'pid':  proc.info['pid'],
                    'name': proc.info['name'],
                    'exe':  exe,
                })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return apps


def has_open_handles(pid: int, directory: str) -> bool:
    """지정 PID가 directory 하위에 열린 파일 핸들을 보유하고 있는지 확인."""
    try:
        proc = psutil.Process(pid)
        for f in proc.open_files():
            if f.path.lower().startswith(directory.lower()):
                return True
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        pass
    return False


def find_process_by_name(name: str) -> list[psutil.Process]:
    """프로세스 이름으로 실행 중인 프로세스 목록 반환."""
    result = []
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            if proc.info['name'] and proc.info['name'].lower() == name.lower():
                result.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return result


def is_hitomi_busy(download_dir: str) -> bool:
    """
    Hitomi Downloader (hitomi_downloader_GUI.exe)가
    download_dir에 활성 파일 핸들을 보유하고 있는지 확인.
    """
    for proc in find_process_by_name('hitomi_downloader_GUI.exe'):
        if has_open_handles(proc.pid, download_dir):
            return True
    return False


def has_hitomi_temp_files(download_dir: str) -> bool:
    """
    Hitomi 임시 파일(tmp*.tmp, tmp*_v.*, tmp*_a.*, tmp*_o.*)이
    download_dir에 존재하는지 확인.
    """
    patterns = ['tmp*.tmp', 'tmp*_v.*', 'tmp*_a.*', 'tmp*_o.*']
    for pattern in patterns:
        if glob.glob(os.path.join(download_dir, pattern)):
            return True
    return False


def is_download_app_active(download_dir: str) -> bool:
    """
    임시파일 존재 여부 + Hitomi 핸들 검사를 결합하여
    다운로드가 아직 진행 중인지 판단.
    """
    if has_hitomi_temp_files(download_dir):
        return True
    if is_hitomi_busy(download_dir):
        return True
    return False
