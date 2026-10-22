#!/usr/bin/env python3
"""Drive a tools/vm/vm.sh VM through the QEMU monitor (HMP).

usage: mon.py shot NAME.png     screenshot into $GBVM_DIR/shots (needs Pillow)
       mon.py type 'text' [noenter]   type text (KD = delay per key, default 0.1 s)
       mon.py <any HMP command>       e.g. mon.py sendkey ctrl-alt-f3, mon.py quit
"""
import os
import socket
import sys
import time

DIR = os.environ.get("GBVM_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".vm"))
SOCK = os.path.join(DIR, "mon.sock")
KEYS = {' ': 'spc', '-': 'minus', '.': 'dot', '/': 'slash', '|': 'shift-backslash', '\\': 'backslash',
        '<': 'shift-comma', ',': 'comma', '{': 'shift-bracket_left', '}': 'shift-bracket_right', '@': 'shift-2',
        '#': 'shift-3', '%': 'shift-5', '^': 'shift-6', '+': 'shift-equal', '>': 'shift-dot', '~': 'shift-grave_accent',
        '_': 'shift-minus', '=': 'equal', ':': 'shift-semicolon', '*': 'shift-8', '"': 'shift-apostrophe',
        "'": 'apostrophe', ';': 'semicolon', '$': 'shift-4', '(': 'shift-9', ')': 'shift-0', '[': 'bracket_left',
        ']': 'bracket_right', '?': 'shift-slash', '!': 'shift-1', '&': 'shift-7'}


def cmd(c, timeout=5):
    s = socket.socket(socket.AF_UNIX); s.settimeout(timeout); s.connect(SOCK)
    def rd():
        b = b''
        try:
            while not b.endswith(b'(qemu) '):
                chunk = s.recv(65536)
                if not chunk:  # monitor closed (e.g. after quit); avoid busy loop
                    break
                b += chunk
        except socket.timeout:
            pass
        return b
    rd(); s.send((c + '\n').encode()); r = rd(); s.close()
    return r.decode(errors='ignore')


def shot(name):
    """GBVM_OUTPUTS=N (vm.sh adds GPUs vga1..): each screen is dumped, side by side."""
    from PIL import Image
    heads = int(os.environ.get('GBVM_OUTPUTS', '1') or 1)
    imgs = []
    for i in range(heads):
        ppm = os.path.join(DIR, 'shot%d.ppm' % i)
        if os.path.exists(ppm):
            os.remove(ppm)
        cmd('screendump ' + ppm + (' vga%d' % i if heads > 1 else '')); time.sleep(1)
        if os.path.exists(ppm):
            imgs.append(Image.open(ppm).convert('RGB'))
    out = os.path.join(DIR, 'shots', name)
    if len(imgs) == 1:
        imgs[0].save(out)
    else:
        w = sum(im.width for im in imgs) + 8 * (len(imgs) - 1)
        canvas = Image.new('RGB', (w, max(im.height for im in imgs)), (255, 0, 255))
        x = 0
        for im in imgs:
            canvas.paste(im, (x, 0)); x += im.width + 8
        canvas.save(out)
    print('saved', out)


def type_text(text, enter=True):
    ks = [KEYS.get(ch, ('shift-' + ch.lower()) if ch.isupper() else ch) for ch in text]
    if enter:
        ks.append('ret')
    delay = float(os.environ.get('KD', '0.1'))
    for k in ks:
        cmd('sendkey %s 100' % k, timeout=2); time.sleep(delay)


if __name__ == '__main__':
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)
    if a[0] == 'shot':
        shot(a[1])
    elif a[0] == 'type':
        type_text(a[1], enter=len(a) < 3)
    else:
        print(cmd(' '.join(a)))
