import os
import sys
import json
import hashlib
import tempfile
import shutil
import os, tempfile, yaml
from pathlib import Path
from .logger import get_logger, LoggerConfig

import requests

APP_VERSION = "1.0.0"
OWNER = "carsupper665"
REPO = "TensorRT-YOLO-assist"
VERSION_URL = f"https://api.github.com/repos/{OWNER}/{REPO}/releases/latest"

class Updater():
    def __init__(self, install_dir: str | Path | None = None, on_update_func: callable = None, value: int = None):
        self.app_ver = APP_VERSION
        self.install_dir = Path(install_dir or os.path.dirname(os.path.abspath(sys.argv[0])))
        self.on_update: callable | None = on_update_func if on_update_func is not None else self._on_update
        self.value = value if value is not None else 0
        log_cfg = LoggerConfig(
            name="Updater",
            level="info",
            to_file=True,
            rotate=False,
            file_name="Updater-log",
            static_file_name=True
        )
        self.logger = get_logger(log_cfg)

    def get_current_ver(self) -> str:
        return self.app_ver
    
    def _on_update(self, **args):
        return

    def get_latest(self) -> dict:
        r = requests.get(url=VERSION_URL, timeout=30)
        r.raise_for_status()
        return r.json()

    @staticmethod
    def _parse_version(ver: str) -> tuple[int, ...]:
        # 把 "TR-0.1.0" -> "0.1.0"
        for prefix in ("TR-", "tr-", "v", "V"):
            if ver.startswith(prefix):
                ver = ver[len(prefix):]
                break
        return tuple(int(x) for x in ver.split("."))

    def _is_newer(self, remote: str, local: str) -> bool:
        return self._parse_version(remote) > self._parse_version(local)

    def _download_file(self, url: str, dst: Path) -> str:
        """下載檔案並回傳 sha256"""
        h = hashlib.sha256()
        last_print = -1
        downloaded = 0
        self.logger.info("Downloading File....")
        with requests.get(url, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(dst, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if not chunk:
                        continue
                    f.write(chunk)
                    h.update(chunk)
                    downloaded += len(chunk)
                    # 每下載一段就簡單顯示一次（或改成每 N KB 顯示）
                    mb = downloaded / (1024 * 1024)
                    if mb != last_print:
                        last_print = mb
                        self.on_update(id="update", status=f"Downloading... {mb:.2f} MB", value=self.value)
                        print(
                            f"\rDownloading... {mb:.2f} MB",
                            end="",
                            flush=True,
                        )
                        
        return h.hexdigest()

    def backup(self, backup_dir: Path | None = None) -> Path:
        """簡單把目前安裝目錄備份一份"""
        backup_dir = backup_dir or (self.install_dir.parent / (self.install_dir.name + "_backup"))
        backup_dir = Path(backup_dir)
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
        shutil.copytree(self.install_dir, backup_dir)
        return backup_dir

    def _apply_update_zip(self, zip_path: Path):
        """
        最簡單版本：解壓 zip 覆蓋到 install_dir
        """
        self.logger.info("unzip file....")
        tmp_dir = Path(tempfile.mkdtemp(prefix="update_tmp_"))
        try:
            inner_zip: Path | None = None
            for root, dirs, files in os.walk(zip_path):
                for name in files:
                    if name.lower().endswith(".zip"):
                        inner_zip = Path(root) / name
                        break
                if inner_zip is not None:
                    break

            if inner_zip is None:
                raise FileNotFoundError(f"no .zip file found under {zip_path}")
            shutil.unpack_archive(str(inner_zip), tmp_dir)
            # 假設 zip 裡面是「直接就是程式內容」，沒有多一層資料夾
            zip_root = next(tmp_dir.iterdir())  # 你已經確定結構固定
            for src_root, dirs, files in os.walk(zip_root):
                rel = Path(src_root).relative_to(zip_root)

                dst_dir = self.install_dir / rel
                dst_dir.mkdir(parents=True, exist_ok=True)
                for name in files:
                    src = Path(src_root) / name
                    dst = dst_dir / name
                    print(f'Copy file: {src} to: {dst}')
                    shutil.move(str(src), str(dst))
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def _update_config(self,) -> dict | None:
        default = self.install_dir / "config" / "default.yaml"
        old = self.install_dir / "config" / "config.yaml"

        old_cfg = self._load_yaml(old)
        new_cfg = self._load_yaml(default)

        new_keys = set(new_cfg.keys())
        old_keys = set(old_cfg.keys())

        if new_keys == old_keys:
            return None
        
        # TODO: key 內可能有 更多 key 需要比較
        
        updated_data = old_cfg
        for nk, nv in new_cfg.items():
            if nk not in old_keys:
                updated_data[nk] = nv
        return updated_data
    
    def _save_new(self, path: str, data: dict):
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            dir_ = os.path.dirname(os.path.abspath(path)) or "."
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=dir_, delete=False
            ) as tf:
                tmp = tf.name
                yaml.safe_dump(
                    data,
                    tf,
                    sort_keys=False,
                    allow_unicode=True,
                    default_flow_style=False,
                )
                tf.flush()
                os.fsync(tf.fileno())
            os.replace(tmp, path)
        except Exception as e:
            sys.__excepthook__(type(e), e, None)
            raise e
            

    def _load_yaml(self, path: Path) -> dict:
        import yaml

        if not path.exists():
            # copy default
            raise FileNotFoundError(f"File Not found at: {path}")
        
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data
    
    def compear_cfg_and_update(self):
        new_data = self._update_config()
        if new_data is None:
            return
        path = str(self.install_dir / "config" / "config.yaml")
        self._save_new(path, new_data)

    def start_update(self) -> tuple[bool, Exception | None]:
        """
        回傳 (True, None) 表示已安裝新版本（應該重啟 APP）
        回傳 (False, None) 表示不需要更新
        回傳 (False, Exception) 表示更新失敗
        """
        try:
            info = self.get_latest()
            tag_name = info["tag_name"]     
            pkg_name = tag_name + "-pkg.zip"
            assets = info["assets"]

            # 沒有新版本
            if not self._is_newer(tag_name, self.app_ver):
                self.logger.warning("already latest version")
                return False, None

            # 先找到 version.json asset
            ver_asset = assets[0]
            if ver_asset is None:
                self.logger.error("no version.json asset found")
                return False, FileNotFoundError("No update info file")

            ver_url = ver_asset["browser_download_url"]  # 這裡用 browser_download_url 才是直接下載檔案
            with tempfile.TemporaryDirectory() as tmpdir:
                tmpdir = Path(tmpdir)
                version_json_path = tmpdir / "version.json"

                # 下載 version.json
                self._download_file(ver_url, version_json_path)
                ver_info = json.loads(version_json_path.read_text(encoding="utf-8"))

                remote_ver = ver_info["version"]

                expected_sha = ver_info.get("sha256", "").lower()

                if not self._is_newer(remote_ver, self.app_ver):
                    self.logger.warning("version.json says no newer version")
                    return False, None

                zipball_url = info["zipball_url" ] 
                pkg_url = zipball_url
                pkg_path = tmpdir / pkg_name

                # 下載更新包
                real_sha = self._download_file(pkg_url, pkg_path)
                if expected_sha and real_sha.lower() != expected_sha:
                    self.logger.info(f"expected: {expected_sha}, \nbut got: {real_sha.lower()}")
                    self.logger.warning("sha256 mismatch, abort update")
                    return False, None

                _bk_path = self.backup()
                self.logger.info(f"Back up to: {_bk_path}")

                self._apply_update_zip(tmpdir)

                self.compear_cfg_and_update()
        except Exception as e:
            import traceback

            tb_text = "".join(traceback.TracebackException.from_exception(e).format())
            # sys.__excepthook__(type, e, None)
            self.logger.error(f"Update error: {tb_text}")
            print(f"update Fail!!, log in {self.install_dir / 'log'}")
            return False, e

        # 到這裡表示更新成功
        self.logger.info("update success, please restart app")
        return True, None
    
if __name__ == "__main__":
    u = Updater("D:\python-test\test-temp")
    u.start_update()
    