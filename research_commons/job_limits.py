"""Linux containment for trusted, preloaded code; not an arbitrary-code sandbox."""
import ctypes
import errno
import os
import resource
import signal
import sys


def install_limits(limits, parent_pid):
    """Fail closed if kernel resource and syscall boundaries cannot be installed.

    Inputs and modules must already be loaded. No open file other than standard
    pipes is inherited. No network, filesystem opens, subprocesses or ptrace after
    this point. The fixed runner never executes user Python.
    """
    if sys.platform != "linux":
        raise RuntimeError("Linux isolation required")
    libc = ctypes.CDLL(None, use_errno=True)
    seccomp = ctypes.CDLL("libseccomp.so.2", use_errno=True)
    seccomp.seccomp_init.argtypes = [ctypes.c_uint32]
    seccomp.seccomp_init.restype = ctypes.c_void_p
    seccomp.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    seccomp.seccomp_rule_add.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint]
    seccomp.seccomp_load.argtypes = [ctypes.c_void_p]
    seccomp.seccomp_release.argtypes = [ctypes.c_void_p]
    if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0 or os.getppid() != parent_pid:
        raise RuntimeError("parent-death fence unavailable")
    if libc.prctl(4, 0, 0, 0, 0) != 0 or libc.prctl(38, 1, 0, 0, 0) != 0:
        raise RuntimeError("privilege fence unavailable")
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_AS, (limits["memory_mib"] * 1048576,) * 2)
    resource.setrlimit(resource.RLIMIT_CPU, (limits["cpu_seconds"],) * 2)
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NOFILE, (16, 16))
    os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})
    context = seccomp.seccomp_init(0x7fff0000)  # SCMP_ACT_ALLOW
    if not context:
        raise RuntimeError("seccomp allocation failed")
    denied = (
        "socket socketpair connect bind listen accept accept4 sendto sendmsg sendmmsg "
        "recvfrom recvmsg recvmmsg setsockopt getsockopt shutdown "
        "open openat openat2 creat unlink unlinkat rename renameat renameat2 "
        "mkdir mkdirat link linkat symlink symlinkat truncate chmod fchmodat chown "
        "fork vfork clone clone3 execve execveat ptrace process_vm_readv process_vm_writev "
        "mount umount2 unshare setns bpf perf_event_open io_uring_setup io_uring_enter "
        "io_uring_register open_by_handle_at pidfd_getfd"
    ).split()
    try:
        for name in denied:
            number = seccomp.seccomp_syscall_resolve_name(name.encode())
            if number >= 0 and seccomp.seccomp_rule_add(context, 0x50000 | errno.EPERM, number, 0) != 0:
                raise RuntimeError("seccomp rule failed")
        if seccomp.seccomp_load(context) != 0:
            raise RuntimeError("seccomp loading failed")
    finally:
        seccomp.seccomp_release(context)
    return {"network": "kernel_denied", "filesystem_open": "kernel_denied",
            "child_processes": "kernel_denied", "cpu_affinity_cores": 1,
            "parent_death": "SIGKILL", "limits": limits}
