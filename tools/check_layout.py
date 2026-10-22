"""仅检查自有界面的实际控件几何，不连接游戏。每个 DPI 独立 Tk 进程。"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def check(width, height, scale):
    import tkinter as tk
    from unittest.mock import patch
    from PIL import Image
    from app import App
    root = tk.Tk()
    root.tk.call('tk', 'scaling', scale * 96 / 72)
    with patch('app.work_area', return_value=(0, 0, width, height)):
        ui = App(root)
    assert 'maa_dir' not in ui.fields, 'obsolete-maa-path-visible'
    root.geometry(f'{width}x{height}+40+40')

    def settle():
        for _ in range(7):
            root.update()
            time.sleep(.025)

    def bounds(widget):
        x = widget.winfo_rootx() - root.winfo_rootx()
        y = widget.winfo_rooty() - root.winfo_rooty()
        return x, y, widget.winfo_width(), widget.winfo_height()

    try:
        settle()
        for button in ui.control_buttons:
            x, y, w, h = bounds(button)
            assert w > 1 and h > 1, ('unlaid-button', button.cget('text'))
            assert x >= 0 and y >= 0 and x+w <= root.winfo_width()+1 and y+h <= root.winfo_height()+1, ('clipped-button',bounds(button))
            assert w >= button.winfo_reqwidth(), ('truncated-button-text', button.cget('text'),w,button.winfo_reqwidth())
        ui.vars['six_star'].set('布局测试：不连接游戏')
        ui.tab.set('config'); ui.show_tab(); settle()
        ui.form_scroller.see(ui.fields['prepare_method']); settle()
        field=ui.fields['prepare_method']; canvas=ui.form_scroller.canvas
        assert field.winfo_rooty() >= canvas.winfo_rooty()-1
        assert field.winfo_rooty()+field.winfo_height() <= canvas.winfo_rooty()+canvas.winfo_height()+1
        assert ui.form_scroller.content.winfo_width() <= canvas.winfo_width()+1, 'horizontal-form-overflow'
        ui.logs.configure(state='normal'); ui.logs.insert('end','日志保留测试'); ui.logs.configure(state='disabled')
        ui.tab.set('monitor'); ui.show_tab()
        ui.last_frame=Image.new('RGB',(1280,720),'#123456'); ui.queue_preview(); settle()
        assert ui.vars['six_star'].get() == '布局测试：不连接游戏'
        assert '日志保留测试' in ui.logs.get('1.0','end')
        bbox=ui.preview_canvas.bbox('all'); pw=ui.preview_canvas.winfo_width(); ph=ui.preview_canvas.winfo_height()
        assert bbox and bbox[0]>=-1 and bbox[1]>=-1 and bbox[2]<=pw+1 and bbox[3]<=ph+1, ('preview-overflow',bbox,pw,ph)
        assert abs(ui.photo.width()/ui.photo.height()-16/9) < .05
        original_mode = ui._mode
        # 同一个窗口跨断点往返，已有配置、日志和截图必须保留。
        root.geometry(f'{max(1200, int(1200*scale))}x{height}')
        settle()
        assert ui._mode == 'wide'
        root.geometry(f'{width}x{height}')
        settle()
        assert ui._mode == original_mode
        assert ui.vars['six_star'].get() == '布局测试：不连接游戏'
        assert '日志保留测试' in ui.logs.get('1.0','end')
        return {'size':[width,height],'scale':scale,'mode':ui._mode,'buttons_visible':True,
                'last_field_reachable':True,'preview_inside_canvas':True,'settings_and_logs_preserved':True,
                'live_resize_preserved':True,'maa_path_removed':True}
    finally:
        root.destroy()


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--case', nargs=3, type=float)
    args=parser.parse_args()
    if args.case:
        w,h,s=args.case
        print(json.dumps(check(int(w),int(h),s),ensure_ascii=False))
    else:
        cases=[(1180,840,1),(900,620,1),(640,480,1),(1024,640,1.25),
               (1280,680,1.5),(1000,620,2),(800,560,2)]
        results=[]
        for w,h,s in cases:
            proc=subprocess.run([sys.executable,__file__,'--case',str(w),str(h),str(s)],capture_output=True,text=True,encoding='utf-8',
                                env={**os.environ,'PYTHONIOENCODING':'utf-8'})
            if proc.returncode:
                raise RuntimeError(f'{w}x{h}@{s}: {proc.stderr} {proc.stdout}')
            results.append(json.loads(proc.stdout))
        output=Path('runtime/layout-check.json'); output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(results,ensure_ascii=False))
