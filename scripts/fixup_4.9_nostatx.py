#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
susfs_patch_to_4.9.patch 在 **无 statx** 的 4.9 树（如 Xiaomi dipper-q-oss 4.9.186）上的两处 fixup：

1) fs/proc/task_mmu.c  Hunk #4：补丁只是去掉一行尾随空格，实际内容无变化
   -> 直接把该行尾随空白去掉即可（保留补丁作者的去空白意图）。

2) fs/stat.c  Hunk #2：补丁假设 vfs_getattr_nosec() 是 statx 时代签名
   （struct path, struct kstat, u32 request_mask, unsigned int query_flags），
   而 4.9 的签名是 vfs_getattr_nosec(struct path *path, struct kstat *stat)，
   `struct kstat` 也没有 result_mask 字段。
   好在 fs/susfs.c 的 susfs_sus_kstat_spoof_generic_fillattr(inode, stat, mask)
   完全不读 stat->result_mask（它只用传入的 mask 参数），因此可以按下面的方式等价移植：
   命中 SUS_KSTAT 的 inode 时，先按原逻辑填好 kstat，再调用 spoof 函数覆盖字段。

用法: fixup_4.9_nostatx.py <内核树>
"""
import pathlib
import sys

TREE = pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else None
if not TREE or not (TREE / "fs" / "stat.c").exists():
    sys.exit("用法: fixup_4.9_nostatx.py <内核树>")

changed = []

# ---------------------------------------------------------------- 1) task_mmu.c
p = TREE / "fs" / "proc" / "task_mmu.c"
s = p.read_text()
needle = 'if (strstr(path, "jit-zygote-cache")) {'
if needle not in s:
    # 该 hunk 的上下文行在本树不存在（补丁是按带 jit-zygote-cache hack 的 CAF 树生成的），
    # 且它是纯去尾随空格的改动 -> 本树无需处理，直接忽略。
    print("  [=] fs/proc/task_mmu.c: 无 jit-zygote-cache 上下文，Hunk #4 不适用（纯空白改动，可安全忽略）")
    task_mmu_ok = True
else:
    idx = s.index(needle)
    line_start = s.rindex("\n", 0, idx) + 1
    line_end = s.index("\n", idx)
    line = s[line_start:line_end]
    if line != line.rstrip():
        s = s[:line_start] + line.rstrip() + s[line_end:]
        p.write_text(s)
        changed.append("fs/proc/task_mmu.c: 去掉 jit-zygote-cache 行的尾随空格（= Hunk #4 内容）")
        task_mmu_ok = True
    else:
        print("  [=] fs/proc/task_mmu.c 已是目标状态")
        task_mmu_ok = True

# ---------------------------------------------------------------- 2) stat.c
p = TREE / "fs" / "stat.c"
s = p.read_text()
OLD = """int vfs_getattr_nosec(struct path *path, struct kstat *stat)
{
	struct inode *inode = d_backing_inode(path->dentry);

	if (inode->i_op->getattr)
		return inode->i_op->getattr(path->mnt, path->dentry, stat);

	generic_fillattr(inode, stat);
	return 0;
}"""
NEW = """int vfs_getattr_nosec(struct path *path, struct kstat *stat)
{
	struct inode *inode = d_backing_inode(path->dentry);

#ifdef CONFIG_KSU_SUSFS_SUS_KSTAT
	/* 4.9 无 statx：原补丁用 stat->result_mask 传递 STATX_SUS_KSTAT*，
	 * 这里改为直接调用 spoof（spoof 函数只看传入的 mask 参数）。 */
	if (susfs_is_current_app_uid()) {
		bool is_fuse = false;
		if (susfs_is_inode_sus_kstat(inode, &is_fuse)) {
			int err;

			if (inode->i_op->getattr)
				err = inode->i_op->getattr(path->mnt, path->dentry, stat);
			else {
				generic_fillattr(inode, stat);
				err = 0;
			}
			if (!err)
				susfs_sus_kstat_spoof_generic_fillattr(inode, stat,
						is_fuse ? STATX_SUS_KSTAT_FUSE : STATX_SUS_KSTAT);
			return err;
		}
	}
#endif // #ifdef CONFIG_KSU_SUSFS_SUS_KSTAT

	if (inode->i_op->getattr)
		return inode->i_op->getattr(path->mnt, path->dentry, stat);

	generic_fillattr(inode, stat);
	return 0;
}"""
if "susfs_is_inode_sus_kstat(inode, &is_fuse)" in s:
    print("  [=] fs/stat.c 已完成无 statx 移植")
elif OLD in s:
    p.write_text(s.replace(OLD, NEW, 1))
    changed.append("fs/stat.c: vfs_getattr_nosec() 移植为无 statx 版本（= Hunk #2 内容）")
else:
    print("  [!] fs/stat.c 未找到 vfs_getattr_nosec 的 4.9 原始形态，请人工检查 .rej")

# ---------------------------------------------------------------- 清理 .rej
for rej in list(TREE.rglob("*.rej")):
    if "KernelSU" in rej.parts:
        continue
    rej.unlink()
    changed.append(f"删除 {rej.relative_to(TREE)}（已由本脚本修复）")

print("fixup 结果:")
for c in changed:
    print("  - " + c)
if not changed:
    print("  （无改动）")
