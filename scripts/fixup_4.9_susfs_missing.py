#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
补齐 SUSFS 4.9 内核侧补丁缺少的 `inotify_mark_user_mask()`。

背景：SUSFS 的 5.10 补丁与 4.9 补丁都在 fs/notify/fdinfo.c 里调用
`inotify_mark_user_mask(mark)`，但**两个补丁都没有定义它** —— 因为 5.10 内核的
include/linux/fsnotify_backend.h 本来就有这个 helper，而 4.9 没有。
（已核对：4.9.186 与 4.9.337 两棵树都没有，属 4.9 全系缺失。）

本脚本在 fs/notify/fdinfo.c 里补一个语义等价的 static inline 版本
（与上游 5.10 的实现一致），只在 CONFIG_KSU_SUSFS 下编译。

用法: fixup_4.9_susfs_missing.py <内核树>
幂等：可重复执行。
"""
import pathlib
import sys

TREE = pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else None
if not TREE or not (TREE / "fs" / "notify" / "fdinfo.c").exists():
    sys.exit("用法: fixup_4.9_susfs_missing.py <内核树>")

HELPER = """#ifdef CONFIG_KSU_SUSFS
/* 上游 5.10 在 include/linux/fsnotify_backend.h 里定义；4.9 缺失，SUSFS 的
 * fdinfo.c 改动会用到它，这里按上游语义补上（只取用户可见的 inotify 掩码位）。 */
static inline __u32 inotify_mark_user_mask(struct fsnotify_mark *fsn_mark)
{
	return fsn_mark->mask & (IN_ALL_EVENTS | IN_UNMOUNT | IN_ONLYDIR |
				 IN_DONT_FOLLOW | IN_EXCL_UNLINK);
}
#endif

"""

changed = []

p = TREE / "fs" / "notify" / "fdinfo.c"
s = p.read_text()

if "inotify_mark_user_mask(struct fsnotify_mark" in s:
    print("  [=] fs/notify/fdinfo.c: helper 已存在")
else:
    anchor = '#include "../fs/mount.h"\n'
    if anchor in s:
        s = s.replace(anchor, anchor + "\n" + HELPER, 1)
        p.write_text(s)
        changed.append("fs/notify/fdinfo.c: 补 inotify_mark_user_mask() helper")
    else:
        print("  [!] fs/notify/fdinfo.c: 找不到锚点 #include \"../fs/mount.h\"")
        sys.exit(1)

# 校验：调用点存在且 helper 已在调用之前定义
s = p.read_text()
call = s.find("inotify_mark_user_mask(mark)")
defn = s.find("static inline __u32 inotify_mark_user_mask")
ok = call > 0 and 0 < defn < call
print("校验(fdinfo): 调用点@%d 定义@%d -> %s" % (call, defn, "OK" if ok else "FAIL"))

# ---------------------------------------------------------------- fs/proc/cmdline.c
# 4.9.186 的 cmdline.c 比补丁基线（4.9.337/CAF）简单，patch 的 fuzz 把两个 hunk 贴错位置：
#   - extern 声明被贴进了 cmdline_proc_show() 函数体
#   - 取 cmdline 的分支被贴到了文件末尾（fs_initcall 之后），成了文件作用域的裸 if -> 编译报错
# 这里按本树结构重写成正确形态（幂等）。
p2 = TREE / "fs" / "proc" / "cmdline.c"
s2 = p2.read_text()
CORRECT = """#include <linux/fs.h>
#include <linux/init.h>
#include <linux/proc_fs.h>
#include <linux/seq_file.h>

#ifdef CONFIG_KSU_SUSFS_SPOOF_CMDLINE_OR_BOOTCONFIG
extern struct static_key_false susfs_is_fake_cmdline_or_bootconfig_buffer_set;
extern void susfs_spoof_cmdline_or_bootconfig(struct seq_file *m);
#endif

static int cmdline_proc_show(struct seq_file *m, void *v)
{
#ifdef CONFIG_KSU_SUSFS_SPOOF_CMDLINE_OR_BOOTCONFIG
\tif (static_branch_likely(&susfs_is_fake_cmdline_or_bootconfig_buffer_set)) {
\t\tsusfs_spoof_cmdline_or_bootconfig(m);
\t\tseq_putc(m, '\\n');
\t\treturn 0;
\t}
#endif
\tseq_printf(m, "%s\\n", saved_command_line);

\treturn 0;
}

static int cmdline_proc_open(struct inode *inode, struct file *file)
{
\treturn single_open(file, cmdline_proc_show, NULL);
}

static const struct file_operations cmdline_proc_fops = {
\t.open\t\t= cmdline_proc_open,
\t.read\t\t= seq_read,
\t.llseek\t\t= seq_lseek,
\t.release\t= single_release,
};

static int __init proc_cmdline_init(void)
{
\tproc_create("cmdline", 0, NULL, &cmdline_proc_fops);
\treturn 0;
}
fs_initcall(proc_cmdline_init);
"""
if "SUSFS_SPOOF_CMDLINE" in s2 and "fs_initcall(proc_cmdline_init);\n#ifdef" not in s2 and s2.count("cmdline_proc_show(struct seq_file") == 1 and "\\tseq_printf(m" not in s2:
    # 已经是正确结构（extern 在函数外 + 分支在函数内 + 文件以 fs_initcall 结尾）
    if s2.rstrip().endswith("fs_initcall(proc_cmdline_init);") and s2.find("extern struct static_key_false") < s2.find("static int cmdline_proc_show"):
        print("  [=] fs/proc/cmdline.c: 结构已正确")
        cmdline_ok = True
    else:
        cmdline_ok = False
else:
    cmdline_ok = False
if not cmdline_ok:
    p2.write_text(CORRECT)
    changed.append("fs/proc/cmdline.c: 重写为正确结构（修正 fuzz 贴错位置的 hunk）")
s2 = p2.read_text()
cmdline_ok = (s2.rstrip().endswith("fs_initcall(proc_cmdline_init);")
              and s2.find("extern struct static_key_false") < s2.find("static int cmdline_proc_show")
              and s2.count("#ifdef CONFIG_KSU_SUSFS_SPOOF_CMDLINE_OR_BOOTCONFIG") == 2)
print("校验(cmdline): 结构正确 =", "OK" if cmdline_ok else "FAIL")
ok = ok and cmdline_ok

print("完成的改动:")
for c in changed:
    print("  - " + c)
if not changed:
    print("  （无）")
sys.exit(0 if ok else 1)
