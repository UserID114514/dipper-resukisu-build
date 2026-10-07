#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把 BakaSU(ReSukiSU) 的 "手动钩子(manual hook)" 集成进 Linux 4.9 arm64 内核树。

用法: integrate_ksu.py <内核树路径>
幂等：重复执行不会重复插入。每一步都有断言，失败即报错退出。
对应文档: https://resukisu.org/zh-Hans/guide/manual-integrate.html (bakasu.org 同源)
"""
import os
import sys
import pathlib

TREE = pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else None
if not TREE or not (TREE / "Makefile").exists():
    sys.exit("用法: integrate_ksu.py <内核树路径>")
if not (TREE / "KernelSU" / "kernel" / "Kbuild").exists():
    sys.exit(f"[!] {TREE}/KernelSU/kernel/Kbuild 不存在，请先把 BakaSU 克隆到 KernelSU/")

changes = []


def read(rel):
    return (TREE / rel).read_text()


def write(rel, text):
    (TREE / rel).write_text(text)


def replace_once(rel, old, new, marker, label):
    """在 rel 文件中把 old 替换为 new；marker 已存在则跳过（幂等）。"""
    s = read(rel)
    if marker in s:
        print(f"  [=] 跳过（已集成）: {label}")
        return False
    n = s.count(old)
    if n != 1:
        raise SystemExit(f"[!] {rel}: 锚点出现 {n} 次（期望 1 次）: {label}\n---\n{old}\n---")
    write(rel, s.replace(old, new, 1))
    changes.append(f"{rel}: {label}")
    print(f"  [+] {rel}: {label}")
    return True


# ---------------------------------------------------------------- 0. 接线
def wire_kernelsu():
    print("[0] 把 KernelSU/kernel 接入内核构建系统")
    mf = TREE / "drivers" / "Makefile"
    s = mf.read_text()
    if "kernelsu" not in s:
        if not s.endswith("\n"):
            s += "\n"
        s += "\nobj-$(CONFIG_KSU) += kernelsu/\n"
        mf.write_text(s)
        changes.append("drivers/Makefile: 追加 obj-$(CONFIG_KSU) += kernelsu/")
        print("  [+] drivers/Makefile 已追加 obj-$(CONFIG_KSU) += kernelsu/")
    else:
        print("  [=] drivers/Makefile 已包含 kernelsu")

    kc = TREE / "drivers" / "Kconfig"
    s = kc.read_text()
    line = 'source "drivers/kernelsu/Kconfig"\n'
    if line not in s:
        idx = s.rstrip().rfind("endmenu")
        if idx < 0:
            raise SystemExit("[!] drivers/Kconfig 找不到 endmenu")
        s = s[:idx] + line + s[idx:]
        kc.write_text(s)
        changes.append("drivers/Kconfig: 引入 kernelsu/Kconfig")
        print("  [+] drivers/Kconfig 已引入 kernelsu/Kconfig")
    else:
        print("  [=] drivers/Kconfig 已包含 kernelsu/Kconfig")

    link = TREE / "drivers" / "kernelsu"
    target = "../KernelSU/kernel"
    if link.is_symlink():
        if os.readlink(link) != target:
            link.unlink()
            link.symlink_to(target)
            print(f"  [+] 修正符号链接 drivers/kernelsu -> {target}")
        else:
            print("  [=] 符号链接 drivers/kernelsu 已存在")
    elif link.exists():
        raise SystemExit("[!] drivers/kernelsu 已存在且不是符号链接")
    else:
        link.symlink_to(target)
        changes.append("drivers/kernelsu -> ../KernelSU/kernel")
        print(f"  [+] 建立符号链接 drivers/kernelsu -> {target}")


# ------------------------------------------------------- 1. fs/stat.c
def patch_stat():
    print("[1] fs/stat.c : ksu_handle_stat / ksu_handle_newfstat_ret / ksu_handle_fstat64_ret")
    extern = """#ifdef CONFIG_KSU_MANUAL_HOOK
__attribute__((hot))
extern int ksu_handle_stat(int *dfd, const char __user **filename_user, int *flags);

__attribute__((hot))
extern void ksu_handle_newfstat_ret(unsigned int *fd, struct stat __user **statbuf_ptr);
#if defined(__ARCH_WANT_STAT64) || defined(__ARCH_WANT_COMPAT_STAT64)
extern void ksu_handle_fstat64_ret(unsigned long *fd, struct stat64 __user **statbuf_ptr);
#endif
#endif

