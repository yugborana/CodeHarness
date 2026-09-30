"""ACL-enforced limits on what a PowerShell command can touch (Windows).

Security model (no admin rights required):
  - ACL deny rules: .git, .agents, .codex, .aws, .env are not writable
  - ACL grant: project directory is writable (for the sandbox to work in)
  - Job Object: KILL_ON_JOB_CLOSE ensures nothing outlives the call
  - Environment poisoning: proxy, git, pip, npm, cargo vars block network

Design follows openai/codex `windows-sandbox-rs` ACL approach.
https://github.com/openai/codex

NOT enforced (requires admin):
  - Network (would need WFP firewall rules)
  - Writes outside the project (would need WRITE_RESTRICTED token + admin
    service, as Codex's elevated backend does)
"""

import base64
import ctypes
import hashlib
import os
import struct
import subprocess
import sys
from pathlib import Path

PROJECT = Path.cwd().resolve()
POWERSHELL = str(Path(os.environ.get("SystemRoot", r"C:\Windows"))
                 / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe")

DWORD, V = ctypes.c_uint32, ctypes.c_void_p


# --- Win32 struct for SetEntriesInAclW ---

class TRUSTEE_W(ctypes.Structure):
    _fields_ = [
        ("pMultipleTrustee", V),
        ("MultipleTrusteeOperation", DWORD),  # 0 = NO_MULTIPLE_TRUSTEE
        ("TrusteeForm", DWORD),               # 0 = TRUSTEE_IS_SID
        ("TrusteeType", DWORD),               # 0 = TRUSTEE_IS_UNKNOWN
        ("ptstrName", V),                      # pointer to SID
    ]

class EXPLICIT_ACCESS_W(ctypes.Structure):
    _fields_ = [
        ("grfAccessPermissions", DWORD),
        ("grfAccessMode", DWORD),
        ("grfInheritance", DWORD),
        ("Trustee", TRUSTEE_W),
    ]


# --- DLL setup ---

_dlls = None

def _dll():
    """kernel32 + advapi32 with prototypes (without them 64-bit handles get truncated)."""
    global _dlls
    if _dlls is not None:
        return _dlls
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    a = ctypes.WinDLL("advapi32", use_last_error=True)
    I, W, P = ctypes.c_int, ctypes.c_wchar_p, ctypes.POINTER

    def sig(fn, res, *args):
        fn.restype, fn.argtypes = res, args

    # kernel32
    sig(k.CloseHandle, I, V)
    sig(k.LocalFree, V, V)
    sig(k.CreateJobObjectW, V, V, W)
    sig(k.SetInformationJobObject, I, V, I, V, DWORD)
    sig(k.AssignProcessToJobObject, I, V, V)
    sig(k.TerminateJobObject, I, V, DWORD)
    # advapi32 — SID + ACL
    sig(a.ConvertStringSidToSidW, I, W, P(V))
    sig(a.GetLengthSid, DWORD, V)
    sig(a.GetNamedSecurityInfoW, DWORD, W, DWORD, DWORD, V, V, P(V), V, P(V))
    sig(a.SetNamedSecurityInfoW, DWORD, W, DWORD, DWORD, V, V, V, V)
    sig(a.SetEntriesInAclW, DWORD, DWORD, V, V, P(V))
    _dlls = (a, k)
    return _dlls


def _chk(ok, what):
    if not ok:
        raise OSError(f"{what} failed: {ctypes.WinError(ctypes.get_last_error())}")


# --- SID + ACL helpers ---

def _cap_sid():
    """Synthetic SID (belongs to no account), stable per project path."""
    d = hashlib.sha256(str(PROJECT).lower().encode()).digest()
    return "S-1-5-21-%d-%d-%d-%d" % struct.unpack("<4I", d[:16])


def _sid(text):
    """Convert a string SID to a binary SID buffer."""
    a, k = _dll()
    p = V()
    _chk(a.ConvertStringSidToSidW(text, ctypes.byref(p)), "ConvertStringSidToSidW")
    raw = ctypes.string_at(p, a.GetLengthSid(p))
    k.LocalFree(p)
    return ctypes.create_string_buffer(raw, len(raw))


# ACL permission masks
_FILE_GENERIC_RWX = 0x120089 | 0x120116 | 0x1200A0  # READ | WRITE | EXECUTE
_DENY_WRITE_MASK  = 0x120116 | 0x10000               # FILE_GENERIC_WRITE | DELETE
_OI_CI = 0x1 | 0x2                                    # OBJECT_INHERIT | CONTAINER_INHERIT

# Directories inside the project that the sandbox must never write to.
_PROTECTED = (".git", ".agents", ".codex", ".aws", ".env")


def _acl_add(path, sid_buf, access_mask, mode, inherit=_OI_CI):
    """Add an ACE to a path's DACL via Win32 API.

    mode: 1 = GRANT_ACCESS, 3 = DENY_ACCESS, 4 = REVOKE_ACCESS
    Uses SetEntriesInAclW (allocates a new DACL) + SetNamedSecurityInfoW.
    This works with synthetic SIDs that icacls rejects.
    """
    a, k = _dll()
    p_dacl, p_sd = V(), V()
    # SE_FILE_OBJECT = 1, DACL_SECURITY_INFORMATION = 4
    rc = a.GetNamedSecurityInfoW(str(path), 1, 4, None, None,
                                 ctypes.byref(p_dacl), None, ctypes.byref(p_sd))
    if rc != 0:
        raise OSError(f"GetNamedSecurityInfoW failed on {path}: error {rc}")
    p_new = V()
    try:
        ea = EXPLICIT_ACCESS_W()
        ea.grfAccessPermissions = access_mask
        ea.grfAccessMode = mode
        ea.grfInheritance = inherit
        ea.Trustee.TrusteeForm = 0        # TRUSTEE_IS_SID
        ea.Trustee.ptstrName = ctypes.addressof(sid_buf)
        rc2 = a.SetEntriesInAclW(1, ctypes.byref(ea), p_dacl, ctypes.byref(p_new))
        if rc2 != 0:
            raise OSError(f"SetEntriesInAclW failed on {path}: error {rc2}")
        rc3 = a.SetNamedSecurityInfoW(str(path), 1, 4, None, None, p_new, None)
        if rc3 != 0:
            raise OSError(f"SetNamedSecurityInfoW failed on {path}: error {rc3}")
    finally:
        if p_new.value:
            k.LocalFree(p_new)
        if p_sd.value:
            k.LocalFree(p_sd)


def _dacl_has_sid(path, sid_str):
    """Quick check: does the DACL on 'path' already mention our SID?"""
    r = subprocess.run(["icacls", str(path)], capture_output=True, text=True, timeout=30)
    return sid_str in r.stdout


def _grant(sid_str, sid_buf):
    """Grant write on project, deny write on protected dirs. Idempotent."""
    if not _dacl_has_sid(PROJECT, sid_str):
        _acl_add(PROJECT, sid_buf, _FILE_GENERIC_RWX, 1, _OI_CI)   # GRANT_ACCESS
    for d in _PROTECTED:
        p = PROJECT / d
        if p.exists() and not _dacl_has_sid(p, sid_str):
            _acl_add(p, sid_buf, _DENY_WRITE_MASK, 3, _OI_CI)      # DENY_ACCESS


def revoke():
    """Remove all ACEs that _grant added. Safe to call even if nothing was granted."""
    sid_buf = _sid(_cap_sid())
    for d in _PROTECTED:
        p = PROJECT / d
        if p.exists():
            try:
                _acl_add(p, sid_buf, 0, 4, 0)   # REVOKE_ACCESS
            except OSError:
                pass
    try:
        _acl_add(PROJECT, sid_buf, 0, 4, 0)
    except OSError:
        pass


# --- environment poisoning ---

def _env_dict():
    """Environment that blocks network access and prevents interactive hangs."""
    tmp = PROJECT / ".agents" / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    dead = "http://127.0.0.1:9"
    return {
        **os.environ,
        "TEMP": str(tmp), "TMP": str(tmp),
        # network poisoning (advisory)
        "HTTP_PROXY": dead, "HTTPS_PROXY": dead, "ALL_PROXY": dead,
        "NO_PROXY": "localhost,127.0.0.1,::1",
        # git: block every transport
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_HTTP_PROXY": dead, "GIT_HTTPS_PROXY": dead,
        "GIT_SSH_COMMAND": "cmd /c exit 1",
        "GIT_ALLOW_PROTOCOLS": "",
        # package managers: offline
        "PIP_NO_INDEX": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "NPM_CONFIG_OFFLINE": "true", "CARGO_NET_OFFLINE": "true",
        # prevent interactive hangs
        "GIT_PAGER": "more.com", "PAGER": "more.com",
    }


# --- public API ---

_PRELUDE = "try{[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)}catch{}\n"
_TRAILER = "\n$ok=$?; if($LASTEXITCODE){exit $LASTEXITCODE}; exit [int](-not $ok)"


def name():
    return "acl-sandbox"


def run(command, timeout=60):
    """Run a PowerShell command in the sandbox.

    Returns subprocess.CompletedProcess with text output.
    Raises subprocess.TimeoutExpired on timeout.
    """
    if sys.platform != "win32":
        raise RuntimeError("this sandbox only works on Windows")
    _, k = _dll()

    # 1. ACL enforcement: grant project, deny protected dirs
    cap = _cap_sid()
    _grant(cap, _sid(cap))

    # 2. Job Object: kills all child processes when handle is closed
    job = k.CreateJobObjectW(None, None)
    _chk(job, "CreateJobObjectW")
    limits = (ctypes.c_byte * (144 if ctypes.sizeof(V) == 8 else 112))()
    ctypes.c_uint32.from_buffer(limits, 16).value = 0x2000   # KILL_ON_JOB_CLOSE
    _chk(k.SetInformationJobObject(job, 9, limits, len(limits)), "SetInformationJobObject")

    try:
        # 3. Launch PowerShell with sandboxed environment
        enc = base64.b64encode(
            (_PRELUDE + command + _TRAILER).encode("utf-16-le")
        ).decode()
        proc = subprocess.Popen(
            [POWERSHELL, "-NoLogo", "-NoProfile", "-NonInteractive",
             "-OutputFormat", "Text", "-EncodedCommand", enc],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(PROJECT),
            env=_env_dict(),
            creationflags=0x08000000,   # CREATE_NO_WINDOW
        )
        # 4. Assign to job so child tree dies with us
        if not k.AssignProcessToJobObject(job, V(int(proc._handle))):
            proc.kill()
            _chk(0, "AssignProcessToJobObject")

        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            k.TerminateJobObject(job, 1)
            stdout, stderr = proc.communicate(timeout=5)
            raise subprocess.TimeoutExpired(
                command, timeout,
                output=stdout.decode("utf-8", errors="replace"),
                stderr=stderr.decode("utf-8", errors="replace"),
            )
        k.TerminateJobObject(job, 1)
        return subprocess.CompletedProcess(
            command, proc.returncode,
            stdout.decode("utf-8", errors="replace"),
            stderr.decode("utf-8", errors="replace"),
        )
    finally:
        k.CloseHandle(job)