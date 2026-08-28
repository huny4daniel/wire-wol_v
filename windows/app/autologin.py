"""부팅 직후 자동 로그인(Autologon) 설정.

Windows 로그인 화면(Winlogon)은 SYSTEM 권한 백그라운드 서비스가 키 입력을
대신 넣어주는 것을 보안 구조(Secure Desktop)상 원천 차단한다 — 그래서 "이미
잠긴 화면을 원격으로 푸는" 기능은 만들 수 없고, 대신 Windows 자체가 지원하는
"부팅 시 자동 로그인"(Sysinternals Autologon과 동일한 방식: AutoAdminLogon
레지스트리 + LSA Secret)을 그대로 노출한다. 비밀번호를 레지스트리에 평문으로
남기지 않기 위해 LSA Secret(DefaultPassword)에 저장한다 — pywin32의
win32security 모듈은 이 LSA Secret API를 감싸지 않아 ctypes로 advapi32를 직접
호출한다.

이 설정은 물리적으로 PC 전원 버튼을 누를 수 있는 사람이면 누구나 비밀번호 없이
로그인할 수 있게 만든다는 점에 주의 — 안드로이드 쪽 설정 화면에 경고 문구를
같이 둔다.
"""
import ctypes
import os
import winreg
from ctypes import wintypes

_WINLOGON_KEY = r'SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon'
_SECRET_NAME = 'DefaultPassword'
_POLICY_ALL_ACCESS = 0x000F0FFF

_advapi32 = ctypes.WinDLL('advapi32', use_last_error=True)


class _LsaUnicodeString(ctypes.Structure):
    _fields_ = [
        ('Length', wintypes.USHORT),
        ('MaximumLength', wintypes.USHORT),
        ('Buffer', wintypes.LPWSTR),
    ]


class _LsaObjectAttributes(ctypes.Structure):
    _fields_ = [
        ('Length', wintypes.ULONG),
        ('RootDirectory', wintypes.HANDLE),
        ('ObjectName', ctypes.c_void_p),
        ('Attributes', wintypes.ULONG),
        ('SecurityDescriptor', wintypes.LPVOID),
        ('SecurityQualityOfService', wintypes.LPVOID),
    ]


_advapi32.LsaOpenPolicy.restype = wintypes.LONG
_advapi32.LsaOpenPolicy.argtypes = [
    ctypes.POINTER(_LsaUnicodeString),
    ctypes.POINTER(_LsaObjectAttributes),
    wintypes.DWORD,
    ctypes.POINTER(wintypes.HANDLE),
]
_advapi32.LsaClose.restype = wintypes.LONG
_advapi32.LsaClose.argtypes = [wintypes.HANDLE]
_advapi32.LsaStorePrivateData.restype = wintypes.LONG
_advapi32.LsaStorePrivateData.argtypes = [
    wintypes.HANDLE,
    ctypes.POINTER(_LsaUnicodeString),
    ctypes.POINTER(_LsaUnicodeString),
]


def _lsa_string(value: str) -> _LsaUnicodeString:
    s = _LsaUnicodeString()
    buf = ctypes.create_unicode_buffer(value)
    s.Buffer = ctypes.cast(buf, wintypes.LPWSTR)
    s.Length = len(value) * 2
    s.MaximumLength = (len(value) + 1) * 2
    s._buf_ref = buf  # buf가 GC되지 않도록 s와 생명주기를 묶어둔다
    return s


def _store_secret(name: str, value: str) -> None:
    obj_attrs = _LsaObjectAttributes()
    obj_attrs.Length = ctypes.sizeof(_LsaObjectAttributes)
    policy_handle = wintypes.HANDLE()
    status = _advapi32.LsaOpenPolicy(None, ctypes.byref(obj_attrs), _POLICY_ALL_ACCESS, ctypes.byref(policy_handle))
    if status != 0:
        raise OSError(f'LsaOpenPolicy 실패 (NTSTATUS={status:#x}) — SYSTEM/관리자 권한이 필요합니다')
    try:
        name_str = _lsa_string(name)
        if value:
            value_str = _lsa_string(value)
            status = _advapi32.LsaStorePrivateData(policy_handle, ctypes.byref(name_str), ctypes.byref(value_str))
        else:
            status = _advapi32.LsaStorePrivateData(policy_handle, ctypes.byref(name_str), None)
        if status != 0:
            raise OSError(f'LsaStorePrivateData 실패 (NTSTATUS={status:#x})')
    finally:
        _advapi32.LsaClose(policy_handle)


def enable(username: str, password: str, domain: str = '') -> None:
    _store_secret(_SECRET_NAME, password)
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _WINLOGON_KEY, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, 'AutoAdminLogon', 0, winreg.REG_SZ, '1')
        winreg.SetValueEx(key, 'DefaultUserName', 0, winreg.REG_SZ, username)
        winreg.SetValueEx(key, 'DefaultDomainName', 0, winreg.REG_SZ, domain or os.environ.get('COMPUTERNAME', ''))
        try:
            winreg.DeleteValue(key, 'DefaultPassword')
        except FileNotFoundError:
            pass


def disable() -> None:
    _store_secret(_SECRET_NAME, '')
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _WINLOGON_KEY, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, 'AutoAdminLogon', 0, winreg.REG_SZ, '0')
        for value_name in ('DefaultUserName', 'DefaultPassword'):
            try:
                winreg.DeleteValue(key, value_name)
            except FileNotFoundError:
                pass
