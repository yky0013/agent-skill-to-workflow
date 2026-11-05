"""Double-click launcher on Windows; uses .venv when installed there."""

import os
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parent
local_python = root / ".venv" / "Scripts" / "pythonw.exe"
if local_python.is_file() and Path(sys.executable).resolve() != local_python.resolve():
    subprocess.Popen([str(local_python), str(Path(__file__).resolve())], cwd=root)
else:
    os.chdir(root)
    try:
        from skill_workflow.gui import launch
        launch()
    except Exception as exc:
        import tkinter as tk
        from tkinter import messagebox
        window = tk.Tk()
        window.withdraw()
        messagebox.showerror("工作台未启动", f"{exc}\n\n请先在仓库目录安装：python -m pip install -e .", parent=window)
        window.destroy()
