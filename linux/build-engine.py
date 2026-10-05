#!/usr/bin/env python3
"""Cross-build the original compiler/recorder and the Proton bridge on Linux.

Dependencies are explicit: .NET 10 SDK, llvm-mingw, pinned DirectX-Headers.
No Windows VM, Visual Studio, system package installation, or root is used.
"""
from pathlib import Path
import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / 'out/toolchains'
LEGACY = Path.home() / '.local/share/scskiller-tools'
LLVM_NAME = 'llvm-mingw-20260922-ucrt-ubuntu-22.04-x86_64'
LLVM_SHA = 'bb7bb7654b33d5aa8712acb837c963b2e0c56352560c76105270a3268c665c21'
DX_REV = 'adbd6f3ba40795c46a8d0f33af00bcb57ff0f0a4'


def run(args, **kwargs):
    print('+', ' '.join(map(str, args)), flush=True)
    subprocess.run(list(map(str, args)), check=True, cwd=ROOT, **kwargs)


def existing(env_name, candidates):
    if os.environ.get(env_name):
        return Path(os.environ[env_name]).expanduser().resolve()
    return next((Path(p) for p in candidates if p and Path(p).exists()), None)


def generate_headers(headers, build):
    lines = ['// Generated from pinned Microsoft DirectX headers. Do not edit.',
             '#include <d3d12.h>', '#include <d3d12sdklayers.h>', '#include <d3d12shader.h>']
    found = set()
    for filename in ('d3d12.h', 'd3d12sdklayers.h', 'd3d12shader.h'):
        text = (headers / 'include/directx' / filename).read_text()
        pairs = re.findall(r'MIDL_INTERFACE\("([0-9a-fA-F-]+)"\)\s*(\w+)', text)
        pairs += re.findall(r'interface DECLSPEC_UUID\("([0-9a-fA-F-]+)"\)\s*(\w+)', text)
        for guid, name in pairs:
            if name in found:
                continue
            found.add(name)
            value = uuid.UUID(guid)
            fields = [value.time_low, value.time_mid, value.time_hi_version, *value.bytes[8:]]
            lines.append('__CRT_UUID_DECL(' + name + ',' + ','.join(map(hex, fields)) + ')')
    (build / 'directx_uuids.h').write_text('\n'.join(lines) + '\n')
    version = (ROOT / 'proxy/version.h.in').read_text()
    for key, value in {'SCSK_VERSION': '0.0.0-internal.0', 'SCSK_VERSION_MAJOR': '0',
                       'SCSK_VERSION_MINOR': '0', 'SCSK_VERSION_PATCH': '0'}.items():
        version = version.replace('@' + key + '@', value)
    (build / 'version.h').write_text(version)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bootstrap', action='store_true', help='download pinned cross toolchain and DirectX headers')
    parser.add_argument('--output', type=Path, default=ROOT / 'dist/linux/engine')
    parser.add_argument('--no-restore', action='store_true', help='use existing NuGet restore (offline rebuild)')
    args = parser.parse_args()
    TOOLS.mkdir(parents=True, exist_ok=True)
    dotnet = existing('SCSKILLER_DOTNET', [shutil.which('dotnet'), TOOLS / 'dotnet/dotnet', LEGACY / 'dotnet/dotnet'])
    llvm = existing('SCSKILLER_LLVM', [TOOLS / LLVM_NAME, LEGACY / LLVM_NAME])
    headers = existing('SCSKILLER_DX_HEADERS', [TOOLS / 'DirectX-Headers', LEGACY / 'DirectX-Headers'])
    if args.bootstrap:
        if llvm is None:
            archive = TOOLS / (LLVM_NAME + '.tar.xz')
            url = 'https://github.com/mstorsjo/llvm-mingw/releases/download/20260922/' + archive.name
            urllib.request.urlretrieve(url, archive)
            if hashlib.sha256(archive.read_bytes()).hexdigest() != LLVM_SHA:
                raise RuntimeError('llvm-mingw download checksum mismatch')
            with tarfile.open(archive) as tar:
                tar.extractall(TOOLS, filter='data')
            llvm = TOOLS / LLVM_NAME
        if headers is None:
            headers = TOOLS / 'DirectX-Headers'
            run(['git', 'clone', 'https://github.com/microsoft/DirectX-Headers.git', headers])
            run(['git', '-C', headers, 'checkout', '--detach', DX_REV])
    if not dotnet or not llvm or not headers:
        raise RuntimeError('Install .NET SDK 10, then use --bootstrap for llvm-mingw and DirectX-Headers. '
                           'Overrides: SCSKILLER_DOTNET (executable), SCSKILLER_LLVM and SCSKILLER_DX_HEADERS (directories).')
    revision = subprocess.check_output(['git', '-C', str(headers), 'rev-parse', 'HEAD'], text=True).strip()
    if revision != DX_REV:
        raise RuntimeError(f'DirectX-Headers must be at {DX_REV}, found {revision}')
    build = ROOT / 'out/linux-native'
    build.mkdir(parents=True, exist_ok=True)
    generate_headers(headers, build)
    compiler = llvm / 'bin/x86_64-w64-mingw32-clang++'
    flags = [compiler, '-std=c++20', '-fms-extensions', '-D_WIN32_WINNT=0x0a00', '-DNTDDI_VERSION=0x0a000000',
             '-D__d3d12shader_h__', '-O2', '-static', '-I' + str(headers / 'include/directx'), '-I' + str(build)]
    libraries = ['-lbcrypt', '-ldxguid', '-lshell32', '-lole32', '-ld3d11', '-ld3dcompiler', '-ldxgi', '-luuid']
    run([*flags, '-shared', 'proxy/proxy.cpp', 'proxy/warm11.cpp', 'proxy/vtslots.cpp', 'proxy/dxguids.cpp',
         'proxy/stubs.S', 'proxy/d3d12.def', '-o', build / 'd3d12.dll', *libraries])
    run([*flags, '-municode', 'proxy/warm.cpp', '-o', build / 'scskiller_warm.exe', '-ldxgi', '-lole32'])
    run([*flags, '-municode', '-Iproxy/third_party/vulkan', 'proxy/selftest.cpp', 'proxy/dxguids.cpp',
         '-o', build / 'selftest.exe', *libraries])
    run([*flags, '-shared', 'proxy/fakenext.cpp', '-o', build / 'fakenext.dll', *libraries])
    args.output = args.output.resolve()
    environment = os.environ.copy()
    environment.setdefault('DOTNET_CLI_HOME', str(ROOT / 'out/dotnet-home'))
    command = [dotnet, 'publish', 'linux/engine/SCSKiller.Linux.Engine.csproj', '-c', 'Release',
               '-o', args.output, '-p:EnableWindowsTargeting=true']
    if args.no_restore:
        command.append('--no-restore')
    run(command, env=environment)
    native = args.output / 'native'
    native.mkdir(parents=True, exist_ok=True)
    for name in ('d3d12.dll', 'scskiller_warm.exe', 'selftest.exe', 'fakenext.dll'):
        shutil.copy2(build / name, native / name)
    for name in ('LICENSE', 'THIRD-PARTY-NOTICES.md'):
        shutil.copy2(ROOT / name, args.output / name)
    shutil.copy2(headers / 'LICENSE', args.output / 'DirectX-Headers-LICENSE.txt')
    (args.output / 'build-info.json').write_text(__import__('json').dumps({
        'llvm': LLVM_NAME, 'llvm_sha256': LLVM_SHA, 'directx_headers': DX_REV,
        'sdk': subprocess.check_output([str(dotnet), '--version'], text=True, env=environment).strip(),
        'source': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True, cwd=ROOT).strip(),
        'dirty': bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT)),
    }, indent=2) + '\n')
    print('Built original core + Proton compiler/recorder:', args.output)


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print('Engine build failed:', error, file=sys.stderr)
        sys.exit(1)
