#!/bin/bash
# 把 BakaSU(ReSukiSU) 接线进内核树：drivers/Makefile + drivers/Kconfig + 符号链接
# 用法: wire_kernelsu.sh <内核树>
set -euo pipefail
TREE=$(realpath "${1:?用法: wire_kernelsu.sh <内核树>}")
[ -d "$TREE/drivers" ] || { echo "[!] $TREE 不是内核树"; exit 1; }
[ -f "$TREE/KernelSU/kernel/Kbuild" ] || { echo "[!] 缺少 $TREE/KernelSU/kernel/Kbuild（请先克隆 Baka-SU/BakaSU 到 KernelSU/）"; exit 1; }

if ! grep -q "kernelsu" "$TREE/drivers/Makefile"; then
  printf '\nobj-$(CONFIG_KSU) += kernelsu/\n' >> "$TREE/drivers/Makefile"
  echo "[+] drivers/Makefile 已追加 obj-\$(CONFIG_KSU) += kernelsu/"
else
  echo "[=] drivers/Makefile 已包含 kernelsu"
fi

if ! grep -q 'drivers/kernelsu/Kconfig' "$TREE/drivers/Kconfig"; then
  python3 - "$TREE/drivers/Kconfig" <<'PY'
import sys, pathlib
p = pathlib.Path(sys.argv[1])
s = p.read_text()
i = s.rstrip().rfind("endmenu")
assert i > 0, "找不到 endmenu"
p.write_text(s[:i] + 'source "drivers/kernelsu/Kconfig"\n' + s[i:])
PY
  echo "[+] drivers/Kconfig 已引入 kernelsu/Kconfig"
else
  echo "[=] drivers/Kconfig 已包含 kernelsu/Kconfig"
fi

ln -sfn ../KernelSU/kernel "$TREE/drivers/kernelsu"
echo "[+] 符号链接 drivers/kernelsu -> ../KernelSU/kernel"
