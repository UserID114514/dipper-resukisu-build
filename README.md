# dipper (小米8) Android 10 内核 + ReSukiSU 编译仓库

用 GitHub Actions 为 **小米8 / dipper / Snapdragon 845 / Android 10（Linux 4.9.186 官方开源树）**
编译集成 **最新 ReSukiSU** 的内核，一次产出两个可刷入包：

| 产物 | 说明 |
| --- | --- |
| `dipper-resukisu-nosusfs.zip` | 手动钩子(manual hook)模式，**不含 SUSFS** |
| `dipper-resukisu-susfs.zip` | SUSFS v2.3.0 内联钩子(inline hook)模式，**含 SUSFS** |

两个包都是 AnyKernel3 格式，用 TWRP / KernelFlasher / EX Kernel Manager 等直接刷入即可（`device.name1=dipper` 校验）。

## 关于 "ReSukiSU"

`ReSukiSU/ReSukiSU` 仓库已 **301 重定向到 [`Baka-SU/BakaSU`](https://github.com/Baka-SU/BakaSU)**
（项目管理器、resukisu.org / bakasu.org 文档均为同一项目）。本仓库的 `integrate_ksu.py`
与 CI 都直接使用 BakaSU 最新 main（当前版本号 v4.1.0 系列），这就是"最新 ReSukiSU"。

## 怎么用

1. 新建一个 GitHub 仓库（私有/公开都行），把本目录（含 `.github/`）推上去：
   ```bash
   cd ci
   git init && git add -A && git commit -m "dipper ReSukiSU build"
   git remote add origin git@github.com:<你的用户名>/<仓库名>.git
   git push -u origin main
   ```
2. 打开仓库 **Actions → Build ReSukiSU kernel for Xiaomi Mi 8 → Run workflow**。
   两个变体会并行构建（`nosusfs` / `susfs`），约 20–40 分钟。
3. 在 **Artifacts** 下载 `dipper-resukisu-nosusfs` / `dipper-resukisu-susfs`。
   打 tag（`v*`）推送时会自动发布到 Release。

工作流输入项可改：`kernel_repo` / `kernel_branch` / `kernel_defconfig`
（默认 `MiCode/Xiaomi_Kernel_OpenSource` + `dipper-q-oss` + `dipper_user_defconfig`）。

## 本地（Linux x86_64）等效命令

```bash
# 依赖
sudo apt-get install -y git flex bison bc cpio zip unzip libssl-dev libelf-dev \
                        gcc-aarch64-linux-gnu gcc-arm-linux-gnueabi python3

# 内核源码（Android 10 官方开源树，4.9.186）
git clone --depth=1 --single-branch -b dipper-q-oss \
    https://github.com/MiCode/Xiaomi_Kernel_OpenSource.git kernel

# ReSukiSU(BakaSU)
git clone https://github.com/Baka-SU/BakaSU kernel/KernelSU

# === 变体 A：不含 SUSFS（手动钩子）===
python3 scripts/integrate_ksu.py kernel
cd kernel
make O=out ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- dipper_user_defconfig
scripts/config --file out/.config -e KSU -e KALLSYMS_ALL -d KSU_TRACEPOINT_HOOK -d KSU_SUSFS \
      -e KSU_MANUAL_HOOK -e KSU_MANUAL_HOOK_AUTO_SETUID_HOOK \
      -e KSU_MANUAL_HOOK_AUTO_INITRC_HOOK -e KSU_MANUAL_HOOK_AUTO_INPUT_HOOK -d COMPAT_VDSO
make O=out ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- olddefconfig
make O=out ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- -j"$(nproc)" \
      CC=aarch64-linux-gnu-gcc KCFLAGS="-Wno-error" HOSTCFLAGS="-fcommon"

# === 变体 B：含 SUSFS ===
# 在干净的内核树上：
bash scripts/integrate_susfs.sh kernel
```

> `CC=...` 覆盖是必须的：小米 CAF 树的 `Makefile:364` 把编译器包成
> `scripts/gcc-wrapper.py`（用 ptrace 扫描告警，且 shebang 是 `python2`）。
> 在 CI/现代发行版上没有 python2，在容器/proot 里 ptrace 嵌套会死锁。

## 目录说明

```
.github/workflows/build-dipper.yml   两个变体的 CI 构建 + AnyKernel3 打包 + Release
scripts/integrate_ksu.py             手动钩子集成（幂等、带断言、含自检）
scripts/integrate_susfs.sh           SUSFS v2.3.0 补丁 + BakaSU 适配的 inline hook 注入
scripts/wire_kernelsu.sh             drivers/Makefile+Kconfig 接线 + 符号链接
patches/susfs_patch_to_4.9.patch     SUSFS v2.3.0 NON-GKI 4.9 内核侧补丁
patches/susfs_inline_hook_bakasu.sh  官方 inline hook 注入器（针对 BakaSU 适配）
patches/dipper-4.9-manual-hook.patch 手动钩子改动（参考用 diff，等价于 integrate_ksu.py）
```

## 出处与许可

- 内核源码：Xiaomi OSS (`MiCode/Xiaomi_Kernel_OpenSource`, 分支 `dipper-q-oss`，GPLv2)
- ReSukiSU：`Baka-SU/BakaSU`（MIT）
- SUSFS 4.9 移植：`JackA1ltman/NonGKI_Kernel_Build_2nd`
  （`Patches/Patch/susfs_patch_to_4.9.patch`，SUSFS v2.3.0 NON-GKI）
  inline hook 注入器适配自 `chorusfruit-233/OnePlus_SDM845_BakaSU_SUSFS`（BakaSU 三参 `ksu_handle_sys_read` 等）
- SUSFS 原始项目：`simonpunk/susfs4ksu`（GitLab）

## 风险与注意

- 刷内核前请备份 `boot` 分区；解锁 Bootloader，必要时 `fastboot --disable-verity --disable-verification flash vbmeta`。
- MIUI 官方 Android 10 与内核 4.9.186 对应；如果你的 ROM 是 LineageOS 17.1 等第三方 Android 10，
  把 `kernel_branch` 换成 `LineageOS/android_kernel_xiaomi_sdm845@lineage-17.1`、`kernel_defconfig` 换成 `dipper_defconfig`。
- SUSFS 会修改大量 VFS/proc 代码，若开机异常先用 `nosusfs` 版本。
- 本项目只做编译集成，未在真机上验证过（无法在本环境刷机）；首次刷入请确保有回滚手段。
