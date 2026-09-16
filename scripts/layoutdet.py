"""检测某一时刻是「共享屏+人像小窗」还是「纯摄像头全画面」。
依据：共享布局下右上角 (x1200-1280, y20-120) 是黑边；纯摄像头下那里是房间。"""
import subprocess
import os as _o
SRC=_o.environ['SRC']
def mode_at(t):
    raw=subprocess.run(['ffmpeg','-v','error','-i',SRC,'-ss',str(t),'-frames:v','1',
        '-vf','crop=80:100:1200:20,format=gray','-f','rawvideo','-'],capture_output=True).stdout
    if not raw: return 'unknown',None
    m=sum(raw)/len(raw)
    return ('screen' if m<20 else 'camera'), round(m,1)
if __name__=='__main__':
    for t in (200,1633,1735,1820,1856,3191,3245,3276,985):
        print(t, mode_at(t))
