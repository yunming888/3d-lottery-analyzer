# -*- coding: utf-8 -*-
"""
atomic_io —— 状态文件原子写 + 跨进程文件锁（2026-10-13 审计修复 A1）

背景（number_generation_audit_2026-10-13.md）：
  旧实现全链路 9 处 `open(path,"w") + json.dump` 直接覆盖，零原子写、零文件锁：
  - 写盘中途崩溃/断电 → 半截 JSON；
  - 自动化 05:00 与手动运行并发 → 后写者覆盖前写者（结算被回滚、轮换丢失）；
  - dlt/ssq load_state 对损坏文件 `except: pass` → 返回空状态 → 覆盖写回，
    26 条结算历史会被静默清空。

本模块提供：
  save_json_atomic(path, data)   tmp + os.replace 原子写（读者永远看到完整旧版或新版）
  file_lock(path)                跨进程排他锁（Windows msvcrt / POSIX fcntl），with 语法
  load_json_checked(path)        损坏时把坏文件备份为 *.corrupt-<ts> 后抛错（绝不静默清空）

注意：.lock / .tmp 文件会驻留 data/，已在 .gitignore 中排除。
"""
import json
import os
import sys
import time
import tempfile

_LOCK_TIMEOUT = 30  # 秒


def _lock_path(path):
    d = os.path.dirname(os.path.abspath(path))
    return os.path.join(d, "." + os.path.basename(path) + ".lock")


class file_lock:
    """跨进程排他锁。用法: with file_lock(path): ... """

    def __init__(self, path, timeout=_LOCK_TIMEOUT):
        self.lock_path = _lock_path(path)
        self.timeout = timeout
        self._fh = None

    def __enter__(self):
        os.makedirs(os.path.dirname(self.lock_path), exist_ok=True)
        f = open(self.lock_path, "a+b")
        deadline = time.time() + self.timeout
        while True:
            try:
                f.seek(0)
                if os.name == "nt":
                    import msvcrt
                    # 锁第 1 字节；文件为空时 msvcrt.locking 会报错，先保证有内容
                    if f.seek(0, os.SEEK_END) == 0:
                        f.write(b"\0")
                        f.flush()
                    f.seek(0)
                    msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._fh = f
                return self
            except OSError:
                if time.time() > deadline:
                    f.close()
                    raise TimeoutError("获取文件锁超时(%ds): %s" % (self.timeout, self.lock_path))
                time.sleep(0.2)

    def __exit__(self, exc_type, exc, tb):
        if self._fh is None:
            return False
        try:
            self._fh.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        finally:
            self._fh.close()
            self._fh = None
        return False


def save_json_atomic(path, data):
    """tmp + os.replace 原子写。os.replace 在 Windows(NTFS) 与 POSIX 上均为原子操作。"""
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix="." + os.path.basename(path), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        raise


def save_json_locked(path, data):
    """带锁的原子写（覆盖前先拿锁，防两进程交错写）。"""
    with file_lock(path):
        save_json_atomic(path, data)


def load_json_checked(path):
    """读取 JSON；损坏时把坏文件备份为 *.corrupt-<时间戳> 并抛 RuntimeError（绝不静默返回空）。

    FileNotFoundError 原样抛出，由调用方决定默认值。
    """
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        ts = time.strftime("%Y%m%d%H%M%S")
        bak = "%s.corrupt-%s" % (path, ts)
        try:
            os.replace(path, bak)
        except Exception:
            bak = "(备份失败)"
        raise RuntimeError("状态文件损坏，已备份至 %s：%s" % (bak, e))


def warn_if_stale_locks(data_dir, max_age_hours=48):
    """可选辅助：检测残留锁文件（正常情况下锁用完即释放，文件本身会驻留，属预期）。
    仅打印提示，不做清理。"""
    try:
        now = time.time()
        for name in os.listdir(data_dir):
            if name.endswith(".lock"):
                p = os.path.join(data_dir, name)
                age_h = (now - os.path.getmtime(p)) / 3600.0
                if age_h > max_age_hours:
                    print("  ⚠️ 残留锁文件 %.0f 小时: %s（若自动化未在跑可手工删除）" % (age_h, p))
    except Exception:
        pass