"""
    replace_once(
        "fs/stat.c",
        "#if !defined(__ARCH_WANT_STAT64) || defined(__ARCH_WANT_SYS_NEWFSTATAT)\nSYSCALL_DEFINE4(newfstatat,",
        extern + "#if !defined(__ARCH_WANT_STAT64) || defined(__ARCH_WANT_SYS_NEWFSTATAT)\nSYSCALL_DEFINE4(newfstatat,",
        "ksu_handle_stat(int *dfd",
        "加入 hook 声明",
    )
    replace_once(
        "fs/stat.c",
        """SYSCALL_DEFINE4(newfstatat, int, dfd, const char __user *, filename,
		struct stat __user *, statbuf, int, flag)
{
	struct kstat stat;
	int error;

	error = vfs_fstatat(dfd, filename, &stat, flag);""",
        """SYSCALL_DEFINE4(newfstatat, int, dfd, const char __user *, filename,
		struct stat __user *, statbuf, int, flag)
{
	struct kstat stat;
	int error;

#ifdef CONFIG_KSU_MANUAL_HOOK
	ksu_handle_stat(&dfd, &filename, &flag);
#endif
	error = vfs_fstatat(dfd, filename, &stat, flag);""",
        "ksu_handle_stat(&dfd",
        "newfstatat 入口 hook",
    )
    replace_once(
        "fs/stat.c",
        """SYSCALL_DEFINE2(newfstat, unsigned int, fd, struct stat __user *, statbuf)
{
	struct kstat stat;
	int error = vfs_fstat(fd, &stat);

	if (!error)
		error = cp_new_stat(&stat, statbuf);

	return error;""",
        """SYSCALL_DEFINE2(newfstat, unsigned int, fd, struct stat __user *, statbuf)
{
	struct kstat stat;
	int error = vfs_fstat(fd, &stat);

	if (!error)
		error = cp_new_stat(&stat, statbuf);

#ifdef CONFIG_KSU_MANUAL_HOOK
	ksu_handle_newfstat_ret(&fd, &statbuf);
#endif
	return error;""",
        "ksu_handle_newfstat_ret(&fd",
        "newfstat 返回 hook",
    )
    replace_once(
        "fs/stat.c",
        """SYSCALL_DEFINE2(fstat64, unsigned long, fd, struct stat64 __user *, statbuf)
{
	struct kstat stat;
	int error = vfs_fstat(fd, &stat);

	if (!error)
		error = cp_new_stat64(&stat, statbuf);

	return error;""",
        """SYSCALL_DEFINE2(fstat64, unsigned long, fd, struct stat64 __user *, statbuf)
{
	struct kstat stat;
	int error = vfs_fstat(fd, &stat);

	if (!error)
		error = cp_new_stat64(&stat, statbuf);

#ifdef CONFIG_KSU_MANUAL_HOOK
	ksu_handle_fstat64_ret(&fd, &statbuf);
#endif
	return error;""",
        "ksu_handle_fstat64_ret(&fd",
        "fstat64 返回 hook(32 位块)",
    )
    replace_once(
        "fs/stat.c",
        """SYSCALL_DEFINE4(fstatat64, int, dfd, const char __user *, filename,
		struct stat64 __user *, statbuf, int, flag)
{
	struct kstat stat;
	int error;

	error = vfs_fstatat(dfd, filename, &stat, flag);""",
        """SYSCALL_DEFINE4(fstatat64, int, dfd, const char __user *, filename,
		struct stat64 __user *, statbuf, int, flag)
{
	struct kstat stat;
	int error;

#ifdef CONFIG_KSU_MANUAL_HOOK
	ksu_handle_stat(&dfd, &filename, &flag);
#endif
	error = vfs_fstatat(dfd, filename, &stat, flag);""",
        "ksu_handle_stat(&dfd, &filename, &flag);\n#endif\n\terror = vfs_fstatat(dfd, filename, &stat, flag);\n\tif (error)\n\t\treturn error;\n\treturn cp_new_stat64",
        "fstatat64 入口 hook(32 位块)",
    )


# ------------------------------------------------------- 2. fs/exec.c
def patch_exec():
    print("[2] fs/exec.c : ksu_handle_execveat / ksu_handle_post_execveat")
    extern = """#ifdef CONFIG_KSU_MANUAL_HOOK
__attribute__((hot))
extern int ksu_handle_execveat(int *fd, struct filename **filename_ptr,
				void *argv, void *envp, int *flags);
__attribute__((hot))
extern int ksu_handle_post_execveat(int *fd, struct filename **filename_ptr,
				void *argv, void *envp, int *flags, int *retval);
#endif

static int do_execveat_common("""
    replace_once(
        "fs/exec.c",
        "static int do_execveat_common(",
        extern,
        "ksu_handle_execveat(int *fd",
        "加入 hook 声明",
    )
    replace_once(
        "fs/exec.c",
        """	struct files_struct *displaced;
	int retval;

	if (IS_ERR(filename))
		return PTR_ERR(filename);""",
        """	struct files_struct *displaced;
	int retval;

#ifdef CONFIG_KSU_MANUAL_HOOK
	ksu_handle_execveat(&fd, &filename, &argv, &envp, &flags);
#endif
	if (IS_ERR(filename))
		return PTR_ERR(filename);""",
        "ksu_handle_execveat(&fd, &filename, &argv, &envp, &flags);\n#endif\n\tif (IS_ERR(filename))",
        "do_execveat_common 入口 hook",
    )
    # 成功路径：在 putname() 之前调用 post hook（避免读取已释放的 filename）
    replace_once(
        "fs/exec.c",
        """	free_bprm(bprm);
	kfree(pathbuf);
	putname(filename);
	if (displaced)
		put_files_struct(displaced);
	return retval;""",
        """	free_bprm(bprm);
	kfree(pathbuf);
#ifdef CONFIG_KSU_MANUAL_HOOK
	ksu_handle_post_execveat(&fd, &filename, &argv, &envp, &flags, &retval);
#endif
	putname(filename);
	if (displaced)
		put_files_struct(displaced);
	return retval;""",
        "ksu_handle_post_execveat(&fd, &filename, &argv, &envp, &flags, &retval);\n#endif\n\tputname(filename);\n\tif (displaced)\n\t\tput_files_struct(displaced);",
        "成功路径 post hook",
    )
    # 失败路径
    replace_once(
        "fs/exec.c",
        """out_ret:
	putname(filename);
	return retval;
}""",
        """out_ret:
#ifdef CONFIG_KSU_MANUAL_HOOK
	ksu_handle_post_execveat(&fd, &filename, &argv, &envp, &flags, &retval);
#endif
	putname(filename);
	return retval;
}""",
        "ksu_handle_post_execveat(&fd, &filename, &argv, &envp, &flags, &retval);\n#endif\n\tputname(filename);\n\treturn retval;",
        "失败路径 post hook",
    )


# ------------------------------------------------------- 3. fs/open.c
def patch_open():
    print("[3] fs/open.c : ksu_handle_faccessat")
    replace_once(
        "fs/open.c",
        "SYSCALL_DEFINE3(faccessat, int, dfd, const char __user *, filename, int, mode)",
        """#ifdef CONFIG_KSU_MANUAL_HOOK
__attribute__((hot))
extern int ksu_handle_faccessat(int *dfd, const char __user **filename_user,
				int *mode, int *flags);
#endif

SYSCALL_DEFINE3(faccessat, int, dfd, const char __user *, filename, int, mode)""",
        "ksu_handle_faccessat(int *dfd",
        "加入 hook 声明",
    )
    replace_once(
        "fs/open.c",
        """	int res;
	unsigned int lookup_flags = LOOKUP_FOLLOW;

	if (mode & ~S_IRWXO)	/* where's F_OK, X_OK, W_OK, R_OK? */""",
        """	int res;
	unsigned int lookup_flags = LOOKUP_FOLLOW;

#ifdef CONFIG_KSU_MANUAL_HOOK
	ksu_handle_faccessat(&dfd, &filename, &mode, NULL);
#endif
	if (mode & ~S_IRWXO)	/* where's F_OK, X_OK, W_OK, R_OK? */""",
        "ksu_handle_faccessat(&dfd, &filename, &mode, NULL);",
        "faccessat 入口 hook",
    )


# ------------------------------------------------------- 4. kernel/reboot.c
def patch_reboot():
    print("[4] kernel/reboot.c : ksu_handle_sys_reboot")
    replace_once(
        "kernel/reboot.c",
        "SYSCALL_DEFINE4(reboot, int, magic1, int, magic2, unsigned int, cmd,",
        """#ifdef CONFIG_KSU_MANUAL_HOOK
extern int ksu_handle_sys_reboot(int magic1, int magic2, unsigned int cmd, void __user **arg);
#endif

SYSCALL_DEFINE4(reboot, int, magic1, int, magic2, unsigned int, cmd,""",
        "ksu_handle_sys_reboot(int magic1",
        "加入 hook 声明",
    )
    replace_once(
        "kernel/reboot.c",
        """	struct pid_namespace *pid_ns = task_active_pid_ns(current);
	char buffer[256];
	int ret = 0;

	/* We only trust the superuser with rebooting the system. */""",
        """	struct pid_namespace *pid_ns = task_active_pid_ns(current);
	char buffer[256];
	int ret = 0;

#ifdef CONFIG_KSU_MANUAL_HOOK
	ksu_handle_sys_reboot(magic1, magic2, cmd, &arg);
#endif
	/* We only trust the superuser with rebooting the system. */""",
        "ksu_handle_sys_reboot(magic1, magic2, cmd, &arg);",
        "reboot syscall hook",
    )


# ------------------------------------------- 5. SELinux 静态符号去 static
def patch_selinux_exports():
    """CONFIG_KALLSYMS_ALL=n 时 ReSukiSU 要求这些符号非 static（见 docs#static-symbol-export）。"""
    print("[5] SELinux 静态符号导出（若 defconfig 已开 KALLSYMS_ALL 则可跳过，但去掉 static 无害）")
    targets = [
        ("security/selinux/selinuxfs.c", "static ssize_t (*write_op[])", "ssize_t (*write_op[])"),
        ("security/selinux/selinuxfs.c", "static const struct file_operations sel_handle_status_ops",
         "const struct file_operations sel_handle_status_ops"),
        ("security/selinux/selinuxfs.c", "static DEFINE_MUTEX(sel_mutex);", "DEFINE_MUTEX(sel_mutex);"),
        ("security/selinux/ss/status.c", "static struct page *selinux_status_page;",
         "struct page *selinux_status_page;"),
        ("security/selinux/ss/status.c", "static DEFINE_MUTEX(selinux_status_lock);",
         "DEFINE_MUTEX(selinux_status_lock);"),
        ("security/selinux/ss/services.c", "static DEFINE_RWLOCK(policy_rwlock);",
         "DEFINE_RWLOCK(policy_rwlock);"),
    ]
    for rel, old, new in targets:
        p = TREE / rel
        if not p.exists():
            print(f"  [-] {rel}: 文件不存在，跳过 {old}")
            continue
        s = p.read_text()
        if old not in s:
            print(f"  [=] {rel}: 已是导出状态/未找到  {old}")
            continue
        if s.count(old) != 1:
            raise SystemExit(f"[!] {rel}: {old} 出现 {s.count(old)} 次")
        p.write_text(s.replace(old, new, 1))
        changes.append(f"{rel}: 去掉 static -> {new}")
        print(f"  [+] {rel}: {old}  ->  {new}")


# ------------------------------------------------------- 6. 自检
def verify():
    print("\n[6] 校验 ReSukiSU 的编译期 hook 检查是否满足")
    checks = [
        ("fs/stat.c", "ksu_handle_stat(", True),
        ("fs/stat.c", "ksu_handle_newfstat_ret(", True),
        ("fs/stat.c", "ksu_handle_fstat64_ret(", True),
        ("fs/exec.c", "ksu_handle_execveat", True),
        ("fs/open.c", "ksu_handle_faccessat", True),
        ("kernel/reboot.c", "ksu_handle_sys_reboot", True),
        ("fs/read_write.c", "ksu_vfs_read_hook", False),
        ("security/selinux/hooks.c", "is_ksu_transition", False),
        ("security/security.c", "ksu_handle_rename", False),
    ]
    bad = 0
    for rel, needle, want in checks:
        s = read(rel)
        got = needle in s
        ok = got == want
        bad += 0 if ok else 1
        print(f"  {'OK ' if ok else 'BAD'} {rel}: {'包含' if got else '不包含'} {needle!r} (期望{'包含' if want else '不包含'})")
    # 静态导出检查（只在未开 KALLSYMS_ALL 时生效）
    for rel, needle in [
        ("security/selinux/selinuxfs.c", "static ssize_t (*write_op[]"),
        ("security/selinux/selinuxfs.c", "static const struct file_operations sel_handle_status_ops"),
        ("security/selinux/selinuxfs.c", "static DEFINE_MUTEX(sel_mutex);"),
        ("security/selinux/ss/status.c", "static struct page *selinux_status_page;"),
        ("security/selinux/ss/status.c", "static DEFINE_MUTEX(selinux_status_lock);"),
        ("security/selinux/ss/services.c", "static DEFINE_RWLOCK(policy_rwlock);"),
    ]:
        got = needle in read(rel) if (TREE / rel).exists() else "文件缺失"
        ok = got is False
        bad += 0 if ok else 1
        print(f"  {'OK ' if ok else 'BAD'} {rel}: {needle!r} {'仍存在' if got is True else ('缺失' if got == '文件缺失' else '已去除')}")
    if bad:
        raise SystemExit(f"[!] {bad} 项自检未通过")
    print("  => 全部通过")


if __name__ == "__main__":
    print(f"内核树: {TREE}")
    wire_kernelsu()
    patch_stat()
    patch_exec()
    patch_open()
    patch_reboot()
    patch_selinux_exports()
    verify()
    print("\n完成的改动:")
    for c in changes:
        print("  - " + c)
    if not changes:
        print("  （无，树已处于目标状态）")
