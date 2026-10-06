import asyncio
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import yaml


def get_config(base_dir: Path, definition_provider):
    config_path = base_dir / "config" / "settings.yaml"

    if not config_path.exists():
        return {"error": "Configuration file not found", "is_first_run": True}

    with open(config_path, "r", encoding="utf-8") as f:
        current_config = yaml.safe_load(f)

    return {
        "config": current_config,
        "definition": definition_provider(),
        "is_first_run": False,
    }


def save_config(req, base_dir: Path, set_nested_value):
    config_path = base_dir / "config" / "settings.yaml"
    config_dir = config_path.parent
    config_dir.mkdir(parents=True, exist_ok=True)

    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            current_config = yaml.safe_load(f) or {}
    else:
        current_config = {
            "paths": {},
            "processing": {},
            "recognition": {},
            "web": {},
        }

    db_path_changed = False
    old_db_path = current_config.get("paths", {}).get("db_path", "")

    for item in req.configs:
        value = item.value

        if item.section == "paths" and item.key == "db_path" and value != old_db_path:
            db_path_changed = True

        if item.type == "int":
            value = int(value)
        elif item.type == "float":
            value = float(value)
        elif item.type == "bool":
            value = value.lower() in ("true", "yes", "1", "on")

        set_nested_value(current_config, f"{item.section}.{item.key}", value)

    if db_path_changed:
        new_db_path = current_config.get("paths", {}).get("db_path", "")
        if new_db_path:
            db_path_obj = Path(new_db_path)
            if not db_path_obj.parent.exists():
                try:
                    db_path_obj.parent.mkdir(parents=True, exist_ok=True)
                except Exception as exc:
                    return {"status": "error", "error": f"无法创建数据库目录: {exc}"}
            try:
                test_file = db_path_obj.parent / ".wingscribe_db_test"
                test_file.touch()
                test_file.unlink()
            except Exception as exc:
                return {"status": "error", "error": f"数据库目录不可写: {exc}"}

    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(current_config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    if db_path_changed:
        return {"status": "saved", "restart_required": True, "db_path_changed": True}

    if req.restart:
        return {"status": "saved", "restart_required": True}

    return {"status": "saved"}


def restart_server(base_dir: Path, config: dict, startup_host, startup_port, startup_python: str, logger):
    host = startup_host or config["web"]["host"]
    port = startup_port or config["web"]["port"]

    app_path = str(base_dir / "src" / "web" / "app.py")
    cmd = [startup_python, app_path, "--host", str(host), "--port", str(port)]

    logger.info("Restarting server with command: %s", " ".join(cmd))

    def _delayed_exit():
        time.sleep(3)
        logger.info("Exiting old server process")
        os._exit(0)

    try:
        subprocess.Popen(
            cmd,
            cwd=str(base_dir),
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
        )

        exit_thread = threading.Thread(target=_delayed_exit, daemon=True)
        exit_thread.start()
        return {"status": "restarting", "message": "Server restarting..."}
    except Exception as exc:
        logger.error("Failed to restart server: %s", exc)
        return {"error": str(exc)}


def validate_config_path(path: str, path_type: str = "directory"):
    try:
        p = Path(path)
        exists = p.exists()
        is_dir = p.is_dir() if exists else False
        is_file = p.is_file() if exists else False
        can_write = False
        can_read = False

        if exists:
            try:
                if is_file:
                    with open(p, "rb") as f:
                        f.read(1)
                    can_read = True
                elif is_dir:
                    list(p.iterdir())
                    can_read = True
            except Exception:
                pass

            try:
                if is_dir:
                    test_file = p / ".wingscribe_write_test"
                    test_file.touch()
                    test_file.unlink()
                elif is_file:
                    test_file = p.parent / ".wingscribe_write_test"
                    test_file.touch()
                    test_file.unlink()
                can_write = True
            except Exception:
                pass

        return {
            "exists": exists,
            "is_directory": is_dir,
            "is_file": is_file,
            "can_write": can_write,
            "can_read": can_read,
        }
    except Exception as exc:
        return {"error": str(exc)}


def _ps_folder_dialog(title: str, initial_dir: str = "") -> str:
    """Windows 回退方案：用 PowerShell 的 FolderBrowserDialog 选文件夹。"""
    ps_script = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$d = New-Object System.Windows.Forms.FolderBrowserDialog; "
        f"$d.Description = {_ps_quote(title)}; "
    )
    if initial_dir and os.path.isdir(initial_dir):
        ps_script += f"$d.SelectedPath = {_ps_quote(initial_dir)}; "
    ps_script += "if ($d.ShowDialog() -eq 'OK') { $d.SelectedPath }"
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True, text=True, timeout=120,
        )
        path = out.stdout.strip()
        return path if path else ""
    except Exception as exc:
        raise Exception(f"PowerShell 文件夹对话框失败: {exc}")


