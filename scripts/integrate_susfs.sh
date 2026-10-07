#!/bin/bash
# 为 Linux 4.9 内核集成 SUSFS v2.3.0 (NON-GKI) + BakaSU(ReSukiSU) inline hooks
# 用法: integrate_susfs.sh <内核树>
#
# 顺序很重要：
#   1) 打 SUSFS 内核侧补丁（20 文件）
#   2) 4.9(无 statx) fixup + 清 .rej
#   3) 接线 KernelSU（必须先建好 drivers/kernelsu 符号链接！注入器要靠它判断
#      BakaSU 是否有 ksu_handle_setresuid，否则会跳过 kernel/sys.c）
#   4) 注入 7 个 inline hook
#   5) 校验（BakaSU 的 kernel/tools/inline_hook_check.mk 在 Kbuild 阶段会硬校验这 7 个钩子，
#      缺失即 $(error) 中断编译，所以必须编译前全部就位）
set -euo pipefail

TREE=$(realpath "${1:?用法: integrate_susfs.sh <内核树>}")
HERE=$(cd "$(dirname "$0")" && pwd)
PATCHES="$HERE/../patches"
cd "$TREE"

echo "=== [1/5] 应用 SUSFS v2.3.0 4.9 内核补丁 ==="
if [ -f fs/susfs.c ] && grep -q "SUSFS_VERSION" include/linux/susfs.h 2>/dev/null; then
  echo "[=] SUSFS 已存在，跳过"
else
  set +e
  # -l: 忽略空白差异（补丁里有一处纯空白 hunk）
  patch -p1 -l --forward --fuzz=3 --no-backup-if-mismatch < "$PATCHES/susfs_patch_to_4.9.patch"
  rc=$?
  set -e
  echo "[i] patch 退出码=$rc"
fi

echo "=== [2/5] 4.9（无 statx）fixup ==="
REJ=$(find . -name '*.rej' -not -path './KernelSU/*' | wc -l)
echo "[i] 待处理 .rej: $REJ"
if [ "$REJ" -ne 0 ]; then
  python3 "$HERE/fixup_4.9_nostatx.py" "$TREE"
  REJ2=$(find . -name '*.rej' -not -path './KernelSU/*' | wc -l)
  [ "$REJ2" -eq 0 ] || { echo "[!] 仍有未处理的 .rej:"; find . -name '*.rej' -not -path './KernelSU/*'; exit 1; }
fi
for f in fs/susfs.c include/linux/susfs.h include/linux/susfs_def.h; do
  [ -f "$f" ] || { echo "[!] 缺少 $f，SUSFS 补丁未成功"; exit 1; }
done
echo "[+] SUSFS $(grep -o '"v[0-9.]*"' include/linux/susfs.h | head -1) 已就位"

echo "=== [3/5] 接线 KernelSU（必须先于注入器）==="
bash "$HERE/wire_kernelsu.sh" "$TREE"

echo "=== [4/5] 注入 BakaSU inline hooks ==="
bash "$PATCHES/susfs_inline_hook_bakasu.sh" "$TREE"

echo "=== [5/5] 校验 inline_hook_check.mk 所需的 7 个钩子 ==="
bad=0
check() { if grep -q "$2" "$1"; then echo "  OK  $1 : $2"; else echo "  BAD $1 : 缺少 $2"; bad=1; fi; }
check kernel/sys.c            ksu_handle_setresuid
check fs/exec.c               ksu_handle_execveat
check fs/open.c               ksu_handle_faccessat
check fs/read_write.c         ksu_handle_sys_read
check fs/stat.c               ksu_handle_stat
check kernel/reboot.c         ksu_handle_sys_reboot
check drivers/input/input.c   ksu_handle_input_handle_event

for pair in fs/read_write.c:ksu_vfs_read_hook drivers/input/input.c:ksu_input_hook \
            fs/exec.c:ksu_execveat_hook fs/read_write.c:ksu_init_rc_hook fs/stat.c:ksu_init_rc_hook; do
  f=${pair%%:*}; sym=${pair##*:}
  if grep -qw "$sym" "$f"; then echo "  BAD $f 含不兼容旧钩子 $sym"; bad=1; fi
done

[ "$bad" -eq 0 ] || { echo "[!] 钩子校验未通过，编译必定失败"; exit 1; }
echo "[+] SUSFS + BakaSU inline hook 集成完成"
