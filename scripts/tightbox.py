import os as _o
SRC=_o.environ['SRC']
import subprocess, json, sys
# 在给定时间窗内采样若干帧，用亮度阈值求"内容包围盒"，再扩成 16:9 的死框（全块不动）
def bbox(t, W=960, H=488, X0=0, Y0=132):
    raw = subprocess.run(['ffmpeg','-v','error','-ss',str(t),'-i',SRC,'-frames:v','1',
        '-vf',f'crop={W}:{H}:{X0}:{Y0},format=gray','-f','rawvideo','-'],capture_output=True).stdout
    if len(raw) < W*H: return None
    THR=95
    # 排除 Excalidraw UI：顶部工具条/右上按钮/左侧面板/底部缩放控件
    XA,XB,YA,YB = 26, 900, 62, 440
    minx,maxx,miny,maxy=W,0,H,0
    for y in range(YA,YB,2):
        row=raw[y*W:(y+1)*W]
        xs=[x for x in range(XA,XB,2) if row[x]>THR]
        if xs:
            miny=min(miny,y); maxy=max(maxy,y)
            minx=min(minx,xs[0]); maxx=max(maxx,xs[-1])
    if maxx<=minx or maxy<=miny: return None
    return minx,miny,maxx,maxy

def tight_crop(t0,t1):
    boxes=[b for b in (bbox(t) for t in (t0+0.5,(t0+t1)/2,t1-0.5)) if b]
    if not boxes: return None
    minx=min(b[0] for b in boxes); miny=min(b[1] for b in boxes)
    maxx=max(b[2] for b in boxes); maxy=max(b[3] for b in boxes)
    pad=26
    minx=max(0,minx-pad); miny=max(0,miny-pad); maxx=min(960,maxx+pad); maxy=min(488,maxy+pad)
    w=maxx-minx; h=maxy-miny
    # 扩成 16:9，并保证比 WIDE 明显更紧（否则这一刀没意义）
    if w/h < 16/9:
        nw=h*16/9
        cx=(minx+maxx)/2; minx=cx-nw/2; maxx=cx+nw/2
    else:
        nh=w*9/16
        cy=(miny+maxy)/2; miny=cy-nh/2; maxy=cy+nh/2
    minx=max(0,minx); miny=max(0,miny); maxx=min(960,maxx); maxy=min(488,maxy)
    w=int((maxx-minx)//2*2); h=int((maxy-miny)//2*2)
    if w>=820 and h>=420: return None   # 和 WIDE 差不多，就别切了
    return int(minx)//2*2, int(miny)//2*2, w, h

if __name__=='__main__':
    sub=json.load(open('sub_v3.json'))
    out=[]
    for i,(a,b,sid) in enumerate(sub):
        mode='WIDE' if i%2==0 else 'TIGHT'
        c=tight_crop(a,b) if mode=='TIGHT' else None
        if mode=='TIGHT' and not c: mode='WIDE'
        out.append(dict(a=a,b=b,seg=sid,mode=mode,crop=c))
        print(f"{i:2} S{sid} {a:7.2f}-{b:7.2f} {mode:5} {c}")
    json.dump(out,open('plan_v3.json','w'))
