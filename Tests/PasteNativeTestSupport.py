"""Compile the real controller/engine with UI and preferences isolated."""
import os
import pathlib
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]

def build_fixture(fixture, name, extra_flags=()):
    paths = [pathlib.Path(p) for p in subprocess.check_output(
        ['/usr/bin/git', 'ls-files', '*.m'], cwd=ROOT, text=True).splitlines()
        if p != 'main.m' and not p.startswith(('FlycutHelper/', 'Tests/'))]
    sources = [ROOT / p for p in paths]
    includes = sorted({ROOT, ROOT / 'Tests', *(p.parent for p in sources)})
    parent = os.environ.get('FC_PASTE_TEST_BUILD_ROOT')
    if parent:
        pathlib.Path(parent).mkdir(parents=True, exist_ok=True)
    directory = pathlib.Path(tempfile.mkdtemp(prefix=name+'-', dir=parent))
    if not parent:
        import atexit, shutil
        atexit.register(shutil.rmtree, directory, ignore_errors=True)
    source = directory / (name+'.m')
    binary = directory / name
    source.write_text(fixture)
    command = ['/usr/bin/xcrun', 'clang', '-fno-objc-arc', '-fobjc-weak',
        '-fblocks', '-fmodules', '-DFLYCUT_MAC=1', '-mmacosx-version-min=13.5',
        '-include', str(ROOT/'Flycut_Prefix.pch'),
        '-include', str(ROOT/'Tests/PasteTestEnvironment.h'), *extra_flags]
    for path in includes:
        command.extend(['-I', str(path)])
    command.extend(map(str, sources))
    command.append(str(source))
    for framework in ('Cocoa', 'Carbon', 'ServiceManagement', 'CloudKit'):
        command.extend(['-framework', framework])
    command.extend(['-o', str(binary)])
    build = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, timeout=300)
    (directory/'build.log').write_text(build.stdout)
    if build.returncode:
        raise AssertionError(build.stdout)
    return binary

def run_fixture(binary, mode):
    return subprocess.run([str(binary), mode], cwd=ROOT, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
