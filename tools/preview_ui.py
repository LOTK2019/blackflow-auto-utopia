"""只预览界面，永不自动连接或启动游戏。"""
import argparse
from pathlib import Path
import sys
import tkinter as tk
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import App
from blackflow.ui_layout import enable_dpi_awareness

parser=argparse.ArgumentParser()
parser.add_argument('--size',default='900x620')
parser.add_argument('--scale',type=float,default=1)
parser.add_argument('--image')
args=parser.parse_args()
enable_dpi_awareness()
root=tk.Tk(); root.tk.call('tk','scaling',args.scale*96/72)
app=App(root)
root.geometry(args.size+'+60+60')
root.title('布局预览 · '+args.size)
if args.image:
    app.last_frame=Image.open(args.image).convert('RGB')
    app.queue_preview()
root.mainloop()