def _ps_file_dialog(title: str, initial_file: str = "", file_types: str = "") -> str:
    """Windows 回退方案：用 PowerShell 的 OpenFileDialog 选文件。"""
    filter_str = "All Files (*.*)|*.*"
    if file_types:
        parts = [f"{ft} (*.{ft})|*.{ft}" for ft in file_types.split("|") if ft]
        if parts:
            filter_str = "|".join(parts)
    ps_script = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$d = New-Object System.Windows.Forms.OpenFileDialog; "
        f"$d.Title = {_ps_quote(title)}; "
        f"$d.Filter = {_ps_quote(filter_str)}; "
    )
    if initial_file:
        ps_script += f"$d.FileName = {_ps_quote(initial_file)}; "
    ps_script += "if ($d.ShowDialog() -eq 'OK') { $d.FileName }"
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True, text=True, timeout=120,
        )
        path = out.stdout.strip()
        return path if path else ""
    except Exception as exc:
        raise Exception(f"PowerShell 文件对话框失败: {exc}")


def _ps_quote(s: str) -> str:
    """将字符串安全地嵌入 PowerShell 单引号字符串。"""
    return "'" + str(s).replace("'", "''") + "'"


def open_folder_dialog(title: str, initial_dir: str = "") -> str:
    result = {"path": None, "error": None}

    def _run_dialog():
        try:
            import tkinter as tk
            from tkinter import filedialog

            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            folder = filedialog.askdirectory(title=title, initialdir=initial_dir or None)
            root.destroy()
            result["path"] = folder
        except Exception:
            # tkinter 不可用时（如精简版 Python），回退到 PowerShell 对话框
            if sys.platform.startswith("win"):
                try:
                    result["path"] = _ps_folder_dialog(title, initial_dir)
                except Exception as exc:
                    result["error"] = str(exc)
            else:
                result["error"] = "tkinter 不可用，请手动输入路径"

    thread = threading.Thread(target=_run_dialog)
    thread.start()
    thread.join()

    if result["error"]:
        raise Exception(result["error"])
    return result["path"]


def open_file_dialog(title: str, initial_file: str = "", file_types: str = "") -> str:
    result = {"path": None, "error": None}

    def _run_dialog():
        try:
            import tkinter as tk
            from tkinter import filedialog

            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)

            filetypes = []
            if file_types:
                for ft in file_types.split("|"):
                    if ft:
                        filetypes.append((ft, f"*.{ft}"))

            file = filedialog.askopenfilename(
                title=title,
                initialfile=initial_file or None,
                filetypes=filetypes if filetypes else [("All Files", "*.*")],
            )
            root.destroy()
            result["path"] = file
        except Exception:
            if sys.platform.startswith("win"):
                try:
                    result["path"] = _ps_file_dialog(title, initial_file, file_types)
                except Exception as exc:
                    result["error"] = str(exc)
            else:
                result["error"] = "tkinter 不可用，请手动输入路径"

    thread = threading.Thread(target=_run_dialog)
    thread.start()
    thread.join()

    if result["error"]:
        raise Exception(result["error"])
    return result["path"]


async def browse_folder_api(title: str = "选择文件夹", initial_path: str = ""):
    try:
        folder_path = await asyncio.to_thread(open_folder_dialog, title, initial_path)
        return {"path": folder_path}
    except Exception as exc:
        return {"error": str(exc), "path": None}


async def browse_file_api(title: str = "选择文件", initial_path: str = "", file_types: str = "xlsx|xls"):
    try:
        file_path = await asyncio.to_thread(open_file_dialog, title, initial_path, file_types)
        return {"path": file_path}
    except Exception as exc:
        return {"error": str(exc), "path": None}
