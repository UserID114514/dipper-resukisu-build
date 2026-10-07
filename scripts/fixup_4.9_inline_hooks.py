#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
修复 SUSFS inline hook 注入器在 **Linux 4.9** 上的三处不匹配（BakaSU 的 SUSFS 模式确实需要
`struct filename **` 版本的 ksu_handle_stat/ksu_handle_faccessat，所以注入位置是对的，
只是 4.9 的函数用 `flag`(单数) 且缺 `filename_lookup` 声明）：

1) fs/stat.c  vfs_fstatat() 里注入的 `fname` 没有声明
   （注入器的 sed 锚点是 `flags`，而 4.9 的形参叫 `flag`）→ 补声明。
2) fs/stat.c  注入代码把 `&flags` 传给 ksu_handle_stat → 4.9 里应为 `&flag`。
3) fs/stat.c / fs/open.c  调用 `filename_lookup()` 但没有声明
   （注入器只在 namei.c 里是 `static int filename_lookup` 时才补 extern；4.9 本来就是非 static，
     于是它没补声明）→ 补上 extern 声明。

用法: fixup_4.9_inline_hooks.py <内核树>
幂等：可重复执行。
"""
import pathlib
import sys

TREE = pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else None
if not TREE or not (TREE / "fs" / "stat.c").exists():
    sys.exit("用法: fixup_4.9_inline_hooks.py <内核树>")

changed = []

# ---------------------------------------------------------------- fs/stat.c
p = TREE / "fs" / "stat.c"
s = p.read_text()

# 1) 给 vfs_fstatat 补 fname 声明
anchor = """int vfs_fstatat(int dfd, const char __user *filename, struct kstat *stat,
		int flag)
{
	struct path path;
	int error = -EINVAL;
	unsigned int lookup_flags = 0;
"""
if "\tstruct filename *fname = NULL;" in s.split("int vfs_fstatat", 1)[-1].split("retry:", 1)[0]:
    print("  [=] fs/stat.c: fname 已声明")
elif anchor in s:
    s = s.replace(anchor, anchor + """#ifdef CONFIG_KSU_SUSFS
	struct filename *fname = NULL;
#endif
""", 1)
    changed.append("fs/stat.c: 在 vfs_fstatat() 补 struct filename *fname 声明")
else:
    print("  [!] fs/stat.c: 未找到 vfs_fstatat 的 4.9 函数头，请人工检查")

# 2) &flags -> &flag
if "ksu_handle_stat(&dfd, &fname, &flags);" in s:
    s = s.replace("ksu_handle_stat(&dfd, &fname, &flags);",
                  "ksu_handle_stat(&dfd, &fname, &flag);", 1)
    changed.append("fs/stat.c: ksu_handle_stat(&dfd, &fname, &flags) -> &flag（4.9 形参为 flag）")

# 3) filename_lookup 声明
marker = "extern struct static_key_true ksu_su_compat_enabled;"
decl = ("extern int filename_lookup(int dfd, struct filename *name, unsigned flags,\n"
        "\t\t\t\tstruct path *path, struct path *root);")
if "extern int filename_lookup" in s:
    print("  [=] fs/stat.c: filename_lookup 已声明")
elif marker in s:
    s = s.replace(marker, marker + "\n" + decl, 1)
    changed.append("fs/stat.c: 补 extern filename_lookup 声明")
else:
    print("  [!] fs/stat.c: 未找到注入的 extern 块标记")
p.write_text(s)

# ---------------------------------------------------------------- fs/open.c
p = TREE / "fs" / "open.c"
s = p.read_text()
if "filename_lookup(dfd, fname" in s or "filename_lookup(" in s:
    if "extern int filename_lookup" in s:
        print("  [=] fs/open.c: filename_lookup 已声明")
    elif marker in s:
        s = s.replace(marker, marker + "\n" + decl, 1)
        changed.append("fs/open.c: 补 extern filename_lookup 声明")
        p.write_text(s)
    else:
        print("  [!] fs/open.c: 未找到注入的 extern 块标记，请人工检查")
else:
    print("  [=] fs/open.c: 未注入 filename_lookup，跳过")

# ---------------------------------------------------------------- 校验
p = TREE / "fs" / "stat.c"
s = p.read_text()
seg = s.split("int vfs_fstatat", 1)[-1].split("retry:", 1)[0]
ok = ("struct filename *fname = NULL;" in seg) and ("ksu_handle_stat(&dfd, &fname, &flag);" in s)
print("\n校验 fs/stat.c: fname 声明 + &flag =", "OK" if ok else "FAIL")
print("完成的改动:")
for c in changed:
    print("  - " + c)
if not changed:
    print("  （无）")
sys.exit(0 if ok else 1)
