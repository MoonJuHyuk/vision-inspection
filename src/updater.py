"""
자동 업데이트 모듈
- .exe 실행 시에만 작동 (소스코드 실행 중에는 스킵)
- GitHub Releases API로 최신 버전 확인
- 새 버전이 있으면 다운로드 후 배치 파일로 교체 + 재시작
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

GITHUB_REPO = "MoonJuHyuk/vision-inspection"
ASSET_NAME   = "vision_inspection.zip"


def _parse_ver(v):
    try:
        return tuple(int(x) for x in v.strip().lstrip("v").split("."))
    except Exception:
        return (0,)


def check_and_update(current_version):
    """시작 시 호출. 새 버전이 있으면 다운로드 후 재시작, 없으면 즉시 반환."""
    if not getattr(sys, "frozen", False):
        return  # 개발 환경(소스 실행)에서는 스킵

    print(f"[UPDATE] 현재 버전: {current_version}  업데이트 확인 중...")
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
        req = urllib.request.Request(url, headers={"User-Agent": "vision-inspection-updater"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read())

        latest_tag = data["tag_name"]
        if _parse_ver(latest_tag) <= _parse_ver(current_version):
            print(f"[UPDATE] 최신 버전입니다.")
            return

        print(f"[UPDATE] 새 버전 발견: {latest_tag} → 다운로드 중...")

        zip_url = next(
            (a["browser_download_url"] for a in data["assets"]
             if a["name"] == ASSET_NAME),
            None,
        )
        if not zip_url:
            print("[UPDATE] 배포 파일을 찾지 못했습니다. 건너뜁니다.")
            return

        # 다운로드
        tmp_zip = os.path.join(tempfile.gettempdir(), "vi_update.zip")
        urllib.request.urlretrieve(zip_url, tmp_zip)

        # 압축 해제
        tmp_dir = os.path.join(tempfile.gettempdir(), "vi_update_files")
        if os.path.exists(tmp_dir):
            shutil.rmtree(tmp_dir)
        with zipfile.ZipFile(tmp_zip, "r") as zf:
            zf.extractall(tmp_dir)

        src_dir  = os.path.join(tmp_dir, "vision_inspection")
        dest_dir = os.path.dirname(sys.executable)
        exe_path = sys.executable

        # 배치 파일: 현재 프로세스 종료 후 파일 교체 → 재시작
        bat = os.path.join(tempfile.gettempdir(), "vi_update.bat")
        with open(bat, "w", encoding="cp949") as f:
            f.write(
                f"@echo off\n"
                f"echo 업데이트 적용 중... {latest_tag}\n"
                f"timeout /t 2 /nobreak > nul\n"
                # settings.py와 data 폴더는 현장 설정 보존 (덮어쓰지 않음)
                f'robocopy "{src_dir}" "{dest_dir}" /E /XF settings.py /XD data'
                f" /NFL /NDL /NJH /NJS\n"
                f'start "" "{exe_path}"\n'
                f'del "%~f0"\n'
            )

        print(f"[UPDATE] 업데이트를 적용하고 재시작합니다...")
        subprocess.Popen(["cmd", "/c", bat], creationflags=subprocess.CREATE_NEW_CONSOLE)
        sys.exit(0)

    except Exception as e:
        print(f"[UPDATE] 확인 실패 (무시하고 계속 실행): {e}")
