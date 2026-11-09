import glob, os

for p in glob.glob("/proc/[0-9]*"):
    try:
        raw = open(p + "/cmdline", "rb").read().replace(b"\x00", b" ").decode(errors="replace").strip()
    except OSError:
        continue
    if "main.py run" in raw:
        print(p.rsplit("/", 1)[-1], "|", raw[:140])
