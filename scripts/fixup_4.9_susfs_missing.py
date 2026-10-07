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
print("校验: 调用点@%d 定义@%d -> %s" % (call, defn, "OK" if ok else "FAIL"))
print("完成的改动:")
for c in changed:
    print("  - " + c)
if not changed:
    print("  （无）")
sys.exit(0 if ok else 1)
